#!/usr/bin/env python
# SPDX-License-Identifier: Apache-2.0
"""Simulate the email ingestion pipeline end-to-end with fake emails.

Seeds a realistic mix of messages the office would receive and pushes each one
through the REAL pipeline (funnel -> extraction [mock provider] -> post-
processing -> materialization), so every review surface has something to show:

  Inbox (/inbox/)
    1.  Simple meeting request          -> draft event w/ contacts + meta chips
    2.  Multi-event email               -> two draft events from one email
    3.  Recurring, open-ended           -> draft + pending series (confirm block)
    4.  Recurring, bounded ("6 weeks")  -> draft + pending series w/ COUNT
    5.  Calendar invite (.ics)          -> deterministic candidate, invite chip
    6.  Forwarded external request      -> draft (original sender judged)
    7.  Dateless legislative anchor     -> draft ("after recess")
    8.  Reschedule of existing event    -> violet change-request card (diff)
    9.  Cancellation (same thread)      -> violet cancellation card
   10.  Possible duplicate              -> draft w/ "possible duplicate" chip

  Triage (/email/triage/)
   11.  Cancellation of unknown event
   12.  DMARC failure (security escalation)
   13.  Event digest (too many dates)

  Diverted mail (/email/diverted/)
   14.  Newsletter (List-Unsubscribe)
   15.  No-reply notification
   16.  Zero-signal thank-you note
   17.  Blocked sender
   18.  Duplicate resend (dedup)

Everything is tagged with a demo mailbox, and re-running the script first
clears the previous demo state, so it is safe to run repeatedly.

Usage (from repo root, LLM_PROVIDER=mock is the dev default):
    python scripts/simulate_email_ingestion.py
    python scripts/simulate_email_ingestion.py --keep   # skip the cleanup pass
"""

import os
import sys
import uuid
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')

import django  # noqa: E402
django.setup()

from apps.authentication.devtools import require_dev_environment  # noqa: E402
require_dev_environment('scripts/simulate_email_ingestion.py')

from django.utils import timezone  # noqa: E402

from apps.email_processing.models import (  # noqa: E402
    AttachmentBlob, EmailProcessing, ExtractionCandidate, FilterLog,
    RawMessage, SenderReputation,
)
from apps.email_processing.tasks.pipeline import run_pipeline  # noqa: E402
from apps.email_processing.postprocess import get_pipeline_user  # noqa: E402
from apps.event_management.models import Event, EventSeries  # noqa: E402

DEMO_MAILBOX = 'scheduling-demo@mail.example.com'
DEMO_NOTE = '[ingestion-demo]'

NOW = timezone.now()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_raw(sender, subject, body, *, sender_name='', headers=None,
             conversation_id=None, internet_message_id=None,
             attachments=None, has_calendar_part=False, minutes_ago=0):
    raw = RawMessage(
        graph_message_id=f'DEMO-{uuid.uuid4()}',
        internet_message_id=internet_message_id or f'<{uuid.uuid4()}@demo.example>',
        conversation_id=conversation_id or f'DEMO-CONV-{uuid.uuid4()}',
        mailbox=DEMO_MAILBOX,
        received_at=NOW - timedelta(minutes=minutes_ago),
        source='sweep',
        sender=sender,
        sender_name=sender_name,
        subject=subject,
        headers=headers or {'Authentication-Results': 'mx.example.com; spf=pass dkim=pass dmarc=pass'},
        body_text=body,
        body_html='',
        attachments=attachments or [],
        has_calendar_part=has_calendar_part,
    )
    raw.save()
    return raw


def cleanup():
    """Remove everything a previous run created (demo mailbox is the marker)."""
    raws = RawMessage.objects.filter(mailbox=DEMO_MAILBOX)
    records = EmailProcessing.objects.filter(raw_message__in=raws)

    series = EventSeries.objects.filter(source_candidate__raw_message__in=raws)
    series_events = Event.objects.filter(series__in=series)
    draft_events = Event.objects.filter(email_links__email__in=records)
    marker_events = Event.objects.filter(notes__contains=DEMO_NOTE)

    n_events = 0
    for qs in (series_events, draft_events, marker_events):
        for event in qs:
            event.delete()
            n_events += 1
    n_series = series.count()
    series.delete()
    n_records = records.count()
    records.delete()
    n_raws = raws.count()
    raws.delete()
    n_reps = SenderReputation.objects.filter(notes__contains=DEMO_NOTE).delete()[0]
    print(f'Cleanup: removed {n_raws} messages, {n_records} records, '
          f'{n_events} events, {n_series} series, {n_reps} reputation rows.')


