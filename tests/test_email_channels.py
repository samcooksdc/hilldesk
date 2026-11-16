# SPDX-License-Identifier: Apache-2.0
"""Phase 3 (channels) tests: ICS parsing, document harvest, forward detection,
and the forward→reputation funnel integration.
"""
import base64
from io import BytesIO

from django.test import TestCase

from apps.email_processing.channels import documents, forwards, ics
from apps.email_processing.models import AttachmentBlob, FilterLog, SenderReputation
from apps.email_processing.tasks.pipeline import run_pipeline

from .test_email_funnel import make_raw


# ---------------------------------------------------------------------------
# ICS fixtures
# ---------------------------------------------------------------------------

ICS_REQUEST = b"""BEGIN:VCALENDAR
PRODID:-//Microsoft Corporation//Outlook 16.0 MIMEDIR//EN
VERSION:2.0
METHOD:REQUEST
BEGIN:VEVENT
UID:040000008200E00074C5B7101A82E00800000000C0@example.com
SUMMARY:Workforce Development Roundtable
DTSTART;TZID=America/New_York:20260716T140000
DTEND;TZID=America/New_York:20260716T150000
LOCATION:2411 Rayburn HOB
DESCRIPTION:Quarterly roundtable with alliance members.
ORGANIZER;CN=Jane Doe:mailto:jane@mma.example
ATTENDEE;CN=Rep. Smith:mailto:scheduler@mail.example.com
SEQUENCE:0
END:VEVENT
END:VCALENDAR
"""

ICS_RECURRING = b"""BEGIN:VCALENDAR
VERSION:2.0
METHOD:REQUEST
BEGIN:VEVENT
UID:recurring-uid-1@example.com
SUMMARY:Weekly Ag Policy Sync
DTSTART;TZID=America/New_York:20260713T090000
DTEND;TZID=America/New_York:20260713T093000
RRULE:FREQ=WEEKLY;BYDAY=MO;COUNT=10
END:VEVENT
END:VCALENDAR
"""

ICS_RECURRING_OPEN_ENDED = b"""BEGIN:VCALENDAR
VERSION:2.0
METHOD:REQUEST
BEGIN:VEVENT
UID:recurring-uid-2@example.com
SUMMARY:Monthly Kiwanis Breakfast
DTSTART;TZID=America/New_York:20260801T080000
RRULE:FREQ=MONTHLY;BYMONTHDAY=1
END:VEVENT
END:VCALENDAR
"""

ICS_CANCEL = b"""BEGIN:VCALENDAR
VERSION:2.0
METHOD:CANCEL
BEGIN:VEVENT
UID:040000008200E00074C5B7101A82E00800000000C0@example.com
SUMMARY:Workforce Development Roundtable
DTSTART;TZID=America/New_York:20260716T140000
SEQUENCE:1
END:VEVENT
END:VCALENDAR
"""

ICS_RESCHEDULE_ONE = b"""BEGIN:VCALENDAR
VERSION:2.0
METHOD:REQUEST
BEGIN:VEVENT
UID:recurring-uid-1@example.com
RECURRENCE-ID;TZID=America/New_York:20260720T090000
SUMMARY:Weekly Ag Policy Sync
DTSTART;TZID=America/New_York:20260721T100000
DTEND;TZID=America/New_York:20260721T103000
SEQUENCE:2
END:VEVENT
END:VCALENDAR
"""


def make_raw_with_ics(ics_bytes, **overrides):
    raw = make_raw(
        has_calendar_part=True,
        attachments=[{'name': 'invite.ics', 'content_type': 'text/calendar',
                      'size': len(ics_bytes), 'is_inline': False}],
        **overrides,
    )
    AttachmentBlob.objects.create(
        raw_message=raw, name='invite.ics', content_type='text/calendar',
        size=len(ics_bytes), payload=ics_bytes,
    )
    return raw


