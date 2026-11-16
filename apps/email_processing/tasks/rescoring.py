# SPDX-License-Identifier: Apache-2.0
"""Divert re-scoring (spec §5, weekly beat).

Divert-store safety must not depend on a human scanning it: this task re-runs
Stage 4 (current anchor dictionary + current reputation) over recently diverted
messages. Anything that now scores pass-forward — a newly allowlisted sender, a
newly added anchor phrase — is promoted into the pipeline, tagged as a
re-score promotion so review cards can show the low-confidence provenance.
"""

import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from ..funnel import build_context
from ..funnel import stage2_reputation, stage4_content
from ..models import FilterLog, RawMessage
from .pipeline import run_pipeline

logger = logging.getLogger('apps.email_processing')


@shared_task
def rescore_diverted():
    """Re-run reputation + content scoring over the recent divert store."""
    window_days = getattr(settings, 'RESCORE_WINDOW_DAYS', 30)
    window_start = timezone.now() - timedelta(days=window_days)

    # Content-diverted messages only: header-diverted mail (List-Unsubscribe,
    # no-reply senders) is machine mail regardless of new anchors, and dedup
    # diverts must never re-enter. Reputation diverts DO requalify (the sender
    # may have been unblocked).
    diverted = (
        RawMessage.objects
        .filter(received_at__gte=window_start,
                filter_logs__outcome='divert',
                filter_logs__stage__in=['2_reputation', '4_content'])
        .exclude(filter_logs__outcome__in=['extract', 'escalate'])
        .exclude(filter_logs__signals__rescore_checked=True)
        .distinct()
    )

    promoted = 0
    checked = 0
    for raw in diverted.iterator():
        checked += 1
        ctx = build_context(raw)

        # Current reputation first (a block still stands; a new allow promotes).
        rep_decision = stage2_reputation.evaluate(ctx)
        if rep_decision.outcome == 'divert':
            promotable = False
        elif ctx.allowlisted:
            promotable = True
        else:
            content_decision = stage4_content.evaluate(ctx)
            promotable = content_decision.outcome == 'pass'

        # Mark as checked either way so the weekly run doesn't rescan forever.
        FilterLog.objects.create(
            raw_message=raw, stage='4_content',
            outcome='pass' if promotable else 'divert',
            signals={'rescore_checked': True, 'promoted': promotable},
        )

        if promotable:
            promoted += 1
            run_pipeline.delay(str(raw.id), force_extract=True)
            logger.info("Re-score promoted diverted message %s", raw.graph_message_id)

    logger.info("Divert re-scoring: checked=%d promoted=%d", checked, promoted)
    return {'checked': checked, 'promoted': promoted}