ICS_INVITE = (
    "BEGIN:VCALENDAR\r\n"
    "PRODID:-//Microsoft Corporation//Outlook 16.0 MIMEDIR//EN\r\n"
    "VERSION:2.0\r\nMETHOD:REQUEST\r\nBEGIN:VEVENT\r\n"
    "UID:demo-invite-workforce-roundtable@mma.example\r\n"
    "SUMMARY:Workforce Development Roundtable\r\n"
    "DTSTART;TZID=America/New_York:20260722T140000\r\n"
    "DTEND;TZID=America/New_York:20260722T150000\r\n"
    "LOCATION:2411 Rayburn House Office Building\r\n"
    "DESCRIPTION:Quarterly roundtable with alliance members.\r\n"
    "ORGANIZER;CN=Dana Whitfield:mailto:dana@mma.example\r\n"
    "ATTENDEE;CN=Scheduling:mailto:scheduling-demo@mail.example.com\r\n"
    "SEQUENCE:0\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
).encode('utf-8')


# ---------------------------------------------------------------------------
# The fake mail
# ---------------------------------------------------------------------------

def seed():
    results = []

    def push(label, raw):
        outcome = run_pipeline(str(raw.id))
        results.append((label, raw, outcome))
        return raw

    # --- Inbox: draft events -------------------------------------------------
    push('1  Simple meeting request', make_raw(
        'dana.whitfield@mma.example',
        'Meeting request — workforce legislation',
        'Dear Scheduler,\n\n'
        'On behalf of the Franklin Manufacturing Alliance, could we schedule a '
        'meeting with the Congresswoman on July 21 at 2pm at the District Office '
        'to discuss the pending workforce development bill? We expect four '
        'attendees including our executive director.\n\n'
        'Best regards,\nDana Whitfield\nFranklin Manufacturing Alliance\n'
        '(517) 555-0140\ndana.whitfield@mma.example',
        sender_name='Dana Whitfield', minutes_ago=30))

    push('2  Multi-event email', make_raw(
        'events@fairviewchamber.example',
        'Two August invitations from the Chamber',
        'Hello! Two invitations for the August calendar:\n\n'
        'EVENT: Ribbon cutting meeting on August 4 at 10am at Innovation Works '
        'in Fairview. Brief remarks requested.\n\n'
        'EVENT: Small business roundtable on August 6 at 1pm at the Fairview '
        'Chamber offices. Q&A with local owners.\n\n'
        'Marcus Bell\nFairview Regional Chamber\nmarcus@fairviewchamber.example',
        sender_name='Marcus Bell', minutes_ago=95))

    push('3  Recurring (open-ended, needs end bound)', make_raw(
        'principal@lakeviewhigh.example',
        'Standing civics briefing',
        'Our seniors would be honored by a weekly civics briefing meeting with '
        'your office at 8am starting July 15. Happy to host at Lakeview High.\n\n'
        'Principal Ortiz\nLakeview High School',
        sender_name='A. Ortiz', minutes_ago=140))

    push('4  Recurring (bounded, 6 weeks)', make_raw(
        'coordinator@agcouncil.example',
        'Harvest season check-ins',
        'Could we set a weekly call meeting at 9am for 6 weeks starting July 14 '
        'to coordinate on the harvest labor situation?\n\n'
        'Priya Nair\nCounty Agriculture Council\n(989) 555-0114',
        sender_name='Priya Nair', minutes_ago=200))

    ics_raw = make_raw(
        'dana@mma.example', 'Invitation: Workforce Development Roundtable',
        'Please see the attached invite.',
        sender_name='Dana Whitfield', has_calendar_part=True,
        attachments=[{'name': 'invite.ics', 'content_type': 'text/calendar',
                      'size': len(ICS_INVITE), 'is_inline': False}],
        minutes_ago=260)
    AttachmentBlob.objects.create(
        raw_message=ics_raw, name='invite.ics', content_type='text/calendar',
        size=len(ICS_INVITE), payload=ICS_INVITE)
    push('5  Calendar invite (.ics)', ics_raw)

    push('6  Forwarded external request', make_raw(
        'staffer@mail.example.com', 'FW: Site visit ask',
        'Flagging this one — think we should try to make it happen?\n\n'
        '________________________________\n'
        'From: Jordan Reyes <jordan@harborfoodbank.example>\n'
        'Sent: Monday, July 6, 2026 9:15 AM\n'
        'To: Scheduling <scheduling-demo@mail.example.com>\n'
        'Subject: Site visit ask\n\n'
        'We would love to schedule a visit to our new distribution center on '
        'July 24 at 11am — the volunteers would be thrilled.\n\n'
        'Jordan Reyes, Harbor Food Bank',
        sender_name='Alex Staffer', minutes_ago=320))

    push('7  Dateless legislative anchor', make_raw(
        'chair@veteranscoalition.example',
        'Visit when you are back in district',
        'No rush on dates — but after recess we would love to host the '
        'Congresswoman for a visit with our post commanders in Fairview. '
        'Mornings work best for the group.\n\n'
        'Cmdr. Ellis (Ret.)\nVeterans Coalition of Elm County',
        sender_name='Cmdr. Ellis', minutes_ago=380))

    # --- Change requests -----------------------------------------------------
    actor = get_pipeline_user()
    Event.objects.create(
        title='Factory tour', type='meeting', status='scheduled',
        start_date=(NOW + timedelta(days=9)).date(),
        start_time=None, location='Lakeside Manufacturing, Plant 2',
        notes=DEMO_NOTE, created_by=actor, modified_by=actor,
    )
    push('8  Reschedule of existing event', make_raw(
        'ops@lakesidemfg.example', 'Factory tour',
        f'Apologies — our line audit moved. Could we reschedule the factory '
        f'tour to {(NOW + timedelta(days=10)).date().strftime("%B %d")} at 3pm '
        f'instead? Same meeting plan otherwise.\n\n'
        'Sam Porter, Lakeside Manufacturing',
        sender_name='Sam Porter', minutes_ago=25))

    # 9: request then a cancellation in the SAME conversation (thread match)
    kiwanis_conv = f'DEMO-CONV-{uuid.uuid4()}'
    push('9a Kiwanis request (context for 9b)', make_raw(
        'club@kiwanisrochester.example', 'Kiwanis pancake breakfast',
        'Would the Congresswoman join our pancake breakfast meeting on '
        'August 8 at 9am at the fairgrounds pavilion?\n\nKiwanis of Fairview',
        conversation_id=kiwanis_conv, minutes_ago=1500))
    push('9b Cancellation (same thread)', make_raw(
        'club@kiwanisrochester.example', 'RE: Kiwanis pancake breakfast',
        'So sorry — we have to cancel the pancake breakfast; the pavilion '
        'flooded over the weekend. We will be back in touch.\n\n'
        'Kiwanis of Fairview',
        conversation_id=kiwanis_conv, minutes_ago=20))

    # 10: duplicate suspect — same title/date as an existing scheduled event
    Event.objects.create(
        title='Meeting request — workforce legislation', type='meeting',
        status='scheduling_in_progress',
        start_date=(NOW + timedelta(days=14)).date(),
        notes=DEMO_NOTE, created_by=actor, modified_by=actor,
    )
    push('10 Possible duplicate', make_raw(
        'dana.whitfield@mma.example', 'Meeting request — workforce legislation',
        f'Following up — checking you received our request to schedule a '
        f'meeting on {(NOW + timedelta(days=14)).date().strftime("%B %d")} '
        f'at 2pm about the workforce bill.\n\nDana Whitfield',
        sender_name='Dana Whitfield', minutes_ago=10))

    # --- Triage --------------------------------------------------------------
    push('11 Cancellation of unknown event', make_raw(
        'unknown@somewhere.example', 'Cancellation',
        'Hi — please cancel the riverfront gala appearance. Thanks.',
        minutes_ago=55))

    push('12 DMARC failure (security)', make_raw(
        'urgent@definitely-real-bank.example', 'URGENT meeting about your account',
        'You must schedule an urgent meeting call today to verify credentials.',
        headers={'Authentication-Results':
                 'mx.example.com; spf=fail smtp.mailfrom=definitely-real-bank.example; '
                 'dkim=fail; dmarc=fail'},
        minutes_ago=70))

    digest_lines = '\n'.join(
        f'July {d} - Community happening number {d} at the pavilion'
        for d in range(8, 28))
    push('13 Event digest (too many dates)', make_raw(
        'digest@communityboard.example', 'This month around the county',
        digest_lines, minutes_ago=85))

    # --- Diverted ------------------------------------------------------------
    push('14 Newsletter (List-Unsubscribe)', make_raw(
        'newsletter@policyweekly.example', 'Policy Weekly — July edition',
        'Top stories this week from around the capitol...',
        headers={'List-Unsubscribe': '<mailto:unsub@policyweekly.example>',
                 'Authentication-Results': 'mx.example.com; spf=pass dkim=pass'},
        minutes_ago=100))

    push('15 No-reply notification', make_raw(
        'no-reply@travelbookings.example', 'Your itinerary confirmation',
        'Your booking is confirmed. Do not reply to this message.',
        minutes_ago=115))

    push('16 Zero-signal thank-you', make_raw(
        'resident@hometown.example', 'Thank you',
        'Just wanted to say thank you for everything your office does for our '
        'community. It does not go unnoticed.',
        minutes_ago=130))

    rep = SenderReputation(sender_email='blast@megapac.example', list='block',
                           notes=f'{DEMO_NOTE} blocked for the demo')
    rep.save()
    push('17 Blocked sender', make_raw(
        'blast@megapac.example', 'Exclusive gala invitation',
        'You are invited to schedule an exclusive gala meeting appearance...',
        minutes_ago=145))

    dup_body = ('Could we schedule a park cleanup kickoff meeting on July 26 '
                'at 8am at Bloomer Park?\n\nFriends of Bloomer Park')
    push('18a Original (context for 18b)', make_raw(
        'friends@bloomerpark.example', 'Park cleanup kickoff', dup_body,
        minutes_ago=1600))
    push('18b Duplicate resend (dedup)', make_raw(
        'friends@bloomerpark.example', 'Park cleanup kickoff', dup_body,
        minutes_ago=5))

    return results


