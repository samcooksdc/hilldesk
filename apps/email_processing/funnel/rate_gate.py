# SPDX-License-Identifier: Apache-2.0
"""Rate gate — volume anomaly guard, evaluated before Stage 4.

A sender exceeding RATE_GATE_SENDER_LIMIT messages in RATE_GATE_WINDOW_MINUTES
(or mailbox-wide volume over RATE_GATE_MAILBOX_LIMIT) escalates — but as ONE
triage item per burst, not N: only the first over-limit message creates a
triage record (``burst_primary``); the rest are logged and folded.

Counts use ``received_at`` (mail-server receipt time), not fetch time, so an
initial delta sync backfilling history doesn't read as a burst.
"""

from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from ..models import FilterLog, RawMessage
from .base import ESCALATE, PASS, StageDecision


def evaluate(ctx) -> StageDecision:
    window_minutes = getattr(settings, 'RATE_GATE_WINDOW_MINUTES', 60)
    sender_limit = getattr(settings, 'RATE_GATE_SENDER_LIMIT', 20)
    mailbox_limit = getattr(settings, 'RATE_GATE_MAILBOX_LIMIT', 200)
    window_start = timezone.now() - timedelta(minutes=window_minutes)

    signals = {}

    sender_count = 0
    if ctx.raw.sender_key:
        sender_count = RawMessage.objects.filter(
            sender_key=ctx.raw.sender_key,
            received_at__gte=window_start,
        ).count()
    mailbox_count = RawMessage.objects.filter(
        mailbox=ctx.raw.mailbox,
        received_at__gte=window_start,
    ).count()
    signals['sender_count'] = sender_count
    signals['mailbox_count'] = mailbox_count

    sender_burst = sender_count > sender_limit
    mailbox_burst = mailbox_count > mailbox_limit
    if not sender_burst and not mailbox_burst:
        return StageDecision(PASS, signals)

    signals['burst'] = 'sender' if sender_burst else 'mailbox'

    # One triage item per burst: primary only if no rate-gate escalation for
    # this sender (or mailbox) already exists inside the window.
    if sender_burst and ctx.raw.sender_key:
        prior = FilterLog.objects.filter(
            stage='rate_gate', outcome='escalate',
            created_at__gte=window_start,
            raw_message__sender_key=ctx.raw.sender_key,
        ).exists()
    else:
        prior = FilterLog.objects.filter(
            stage='rate_gate', outcome='escalate',
            created_at__gte=window_start,
            raw_message__mailbox=ctx.raw.mailbox,
        ).exists()
    signals['burst_primary'] = not prior

    return StageDecision(ESCALATE, signals, score=float(max(sender_count, mailbox_count)))
