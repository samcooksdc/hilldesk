# SPDX-License-Identifier: Apache-2.0
"""Post-processing & materialization (spec §8): deterministic, no model call.

Turns validated ExtractionCandidate rows into the review surfaces the current
inbox already renders:

- NEW_EVENT / UNCERTAIN / unmatched RECURRING_EVENT → draft Event
  (``requires_human_review=True``) with ``extracted_fields`` v2 + a ``meta``
  block; multi-event fan-out = multiple Events (zero inbox listing changes).
- Matched NEW_EVENT → duplicate suspect: still a draft Event, with
  ``meta.duplicate_of`` (a dropped real event is worse than a duplicate card).
- RECURRING_EVENT → draft Event for the first occurrence + pending inactive
  EventSeries; approval activates and materializes.
- RESCHEDULE / CANCELLATION with a match → EventChangeSuggestion rows
  (one per changed field, grouped by candidate; origin='email_ingestion'),
  reusing the existing approve()/apply machinery. Without a match → escalate
  ("cancellation of unknown event"), never guess.
"""

import logging
from collections import defaultdict
from datetime import date, time
from typing import Any, Dict, List, Optional, Tuple

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone as dj_tz

from .matching import match_existing_event
from .models import EmailProcessing, ExtractionCandidate, FilterLog

logger = logging.getLogger('apps.email_processing')
security_logger = logging.getLogger('security_audit')

User = get_user_model()

PIPELINE_USERNAME = 'hilldesk_pipeline'

_SCALAR_FIELDS = ('title', 'type', 'format', 'start_date', 'start_time',
                  'end_date', 'end_time', 'location', 'description')


def get_pipeline_user():
    """The system actor for pipeline-created rows (Event.created_by is a
    non-null PROTECT FK). Inactive: it can never log in."""
    user, _ = User.objects.get_or_create(
        username=PIPELINE_USERNAME,
        defaults={
            'email': 'pipeline@hilldesk.invalid',
            'first_name': 'HillDesk',
            'last_name': 'Pipeline',
            'is_active': False,
        },
    )
    return user


# ---------------------------------------------------------------------------
# Field shaping
# ---------------------------------------------------------------------------

def _parse_date(value) -> Optional[date]:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except (ValueError, TypeError):
        return None


def _parse_time(value) -> Optional[time]:
    try:
        return time.fromisoformat(str(value)) if value else None
    except (ValueError, TypeError):
        return None


def resolve_timezone(payload: Dict[str, Any]) -> Tuple[str, str, bool]:
    """(timezone, basis, ambiguous) — no zoneless time ever reaches an Event.

    The candidate's proposed zone is used when it is a zone the office's
    choices accept; otherwise the office default with the basis recorded so
    the review card can flag it.
    """
    proposed = ((payload.get('timezone') or {}).get('proposed') or '').strip()
    proposed_basis = (payload.get('timezone') or {}).get('basis') or ''
    valid = {tz for tz, _ in settings.TIMEZONE_CHOICES}
    office_default = getattr(settings, 'TIME_ZONE', 'America/New_York')
    if office_default not in valid and valid:
        office_default = sorted(valid)[0]

    if proposed in valid:
        return proposed, proposed_basis or 'model_proposed', False
    if proposed:
        # Proposed a zone we can't represent — fall back, but flag for review.
        return office_default, f'office_default (proposed {proposed!r} not available)', True
    return office_default, 'office_default', False


def _span_for(value: Optional[str], body: str) -> Dict[str, Any]:
    """Locate a verbatim string in the body for review-card highlighting."""
    if not value or not body:
        return {}
    idx = body.lower().find(str(value).lower())
    if idx < 0:
        return {}
    return {'start_index': idx, 'end_index': idx + len(str(value)),
            'text_snippet': body[max(0, idx - 30):idx + len(str(value)) + 30]}


