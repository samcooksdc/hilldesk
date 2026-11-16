# SPDX-License-Identifier: Apache-2.0
"""Per-message pipeline orchestration.

Reception enqueues ``run_pipeline`` for every newly ingested RawMessage. The
task runs the deterministic funnel; outcomes:

- ``divert``   → nothing beyond RawMessage + FilterLog (the divert store is a
                 query, not a table).
- ``escalate`` → an ``EmailProcessing`` row with status ``escalated`` so triage
                 can surface it (rate-gate bursts fold into one triage item).
- ``extract``  → an ``EmailProcessing`` row, then the SINGLE extraction call
                 (spec §7): deterministic ICS candidates first; one model call
                 (schema-validated, one repair retry, escalate on persistent
                 failure) unless the calendar part covers the message; results
                 persisted as ExtractionCandidate rows for Phase-5
                 post-processing.
"""

import logging
from email.utils import parseaddr

from celery import shared_task
from django.conf import settings
from django.core.exceptions import ValidationError

from ..funnel import run_funnel
from ..models import EmailProcessing, ExtractionCandidate, FilterLog, RawMessage

logger = logging.getLogger('apps.email_processing')
security_logger = logging.getLogger('security_audit')

# Placeholder that satisfies EmailField validation when a message arrives with
# a missing/undecodable sender (itself a strong escalation signal).
_FALLBACK_SENDER = 'unknown@sender.invalid'


def _valid_sender(raw_sender: str) -> str:
    addr = parseaddr(raw_sender or '')[1]
    return addr if addr and '@' in addr else _FALLBACK_SENDER


def _complete_email_data(raw: RawMessage, body_text: str) -> dict:
    """Standardized email payload consumed by the inbox/review UI (the shape
    EmailProcessing.complete_email_data has always carried: email_id, thread_id,
    body{text, preview}, attachments)."""
    return {
        'email_id': raw.graph_message_id,
        'internet_message_id': raw.internet_message_id,
        'thread_id': raw.conversation_id,
        'subject': raw.subject,
        'sender': raw.sender,
        'sender_name': raw.sender_name,
        'received': raw.received_at.isoformat(),
        'mailbox': raw.mailbox,
        'source': raw.source,
        'body': {
            'text': body_text,
            'preview': (body_text or '')[:200],
        },
        'attachments': raw.attachments,
        'has_calendar_part': raw.has_calendar_part,
        'email_type': 'ingestion',
    }


def _ensure_email_processing(raw: RawMessage, body_text: str, *,
                             status: str, is_scheduling: bool,
                             confidence: float) -> EmailProcessing:
    """Create (or fetch) the pipeline-visible record for this message.

    Keyed on the unique ``email_id`` so re-runs (promotion, re-scoring) reuse
    the existing row instead of violating uniqueness.
    """
    existing = EmailProcessing.objects.filter(email_id=raw.graph_message_id).first()
    if existing is not None:
        updates = []
        if existing.raw_message_id is None:
            existing.raw_message = raw
            updates.append('raw_message')
        # A promoted/re-scored message moves forward, never backward: escalated
        # may become pending, but a verified/rejected row is left alone.
        if status == 'pending' and existing.status in ('escalated', 'error'):
            existing.status = 'pending'
            existing.is_scheduling_request = True
            updates.extend(['status', 'is_scheduling_request'])
        if updates:
            existing.save()
        return existing

    return EmailProcessing.objects.create(
        email_id=raw.graph_message_id,
        subject=(raw.subject or '(no subject)')[:1000],
        sender=_valid_sender(raw.sender),
        sender_name=(raw.sender_name or '')[:200],
        received=raw.received_at,
        status=status,
        is_scheduling_request=is_scheduling,
        confidence=max(0.0, min(confidence, 1.0)),
        complete_email_data=_complete_email_data(raw, body_text),
        # Placeholder until the extraction call (Phase 4) fills it; the model
        # rejects a blank dict, and recording the funnel verdict is useful.
        extracted_data={'ingestion': {'funnel_status': status}},
        raw_message=raw,
    )


