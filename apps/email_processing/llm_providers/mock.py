# SPDX-License-Identifier: Apache-2.0
"""
Mock LLM Provider for offline development.

Implements ``extract_candidates`` with DETERMINISTIC candidate sets
keyed off content markers, so tests and demo scripts exercise the multi-event,
recurrence, reschedule, and cancellation paths with no network and no API key.

Markers (all case-insensitive, matched in the combined subject+body+attachment
text):

- Segmentation: paragraphs beginning ``EVENT:`` each become one candidate
  (multi-event fan-out). Without the marker, the whole message is one candidate.
- Intent: 'cancel'  → CANCELLATION; 'reschedule'/'move it'/'postpone' →
  RESCHEDULE; 'every week'/'weekly'/'monthly'/'recurring' → RECURRING_EVENT;
  otherwise NEW_EVENT (or UNCERTAIN when no date/time/scheduling signal exists).
- Recurrence end: 'until <anything>' or 'for N weeks/months' → has_end=True.
- Simple regex extraction for date (ISO or 'July 20'), time ('2pm', '14:00'),
  location ('Location: X' line or 'at/in <Title Case Place>'), organization
  ('on behalf of X' / 'Organization: X'), and signature contact details.
"""

import logging
import re
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from .base import BaseLLMProvider, DraftGenerationResult
from .schema import MessageBundle, RawModelOutput

logger = logging.getLogger(__name__)

_MONTHS = {
    'january': 1, 'february': 2, 'march': 3, 'april': 4, 'may': 5, 'june': 6,
    'july': 7, 'august': 8, 'september': 9, 'october': 10, 'november': 11,
    'december': 12,
}

_ISO_DATE = re.compile(r'\b(\d{4})-(\d{2})-(\d{2})\b')
_MONTH_DAY = re.compile(
    r'\b(january|february|march|april|may|june|july|august|september|october|'
    r'november|december)\s+(\d{1,2})\b', re.I)
_TIME = re.compile(r'\b(\d{1,2}):(\d{2})\s*(am|pm)?\b|\b(\d{1,2})\s*(am|pm)\b', re.I)
_LOCATION_LINE = re.compile(r'^\s*location:\s*(.+)$', re.I | re.M)
_AT_PLACE = re.compile(r'\b(?:at|in)\s+((?:the\s+)?[A-Z][\w.\'-]*(?:\s+[A-Z0-9][\w.\'-]*){0,5})')
_ORG_LINE = re.compile(r'^\s*organization:\s*(.+)$', re.I | re.M)
_ON_BEHALF = re.compile(r'on behalf of\s+((?:the\s+)?[A-Z][\w&.\'-]*(?:\s+[A-Z&][\w&.\'-]*){0,6})', re.I)
_TITLE_LINE = re.compile(r'^\s*(?:title|event):\s*(.+)$', re.I | re.M)
_EMAIL = re.compile(r'\b([\w.+-]+@[\w-]+\.[\w.-]+)\b')
_PHONE = re.compile(r'\(?\b\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b')
_UNTIL = re.compile(r'\buntil\b|\bthrough\s+(the\s+end|december|[a-z]+\s+\d)', re.I)
_FOR_N = re.compile(r'\bfor\s+(\d+|the next \d+)\s+(weeks?|months?|sessions?)\b', re.I)

_SCHEDULING_WORDS = ('meeting', 'meet', 'schedule', 'visit', 'briefing', 'event',
                     'invite', 'invitation', 'roundtable', 'tour', 'call',
                     'breakfast', 'luncheon', 'reception')