def build_extracted_fields(candidate: ExtractionCandidate, body: str,
                           tz_resolved: str, tz_basis: str, tz_ambiguous: bool,
                           duplicate_of=None) -> Dict[str, Any]:
    """The event's ``extracted_fields`` v2 structure, built mechanically from
    the candidate. Cards come from the existing contacts builder so the current
    review-card JS works unchanged; ``meta`` is additive (schema_version stays
    2-compatible — FieldReviewService treats it as a non-field key)."""
    from apps.contacts.extraction import build_review_parties

    payload = candidate.payload or {}
    event_fields = payload.get('event') or {}
    verbatim = payload.get('verbatim') or {}
    confidence = float(payload.get('confidence', candidate.confidence) or 0.0)

    ef = build_review_parties(payload.get('contacts') or [],
                              payload.get('organizations') or [], body)

    for field in _SCALAR_FIELDS:
        value = event_fields.get(field)
        if value in (None, '', []):
            continue
        cell = {
            'value': value,
            'confidence': confidence,
            'status': 'pending',
            'reviewed_by': None,
            'reviewed_at': None,
        }
        if field in ('start_date', 'end_date'):
            cell.update(_span_for(verbatim.get('date_text'), body))
        elif field in ('start_time', 'end_time'):
            cell.update(_span_for(verbatim.get('time_text'), body))
        else:
            cell.update(_span_for(str(value), body))
        ef[field] = cell

    for field in ('legislative_topics', 'participants'):
        values = event_fields.get(field)
        if values:
            ef[field] = {'value': values, 'confidence': confidence,
                         'status': 'pending', 'reviewed_by': None, 'reviewed_at': None}

    ef['meta'] = {
        'origin': 'email_ingestion',
        'intent': candidate.intent,
        'confidence': confidence,
        'channel': (candidate.provenance or {}).get('channel', 'body'),
        'verbatim': verbatim,
        'timezone': {'resolved': tz_resolved, 'basis': tz_basis,
                     'ambiguous': tz_ambiguous},
        'recurrence': {'rrule': candidate.recurrence_rule,
                       'needs_end': candidate.recurrence_needs_end},
        'candidate_id': str(candidate.id),
    }
    if duplicate_of is not None:
        ef['meta']['duplicate_of'] = {'event_id': str(duplicate_of.id),
                                      'title': duplicate_of.title,
                                      'start_date': (duplicate_of.start_date.isoformat()
                                                     if duplicate_of.start_date else None)}
    return ef


# ---------------------------------------------------------------------------
# Materializers
# ---------------------------------------------------------------------------

def _attach_sources(event, record: EmailProcessing, actor,
                    is_primary: bool = True) -> None:
    from apps.event_management.models import EventEmailLink, EventThreadLink

    EventEmailLink.objects.get_or_create(
        event=event, email=record,
        defaults={'mode': 'include', 'origin': 'ai_auto',
                  'is_primary': is_primary, 'linked_by': actor},
    )
    if record.thread_id:
        EventThreadLink.objects.get_or_create(
            event=event, thread_id=record.thread_id,
            defaults={'linked_by': actor},
        )


def _materialize_draft_event(candidate: ExtractionCandidate,
                             record: EmailProcessing, body: str, actor,
                             duplicate_of=None):
    from apps.event_management.models import Event

    payload = candidate.payload or {}
    event_fields = payload.get('event') or {}
    tz_resolved, tz_basis, tz_ambiguous = resolve_timezone(payload)

    event = Event.objects.create(
        title=(event_fields.get('title') or record.subject or '(untitled)')[:200],
        type=(event_fields.get('type') or 'meeting')[:20],
        format=(event_fields.get('format') or '')[:20],
        start_date=_parse_date(event_fields.get('start_date')),
        start_time=_parse_time(event_fields.get('start_time')),
        end_date=_parse_date(event_fields.get('end_date')),
        end_time=_parse_time(event_fields.get('end_time')),
        timezone=tz_resolved,
        location=(event_fields.get('location') or '')[:500],
        description=event_fields.get('description') or '',
        legislative_topics=event_fields.get('legislative_topics') or [],
        participants=event_fields.get('participants') or [],
        status='received',
        requires_human_review=True,
        extracted_fields=build_extracted_fields(
            candidate, body, tz_resolved, tz_basis, tz_ambiguous,
            duplicate_of=duplicate_of,
        ),
        created_by=actor,
        modified_by=actor,
    )
    _attach_sources(event, record, actor)
    return event


def _materialize_series(candidate: ExtractionCandidate, draft_event, actor):
    """Pending, INACTIVE series — activation requires a reviewer-confirmed end
    bound (spec §9)."""
    from apps.event_management.models import EventSeries

    rrule = candidate.recurrence_rule or 'FREQ=WEEKLY'
    upper = rrule.upper()
    count = None
    until = None
    for part in upper.replace(' ', '').split(';'):
        if part.startswith('COUNT='):
            try:
                count = int(part.split('=', 1)[1])
            except ValueError:
                pass
        elif part.startswith('UNTIL='):
            until = _parse_date(f"{part[6:10]}-{part[10:12]}-{part[12:14]}")

    series = EventSeries.objects.create(
        rrule=rrule,
        dtstart_date=draft_event.start_date or dj_tz.now().date(),
        dtstart_time=draft_event.start_time,
        timezone=draft_event.timezone,
        until_date=until,
        count=count,
        title_template=draft_event.title,
        source_candidate=candidate,
        created_by=actor,
        is_active=False,
    )
    draft_event.series = series
    draft_event.series_occurrence_date = draft_event.start_date
    draft_event.save()
    return series


