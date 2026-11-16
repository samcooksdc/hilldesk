# SPDX-License-Identifier: Apache-2.0
"""Funnel Stage 3 — dedup. MESSAGE IDENTITY ONLY.

Two checks, both about "have we already processed this exact message":

(a) Same ``internet_message_id`` on another RawMessage whose pipeline already
    ran → duplicate delivery (e.g. the same mail landing in two subscribed
    mailboxes, or a webhook/sweep race that slipped past reception idempotency).
(b) Normalized hash of (sender, Re/Fwd-stripped subject, quoted-history-
    stripped NEW content, attachment names) seen within ``DEDUP_WINDOW_DAYS``
    → content-identical resend.

Explicitly NOT thread similarity. A new message in an existing conversation is
never a duplicate no matter how much history it quotes — the stripping happens
*before* hashing, so a short "move it to 3pm" reply hashes on "move it to 3pm",
not on the quoted thread. tests/test_dedup_vs_reschedule.py guards this.
"""

import hashlib
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from ..models import FilterLog, RawMessage
from .base import DIVERT, PASS, StageDecision


def compute_dedup_hash(sender_email: str, subject_normalized: str,
                       new_content: str, attachment_names) -> str:
    """Stable content fingerprint for near-duplicate detection.

    Normalization: lowercased sender, prefix-stripped subject, whitespace-
    collapsed new content, sorted attachment names (so an attachment-only
    message with an empty body still fingerprints on what it carries).
    """
    content_norm = ' '.join((new_content or '').split()).lower()
    names = ','.join(sorted((n or '').lower() for n in attachment_names))
    material = '|'.join([
        (sender_email or '').strip().lower(),
        subject_normalized or '',
        content_norm,
        names,
    ])
    return hashlib.sha256(material.encode('utf-8')).hexdigest()


def evaluate(ctx, identity_only: bool = False) -> StageDecision:
    """``identity_only`` (allowlisted senders): run check (a) but skip the
    content hash — a stakeholder's similar-looking messages are never dropped
    by a fingerprint, only exact redelivery is."""
    signals = {}

    # (a) Duplicate delivery by RFC-5322 Message-ID.
    imid = ctx.raw.internet_message_id
    if imid:
        prior = (RawMessage.objects
                 .filter(internet_message_id=imid)
                 .exclude(pk=ctx.raw.pk))
        if prior.exists() and FilterLog.objects.filter(raw_message__in=prior).exists():
            signals['duplicate_of'] = 'internet_message_id'
            signals['internet_message_id'] = imid
            return StageDecision(DIVERT, signals)

    dedup_hash = compute_dedup_hash(
        ctx.sender_email,
        ctx.subject_normalized,
        ctx.new_content,
        [a.get('name', '') for a in (ctx.raw.attachments or [])],
    )
    signals['dedup_hash'] = dedup_hash

    if identity_only:
        signals['content_hash_skipped'] = 'allowlisted'
        return StageDecision(PASS, signals)

    # (b) Content-identical resend within the window. Every stage-3 log row
    # carries the hash, so presence of ANY prior row with this hash means the
    # same content already went through the funnel.
    window_days = getattr(settings, 'DEDUP_WINDOW_DAYS', 14)
    window_start = timezone.now() - timedelta(days=window_days)
    duplicate = (FilterLog.objects
                 .filter(stage='3_dedup',
                         dedup_hash=dedup_hash,
                         created_at__gte=window_start)
                 .exclude(raw_message=ctx.raw)
                 .exists())
    if duplicate:
        signals['duplicate_of'] = 'content_hash'
        return StageDecision(DIVERT, signals)

    return StageDecision(PASS, signals)
