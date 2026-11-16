# SPDX-License-Identifier: Apache-2.0
"""Microsoft Graph change-notification webhook.

Optional latency accelerator (behind ``GRAPH_WEBHOOK_ENABLED``). Unauthenticated
by necessity — Graph cannot present a session — so the gate is: a valid
``clientState`` on every notification, plus strict payload-shape validation. No
data is trusted from the notification beyond the resource id; ``fetch_message``
re-reads the message from Graph.
"""

import json
import logging

from django.conf import settings
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import SubscriptionState
from .tasks.reception import fetch_message

logger = logging.getLogger('apps.email_processing')
security_logger = logging.getLogger('security_audit')


@csrf_exempt
@require_POST
def graph_webhook(request):
    """Handle the Graph subscription handshake and change notifications.

    - Handshake: Graph POSTs with a ``validationToken`` query param; echo it
      back verbatim as ``text/plain`` with 200.
    - Notifications: validate each notification's ``clientState``, then enqueue
      a fetch per valid notification and return 202 immediately.
    """
    if not getattr(settings, 'GRAPH_WEBHOOK_ENABLED', False):
        return HttpResponse(status=404)

    # Subscription validation handshake.
    validation_token = request.GET.get('validationToken')
    if validation_token is not None:
        return HttpResponse(validation_token, content_type='text/plain', status=200)

    try:
        payload = json.loads(request.body.decode('utf-8'))
        notifications = payload.get('value', [])
    except (ValueError, AttributeError, UnicodeDecodeError):
        logger.warning("graph_webhook: unparseable notification body")
        return JsonResponse({'error': 'invalid payload'}, status=400)

    if not isinstance(notifications, list):
        return JsonResponse({'error': 'invalid payload'}, status=400)

    expected_state = getattr(settings, 'GRAPH_WEBHOOK_CLIENT_STATE', '')
    queued = 0
    for notif in notifications:
        if not isinstance(notif, dict):
            continue
        # clientState is the shared secret; a mismatch means the notification is
        # not from our subscription — reject the whole request, do not process.
        if notif.get('clientState') != expected_state:
            security_logger.warning(
                'graph_webhook: clientState mismatch — rejecting notification batch',
                extra={'subscription_id': notif.get('subscriptionId')},
            )
            return HttpResponseForbidden('clientState mismatch')

        message_id = (notif.get('resourceData') or {}).get('id')
        subscription_id = notif.get('subscriptionId')
        if not message_id or not subscription_id:
            continue

        mailbox = (
            SubscriptionState.objects
            .filter(subscription_id=subscription_id)
            .values_list('mailbox', flat=True)
            .first()
        )
        if not mailbox:
            logger.warning("graph_webhook: no mailbox for subscription %s", subscription_id)
            continue

        fetch_message.delay(mailbox, message_id)
        queued += 1

    # 202: accepted; processing happens asynchronously.
    return HttpResponse(status=202)