def _log_extraction(raw: RawMessage, outcome: str, signals: dict) -> None:
    FilterLog.objects.create(raw_message=raw, stage='extraction',
                             outcome=outcome, signals=signals)


def _escalate_extraction(raw: RawMessage, record: EmailProcessing,
                         reason: str, detail: str = '') -> str:
    """Extraction could not produce trustworthy candidates → human triage.
    Never act on free text (spec §6.4 trust boundary)."""
    record.status = 'escalated'
    record.set_extracted_field('escalation', {'reason': reason, 'detail': detail[:500]})
    record.save()
    _log_extraction(raw, 'escalate', {'reason': reason, 'detail': detail[:500]})
    security_logger.warning(
        'Extraction escalated', extra={'raw_message_id': str(raw.id), 'reason': reason},
    )
    return 'escalate'


def _persist_candidates(raw: RawMessage, record: EmailProcessing,
                        candidates: list, channel_default: str) -> int:
    created = 0
    for cand in candidates:
        recurrence = cand.get('recurrence') or {}
        rrule = recurrence.get('rrule')
        provenance = cand.pop('provenance', None) or {'channel': channel_default}
        ExtractionCandidate.objects.create(
            raw_message=raw,
            email_processing=record,
            thread=record.thread,
            intent=cand['intent'],
            payload=cand,
            provenance=provenance,
            confidence=max(0.0, min(float(cand.get('confidence', 0.0)), 1.0)),
            recurrence_rule=rrule,
            recurrence_needs_end=bool(rrule) and not recurrence.get('has_end', False),
        )
        created += 1
    return created


def _run_extraction(raw: RawMessage, ctx, record: EmailProcessing) -> str:
    """The single extraction call, plus the deterministic channels around it.

    Returns the final pipeline outcome: 'extract' or 'escalate'.
    """
    from ..channels import documents, ics
    from ..llm_providers import get_llm_provider
    from ..llm_providers.schema import MessageBundle, validate_candidate_set

    # --- Calendar channel: deterministic, confidence 1.0, no model ---
    ics_candidates = []
    if raw.has_calendar_part:
        ics_candidates = ics.parse_calendar_candidates(raw)
        if not ics_candidates:
            return _escalate_extraction(raw, record, 'unparseable_calendar',
                                        'has_calendar_part but no VEVENT parsed')

    # A parsed calendar part covers the message unless the body carries
    # substantial non-boilerplate prose (then body extraction runs additionally).
    needs_model = not ics_candidates or ics.substantial_body_prose(ctx.new_content)

    # --- Document channel: harvest text/images; unreadable → escalate ---
    harvest = documents.harvest(raw)
    if harvest.failures:
        return _escalate_extraction(
            raw, record, 'attachment_unreadable',
            '; '.join(f"{f['name']}: {f['reason']}" for f in harvest.failures),
        )

    model_candidates = []
    notes = None
    if needs_model:
        provider = get_llm_provider()
        bundle = MessageBundle(
            subject=raw.subject,
            new_content=ctx.new_content,
            thread_context=(ctx.body_text[len(ctx.new_content):].strip()
                            if ctx.body_text != ctx.new_content else ''),
            attachment_texts=harvest.texts,
            image_blocks=harvest.images,
            sender_email=ctx.sender_email,
            sender_name=raw.sender_name or '',
            received_at_iso=raw.received_at.isoformat(),
            office_timezone=getattr(settings, 'TIME_ZONE', 'America/New_York'),
            action_intent_hint=ctx.action_intent,
        )
        output = provider.extract_candidates(bundle)

        # Trust boundary: schema-validate; ONE repair retry; then escalate.
        errors = ([output.error] if output.error
                  else validate_candidate_set(output.data))
        if errors:
            bundle.repair_error = '\n'.join(errors)[:2000]
            output = provider.extract_candidates(bundle)
            errors = ([output.error] if output.error
                      else validate_candidate_set(output.data))
        if errors:
            return _escalate_extraction(raw, record, 'malformed_model_output',
                                        '\n'.join(errors))
        model_candidates = output.data.get('candidates', [])
        notes = output.data.get('notes')

    # --- Persist ---
    created = _persist_candidates(raw, record, ics_candidates, 'ics')
    created += _persist_candidates(raw, record, model_candidates, 'body')

    all_confidences = [c.confidence for c in record.candidates.all()] or [0.0]
    record.status = 'processed'
    record.is_scheduling_request = created > 0
    record.confidence = max(all_confidences)
    record.extracted_data = {
        'schema': 'candidate_set_v1',
        'candidate_count': created,
        'ics_candidates': len(ics_candidates),
        'model_candidates': len(model_candidates),
        'notes': notes,
    }
    record.save()

    _log_extraction(raw, 'extract', {
        'candidates': created,
        'ics': len(ics_candidates),
        'model': len(model_candidates),
        'model_called': needs_model,
    })

    # Post-processing & materialization (spec §8): candidates become the
    # review surfaces the inbox renders (draft Events / change suggestions).
    from ..postprocess import process_candidates
    result = process_candidates(record)
    return result['outcome']


