# SPDX-License-Identifier: Apache-2.0
"""Funnel engine: orders the stages, applies short-circuit semantics, and
writes one FilterLog row per stage evaluated.

Order (spec §5): scope → headers → reputation → dedup → rate gate → content.
Channel bypasses: a calendar part or document attachments skip content scoring
(those channels are deterministic / force pass-forward); an allowlisted sender
skips content scoring and content-hash dedup.
"""

import logging
from dataclasses import dataclass
from typing import Optional

from ..models import FilterLog, RawMessage
from .. import thread_text
from . import rate_gate, stage1_headers, stage2_reputation, stage3_dedup, stage4_content
from .base import DIVERT, ESCALATE, EXTRACT, PASS, FunnelContext, StageDecision

logger = logging.getLogger('apps.email_processing')

# Attachment content types / extensions that force pass-forward past stage 4
# (the document channel: PDFs, Word docs, images that may BE the invitation).
_DOCUMENT_CONTENT_PREFIXES = ('application/pdf', 'image/')
_DOCUMENT_CONTENT_TYPES = {
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/msword',
}
_DOCUMENT_EXTENSIONS = ('.pdf', '.docx', '.doc', '.png', '.jpg', '.jpeg', '.tiff')


@dataclass
class FunnelResult:
    """Final funnel verdict for one pipeline run."""
    outcome: str                     # 'extract' | 'divert' | 'escalate'
    terminal_stage: str              # stage that decided it
    context: FunnelContext
    decision: StageDecision          # the terminal stage's decision


def _has_document_attachments(raw: RawMessage) -> bool:
    for att in raw.attachments or []:
        if att.get('is_inline'):
            continue
        ctype = (att.get('content_type') or '').lower()
        name = (att.get('name') or '').lower()
        if ctype in _DOCUMENT_CONTENT_TYPES or ctype.startswith(_DOCUMENT_CONTENT_PREFIXES):
            return True
        if name.endswith(_DOCUMENT_EXTENSIONS):
            return True
    return False


def build_context(raw: RawMessage) -> FunnelContext:
    """Decode/strip the message once; stages stay cheap and pure."""
    from ..channels import forwards

    body = thread_text.message_text(raw)
    sender = (raw.sender or '').strip()
    domain = sender.split('@')[1].lower() if '@' in sender else ''
    fwd = forwards.detect(raw.subject, body)
    return FunnelContext(
        raw=raw,
        body_text=body,
        new_content=thread_text.strip_quoted_history(body),
        subject_normalized=thread_text.normalize_subject(raw.subject),
        sender_email=sender,
        sender_domain=domain,
        has_calendar_part=raw.has_calendar_part,
        has_document_attachments=_has_document_attachments(raw),
        is_forward=fwd.is_forward,
        original_sender=fwd.original_sender,
    )


def _log(raw: RawMessage, stage: str, decision: StageDecision) -> None:
    FilterLog.objects.create(
        raw_message=raw,
        stage=stage,
        signals=decision.signals,
        score=decision.score,
        outcome=decision.outcome,
        dedup_hash=decision.signals.get('dedup_hash', '') if stage == '3_dedup' else '',
    )


def run_funnel(raw: RawMessage, force_extract: bool = False) -> FunnelResult:
    """Run the deterministic funnel over one message, logging every stage.

    ``force_extract`` (divert-store promotion, re-scoring pass-forwards) skips
    judgment entirely and records the override in the ledger.
    """
    ctx = build_context(raw)

    # Stage 0 — scope/entry record: how this message arrived and what channels
    # it carries. Pure bookkeeping, always 'pass'.
    scope = StageDecision(PASS, {
        'source': raw.source,
        'mailbox': raw.mailbox,
        'has_calendar_part': ctx.has_calendar_part,
        'has_document_attachments': ctx.has_document_attachments,
        'forced': force_extract,
    })
    _log(raw, '0_scope', scope)

    if force_extract:
        decision = StageDecision(EXTRACT, {'forced': True})
        _log(raw, 'extraction', decision)
        return FunnelResult(EXTRACT, '0_scope', ctx, decision)

    # Stage 1 — headers
    d1 = stage1_headers.evaluate(ctx)
    _log(raw, '1_headers', d1)
    if d1.outcome in (DIVERT, ESCALATE):
        return FunnelResult(d1.outcome, '1_headers', ctx, d1)

    # Stage 2 — reputation
    d2 = stage2_reputation.evaluate(ctx)
    _log(raw, '2_reputation', d2)
    if d2.outcome == DIVERT:
        return FunnelResult(DIVERT, '2_reputation', ctx, d2)

    # Stage 3 — dedup (identity-only for allowlisted senders)
    d3 = stage3_dedup.evaluate(ctx, identity_only=ctx.allowlisted)
    _log(raw, '3_dedup', d3)
    if d3.outcome == DIVERT:
        return FunnelResult(DIVERT, '3_dedup', ctx, d3)

    # Rate gate — before stage 4
    dg = rate_gate.evaluate(ctx)
    _log(raw, 'rate_gate', dg)
    if dg.outcome == ESCALATE:
        return FunnelResult(ESCALATE, 'rate_gate', ctx, dg)

    # Stage 4 — content heuristics; bypassed for allowlist and channel mail.
    bypass: Optional[str] = None
    if ctx.allowlisted:
        bypass = 'allowlist'
    elif ctx.has_calendar_part:
        bypass = 'calendar_part'
    elif ctx.has_document_attachments:
        bypass = 'document_attachments'

    if bypass:
        d4 = StageDecision(PASS, {'bypass': bypass})
    else:
        d4 = stage4_content.evaluate(ctx)
    _log(raw, '4_content', d4)
    if d4.outcome in (DIVERT, ESCALATE):
        return FunnelResult(d4.outcome, '4_content', ctx, d4)

    # Survived the funnel → extraction.
    return FunnelResult(EXTRACT, '4_content', ctx, d4)
