# SPDX-License-Identifier: Apache-2.0
"""Reception tasks: sweep (primary), webhook fan-in, and subscription lifecycle.

The sweep is the always-on front door. Every ``INGEST_SWEEP_MINUTES`` it delta-
queries each mailbox in ``SCHEDULING_MAILBOXES``, persists any message not yet
seen as a RawMessage, and enqueues ``run_pipeline``. Webhooks (optional) merely
lower latency by calling ``fetch_message`` sooner; because the sweep re-reads
from Graph, a lapsed/disabled webhook degrades latency, not correctness.
"""

import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from ..graph_client import MicrosoftGraphClient, GraphAPIError
from ..models import RawMessage, SubscriptionState
from ..reception import ingest_message
from .pipeline import run_pipeline

logger = logging.getLogger('apps.email_processing')
security_logger = logging.getLogger('security_audit')

# Graph mail subscriptions max out well under 3 days; renew inside 24h.
_SUBSCRIPTION_LIFETIME_MINUTES = 4230  # ~2.9 days, safely under the Graph cap
_INBOX_RESOURCE = "users/{mailbox}/mailFolders/inbox/messages"


def _scheduling_mailboxes():
    return getattr(settings, 'SCHEDULING_MAILBOXES', []) or []


@shared_task
def ingestion_sweep():
    """Beat task: reconcile every scheduling mailbox. Fans out per mailbox."""
    mailboxes = _scheduling_mailboxes()
    if not mailboxes:
        logger.info("ingestion_sweep: no SCHEDULING_MAILBOXES configured; nothing to do")
        return {'mailboxes': 0}
    for mailbox in mailboxes:
        sweep_mailbox.delay(mailbox)
    return {'mailboxes': len(mailboxes)}


@shared_task(bind=True, max_retries=3)
def sweep_mailbox(self, mailbox: str):
    """Delta-sweep one mailbox, ingesting any message not already seen.

    Uses the persisted delta token for an incremental read; on an invalidated
    token falls back to a received-time window listing and resets the token so
    the next sweep re-establishes delta. New messages are ingested and pushed
    into the pipeline; a message that is new *here* while webhooks are enabled is
    logged as a reconciliation gap (the webhook silently dropped it).
    """
    client = MicrosoftGraphClient()
    state, _ = SubscriptionState.objects.get_or_create(
        mailbox=mailbox,
        defaults={'resource': _INBOX_RESOURCE.format(mailbox=mailbox)},
    )

    used_fallback = False
    try:
        result = client.delta_messages(mailbox, delta_link=state.delta_token or None)
        messages = result['messages']
        new_delta_link = result['delta_link']
    except GraphAPIError as exc:
        used_fallback = True
        logger.warning("sweep_mailbox(%s): delta failed (%s); window-listing", mailbox, exc)
        since = state.last_sweep_at or (timezone.now() - timedelta(days=1))
        try:
            messages = client.list_recent_messages(mailbox, since=since)
        except GraphAPIError as exc2:
            logger.error("sweep_mailbox(%s): window listing also failed: %s", mailbox, exc2)
            raise self.retry(countdown=60 * (2 ** self.request.retries), exc=exc2)
        new_delta_link = ''  # force a fresh full delta sync next run

    webhook_enabled = getattr(settings, 'GRAPH_WEBHOOK_ENABLED', False)
    ingested = 0
    gaps = 0
    for msg in messages:
        graph_id = msg.get('id')
        if not graph_id or RawMessage.objects.filter(graph_message_id=graph_id).exists():
            continue
        try:
            raw, created = ingest_message(client, mailbox, graph_id, source='sweep')
        except GraphAPIError as exc:
            logger.warning("sweep_mailbox(%s): ingest of %s failed: %s", mailbox, graph_id, exc)
            continue
        if not created or raw is None:
            continue
        ingested += 1
        run_pipeline.delay(str(raw.id))
        if webhook_enabled:
            gaps += 1
            security_logger.warning(
                'Reconciliation gap: sweep found a message the webhook missed',
                extra={'mailbox': mailbox, 'raw_message_id': str(raw.id),
                       'graph_message_id': graph_id, 'timestamp': timezone.now().isoformat()},
            )

    # SubscriptionState is mutable bookkeeping (unlike the immutable RawMessage).
    state.delta_token = new_delta_link or ''
    state.last_sweep_at = timezone.now()
    state.last_reconciled_at = timezone.now()
    state.save(update_fields=['delta_token', 'last_sweep_at', 'last_reconciled_at', 'updated_at'])

    logger.info("sweep_mailbox(%s): ingested=%d gaps=%d fallback=%s",
                mailbox, ingested, gaps, used_fallback)
    return {'mailbox': mailbox, 'ingested': ingested, 'gaps': gaps, 'fallback': used_fallback}


