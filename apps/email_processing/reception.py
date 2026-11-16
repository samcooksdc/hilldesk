# SPDX-License-Identifier: Apache-2.0
"""Reception layer for the email ingestion pipeline.

Turns a Microsoft Graph message into an immutable :class:`RawMessage` (plus
stored :class:`AttachmentBlob` payloads) — the audit floor written *before* any
funnel/extraction logic runs. Idempotent: a message already present (by Graph
id) is never re-ingested, so sweeps and webhooks can both deliver the same id
safely.
"""

import base64
import logging
from datetime import datetime, timezone as dt_timezone
from typing import Any, Dict, List, Optional, Tuple

from django.conf import settings
from django.utils import timezone

from .graph_client import MicrosoftGraphClient
from .models import AttachmentBlob, RawMessage

logger = logging.getLogger('apps.email_processing')
security_logger = logging.getLogger('security_audit')

# Content types / extensions that mark a message as carrying a calendar object.
_CALENDAR_CONTENT_TYPES = {'text/calendar', 'application/ics'}


def headers_to_dict(internet_headers: Optional[List[Dict[str, str]]]) -> Dict[str, str]:
    """Flatten Graph ``internetMessageHeaders`` (a list of {name, value}) into a
    case-preserving dict. Duplicate header names are joined with newlines so
    multi-valued headers (e.g. Received) are not silently dropped."""
    result: Dict[str, str] = {}
    for header in internet_headers or []:
        name = (header or {}).get('name')
        value = (header or {}).get('value', '')
        if not name:
            continue
        if name in result:
            result[name] = f"{result[name]}\n{value}"
        else:
            result[name] = value
    return result


def _extract_sender(msg: Dict[str, Any]) -> Tuple[str, str]:
    """Return (email, display_name) from a Graph message's sender/from block."""
    holder = msg.get('sender') or msg.get('from') or {}
    addr = (holder.get('emailAddress') or {})
    return addr.get('address', '') or '', addr.get('name', '') or ''


def _parse_received(msg: Dict[str, Any]):
    """Parse receivedDateTime to an aware datetime, defaulting to now."""
    raw = msg.get('receivedDateTime')
    if not raw:
        return timezone.now()
    try:
        dt = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, dt_timezone.utc)
        return dt
    except (ValueError, TypeError):
        return timezone.now()


def _attachment_metadata(graph_attachments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Reduce Graph attachment objects to the metadata stored on RawMessage."""
    meta = []
    for att in graph_attachments:
        meta.append({
            'graph_id': att.get('id', ''),
            'name': att.get('name', ''),
            'content_type': att.get('contentType', ''),
            'size': att.get('size', 0) or 0,
            'is_inline': bool(att.get('isInline', False)),
            'content_id': att.get('contentId', '') or '',
        })
    return meta


def detect_calendar_part(msg: Dict[str, Any], attachment_meta: List[Dict[str, Any]]) -> bool:
    """True if the message carries a calendar object.

    Signals: an Outlook meeting-message type, a text/calendar attachment, or a
    ``.ics`` file attachment. Cheap and deterministic — the ICS channel (Phase 3)
    does the actual parsing; here we only flag presence so the funnel can route.
    """
    if msg.get('meetingMessageType') not in (None, 'none'):
        return True
    for att in attachment_meta:
        ctype = (att.get('content_type') or '').lower()
        name = (att.get('name') or '').lower()
        if ctype in _CALENDAR_CONTENT_TYPES or name.endswith('.ics'):
            return True
    return False


def _store_attachment_blobs(raw: RawMessage, graph_attachments: List[Dict[str, Any]]) -> int:
    """Persist attachment payloads at or below the size cap as AttachmentBlob
    rows. Returns the number stored. Oversized/reference attachments are skipped
    (kept as metadata only on the RawMessage; re-fetched from Graph on demand)."""
    max_bytes = getattr(settings, 'ATTACHMENT_STORE_MAX_BYTES', 10 * 1024 * 1024)
    stored = 0
    for att in graph_attachments:
        content_b64 = att.get('contentBytes')
        size = att.get('size', 0) or 0
        # Only fileAttachment items carry contentBytes; skip item/reference ones.
        if not content_b64 or size > max_bytes:
            continue
        try:
            payload = base64.b64decode(content_b64)
        except (ValueError, TypeError):
            logger.warning("Undecodable attachment %s on %s", att.get('name'), raw.graph_message_id)
            continue
        AttachmentBlob.objects.create(
            raw_message=raw,
            graph_attachment_id=att.get('id', '') or '',
            name=att.get('name', '') or '',
            content_type=att.get('contentType', '') or '',
            content_id=att.get('contentId', '') or '',
            size=size,
            is_inline=bool(att.get('isInline', False)),
            payload=payload,
        )
        stored += 1
    return stored


def ingest_message(
    client: MicrosoftGraphClient,
    mailbox: str,
    graph_message_id: str,
    source: str = 'sweep',
    full_message: Optional[Dict[str, Any]] = None,
) -> Tuple[Optional[RawMessage], bool]:
    """Fetch and persist one message as an immutable RawMessage.

    Idempotent: if a RawMessage already exists for ``graph_message_id`` it is
    returned unchanged with ``created=False`` (this is how sweep+webhook
    de-duplicate delivery of the same message).

    Returns ``(raw_message, created)``. ``raw_message`` is None only if the
    fetch failed.
    """
    existing = RawMessage.objects.filter(graph_message_id=graph_message_id).first()
    if existing is not None:
        return existing, False

    if full_message is None:
        full_message = client.get_message_full(mailbox, graph_message_id)

    graph_attachments: List[Dict[str, Any]] = []
    if full_message.get('hasAttachments'):
        try:
            graph_attachments = client.get_message_attachments(mailbox, graph_message_id)
        except Exception as exc:  # attachment fetch must not lose the message
            logger.warning("Attachment fetch failed for %s: %s", graph_message_id, exc)

    attachment_meta = _attachment_metadata(graph_attachments)
    sender_email, sender_name = _extract_sender(full_message)
    body = full_message.get('body') or {}
    body_content = body.get('content', '') or ''
    is_html = (body.get('contentType', '') or '').lower() == 'html'

    raw = RawMessage(
        graph_message_id=graph_message_id,
        internet_message_id=full_message.get('internetMessageId', '') or '',
        conversation_id=full_message.get('conversationId', '') or '',
        mailbox=mailbox,
        received_at=_parse_received(full_message),
        source=source,
        sender=sender_email,
        sender_name=sender_name,
        subject=(full_message.get('subject', '') or '')[:1000],
        headers=headers_to_dict(full_message.get('internetMessageHeaders')),
        body_html=body_content if is_html else '',
        body_text='' if is_html else body_content,
        attachments=attachment_meta,
        has_calendar_part=detect_calendar_part(full_message, attachment_meta),
    )
    raw.save()

    stored = _store_attachment_blobs(raw, graph_attachments)
    security_logger.info(
        'Raw message ingested',
        extra={
            'raw_message_id': str(raw.id),
            'mailbox': mailbox,
            'source': source,
            'has_calendar_part': raw.has_calendar_part,
            'attachments_stored': stored,
            'timestamp': timezone.now().isoformat(),
        },
    )
    return raw, True