def report(results):
    print()
    print(f'{"#/label":44s} {"funnel/pipeline":16s} {"cands":>5s}  materialized as')
    print('-' * 100)
    for label, raw, outcome in results:
        cands = ExtractionCandidate.objects.filter(raw_message=raw)
        made = []
        for c in cands:
            if c.created_event_id:
                made.append('draft event' + (' + series' if c.series.exists() else ''))
            if c.change_suggestion_id:
                n = c.change_suggestions.count()
                made.append(f'change request ({n} field{"s" if n != 1 else ""})')
            if c.status == 'escalated':
                made.append('triage item')
        if not made:
            last = (FilterLog.objects.filter(raw_message=raw)
                    .order_by('-created_at').first())
            if outcome['status'] == 'divert':
                made.append(f'diverted ({last.stage if last else "?"})')
            elif outcome['status'] == 'escalate':
                made.append('triage item')
        print(f'{label:44s} {outcome["status"]:16s} {cands.count():>5d}  {", ".join(made) or "-"}')

    print()
    print('Where to look (log in first):')
    print('  Inbox (drafts, chips, change requests, series confirm):  http://127.0.0.1:8000/inbox/')
    print('  Triage (escalations, delivery health):                   http://127.0.0.1:8000/email/triage/')
    print('  Diverted mail (browse + promote):                        http://127.0.0.1:8000/email/diverted/')
    print('  Admin (RawMessage / FilterLog / candidates):             http://127.0.0.1:8000/admin/')


if __name__ == '__main__':
    if '--keep' not in sys.argv:
        cleanup()
    results = seed()
    report(results)