class MockProvider(BaseLLMProvider):
    """Offline provider producing schema-valid, deterministic candidate sets."""

    def extract_candidates(self, bundle: MessageBundle) -> RawModelOutput:
        text_parts = [bundle.subject or '', bundle.new_content or '']
        text_parts += [a.get('text', '') for a in bundle.attachment_texts]
        full_text = '\n'.join(p for p in text_parts if p)

        segments = self._segment(full_text)
        candidates = [
            self._candidate_from_segment(seg, bundle, idx)
            for idx, seg in enumerate(segments)
        ]
        return RawModelOutput(
            data={'candidates': candidates, 'notes': 'mock provider (deterministic)'},
            raw_text='',
        )

    # ------------------------------------------------------------------
    # Segmentation & candidate construction
    # ------------------------------------------------------------------

    def _segment(self, text: str) -> List[str]:
        """Lines starting with 'EVENT:' fan out into one segment each."""
        parts = re.split(r'(?=^[ \t]*EVENT[ \t]*:)', text, flags=re.I | re.M)
        event_blocks = [p for p in parts
                        if re.match(r'[ \t]*event[ \t]*:', p, re.I)]
        if len(event_blocks) >= 2:
            return event_blocks
        return [text]

    def _candidate_from_segment(self, segment: str, bundle: MessageBundle,
                                index: int) -> Dict[str, Any]:
        lower = segment.lower()

        rrule, has_end = self._recurrence(lower)
        if 'cancel' in lower:
            intent = 'CANCELLATION'
        elif any(w in lower for w in ('reschedul', 'move it', 'move the', 'postpon', 'push back')):
            intent = 'RESCHEDULE'
        elif rrule:
            intent = 'RECURRING_EVENT'
        else:
            intent = 'NEW_EVENT'

        start_date, date_text = self._extract_date(segment, bundle)
        start_time, time_text = self._extract_time(segment)
        location = self._extract_location(segment)
        organization = self._extract_organization(segment)
        title = self._extract_title(segment, bundle, organization)
        contacts = self._extract_contacts(segment, bundle, organization)

        has_signal = bool(start_date or start_time
                          or any(w in lower for w in _SCHEDULING_WORDS))
        if intent == 'NEW_EVENT' and not has_signal:
            intent = 'UNCERTAIN'

        if intent == 'CANCELLATION':
            confidence = 0.85
        elif intent == 'UNCERTAIN':
            confidence = 0.4
        elif start_date and start_time:
            confidence = 0.9
        elif start_date:
            confidence = 0.7
        else:
            confidence = 0.5

        target_hint = None
        if intent in ('RESCHEDULE', 'CANCELLATION'):
            target_hint = title or (bundle.subject or '').strip() or None

        anchor = segment.strip()[:40]
        span_start = max(0, (bundle.new_content or '').find(anchor.splitlines()[0] if anchor else ''))

        return {
            'intent': intent,
            'confidence': confidence,
            'event': {
                'title': title,
                'type': 'meeting',
                'format': None,
                'start_date': start_date,
                'start_time': start_time,
                'end_date': None,
                'end_time': None,
                'location': location,
                'description': segment.strip()[:500] or None,
                'legislative_topics': [],
                'participants': [c['name'] for c in contacts if c.get('name')],
            },
            'verbatim': {'date_text': date_text, 'time_text': time_text},
            'timezone': {
                'proposed': bundle.office_timezone,
                'basis': 'office_default (mock)',
            },
            'recurrence': {'rrule': rrule, 'has_end': has_end},
            'contacts': contacts,
            'organizations': (
                [{'name': organization, 'location': None, 'email': None,
                  'phone': None, 'source_span': None}] if organization else []
            ),
            'reschedule_target_hint': target_hint if intent == 'RESCHEDULE' else None,
            'cancellation_target_hint': target_hint if intent == 'CANCELLATION' else None,
            'source_span': [span_start, span_start + len(anchor)] if anchor else None,
        }

    # ------------------------------------------------------------------
    # Deterministic field extraction
    # ------------------------------------------------------------------

    def _extract_date(self, text: str, bundle: MessageBundle) -> Tuple[Optional[str], Optional[str]]:
        m = _ISO_DATE.search(text)
        if m:
            return m.group(0), m.group(0)
        m = _MONTH_DAY.search(text)
        if m:
            month = _MONTHS[m.group(1).lower()]
            day = int(m.group(2))
            year = self._reference_year(bundle, month)
            try:
                return date(year, month, day).isoformat(), m.group(0)
            except ValueError:
                return None, m.group(0)
        return None, None

    def _reference_year(self, bundle: MessageBundle, month: int) -> int:
        """Resolve a yearless date against the received date (never past)."""
        ref_year, ref_month = 2026, 1
        m = re.match(r'(\d{4})-(\d{2})', bundle.received_at_iso or '')
        if m:
            ref_year, ref_month = int(m.group(1)), int(m.group(2))
        return ref_year + 1 if month < ref_month else ref_year

    def _extract_time(self, text: str) -> Tuple[Optional[str], Optional[str]]:
        m = _TIME.search(text)
        if not m:
            return None, None
        if m.group(1) is not None:
            hour, minute, ampm = int(m.group(1)), int(m.group(2)), m.group(3)
        else:
            hour, minute, ampm = int(m.group(4)), 0, m.group(5)
        if ampm:
            if ampm.lower() == 'pm' and hour != 12:
                hour += 12
            if ampm.lower() == 'am' and hour == 12:
                hour = 0
        if not (0 <= hour <= 23):
            return None, m.group(0)
        return f"{hour:02d}:{minute:02d}", m.group(0)

    def _extract_location(self, text: str) -> Optional[str]:
        m = _LOCATION_LINE.search(text)
        if m:
            return m.group(1).strip()
        m = _AT_PLACE.search(text)
        if m:
            return m.group(1).strip()
        return None

    def _extract_organization(self, text: str) -> Optional[str]:
        m = _ORG_LINE.search(text)
        if m:
            return m.group(1).strip()
        m = _ON_BEHALF.search(text)
        if m:
            return m.group(1).strip()
        return None

    def _extract_title(self, text: str, bundle: MessageBundle,
                       organization: Optional[str]) -> Optional[str]:
        m = _TITLE_LINE.search(text)
        if m:
            return m.group(1).strip()
        subject = (bundle.subject or '').strip()
        if subject:
            return subject
        if organization:
            return f"Meeting with {organization}"
        return None

    def _extract_contacts(self, text: str, bundle: MessageBundle,
                          organization: Optional[str]) -> List[Dict[str, Any]]:
        contacts = []
        sender_name = (bundle.sender_name or '').strip()
        sender_email = (bundle.sender_email or '').strip()
        if sender_name or sender_email:
            phone_m = _PHONE.search(text)
            contacts.append({
                'name': sender_name or sender_email,
                'email': sender_email or None,
                'phone': phone_m.group(0) if phone_m else None,
                'position': None,
                'organization': organization,
                'role': 'point_of_contact',
                'source_span': None,
            })
        # Additional emails in the body become attendees.
        for email in _EMAIL.findall(text):
            if email.lower() == sender_email.lower():
                continue
            contacts.append({
                'name': email.split('@')[0].replace('.', ' ').title(),
                'email': email,
                'phone': None,
                'position': None,
                'organization': organization,
                'role': 'attendee',
                'source_span': None,
            })
        return contacts

    def _recurrence(self, lower: str) -> Tuple[Optional[str], bool]:
        rrule = None
        if 'every week' in lower or 'weekly' in lower:
            rrule = 'FREQ=WEEKLY'
        elif 'every month' in lower or 'monthly' in lower:
            rrule = 'FREQ=MONTHLY'
        elif 'every day' in lower or 'daily' in lower:
            rrule = 'FREQ=DAILY'
        elif 'recurring' in lower or 'every ' in lower:
            rrule = 'FREQ=WEEKLY'
        if rrule is None:
            return None, False

        has_end = False
        m = _FOR_N.search(lower)
        if m:
            count = re.search(r'\d+', m.group(1))
            if count:
                rrule += f';COUNT={count.group(0)}'
                has_end = True
        elif _UNTIL.search(lower):
            rrule += ';UNTIL=20261231T000000Z'
            has_end = True
        return rrule, has_end

    # ------------------------------------------------------------------
    # Draft generation (unchanged surface, used by draft_generation_service)
    # ------------------------------------------------------------------

    def generate_email_draft(self, inbound_email, event_context, template_text=None,
                             refinement=None, previous_draft=None, user_prompt=None):
        """
        Generate a mock email draft response.
        Returns a professional canned response using event context.
        """
        member = event_context.get('member_name', '{member_name}')
        event_title = event_context.get('event_title', '{event_title}')
        event_date = event_context.get('event_date', '{event_date}')
        staffer = event_context.get('staffer_name', '{staffer_name}')
        sender = event_context.get('sender_name', '{sender_name}')

        if refinement == 'shorter':
            draft = (
                f"Dear {sender},\n\n"
                f"Thank you for the invitation. {member} will attend {event_title} on {event_date}.\n\n"
                f"Best regards,\n{staffer}"
            )
        elif refinement == 'more_formal':
            draft = (
                f"Dear {sender},\n\n"
                f"On behalf of {member}, I write to acknowledge receipt of your correspondence "
                f"regarding {event_title}. The office has reviewed the scheduling details and "
                f"is pleased to confirm participation on {event_date}.\n\n"
                f"Should any additional information be required, please do not hesitate to "
                f"contact our office.\n\n"
                f"Respectfully,\n{staffer}"
            )
        else:
            draft = (
                f"Dear {sender},\n\n"
                f"Thank you for reaching out regarding {event_title}. {member} appreciates the "
                f"invitation and we are pleased to confirm attendance on {event_date}.\n\n"
                f"Please let us know if there are any logistical details we should be aware of, "
                f"including parking, building access, or materials to review in advance.\n\n"
                f"We look forward to it.\n\n"
                f"Best regards,\n{staffer}"
            )

        logger.debug(f"Mock draft generated (refinement={refinement})")
        return DraftGenerationResult(
            draft_text=draft,
            tone='professional',
            confidence=0.85,
            warnings=['This is a mock draft for development']
        )

    def generate_email_draft_stream(self, inbound_email, event_context, template_text=None,
                                     refinement=None, previous_draft=None, user_prompt=None):
        """
        Generate mock draft with simulated streaming.
        Yields words one at a time with small delays.
        """
        import time
        result = self.generate_email_draft(
            inbound_email, event_context, template_text, refinement, previous_draft,
            user_prompt=user_prompt,
        )
        words = result.draft_text.split(' ')
        for i, word in enumerate(words):
            separator = ' ' if i > 0 else ''
            yield separator + word
            time.sleep(0.03)

    def health_check(self) -> bool:
        """
        Check if the mock provider is healthy.

        Always returns True since there are no external dependencies.

        Returns:
            True (always healthy)
        """
        logger.debug("Mock provider health check: OK")
        return True