def _materialize_change_suggestions(candidate: ExtractionCandidate,
                                    matched_event, record: EmailProcessing):
    """RESCHEDULE/CANCELLATION → EventChangeSuggestion rows on the matched
    event: one row per changed field (the model is one-field-per-row), all
    sharing origin='email_ingestion' + this candidate, so the inbox feed can
    group them into a single card and reuse the existing approve machinery."""
    from apps.event_management.models import EventChangeSuggestion

    payload = candidate.payload or {}
    event_fields = payload.get('event') or {}
    verbatim = payload.get('verbatim') or {}
    reason_bits = [f"From email: {record.subject!r}"]
    if verbatim.get('date_text') or verbatim.get('time_text'):
        reason_bits.append(
            'verbatim: ' + ' '.join(filter(None, [verbatim.get('date_text'),
                                                  verbatim.get('time_text')])))
    reason = '; '.join(reason_bits)

    suggestions = []
    if candidate.intent == 'CANCELLATION':
        suggestions.append(EventChangeSuggestion.objects.create(
            event=matched_event,
            field_name='status',
            current_value=str(matched_event.status),
            suggested_value='cancelled',
            reason=reason,
            suggested_by=None,
            origin='email_ingestion',
            source_candidate=candidate,
        ))
        return suggestions

    for field in ('start_date', 'start_time', 'end_date', 'end_time', 'location'):
        new_value = event_fields.get(field)
        if new_value in (None, ''):
            continue
        current = getattr(matched_event, field, None)
        current_str = current.isoformat() if hasattr(current, 'isoformat') else str(current or '')
        if str(new_value) == current_str:
            continue
        suggestions.append(EventChangeSuggestion.objects.create(
            event=matched_event,
            field_name=field,
            current_value=current_str,
            suggested_value=str(new_value),
            reason=reason,
            suggested_by=None,
            origin='email_ingestion',
            source_candidate=candidate,
        ))
    return suggestions


# ---------------------------------------------------------------------------
# Enumerated-recurrence fold (spec §8.3)
# ---------------------------------------------------------------------------

def _detect_cadence(dates: List[date]) -> Optional[str]:
    """A near-constant gap across ≥3 dates reads as a cadence."""
    if len(dates) < 3:
        return None
    dates = sorted(dates)
    gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
    if any(g <= 0 for g in gaps):
        return None
    avg = sum(gaps) / len(gaps)
    if all(abs(g - avg) <= 1 for g in gaps):
        if 6 <= avg <= 8:
            return 'FREQ=WEEKLY'
        if 13 <= avg <= 15:
            return 'FREQ=WEEKLY;INTERVAL=2'
        if 27 <= avg <= 32:
            return 'FREQ=MONTHLY'
    return None