@shared_task(bind=True, max_retries=3)
def run_pipeline(self, raw_message_id: str, force_extract: bool = False):
    """Process one ingested message through the funnel.

    ``force_extract`` is the divert-store "promote to extraction" path: skips
    funnel judgment, records the override in FilterLog.
    """
    raw = RawMessage.objects.filter(pk=raw_message_id).first()
    if raw is None:
        logger.warning("run_pipeline: RawMessage %s not found", raw_message_id)
        return {'status': 'missing', 'raw_message_id': str(raw_message_id)}

    # Idempotency guard: a normal enqueue never re-runs a message whose funnel
    # already ran (Celery redelivery, sweep/webhook races). Forced runs are
    # deliberate re-entries and proceed.
    if not force_extract and raw.filter_logs.exists():
        logger.info("run_pipeline: %s already has a pipeline run; skipping", raw.graph_message_id)
        return {'status': 'already_processed', 'raw_message_id': str(raw.id)}

    result = run_funnel(raw, force_extract=force_extract)
    outcome = result.outcome
    signals = result.decision.signals

    record_id = None
    try:
        if outcome == 'extract':
            record = _ensure_email_processing(
                raw, result.context.body_text,
                status='pending', is_scheduling=True,
                confidence=min(result.decision.score / 10.0, 1.0),
            )
            record_id = str(record.id)
            outcome = _run_extraction(raw, result.context, record)
        elif outcome == 'escalate':
            # Rate-gate bursts produce ONE triage item: only the primary
            # message of a burst creates a record; the rest are ledger-only.
            if signals.get('burst_primary') is not False:
                record = _ensure_email_processing(
                    raw, result.context.body_text,
                    status='escalated', is_scheduling=False,
                    confidence=0.0,
                )
                record_id = str(record.id)
    except ValidationError as exc:
        logger.error("run_pipeline: EmailProcessing validation failed for %s: %s",
                     raw.graph_message_id, exc)
        raise self.retry(countdown=30 * (2 ** self.request.retries), exc=exc)

    security_logger.info(
        'Pipeline run completed',
        extra={
            'raw_message_id': str(raw.id),
            'outcome': outcome,
            'terminal_stage': result.terminal_stage,
            'forced': force_extract,
            'email_processing_id': record_id,
        },
    )
    return {
        'status': outcome,
        'terminal_stage': result.terminal_stage,
        'raw_message_id': str(raw.id),
        'email_processing_id': record_id,
    }
