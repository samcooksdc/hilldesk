# SPDX-License-Identifier: Apache-2.0
"""Calendar-object channel: deterministic candidate extraction from ICS data.

A calendar part is machine-readable truth — no language model involved, every
candidate carries confidence 1.0. Mapping (spec §6.1):

- ``METHOD:REQUEST``            → NEW_EVENT (RECURRING_EVENT when an RRULE is present)
- ``METHOD:CANCEL``             → CANCELLATION
- ``RECURRENCE-ID`` on REQUEST  → RESCHEDULE of that single occurrence

The VEVENT UID goes into provenance for post-processing's exact-match against
previously materialized events. Candidates are plain dicts in the §7 schema
shape; Phase 4 persists them as ExtractionCandidate rows.
"""

import logging
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from django.conf import settings
from icalendar import Calendar

logger = logging.getLogger('apps.email_processing')

# Body prose below this length (after boilerplate stripping) is considered
# pure invite carrier — no additional body extraction runs.
DEFAULT_BODY_PROSE_THRESHOLD = 200

_BOILERPLATE_LINES = re.compile(
    r'^\s*('
    r'(please\s+)?(see|find)\s+(the\s+)?attached.*|'
    r'invite\s+(is\s+)?attached.*|'
    r'calendar\s+invite.*|'
    r'sent\s+from\s+my\s+\w+.*|'
    r'when:.*|where:.*|organizer:.*|'
    r'[-_*=]{3,}\s*'
    r')$',
    re.IGNORECASE,
)


def _ical_sources(raw_message) -> List[Dict[str, Any]]:
    """Yield {name, data} for every calendar payload stored on the message."""
    sources = []
    for blob in raw_message.attachment_blobs.all():
        ctype = (blob.content_type or '').lower()
        name = (blob.name or '').lower()
        if 'text/calendar' in ctype or 'application/ics' in ctype or name.endswith('.ics'):
            sources.append({'name': blob.name or 'calendar.ics',
                            'data': bytes(blob.payload)})
    return sources


def _fmt_date(value) -> Optional[str]:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return None


def _fmt_time(value) -> Optional[str]:
    if isinstance(value, datetime):
        return value.strftime('%H:%M')
    return None  # all-day (date-only) values carry no time


def _tz_name(value) -> str:
    if isinstance(value, datetime) and value.tzinfo is not None:
        return str(value.tzinfo)
    return ''


def _person(address_value, cn: str = '') -> Dict[str, Any]:
    email = str(address_value or '')
    if email.lower().startswith('mailto:'):
        email = email[7:]
    return {'name': cn or '', 'email': email, 'phone': None,
            'position': None, 'organization': None, 'source_span': None}


def _rrule_string(vevent) -> Optional[str]:
    rrule = vevent.get('RRULE')
    if rrule is None:
        return None
    try:
        return rrule.to_ical().decode('utf-8')
    except Exception:
        return None


def _rrule_has_end(rrule_str: Optional[str]) -> bool:
    if not rrule_str:
        return False
    upper = rrule_str.upper()
    return 'UNTIL=' in upper or 'COUNT=' in upper


def _vevent_to_candidate(vevent, method: str, source_name: str) -> Dict[str, Any]:
    dtstart = vevent.get('DTSTART')
    dtend = vevent.get('DTEND')
    start_value = dtstart.dt if dtstart is not None else None
    end_value = dtend.dt if dtend is not None else None

    recurrence_id = vevent.get('RECURRENCE-ID')
    rrule_str = _rrule_string(vevent)

    if method == 'CANCEL':
        intent = 'CANCELLATION'
    elif recurrence_id is not None:
        intent = 'RESCHEDULE'          # a single occurrence moved
    elif rrule_str:
        intent = 'RECURRING_EVENT'
    else:
        intent = 'NEW_EVENT'

    contacts = []
    organizer = vevent.get('ORGANIZER')
    if organizer is not None:
        contacts.append(_person(organizer, str(organizer.params.get('CN', ''))))
    attendees = vevent.get('ATTENDEE')
    if attendees is not None:
        if not isinstance(attendees, list):
            attendees = [attendees]
        for att in attendees:
            contacts.append(_person(att, str(att.params.get('CN', ''))))

    return {
        'intent': intent,
        'confidence': 1.0,
        'event': {
            'title': str(vevent.get('SUMMARY', '') or ''),
            'type': 'meeting',
            'format': None,
            'start_date': _fmt_date(start_value),
            'start_time': _fmt_time(start_value),
            'end_date': _fmt_date(end_value),
            'end_time': _fmt_time(end_value),
            'location': str(vevent.get('LOCATION', '') or ''),
            'description': str(vevent.get('DESCRIPTION', '') or ''),
            'legislative_topics': [],
            'participants': [c['name'] or c['email'] for c in contacts],
        },
        'verbatim': {
            'date_text': dtstart.to_ical().decode() if dtstart is not None else None,
            'time_text': None,
        },
        'timezone': {'proposed': _tz_name(start_value), 'basis': 'ics_dtstart'},
        'recurrence': {'rrule': rrule_str, 'has_end': _rrule_has_end(rrule_str)},
        'contacts': contacts,
        'organizations': [],
        'reschedule_target_hint': None,
        'cancellation_target_hint': (
            str(vevent.get('SUMMARY', '') or '') if intent == 'CANCELLATION' else None
        ),
        'source_span': None,
        'provenance': {
            'channel': f'attachment:{source_name}',
            'uid': str(vevent.get('UID', '') or ''),
            'method': method,
            'sequence': int(vevent.get('SEQUENCE', 0) or 0),
            'recurrence_id': (
                recurrence_id.dt.isoformat() if recurrence_id is not None else None
            ),
        },
    }


def parse_calendar_candidates(raw_message) -> List[Dict[str, Any]]:
    """Parse every stored calendar payload on the message into candidates.

    Unparseable payloads are logged and skipped — the caller decides whether a
    has_calendar_part message with zero parsed candidates should escalate.
    """
    candidates: List[Dict[str, Any]] = []
    for source in _ical_sources(raw_message):
        try:
            cal = Calendar.from_ical(source['data'])
        except Exception as exc:
            logger.warning("Unparseable calendar part %s on %s: %s",
                           source['name'], raw_message.graph_message_id, exc)
            continue
        method = str(cal.get('METHOD', 'REQUEST') or 'REQUEST').upper()
        for vevent in cal.walk('VEVENT'):
            try:
                candidates.append(_vevent_to_candidate(vevent, method, source['name']))
            except Exception as exc:
                logger.warning("VEVENT mapping failed in %s on %s: %s",
                               source['name'], raw_message.graph_message_id, exc)
    return candidates


def substantial_body_prose(body_text: str) -> bool:
    """True when the body carries real prose beyond invite boilerplate — in
    which case body extraction runs IN ADDITION to the deterministic ICS path
    (the human wrote something the invite doesn't capture)."""
    threshold = getattr(settings, 'ICS_BODY_PROSE_THRESHOLD',
                        DEFAULT_BODY_PROSE_THRESHOLD)
    kept = [
        line for line in (body_text or '').splitlines()
        if line.strip() and not _BOILERPLATE_LINES.match(line)
    ]
    return len(' '.join(kept)) > threshold