def fold_enumerated_recurrence(record: EmailProcessing,
                               candidates: List[ExtractionCandidate]
                               ) -> List[ExtractionCandidate]:
    """N NEW_EVENT candidates sharing title + attendees across a detectable
    cadence fold into ONE RECURRING_EVENT candidate; originals are recorded in
    provenance and marked superseded."""
    groups = defaultdict(list)
    for cand in candidates:
        if cand.intent != 'NEW_EVENT':
            continue
        payload = cand.payload or {}
        title = ' '.join(((payload.get('event') or {}).get('title') or '').split()).lower()
        attendees = frozenset((c.get('email') or c.get('name') or '').lower()
                              for c in payload.get('contacts') or [])
        if title:
            groups[(title, attendees)].append(cand)

    out = [c for c in candidates]
    for (title, _), members in groups.items():
        dates = [d for d in (_parse_date((m.payload.get('event') or {}).get('start_date'))
                             for m in members) if d]
        if len(dates) < 3 or len(dates) != len(members):
            continue
        rrule = _detect_cadence(dates)
        if not rrule:
            continue

        first = min(members, key=lambda m: (m.payload.get('event') or {}).get('start_date') or '')
        folded_payload = dict(first.payload)
        folded_payload['intent'] = 'RECURRING_EVENT'
        folded_payload['recurrence'] = {'rrule': f"{rrule};COUNT={len(members)}",
                                        'has_end': True}
        folded = ExtractionCandidate.objects.create(
            raw_message=record.raw_message,
            email_processing=record,
            thread=record.thread,
            intent='RECURRING_EVENT',
            payload=folded_payload,
            provenance={'channel': 'fold',
                        'folded_from': [str(m.id) for m in members]},
            confidence=min(float(m.confidence) for m in members),
            recurrence_rule=f"{rrule};COUNT={len(members)}",
            recurrence_needs_end=False,
        )
        for member in members:
            member.status = 'superseded'
            member.save(update_fields=['status', 'updated_at'])
            out.remove(member)
        out.append(folded)
        logger.info("Folded %d enumerated candidates into series candidate %s",
                    len(members), folded.id)
    return out


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def process_candidates(record: EmailProcessing) -> Dict[str, Any]:
    """Run cap → fold → match → route for one message's candidates.

    Returns a summary dict; also writes the ``postprocess`` FilterLog row and
    updates candidate/record statuses.
    """
    raw = record.raw_message
    candidates = list(record.candidates.filter(status='pending_review'))
    body = (record.get_email_body() or {}).get('text', '') or ''
    summary = {'events_created': 0, 'series_created': 0,
               'suggestions_created': 0, 'escalated': 0, 'folded': 0}

    if not candidates:
        FilterLog.objects.create(raw_message=raw, stage='postprocess',
                                 outcome='extract', signals={'candidates': 0})
        return {'outcome': 'extract', **summary}

    # 1. Cap check — collapse to one triage item, never N.
    cap = getattr(settings, 'CANDIDATE_CAP', 10)
    if len(candidates) > cap:
        for cand in candidates:
            cand.status = 'escalated'
            cand.save(update_fields=['status', 'updated_at'])
        record.status = 'escalated'
        record.set_extracted_field('escalation', {
            'reason': 'candidate_cap',
            'detail': f'{len(candidates)} candidates > cap {cap} — review source',
        })
        record.save()
        FilterLog.objects.create(
            raw_message=raw, stage='postprocess', outcome='escalate',
            signals={'reason': 'candidate_cap', 'count': len(candidates)},
        )
        return {'outcome': 'escalate', 'escalated': len(candidates), **summary}

    # 3. Enumerated-recurrence fold (2 — recurrence completeness — is already
    # carried on the candidate rows from extraction).
    candidates = fold_enumerated_recurrence(record, candidates)
    summary['folded'] = len([c for c in candidates
                             if (c.provenance or {}).get('channel') == 'fold'])

    actor = get_pipeline_user()

    for cand in candidates:
        # 4. Match against existing events.
        matched, basis = match_existing_event(cand, record)
        cand.matched_event = matched
        cand.match_basis = basis

        # 5. Intent routing.
        if cand.intent in ('NEW_EVENT', 'UNCERTAIN'):
            event = _materialize_draft_event(cand, record, body, actor,
                                             duplicate_of=matched)
            cand.created_event = event
            cand.status = 'materialized'
            summary['events_created'] += 1
        elif cand.intent == 'RECURRING_EVENT':
            event = _materialize_draft_event(cand, record, body, actor,
                                             duplicate_of=matched)
            _materialize_series(cand, event, actor)
            cand.created_event = event
            cand.status = 'materialized'
            summary['events_created'] += 1
            summary['series_created'] += 1
        elif cand.intent in ('RESCHEDULE', 'CANCELLATION'):
            if matched is not None:
                suggestions = _materialize_change_suggestions(cand, matched, record)
                cand.change_suggestion = suggestions[0] if suggestions else None
                cand.status = 'materialized'
                summary['suggestions_created'] += len(suggestions)
                # Attach the requesting email to the matched event so the
                # editing modal's email pane shows the source next to the
                # change-request review (same surface as extraction review).
                # Not primary — the matched event may already have one.
                _attach_sources(matched, record, actor, is_primary=False)
            else:
                # Never guess which event to change (spec §8.5).
                cand.status = 'escalated'
                summary['escalated'] += 1
                security_logger.warning(
                    '%s of unknown event escalated', cand.intent,
                    extra={'candidate_id': str(cand.id),
                           'raw_message_id': str(raw.id)},
                )
        cand.save()

    FilterLog.objects.create(
        raw_message=raw, stage='postprocess', outcome='extract',
        signals=summary,
    )
    return {'outcome': 'extract', **summary}
