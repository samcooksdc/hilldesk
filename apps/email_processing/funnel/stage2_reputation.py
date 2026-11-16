# SPDX-License-Identifier: Apache-2.0
"""Funnel Stage 2 — sender reputation.

Blind-index lookup on the sender address, then a plaintext lookup on the
domain. For forwarded mail with a recoverable original sender, the ORIGINAL
address is judged — an internal allowlisted forwarder must not launder an
unknown external request past scrutiny. Semantics:

- ``block`` → divert.
- ``allow`` → pass, AND the engine skips content scoring (stage 4) plus the
  content-hash half of dedup entirely: a known stakeholder is never dropped by
  a threshold. (Exact duplicate-delivery dedup still applies — redelivery of
  the same message is a transport artifact, not a judgment call.)
- no row / ``unknown`` → pass with ``unknown_sender`` set, which biases stage 4
  toward pass-forward.
"""

from django.utils import timezone

from apps.contacts.crypto import email_blind_index

from ..models import SenderReputation
from .base import DIVERT, PASS, StageDecision


def evaluate(ctx) -> StageDecision:
    signals = {}
    rep = None
    basis = None

    subject_email = (ctx.reputation_sender or '').strip()
    subject_key = email_blind_index(subject_email) if subject_email else ''
    subject_domain = (subject_email.split('@')[1].lower()
                      if '@' in subject_email else '')
    if ctx.is_forward and ctx.original_sender:
        signals['judged'] = 'forwarded_original'

    if subject_key:
        rep = (SenderReputation.objects
               .exclude(sender_key='')
               .filter(sender_key=subject_key)
               .first())
        if rep is not None:
            basis = 'sender'
    if rep is None and subject_domain:
        rep = (SenderReputation.objects
               .exclude(domain='')
               .filter(domain=subject_domain)
               .first())
        if rep is not None:
            basis = 'domain'

    if rep is None:
        ctx.unknown_sender = True
        signals['reputation'] = 'none'
        return StageDecision(PASS, signals)

    # Bookkeeping only — cheap, and keeps the reputation page honest about
    # which entries are live.
    SenderReputation.objects.filter(pk=rep.pk).update(last_seen=timezone.now())

    signals['reputation'] = rep.list
    signals['basis'] = basis
    ctx.unknown_sender = rep.list != 'allow'

    if rep.list == 'block':
        return StageDecision(DIVERT, signals)
    if rep.list == 'allow':
        ctx.allowlisted = True
    return StageDecision(PASS, signals)