class IcsChannelTests(TestCase):
    def test_request_parses_to_new_event_candidate(self):
        raw = make_raw_with_ics(ICS_REQUEST)
        candidates = ics.parse_calendar_candidates(raw)
        self.assertEqual(len(candidates), 1)
        c = candidates[0]
        self.assertEqual(c['intent'], 'NEW_EVENT')
        self.assertEqual(c['confidence'], 1.0)
        self.assertEqual(c['event']['title'], 'Workforce Development Roundtable')
        self.assertEqual(c['event']['start_date'], '2026-07-16')
        self.assertEqual(c['event']['start_time'], '14:00')
        self.assertEqual(c['event']['end_time'], '15:00')
        self.assertEqual(c['event']['location'], '2411 Rayburn HOB')
        self.assertEqual(c['timezone']['proposed'], 'America/New_York')
        self.assertIn('jane@mma.example', [p['email'] for p in c['contacts']])
        self.assertTrue(c['provenance']['uid'].startswith('040000008200'))
        self.assertEqual(c['provenance']['method'], 'REQUEST')

    def test_rrule_maps_to_recurring_event(self):
        raw = make_raw_with_ics(ICS_RECURRING)
        c = ics.parse_calendar_candidates(raw)[0]
        self.assertEqual(c['intent'], 'RECURRING_EVENT')
        self.assertIn('FREQ=WEEKLY', c['recurrence']['rrule'])
        self.assertTrue(c['recurrence']['has_end'])  # COUNT=10

    def test_open_ended_rrule_flags_missing_end(self):
        raw = make_raw_with_ics(ICS_RECURRING_OPEN_ENDED)
        c = ics.parse_calendar_candidates(raw)[0]
        self.assertEqual(c['intent'], 'RECURRING_EVENT')
        self.assertFalse(c['recurrence']['has_end'])

    def test_cancel_maps_to_cancellation(self):
        raw = make_raw_with_ics(ICS_CANCEL)
        c = ics.parse_calendar_candidates(raw)[0]
        self.assertEqual(c['intent'], 'CANCELLATION')
        self.assertEqual(c['cancellation_target_hint'], 'Workforce Development Roundtable')

    def test_recurrence_id_maps_to_reschedule_of_occurrence(self):
        raw = make_raw_with_ics(ICS_RESCHEDULE_ONE)
        c = ics.parse_calendar_candidates(raw)[0]
        self.assertEqual(c['intent'], 'RESCHEDULE')
        self.assertEqual(c['provenance']['recurrence_id'][:10], '2026-07-20')
        self.assertEqual(c['event']['start_date'], '2026-07-21')

    def test_unparseable_calendar_yields_no_candidates(self):
        raw = make_raw_with_ics(b'NOT A CALENDAR')
        self.assertEqual(ics.parse_calendar_candidates(raw), [])

    def test_body_prose_threshold(self):
        self.assertFalse(ics.substantial_body_prose(
            'Please see attached.\nSent from my iPhone'))
        prose = ('Beyond the invite, we would also like to discuss the pending '
                 'workforce bill and introduce our new executive director, who '
                 'will be joining the meeting along with two board members from '
                 'the Fairview chapter. Please let us know about press availability '
                 'and whether the Congresswoman can stay for photos afterward.')
        self.assertTrue(ics.substantial_body_prose(prose))


# ---------------------------------------------------------------------------
# Document harvest
# ---------------------------------------------------------------------------

# Minimal but valid single-page PDF with one text object.
MINIMAL_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]"
    b"/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
    b"4 0 obj<</Length 96>>stream\n"
    b"BT /F1 12 Tf 72 720 Td (Invitation: Community Breakfast on July 20 at "
    b"9:00 AM in Fairview) Tj ET\n"
    b"endstream endobj\n"
    b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
    b"xref\n0 6\n0000000000 65535 f \n"
    b"trailer<</Size 6/Root 1 0 R>>\n"
    b"startxref\n0\n%%EOF\n"
)


def _docx_bytes(paragraphs):
    from docx import Document
    doc = Document()
    for p in paragraphs:
        doc.add_paragraph(p)
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