@shared_task(bind=True, max_retries=3)
def fetch_message(self, mailbox: str, graph_message_id: str):
    """Fetch and ingest a single message (webhook fan-in path).

    The webhook notification is trusted only for the resource id; this task
    re-reads the message from Graph. Idempotent against the sweep via the
    RawMessage id check inside ``ingest_message``.
    """
    client = MicrosoftGraphClient()
    try:
        raw, created = ingest_message(client, mailbox, graph_message_id, source='webhook')
    except GraphAPIError as exc:
        logger.warning("fetch_message(%s, %s) failed: %s", mailbox, graph_message_id, exc)
        raise self.retry(countdown=30 * (2 ** self.request.retries), exc=exc)
    if raw is not None and created:
        run_pipeline.delay(str(raw.id))
    return {'mailbox': mailbox, 'created': bool(created and raw is not None)}


@shared_task
def manage_subscriptions():
    """Create missing subscriptions and renew expiring ones (webhook lifecycle).

    No-op unless ``GRAPH_WEBHOOK_ENABLED``. Renewal failure marks the mailbox's
    subscription ``lapsed`` and logs at CRITICAL — the sweep keeps mail flowing
    meanwhile, which is what makes a lapse survivable.
    """
    if not getattr(settings, 'GRAPH_WEBHOOK_ENABLED', False):
        return {'enabled': False}

    notification_url = getattr(settings, 'GRAPH_WEBHOOK_NOTIFICATION_URL', '')
    client_state = getattr(settings, 'GRAPH_WEBHOOK_CLIENT_STATE', '')
    if not notification_url or not client_state:
        logger.error("manage_subscriptions: webhook enabled but notification URL / client state missing")
        return {'enabled': True, 'error': 'misconfigured'}

    client = MicrosoftGraphClient()
    created = renewed = failed = 0
    for mailbox in _scheduling_mailboxes():
        state, _ = SubscriptionState.objects.get_or_create(
            mailbox=mailbox,
            defaults={'resource': _INBOX_RESOURCE.format(mailbox=mailbox)},
        )
        resource = state.resource or _INBOX_RESOURCE.format(mailbox=mailbox)
        expiration = timezone.now() + timedelta(minutes=_SUBSCRIPTION_LIFETIME_MINUTES)
        try:
            if not state.subscription_id:
                resp = client.create_subscription(resource, notification_url, client_state, expiration)
                state.subscription_id = resp.get('id', '') or ''
                state.expires_at = expiration
                state.last_renewed_at = timezone.now()
                state.last_renewal_error = ''
                state.status = 'active'
                state.resource = resource
                state.save()
                created += 1
            elif state.needs_renewal:
                client.renew_subscription(state.subscription_id, expiration)
                state.expires_at = expiration
                state.last_renewed_at = timezone.now()
                state.last_renewal_error = ''
                state.status = 'active'
                state.save()
                renewed += 1
        except GraphAPIError as exc:
            failed += 1
            state.status = 'lapsed'
            state.last_renewal_error = str(exc)
            state.save()
            security_logger.critical(
                'Graph subscription lapsed — falling back to sweep-only delivery',
                extra={'mailbox': mailbox, 'subscription_id': state.subscription_id,
                       'error': str(exc), 'timestamp': timezone.now().isoformat()},
            )

    return {'enabled': True, 'created': created, 'renewed': renewed, 'failed': failed}