class DocumentHarvestTests(TestCase):
    def _raw_with_attachment(self, name, content_type, payload):
        raw = make_raw(
            attachments=[{'name': name, 'content_type': content_type,
                          'size': len(payload), 'is_inline': False}],
        )
        AttachmentBlob.objects.create(
            raw_message=raw, name=name, content_type=content_type,
            size=len(payload), payload=payload,
        )
        return raw

    def test_pdf_text_harvest(self):
        raw = self._raw_with_attachment('invite.pdf', 'application/pdf', MINIMAL_PDF)
        result = documents.harvest(raw)
        self.assertEqual(len(result.texts), 1)
        self.assertIn('Community Breakfast', result.texts[0]['text'])
        self.assertEqual(result.failures, [])

    def test_docx_text_harvest(self):
        payload = _docx_bytes([
            'You are cordially invited to the annual Veterans Luncheon.',
            'Friday, August 14 at noon, American Legion Post 49.',
        ])
        raw = self._raw_with_attachment(
            'invite.docx',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            payload,
        )
        result = documents.harvest(raw)
        self.assertEqual(len(result.texts), 1)
        self.assertIn('Veterans Luncheon', result.texts[0]['text'])

    def test_image_collected_for_vision(self):
        png = base64.b64decode(
            'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQ'
            'DwAEhQGAhKmMIQAAAABJRU5ErkJggg=='
        )
        raw = self._raw_with_attachment('flyer.png', 'image/png', png)
        result = documents.harvest(raw)
        self.assertEqual(result.texts, [])
        self.assertEqual(len(result.images), 1)
        self.assertEqual(result.images[0]['content_type'], 'image/png')

    def test_unstored_oversized_attachment_reports_failure(self):
        raw = make_raw(attachments=[{
            'name': 'huge.pdf', 'content_type': 'application/pdf',
            'size': 50_000_000, 'is_inline': False,
        }])  # metadata only — no blob stored
        result = documents.harvest(raw)
        self.assertEqual(result.failures, [{'name': 'huge.pdf', 'reason': 'not_stored'}])

    def test_corrupt_pdf_reports_failure(self):
        raw = self._raw_with_attachment('bad.pdf', 'application/pdf', b'%PDF-broken')
        result = documents.harvest(raw)
        self.assertEqual(len(result.failures), 1)
        self.assertIn('pdf_unreadable', result.failures[0]['reason'])


# ---------------------------------------------------------------------------
# Forward detection + reputation integration
# ---------------------------------------------------------------------------

OUTLOOK_FORWARD_BODY = (
    "Flagging this — can we fit it in?\n\n"
    "________________________________\n"
    "From: Jane Doe <jane@mma.example>\n"
    "Sent: Monday, July 6, 2026 9:15 AM\n"
    "To: Scheduling <scheduling@mail.example.com>\n"
    "Subject: Meeting request\n\n"
    "We would like to request a meeting with the Congresswoman next Thursday."
)

GMAIL_FORWARD_BODY = (
    "See below.\n\n"
    "---------- Forwarded message ---------\n"
    "From: Jane Doe <jane@mma.example>\n"
    "Date: Mon, Jul 6, 2026 at 9:15 AM\n"
    "Subject: Meeting request\n"
    "To: <scheduling@mail.example.com>\n\n"
    "We would like to request a meeting next Thursday."
)


class ForwardDetectionTests(TestCase):
    def test_outlook_forward_block(self):
        info = forwards.detect('FW: Meeting request', OUTLOOK_FORWARD_BODY)
        self.assertTrue(info.is_forward)
        self.assertEqual(info.original_sender, 'jane@mma.example')
        self.assertEqual(info.original_name, 'Jane Doe')

    def test_gmail_forward_block(self):
        info = forwards.detect('Fwd: Meeting request', GMAIL_FORWARD_BODY)
        self.assertTrue(info.is_forward)
        self.assertEqual(info.original_sender, 'jane@mma.example')

    def test_plain_reply_is_not_a_forward(self):
        info = forwards.detect('RE: Meeting request',
                               'Sounds good — Thursday works for us.')
        self.assertFalse(info.is_forward)
        self.assertEqual(info.original_sender, '')

    def test_blocked_original_sender_is_not_laundered_by_internal_forwarder(self):
        # The original sender is blocked; the forwarding staffer's domain is
        # allowlisted. Reputation must judge the ORIGINAL sender → divert.
        SenderReputation.objects.create(sender_email='jane@mma.example', list='block')
        SenderReputation.objects.create(domain='mail.house.gov', list='allow')

        raw = make_raw(sender='staffer@mail.example.com',
                       subject='FW: Meeting request',
                       body=OUTLOOK_FORWARD_BODY)
        result = run_pipeline(str(raw.id))
        self.assertEqual(result['status'], 'divert')
        log = FilterLog.objects.get(raw_message=raw, stage='2_reputation')
        self.assertEqual(log.signals['judged'], 'forwarded_original')
        self.assertEqual(log.signals['reputation'], 'block')

    def test_forward_of_unknown_sender_is_not_boosted_by_forwarder_allowlist(self):
        # Internal domain allowlisted; original sender unknown. The message may
        # still pass on content, but NOT via the allowlist bypass.
        SenderReputation.objects.create(domain='mail.house.gov', list='allow')
        raw = make_raw(sender='staffer@mail.example.com',
                       subject='FW: Meeting request',
                       body=OUTLOOK_FORWARD_BODY)
        result = run_pipeline(str(raw.id))
        self.assertEqual(result['status'], 'extract')  # content passes on merit
        log = FilterLog.objects.get(raw_message=raw, stage='4_content')
        self.assertNotEqual(log.signals.get('bypass'), 'allowlist')
