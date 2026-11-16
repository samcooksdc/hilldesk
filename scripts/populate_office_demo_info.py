#!/usr/bin/env python
# SPDX-License-Identifier: Apache-2.0
"""
Populate the Smith demo office with 20 realistic, politically-neutral inbox
events using the verbatim spec function from the original demo prompt. All
events fall within the next 7 days. Each event gets:
  - An Event record with status, type, format, location, topics
  - An EmailProcessing record (the inbox email that triggered it)
  - Event.staff assignment matching legislative areas
  - approval_routing JSON + EventApproval rows in one of three states:
        * fully_approved  -> all stages already approved (scheduled / rsvped)
        * stage1_done     -> stage 1 approved, waiting on Samuel (scheduling_in_progress)
        * pending         -> nothing approved yet (received / hold / fyied)

Status and routing state are correlated: scheduled events have full approval
history; received events sit untouched in the inbox.

Clears existing event / email / approval data for the Smith office before
populating, so re-runs always produce the same clean demo state.

Run AFTER scripts/create_demo_office.py.

Usage:
    python scripts/populate_office_demo_info.py
"""

import os
import random
import sys
import uuid
from datetime import date, datetime, time, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')

import django
django.setup()

from apps.authentication.devtools import require_dev_environment  # noqa: E402
require_dev_environment('scripts/populate_office_demo_info.py')

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from apps.api.services import ApprovalRoutingService
from apps.authentication.models import Office
from apps.contacts.extraction import build_review_parties
from apps.contacts.models import (
    Contact,
    ContactEmailAddress,
    ContactPhoneNumber,
    Organization,
)
from apps.contacts.services import attach_contact_org_to_event
from apps.email_processing.models import EmailProcessing, EmailThread
from apps.event_management.models import (
    Event,
    EventApproval,
    EventChangeHistory,
    EventChangeSuggestion,
    EventReviewAuditLog,
)

User = get_user_model()

OFFICE_NAME = 'Office of Rep. James Smith'
DC_OFFICE = '4340 Rayburn House Office Building, Washington, DC 20515'
DISTRICT_OFFICE = '215 E Main St, Fairview, FR 00000'
SCHEDULING_INBOX = {
    'email': 'scheduling@smith.example.com',
    'name': 'Office of Rep. James Smith',
}

# Topic -> usernames responsible for that area, drawn from OfficeStaff.legislative_areas.
TOPIC_TO_STAFF = {
    'Foreign Relations': ['stepan', 'gibson', 'mac', 'amelia'],
    'Education':         ['kaden', 'meaghan'],
    'Industry':          ['kaden', 'mac'],
    'Crime':             ['meaghan'],
    'Healthcare':        ['gibson', 'amelia'],
}


# ---------------------------------------------------------------------------
# Date / text helpers (verbatim from the original demo prompt)
# ---------------------------------------------------------------------------
TODAY = date.today()


def in_days(offset):
    return TODAY + timedelta(days=offset)


def next_weekday(weekday):
    """Next occurrence of `weekday` (Mon=0) strictly after today, within 7 days."""
    days = (weekday - TODAY.weekday()) % 7
    days = days or 7
    return TODAY + timedelta(days=days)


def ordinal(n):
    if 11 <= (n % 100) <= 13:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


def long_date(d):
    return f"{d.strftime('%A, %B')} {ordinal(d.day)}, {d.year}"


def find_text_position(needle, haystack):
    if needle is None:
        return None, None
    start = haystack.find(needle)
    if start == -1:
        return None, None
    return start, start + len(needle)


def build_extracted_fields(field_specs, body):
    extracted = {}
    for name, value, confidence, snippet in field_specs:
        start_index, end_index = find_text_position(snippet, body)
        extracted[name] = {
            'value': value,
            'confidence': confidence,
            'status': 'pending',
            'start_index': start_index,
            'end_index': end_index,
            'text_snippet': snippet,
        }
    return extracted


# ---------------------------------------------------------------------------
# Multi-contact / multi-org extraction-review demo data (v2 shape)
# ---------------------------------------------------------------------------
# Contact/org fields that are now reviewed as cards, not flat scalar fields.
CARD_FIELD_NAMES = {
    'group', 'point_of_contact_name', 'point_of_contact_email', 'point_of_contact_phone',
}

# Positions from the email signatures, keyed by POC email. The auto-created
# Contact (made by attach_contact_org_to_event) carries no position, so this
# surfaces on the POC card as a 'link + update' addition — except for the seeded
# contact below, where it differs and becomes a confirmable REPLACE.
POC_POSITIONS = {
    'mholt@riverbendsistercities.example': 'President',
    'dvance@valleystemnetwork.example': 'Policy Coordinator',
    'pstrickland@hmcouncil.example': 'Executive Director',
    'kwexler@valleysheriffs.example': 'Director of Government Affairs',
    'apierce@rhha.example': 'Board Chair',
    'bmaddox@pvcc.example': 'Director of Community Relations',
    'lcardenas@valss.example': 'Director of Government Relations',
    'cwhitmore@svfarmbureau.example': 'President',
}

# Org locations keyed by org name → a 'link + update' addition on the org card.
ORG_LOCATIONS = {
    'Riverbend Sister Cities Alliance': 'Fairview, FR',
    "Valley Sheriffs' Association": 'Fairview, FR',
    'Ridgeline Community College': 'Ridgeline, FR',
}

# Extra people named in the email prose, keyed by POC email. They aren't in the
# directory, so their cards resolve as 'new'.
EXTRA_PARTIES = {
    'kwexler@valleysheriffs.example': [
        {'name': 'Sheriff Thomas Reardon', 'position': 'Sheriff, Cedar County',
         'organization': "Valley Sheriffs' Association", 'role': 'attendee'},
    ],
    'bmaddox@pvcc.example': [
        {'name': 'Ellen Brock', 'position': 'President',
         'organization': 'Ridgeline Community College', 'role': 'host_speaker'},
    ],
    'mcaron@nbtrade.example': [
        {'name': 'Henri Lavoie', 'position': 'Trade Attaché',
         'organization': 'Canadian Trade Office', 'role': 'attendee'},
    ],
    'cwhitmore@svfarmbureau.example': [
        {'name': 'Joan Petty', 'position': 'Government Affairs',
         'organization': 'Cedar Valley Farm Bureau', 'role': 'attendee'},
    ],
}

def derive_parties(spec):
    """Build the (parties, orgs) lists for a review spec's v2 extraction cards."""
    ev = spec['event']
    poc_email = ev['poc_email']
    parties = [{
        'name': ev['poc_name'], 'email': poc_email, 'phone': ev['poc_phone'],
        'position': POC_POSITIONS.get(poc_email, ''), 'organization': ev['group'],
        'role': 'point_of_contact',
    }]
    parties.extend(EXTRA_PARTIES.get(poc_email, []))
    orgs = [{'name': ev['group'], 'location': ORG_LOCATIONS.get(ev['group'], '')}]
    return parties, orgs


def seed_directory(user):
    """Pre-seed a small existing directory so review cards demonstrate matching.

    Review-bucket events tie NOTHING to the directory (per the human-in-the-loop
    rule, links are created only when a review completes), so without an existing
    directory every review card would resolve to 'new'. These rows stand in for
    contacts/orgs the office already knows, chosen so the cards show the full
    spread: a plain link, a link with additions, and a link with a replace.
    """
    def contact(name, email, position='', phone=''):
        c = Contact.objects.create(name=name, position=position,
                                   created_by=user, modified_by=user)
        if email:
            ContactEmailAddress.objects.create(
                contact=c, email=email, is_primary=True,
                created_by=user, modified_by=user)
        if phone:
            ContactPhoneNumber.objects.create(
                contact=c, phone=phone, is_primary=True,
                created_by=user, modified_by=user)
        return c

    # Replace demo: stored position differs from the extracted 'President'
    # (also no stored phone → the card's phone is an addition).
    contact('Marsha Holt', 'mholt@riverbendsistercities.example',
            position='Founding Member')
    # Plain link: everything the card carries already matches (no updates).
    contact('Daniel Vance', 'dvance@valleystemnetwork.example', position='Policy Coordinator')
    # Link + additions: stored row lacks the position the card carries.
    contact('Karen Wexler', 'kwexler@valleysheriffs.example')
    # Orgs with no stored location → the card's location is an addition.
    Organization.objects.create(name='Riverbend Sister Cities Alliance',
                                created_by=user, modified_by=user)
    Organization.objects.create(name='Valley STEM Educators Network',
                                created_by=user, modified_by=user)


# Per-email event dates
TUE = next_weekday(1)          # "next Tuesday"
THU = next_weekday(3)          # "this Thursday"
D1, D3, D4, D5 = in_days(5), in_days(2), in_days(3), in_days(6)
D6, D7, D9, D10 = in_days(4), in_days(1), in_days(5), in_days(3)
D11, D12, D13, D14 = in_days(6), in_days(4), in_days(7), in_days(5)
D15, D16, D18, D20 = in_days(2), in_days(4), in_days(3), in_days(6)

# "first week of March ... Monday the 2nd" -> the next March 2 strictly in the
# future, so the Farm Bureau request stays forward-dated and body-coherent on
# every re-run regardless of when populate is run.
MAR2 = date(TODAY.year, 3, 2)
if MAR2 <= TODAY:
    MAR2 = date(TODAY.year + 1, 3, 2)


# ---------------------------------------------------------------------------
# Specs (verbatim from the original demo prompt, with format='in-person'
# instead of 'in_person' to match the live Office.event_format_choices values)
# ---------------------------------------------------------------------------
def build_specs():
    specs = []

    # 1 - Foreign Relations / Event / In Person
    body = f"""Dear Representative Smith,

On behalf of the Riverbend Sister Cities Alliance, I would like to invite you to attend our annual International Friendship Reception, celebrating the First District's cultural exchange partnerships with communities in Germany, Japan, and Kenya.

The reception will be held on {long_date(D1)} from 6:00 PM to 8:00 PM at The Magnolia Hotel, 11 N Main St, Fairview, FR 00000. Brief remarks from visiting delegations are planned at 6:45 PM. No formal address is requested of you; your presence alone would be a wonderful show of support.

We would be honored to recognize you from the podium if you are able to join us.

Warm regards,
Marsha Holt
President, Riverbend Sister Cities Alliance
mholt@riverbendsistercities.example
(540) 555-0173"""
    specs.append({
        'subject': 'Invitation: Annual International Friendship Reception',
        'sender_name': 'Marsha Holt', 'sender_email': 'mholt@riverbendsistercities.example',
        'recv': (7, 12), 'confidence': 0.94, 'body': body,
        'event': dict(title='Riverbend Sister Cities International Friendship Reception',
                      type='event', format='in-person',
                      group='Riverbend Sister Cities Alliance',
                      description="Annual reception celebrating the district's international sister-city partnerships; visiting delegations from Germany, Japan, and Kenya will give brief remarks.",
                      start_date=D1, start_time=time(18, 0), end_time=time(20, 0),
                      location='The Magnolia Hotel, 11 N Main St, Fairview, FR 00000',
                      poc_name='Marsha Holt', poc_email='mholt@riverbendsistercities.example',
                      poc_phone='(540) 555-0173', topics=['Foreign Relations']),
        'fields': [
            ('title', 'Riverbend Sister Cities International Friendship Reception', 0.91, 'annual International Friendship Reception'),
            ('group', 'Riverbend Sister Cities Alliance', 0.98, 'Riverbend Sister Cities Alliance'),
            ('start_date', D1.isoformat(), 0.96, long_date(D1)),
            ('start_time', '18:00', 0.95, '6:00 PM'),
            ('end_time', '20:00', 0.95, '8:00 PM'),
            ('location', 'The Magnolia Hotel, 11 N Main St, Fairview, FR 00000', 0.96, 'The Magnolia Hotel, 11 N Main St, Fairview, FR 00000'),
            ('point_of_contact_name', 'Marsha Holt', 0.95, 'Marsha Holt'),
            ('point_of_contact_email', 'mholt@riverbendsistercities.example', 0.98, 'mholt@riverbendsistercities.example'),
            ('point_of_contact_phone', '(540) 555-0173', 0.95, '(540) 555-0173'),
            ('type', 'event', 0.90, 'reception'),
        ],
    })

    # 2 - Education / Meeting / In Person / "in your office" + "next Tuesday" + duration
    body = """Hi,

I'm writing on behalf of the Valley STEM Educators Network to request a brief meeting with the Congressman to discuss federal support for K-12 computer science instruction in rural districts.

Would next Tuesday work? We were hoping to meet in your office at 2:00 PM, and we expect to need about 45 minutes. Two of our teacher members from the district would join me.

Thank you,
Daniel Vance
Policy Coordinator, Valley STEM Educators Network
dvance@valleystemnetwork.example"""
    specs.append({
        'subject': 'Meeting request - K-12 computer science instruction',
        'sender_name': 'Daniel Vance', 'sender_email': 'dvance@valleystemnetwork.example',
        'recv': (8, 3), 'confidence': 0.93, 'body': body,
        'event': dict(title='Meeting with Valley STEM Educators Network',
                      type='meeting', format='in-person',
                      group='Valley STEM Educators Network',
                      description='Discussion of federal support for K-12 computer science instruction in rural school districts.',
                      start_date=TUE, start_time=time(14, 0), end_time=time(14, 45),
                      location=DC_OFFICE,
                      poc_name='Daniel Vance', poc_email='dvance@valleystemnetwork.example',
                      poc_phone='', topics=['Education']),
        'fields': [
            ('title', 'Meeting with Valley STEM Educators Network', 0.89, 'brief meeting with the Congressman to discuss federal support for K-12 computer science instruction'),
            ('group', 'Valley STEM Educators Network', 0.98, 'Valley STEM Educators Network'),
            ('start_date', TUE.isoformat(), 0.92, 'next Tuesday'),
            ('start_time', '14:00', 0.94, '2:00 PM'),
            ('end_time', '14:45', 0.88, 'about 45 minutes'),
            ('location', DC_OFFICE, 0.87, 'in your office'),
            ('point_of_contact_name', 'Daniel Vance', 0.94, 'Daniel Vance'),
            ('point_of_contact_email', 'dvance@valleystemnetwork.example', 0.98, 'dvance@valleystemnetwork.example'),
            ('type', 'meeting', 0.93, 'meeting'),
        ],
    })

    # 3 - Industry / Meeting / Virtual / 30-minute call
    body = f"""Good afternoon,

The Highland Manufacturers Council would appreciate a virtual call with the Congressman regarding workforce training programs for small manufacturers in the First District.

We would like to propose {long_date(D3)} at 11:00 AM. The call should run about half an hour. We can host on Zoom and will circulate a link once confirmed.

Best,
Patricia Strickland
Executive Director, Highland Manufacturers Council
pstrickland@hmcouncil.example"""
    specs.append({
        'subject': 'Virtual call request: manufacturing workforce training',
        'sender_name': 'Patricia Strickland', 'sender_email': 'pstrickland@hmcouncil.example',
        'recv': (8, 41), 'confidence': 0.92, 'body': body,
        'event': dict(title='Virtual Call with Highland Manufacturers Council',
                      type='meeting', format='virtual',
                      group='Highland Manufacturers Council',
                      description='Discussion of workforce training programs for small manufacturers in the district.',
                      start_date=D3, start_time=time(11, 0), end_time=time(11, 30),
                      location='Virtual (Zoom)',
                      poc_name='Patricia Strickland', poc_email='pstrickland@hmcouncil.example',
                      poc_phone='', topics=['Industry']),
        'fields': [
            ('title', 'Virtual Call with Highland Manufacturers Council', 0.88, 'virtual call with the Congressman regarding workforce training programs for small manufacturers'),
            ('group', 'Highland Manufacturers Council', 0.98, 'Highland Manufacturers Council'),
            ('start_date', D3.isoformat(), 0.95, long_date(D3)),
            ('start_time', '11:00', 0.94, '11:00 AM'),
            ('end_time', '11:30', 0.89, 'about half an hour'),
            ('location', 'Virtual (Zoom)', 0.90, 'host on Zoom'),
            ('format', 'virtual', 0.93, 'virtual call'),
            ('point_of_contact_name', 'Patricia Strickland', 0.94, 'Patricia Strickland'),
            ('point_of_contact_email', 'pstrickland@hmcouncil.example', 0.98, 'pstrickland@hmcouncil.example'),
            ('type', 'meeting', 0.92, 'call'),
        ],
    })

    # 4 - Crime / Meeting / In Person / "in your office" + explicit times
    body = f"""Dear Congressman Smith,

The Valley Sheriffs' Association respectfully requests a meeting to brief you on rural law enforcement staffing and federal grant programs that support local agencies.

We would like to meet in your office on {long_date(D4)} from 9:30 AM to 10:15 AM. Sheriff Thomas Reardon of Cedar County and two association representatives would attend.

Respectfully,
Karen Wexler
Director of Government Affairs, Valley Sheriffs' Association
kwexler@valleysheriffs.example
(804) 555-2290"""
    specs.append({
        'subject': 'Briefing request - rural law enforcement staffing',
        'sender_name': 'Karen Wexler', 'sender_email': 'kwexler@valleysheriffs.example',
        'recv': (9, 17), 'confidence': 0.95, 'body': body,
        'event': dict(title="Briefing with Valley Sheriffs' Association",
                      type='meeting', format='in-person',
                      group="Valley Sheriffs' Association",
                      description='Briefing on rural law enforcement staffing and federal grant programs supporting local agencies.',
                      start_date=D4, start_time=time(9, 30), end_time=time(10, 15),
                      location=DC_OFFICE,
                      poc_name='Karen Wexler', poc_email='kwexler@valleysheriffs.example',
                      poc_phone='(804) 555-2290', topics=['Crime']),
        'fields': [
            ('title', "Briefing with Valley Sheriffs' Association", 0.90, 'meeting to brief you on rural law enforcement staffing and federal grant programs'),
            ('group', "Valley Sheriffs' Association", 0.97, "Valley Sheriffs' Association"),
            ('start_date', D4.isoformat(), 0.96, long_date(D4)),
            ('start_time', '09:30', 0.95, '9:30 AM'),
            ('end_time', '10:15', 0.95, '10:15 AM'),
            ('location', DC_OFFICE, 0.87, 'in your office'),
            ('point_of_contact_name', 'Karen Wexler', 0.95, 'Karen Wexler'),
            ('point_of_contact_email', 'kwexler@valleysheriffs.example', 0.98, 'kwexler@valleysheriffs.example'),
            ('point_of_contact_phone', '(804) 555-2290', 0.95, '(804) 555-2290'),
            ('type', 'meeting', 0.93, 'meeting'),
        ],
    })

    # 5 - Healthcare / Meeting / Hybrid
    body = f"""Dear Representative Smith,

I write to request a meeting on behalf of the Rural Highlands Hospital Alliance to discuss the financial pressures facing critical-access hospitals in the First District and the role of federal reimbursement programs in keeping rural facilities open.

Our member hospitals serve more than 180,000 residents across the district, and several have reduced service lines over the past two years. We would welcome the chance to walk your team through the data and discuss policy options that have drawn bipartisan interest, including telehealth reimbursement and workforce pipeline support.

We propose {long_date(D5)} at 1:30 PM, for approximately one hour. We can convene at Maple Ridge Community Hospital, 1 Health Circle, Fairview, FR 00000, with a virtual option for staff who cannot attend in person.

Thank you for your attention to rural health care.

Sincerely,
Dr. Alan Pierce
Board Chair, Rural Highlands Hospital Alliance
apierce@rhha.example
(540) 555-6611"""
    specs.append({
        'subject': 'Meeting request - critical-access hospital funding',
        'sender_name': 'Dr. Alan Pierce', 'sender_email': 'apierce@rhha.example',
        'recv': (9, 52), 'confidence': 0.94, 'body': body,
        'event': dict(title='Meeting with Rural Highlands Hospital Alliance',
                      type='meeting', format='hybrid',
                      group='Rural Highlands Hospital Alliance',
                      description='Discussion of financial pressures on critical-access hospitals and federal reimbursement programs, including telehealth reimbursement and rural workforce support.',
                      start_date=D5, start_time=time(13, 30), end_time=time(14, 30),
                      location='Maple Ridge Community Hospital, 1 Health Circle, Fairview, FR 00000',
                      poc_name='Dr. Alan Pierce', poc_email='apierce@rhha.example',
                      poc_phone='(540) 555-6611', topics=['Healthcare']),
        'fields': [
            ('title', 'Meeting with Rural Highlands Hospital Alliance', 0.90, 'meeting on behalf of the Rural Highlands Hospital Alliance'),
            ('group', 'Rural Highlands Hospital Alliance', 0.98, 'Rural Highlands Hospital Alliance'),
            ('start_date', D5.isoformat(), 0.96, long_date(D5)),
            ('start_time', '13:30', 0.95, '1:30 PM'),
            ('end_time', '14:30', 0.88, 'for approximately one hour'),
            ('location', 'Maple Ridge Community Hospital, 1 Health Circle, Fairview, FR 00000', 0.93, 'Maple Ridge Community Hospital, 1 Health Circle, Fairview, FR 00000'),
            ('format', 'hybrid', 0.90, 'with a virtual option'),
            ('point_of_contact_name', 'Dr. Alan Pierce', 0.94, 'Dr. Alan Pierce'),
            ('point_of_contact_email', 'apierce@rhha.example', 0.98, 'apierce@rhha.example'),
            ('point_of_contact_phone', '(540) 555-6611', 0.95, '(540) 555-6611'),
            ('type', 'meeting', 0.92, 'meeting'),
        ],
    })

    # 6 - Education / Meeting / In Person / DISTRICT office disambiguation + duration
    body = f"""Hello,

Ridgeline Community College would like to invite the Congressman to a working meeting on apprenticeship and dual-enrollment programs that connect local students to advanced-manufacturing careers.

We would be glad to come to your district office on {long_date(D6)} at 3:00 PM. Please plan for about one hour. President Ellen Brock and our workforce dean would attend.

Kind regards,
Brian Maddox
Director of Community Relations, Ridgeline Community College
bmaddox@pvcc.example
(540) 555-7788"""
    specs.append({
        'subject': 'Invitation - apprenticeship & dual-enrollment programs',
        'sender_name': 'Brian Maddox', 'sender_email': 'bmaddox@pvcc.example',
        'recv': (10, 24), 'confidence': 0.93, 'body': body,
        'event': dict(title='Meeting with Ridgeline Community College',
                      type='meeting', format='in-person',
                      group='Ridgeline Community College',
                      description='Working meeting on apprenticeship and dual-enrollment programs connecting students to advanced-manufacturing careers.',
                      start_date=D6, start_time=time(15, 0), end_time=time(16, 0),
                      location=DISTRICT_OFFICE,
                      poc_name='Brian Maddox', poc_email='bmaddox@pvcc.example',
                      poc_phone='(540) 555-7788', topics=['Education']),
        'fields': [
            ('title', 'Meeting with Ridgeline Community College', 0.89, 'working meeting on apprenticeship and dual-enrollment programs'),
            ('group', 'Ridgeline Community College', 0.98, 'Ridgeline Community College'),
            ('start_date', D6.isoformat(), 0.96, long_date(D6)),
            ('start_time', '15:00', 0.95, '3:00 PM'),
            ('end_time', '16:00', 0.88, 'about one hour'),
            ('location', DISTRICT_OFFICE, 0.86, 'your district office'),
            ('point_of_contact_name', 'Brian Maddox', 0.94, 'Brian Maddox'),
            ('point_of_contact_email', 'bmaddox@pvcc.example', 0.98, 'bmaddox@pvcc.example'),
            ('point_of_contact_phone', '(540) 555-7788', 0.95, '(540) 555-7788'),
            ('type', 'meeting', 0.92, 'meeting'),
        ],
    })

    # 7 - Industry / Speaking / In Person
    body = f"""Dear Congressman Smith,

The Cedar Business Council would be honored to have you address our members at our monthly business breakfast. This month's program focuses on small-business growth and regional supply chains.

We hope you can speak for about fifteen minutes beginning at 8:00 AM on {long_date(D7)} at The Magnolia Hotel ballroom, 11 N Main St, Fairview, FR 00000. We expect roughly 90 local business owners.

We would be grateful for your participation.

Sincerely,
Lauren Pierson
Executive Director, Cedar Business Council
lpierson@rockbridgebusiness.example
(540) 555-3344"""
    specs.append({
        'subject': 'Speaking invitation - monthly business breakfast',
        'sender_name': 'Lauren Pierson', 'sender_email': 'lpierson@rockbridgebusiness.example',
        'recv': (10, 58), 'confidence': 0.94, 'body': body,
        'event': dict(title='Remarks at Cedar Business Council Breakfast',
                      type='speaking', format='in-person',
                      group='Cedar Business Council',
                      description='Brief address to chamber members at the monthly business breakfast on small-business growth and regional supply chains.',
                      start_date=D7, start_time=time(8, 0), end_time=time(8, 15),
                      location='The Magnolia Hotel ballroom, 11 N Main St, Fairview, FR 00000',
                      poc_name='Lauren Pierson', poc_email='lpierson@rockbridgebusiness.example',
                      poc_phone='(540) 555-3344', topics=['Industry']),
        'fields': [
            ('title', 'Remarks at Cedar Business Council Breakfast', 0.88, 'address our members at our monthly business breakfast'),
            ('group', 'Cedar Business Council', 0.98, 'Cedar Business Council'),
            ('start_date', D7.isoformat(), 0.96, long_date(D7)),
            ('start_time', '08:00', 0.95, '8:00 AM'),
            ('end_time', '08:15', 0.88, 'speak for about fifteen minutes'),
            ('location', 'The Magnolia Hotel ballroom, 11 N Main St, Fairview, FR 00000', 0.95, 'The Magnolia Hotel ballroom, 11 N Main St, Fairview, FR 00000'),
            ('point_of_contact_name', 'Lauren Pierson', 0.94, 'Lauren Pierson'),
            ('point_of_contact_email', 'lpierson@rockbridgebusiness.example', 0.98, 'lpierson@rockbridgebusiness.example'),
            ('point_of_contact_phone', '(540) 555-3344', 0.95, '(540) 555-3344'),
            ('type', 'speaking', 0.92, 'speak'),
        ],
    })

    # 8 - Healthcare / Meeting / Virtual / "this Thursday" + 30 min
    body = """Hi there,

Quick request - the Valley Nurses Guild would love 30 minutes with the Congressman to talk about nurse staffing standards. Could we do this Thursday at 4:00 PM over Teams?

Thanks so much,
Nina Barrett
Valley Nurses Guild
nbarrett@valleynurses.example"""
    specs.append({
        'subject': 'Quick virtual meeting - nurse staffing',
        'sender_name': 'Nina Barrett', 'sender_email': 'nbarrett@valleynurses.example',
        'recv': (11, 36), 'confidence': 0.90, 'body': body,
        'event': dict(title='Virtual Meeting with Valley Nurses Guild',
                      type='meeting', format='virtual',
                      group='Valley Nurses Guild',
                      description='Brief discussion of nurse staffing standards.',
                      start_date=THU, start_time=time(16, 0), end_time=time(16, 30),
                      location='Virtual (Microsoft Teams)',
                      poc_name='Nina Barrett', poc_email='nbarrett@valleynurses.example',
                      poc_phone='', topics=['Healthcare']),
        'fields': [
            ('title', 'Virtual Meeting with Valley Nurses Guild', 0.87, 'talk about nurse staffing standards'),
            ('group', 'Valley Nurses Guild', 0.97, 'Valley Nurses Guild'),
            ('start_date', THU.isoformat(), 0.91, 'this Thursday'),
            ('start_time', '16:00', 0.94, '4:00 PM'),
            ('end_time', '16:30', 0.89, '30 minutes'),
            ('location', 'Virtual (Microsoft Teams)', 0.90, 'over Teams'),
            ('format', 'virtual', 0.92, 'over Teams'),
            ('point_of_contact_name', 'Nina Barrett', 0.93, 'Nina Barrett'),
            ('point_of_contact_email', 'nbarrett@valleynurses.example', 0.98, 'nbarrett@valleynurses.example'),
            ('type', 'meeting', 0.90, '30 minutes with the Congressman'),
        ],
    })

    # 9 - Foreign Relations / Meeting / In Person / "Washington office" -> DC
    body = f"""Dear Representative Smith,

The Cedar Valley Sister Communities Council requests a courtesy meeting to introduce a visiting delegation of municipal officials from our partner region in Costa Rica, who are touring Franklin to study local economic development.

We hope to visit your Washington office on {long_date(D9)} at 10:00 AM to 10:30 AM. The delegation includes four guests and an interpreter.

With appreciation,
Gregory Sutton
Chair, Cedar Valley Sister Communities Council
gsutton@rvscc.example
(540) 555-9012"""
    specs.append({
        'subject': 'Courtesy meeting - visiting Costa Rican delegation',
        'sender_name': 'Gregory Sutton', 'sender_email': 'gsutton@rvscc.example',
        'recv': (12, 9), 'confidence': 0.92, 'body': body,
        'event': dict(title='Courtesy Meeting with Costa Rican Municipal Delegation',
                      type='meeting', format='in-person',
                      group='Cedar Valley Sister Communities Council',
                      description='Courtesy introduction of a visiting delegation of municipal officials from a partner region in Costa Rica studying local economic development.',
                      start_date=D9, start_time=time(10, 0), end_time=time(10, 30),
                      location=DC_OFFICE,
                      poc_name='Gregory Sutton', poc_email='gsutton@rvscc.example',
                      poc_phone='(540) 555-9012', topics=['Foreign Relations']),
        'fields': [
            ('title', 'Courtesy Meeting with Costa Rican Municipal Delegation', 0.88, 'courtesy meeting to introduce a visiting delegation of municipal officials'),
            ('group', 'Cedar Valley Sister Communities Council', 0.97, 'Cedar Valley Sister Communities Council'),
            ('start_date', D9.isoformat(), 0.96, long_date(D9)),
            ('start_time', '10:00', 0.95, '10:00 AM'),
            ('end_time', '10:30', 0.95, '10:30 AM'),
            ('location', DC_OFFICE, 0.86, 'your Washington office'),
            ('point_of_contact_name', 'Gregory Sutton', 0.94, 'Gregory Sutton'),
            ('point_of_contact_email', 'gsutton@rvscc.example', 0.98, 'gsutton@rvscc.example'),
            ('point_of_contact_phone', '(540) 555-9012', 0.95, '(540) 555-9012'),
            ('type', 'meeting', 0.92, 'courtesy meeting'),
        ],
    })

    # 10 - Crime / Event / In Person (short)
    body = f"""Congressman Smith,

Cedar Victim Support Services invites you to our brief Crime Victims' Rights Week recognition on {long_date(D10)} at 12:00 PM at the Cedar County Courthouse, 2 S Main St, Fairview, FR 00000. The program runs 30 minutes and honors local victim advocates.

Thank you,
Holly Barton
Director, Cedar Victim Support Services
hbarton@rvss.example"""
    specs.append({
        'subject': "Invitation: Crime Victims' Rights Week recognition",
        'sender_name': 'Holly Barton', 'sender_email': 'hbarton@rvss.example',
        'recv': (12, 47), 'confidence': 0.91, 'body': body,
        'event': dict(title="Crime Victims' Rights Week Recognition",
                      type='event', format='in-person',
                      group='Cedar Victim Support Services',
                      description="Brief recognition program for Crime Victims' Rights Week honoring local victim advocates.",
                      start_date=D10, start_time=time(12, 0), end_time=time(12, 30),
                      location='Cedar County Courthouse, 2 S Main St, Fairview, FR 00000',
                      poc_name='Holly Barton', poc_email='hbarton@rvss.example',
                      poc_phone='', topics=['Crime']),
        'fields': [
            ('title', "Crime Victims' Rights Week Recognition", 0.90, "Crime Victims' Rights Week recognition"),
            ('group', 'Cedar Victim Support Services', 0.97, 'Cedar Victim Support Services'),
            ('start_date', D10.isoformat(), 0.96, long_date(D10)),
            ('start_time', '12:00', 0.95, '12:00 PM'),
            ('end_time', '12:30', 0.88, 'runs 30 minutes'),
            ('location', 'Cedar County Courthouse, 2 S Main St, Fairview, FR 00000', 0.95, 'Cedar County Courthouse, 2 S Main St, Fairview, FR 00000'),
            ('point_of_contact_name', 'Holly Barton', 0.94, 'Holly Barton'),
            ('point_of_contact_email', 'hbarton@rvss.example', 0.98, 'hbarton@rvss.example'),
            ('type', 'event', 0.90, 'recognition'),
        ],
    })

    # 11 - Education / Hearing / Hybrid
    body = f"""Dear Representative Smith,

The Fairview Community School Board will hold a public hearing on its long-range facilities plan and would welcome brief remarks from you on federal infrastructure and education funding that supports school construction.

The hearing is scheduled for {long_date(D11)} from 6:30 PM to 8:00 PM at Fairview City Hall, 300 E Washington St, Fairview, FR 00000. Members of the public may also attend by livestream.

If you are available, we would invite your remarks near the start of the hearing.

Respectfully,
Howard Woods
Clerk, Fairview Community School Board
hwoods@lexcommunityschools.example
(540) 555-4455"""
    specs.append({
        'subject': 'Public hearing - long-range facilities plan',
        'sender_name': 'Howard Woods', 'sender_email': 'hwoods@lexcommunityschools.example',
        'recv': (13, 22), 'confidence': 0.93, 'body': body,
        'event': dict(title='Fairview Community School Board Public Hearing',
                      type='hearing', format='hybrid',
                      group='Fairview Community School Board',
                      description="Public hearing on the school board's long-range facilities plan; the Congressman is invited to give brief remarks on federal education and infrastructure funding.",
                      start_date=D11, start_time=time(18, 30), end_time=time(20, 0),
                      location='Fairview City Hall, 300 E Washington St, Fairview, FR 00000',
                      poc_name='Howard Woods', poc_email='hwoods@lexcommunityschools.example',
                      poc_phone='(540) 555-4455', topics=['Education']),
        'fields': [
            ('title', 'Fairview Community School Board Public Hearing', 0.89, 'public hearing on its long-range facilities plan'),
            ('group', 'Fairview Community School Board', 0.97, 'Fairview Community School Board'),
            ('start_date', D11.isoformat(), 0.96, long_date(D11)),
            ('start_time', '18:30', 0.95, '6:30 PM'),
            ('end_time', '20:00', 0.95, '8:00 PM'),
            ('location', 'Fairview City Hall, 300 E Washington St, Fairview, FR 00000', 0.95, 'Fairview City Hall, 300 E Washington St, Fairview, FR 00000'),
            ('format', 'hybrid', 0.90, 'attend by livestream'),
            ('point_of_contact_name', 'Howard Woods', 0.94, 'Howard Woods'),
            ('point_of_contact_email', 'hwoods@lexcommunityschools.example', 0.98, 'hwoods@lexcommunityschools.example'),
            ('point_of_contact_phone', '(540) 555-4455', 0.95, '(540) 555-4455'),
            ('type', 'hearing', 0.93, 'public hearing'),
        ],
    })

    # 12 - Industry / Meeting / In Person / "in your office" + duration
    body = f"""Dear Congressman,

The Highland Broadband Coalition requests a meeting to update your office on rural broadband deployment in the First District and to discuss federal funding timelines.

Could we meet in your office on {long_date(D12)} at 1:00 PM? We anticipate needing roughly 45 minutes. Our executive director and two member providers would attend.

Best regards,
Steven Boyer
Policy Lead, Highland Broadband Coalition
sboyer@highlandbroadband.example
(540) 555-6677"""
    specs.append({
        'subject': 'Meeting request - rural broadband deployment',
        'sender_name': 'Steven Boyer', 'sender_email': 'sboyer@highlandbroadband.example',
        'recv': (14, 5), 'confidence': 0.93, 'body': body,
        'event': dict(title='Meeting with Highland Broadband Coalition',
                      type='meeting', format='in-person',
                      group='Highland Broadband Coalition',
                      description='Update on rural broadband deployment in the district and discussion of federal funding timelines.',
                      start_date=D12, start_time=time(13, 0), end_time=time(13, 45),
                      location=DC_OFFICE,
                      poc_name='Steven Boyer', poc_email='sboyer@highlandbroadband.example',
                      poc_phone='(540) 555-6677', topics=['Industry']),
        'fields': [
            ('title', 'Meeting with Highland Broadband Coalition', 0.89, 'meeting to update your office on rural broadband deployment'),
            ('group', 'Highland Broadband Coalition', 0.97, 'Highland Broadband Coalition'),
            ('start_date', D12.isoformat(), 0.96, long_date(D12)),
            ('start_time', '13:00', 0.95, '1:00 PM'),
            ('end_time', '13:45', 0.88, 'roughly 45 minutes'),
            ('location', DC_OFFICE, 0.87, 'in your office'),
            ('point_of_contact_name', 'Steven Boyer', 0.94, 'Steven Boyer'),
            ('point_of_contact_email', 'sboyer@highlandbroadband.example', 0.98, 'sboyer@highlandbroadband.example'),
            ('point_of_contact_phone', '(540) 555-6677', 0.95, '(540) 555-6677'),
            ('type', 'meeting', 0.93, 'meeting'),
        ],
    })

    # 13 - Healthcare / Event / In Person
    body = f"""Dear Representative Smith,

You are warmly invited to the ribbon-cutting for the new wing of the Maple Grove Community Health Center, which expands primary care and dental services for uninsured residents of the district.

The ceremony will take place on {long_date(D13)} at 11:00 AM to 11:45 AM at the Maple Grove Community Health Center, 100 Greenhouse Rd, Fairview, FR 00000. A short tour will follow.

We would be delighted to have you join us and offer a few words if you wish.

Sincerely,
Denise Hayes
Community Outreach Manager, Maple Grove Community Health Center
dhayes@mgchc.example
(540) 555-8899"""
    specs.append({
        'subject': 'Invitation: community health center ribbon-cutting',
        'sender_name': 'Denise Hayes', 'sender_email': 'dhayes@mgchc.example',
        'recv': (14, 38), 'confidence': 0.94, 'body': body,
        'event': dict(title='Ribbon-Cutting: Maple Grove Community Health Center',
                      type='event', format='in-person',
                      group='Maple Grove Community Health Center',
                      description='Ribbon-cutting for a new wing expanding primary care and dental services for uninsured district residents, followed by a short tour.',
                      start_date=D13, start_time=time(11, 0), end_time=time(11, 45),
                      location='Maple Grove Community Health Center, 100 Greenhouse Rd, Fairview, FR 00000',
                      poc_name='Denise Hayes', poc_email='dhayes@mgchc.example',
                      poc_phone='(540) 555-8899', topics=['Healthcare']),
        'fields': [
            ('title', 'Ribbon-Cutting: Maple Grove Community Health Center', 0.89, 'ribbon-cutting for the new wing of the Maple Grove Community Health Center'),
            ('group', 'Maple Grove Community Health Center', 0.97, 'Maple Grove Community Health Center'),
            ('start_date', D13.isoformat(), 0.96, long_date(D13)),
            ('start_time', '11:00', 0.95, '11:00 AM'),
            ('end_time', '11:45', 0.95, '11:45 AM'),
            ('location', 'Maple Grove Community Health Center, 100 Greenhouse Rd, Fairview, FR 00000', 0.95, 'Maple Grove Community Health Center, 100 Greenhouse Rd, Fairview, FR 00000'),
            ('point_of_contact_name', 'Denise Hayes', 0.94, 'Denise Hayes'),
            ('point_of_contact_email', 'dhayes@mgchc.example', 0.98, 'dhayes@mgchc.example'),
            ('point_of_contact_phone', '(540) 555-8899', 0.95, '(540) 555-8899'),
            ('type', 'event', 0.90, 'ribbon-cutting'),
        ],
    })

    # 14 - Foreign Relations / Meeting / In Person
    body = f"""Dear Congressman Smith,

The Northern Border Trade Council would value a meeting to discuss cross-border trade in agricultural goods and manufactured components, which support a number of employers in the First District.

We propose {long_date(D14)} from 2:00 PM to 3:00 PM at The Lafayette Hotel, 800 16th St NW, Washington, DC 20006. Our trade director and a representative from the Canadian consulate would attend.

We appreciate your consideration.

Regards,
Marie Caron
Director, Northern Border Trade Council
mcaron@nbtrade.example
(202) 555-7711"""
    specs.append({
        'subject': 'Meeting request - cross-border trade',
        'sender_name': 'Marie Caron', 'sender_email': 'mcaron@nbtrade.example',
        'recv': (15, 14), 'confidence': 0.93, 'body': body,
        'event': dict(title='Meeting with Northern Border Trade Council',
                      type='meeting', format='in-person',
                      group='Northern Border Trade Council',
                      description='Discussion of cross-border trade in agricultural goods and manufactured components affecting district employers.',
                      start_date=D14, start_time=time(14, 0), end_time=time(15, 0),
                      location='The Lafayette Hotel, 800 16th St NW, Washington, DC 20006',
                      poc_name='Marie Caron', poc_email='mcaron@nbtrade.example',
                      poc_phone='(202) 555-7711', topics=['Foreign Relations']),
        'fields': [
            ('title', 'Meeting with Northern Border Trade Council', 0.89, 'meeting to discuss cross-border trade in agricultural goods and manufactured components'),
            ('group', 'Northern Border Trade Council', 0.97, 'Northern Border Trade Council'),
            ('start_date', D14.isoformat(), 0.96, long_date(D14)),
            ('start_time', '14:00', 0.95, '2:00 PM'),
            ('end_time', '15:00', 0.95, '3:00 PM'),
            ('location', 'The Lafayette Hotel, 800 16th St NW, Washington, DC 20006', 0.95, 'The Lafayette Hotel, 800 16th St NW, Washington, DC 20006'),
            ('point_of_contact_name', 'Marie Caron', 0.94, 'Marie Caron'),
            ('point_of_contact_email', 'mcaron@nbtrade.example', 0.98, 'mcaron@nbtrade.example'),
            ('point_of_contact_phone', '(202) 555-7711', 0.95, '(202) 555-7711'),
            ('type', 'meeting', 0.92, 'meeting'),
        ],
    })

    # 15 - Education / Event / In Person / start time only, NO end (correct omission)
    body = f"""Dear Representative Smith,

The Highland Scholars Foundation invites you to our annual Scholarship Awards Night, where we recognize 40 graduating seniors from across the First District who are pursuing higher education.

The program begins at 6:00 PM on {long_date(D15)} at the Diamond Street Community Center, 302 Diamond St, Fairview, FR 00000. We would be honored if you could help present the awards.

Warmly,
Carl Dalton
Board President, Highland Scholars Foundation
cdalton@highlandscholars.example
(540) 555-2233"""
    specs.append({
        'subject': 'Invitation: annual Scholarship Awards Night',
        'sender_name': 'Carl Dalton', 'sender_email': 'cdalton@highlandscholars.example',
        'recv': (16, 1), 'confidence': 0.92, 'body': body,
        'event': dict(title='Highland Scholars Foundation Scholarship Awards Night',
                      type='event', format='in-person',
                      group='Highland Scholars Foundation',
                      description='Annual awards night recognizing 40 graduating seniors from the district pursuing higher education; the Congressman is invited to help present awards.',
                      start_date=D15, start_time=time(18, 0), end_time=None,
                      location='Diamond Street Community Center, 302 Diamond St, Fairview, FR 00000',
                      poc_name='Carl Dalton', poc_email='cdalton@highlandscholars.example',
                      poc_phone='(540) 555-2233', topics=['Education']),
        'fields': [
            ('title', 'Highland Scholars Foundation Scholarship Awards Night', 0.89, 'annual Scholarship Awards Night'),
            ('group', 'Highland Scholars Foundation', 0.97, 'Highland Scholars Foundation'),
            ('start_date', D15.isoformat(), 0.96, long_date(D15)),
            ('start_time', '18:00', 0.95, '6:00 PM'),
            ('location', 'Diamond Street Community Center, 302 Diamond St, Fairview, FR 00000', 0.95, 'Diamond Street Community Center, 302 Diamond St, Fairview, FR 00000'),
            ('point_of_contact_name', 'Carl Dalton', 0.94, 'Carl Dalton'),
            ('point_of_contact_email', 'cdalton@highlandscholars.example', 0.98, 'cdalton@highlandscholars.example'),
            ('point_of_contact_phone', '(540) 555-2233', 0.95, '(540) 555-2233'),
            ('type', 'event', 0.90, 'Scholarship Awards Night'),
        ],
    })

    # 16 - Industry / Meeting / In Person
    body = f"""Hello,

The Valley Agricultural Producers Guild would like to meet with the Congressman to discuss farm labor, equipment costs, and regional market access for Sixth District producers.

We propose {long_date(D16)} from 9:00 AM to 9:45 AM at the Cedar County Fairgrounds office, 1 Fairground Rd, Fairview, FR 00000.

Thank you,
Wesley Coleman
Field Director, Valley Agricultural Producers Guild
wcoleman@valleyproducers.example
(540) 555-1199"""
    specs.append({
        'subject': 'Meeting request - agricultural producers',
        'sender_name': 'Wesley Coleman', 'sender_email': 'wcoleman@valleyproducers.example',
        'recv': (16, 49), 'confidence': 0.92, 'body': body,
        'event': dict(title='Meeting with Valley Agricultural Producers Guild',
                      type='meeting', format='in-person',
                      group='Valley Agricultural Producers Guild',
                      description='Discussion of farm labor, equipment costs, and regional market access for district producers.',
                      start_date=D16, start_time=time(9, 0), end_time=time(9, 45),
                      location='Cedar County Fairgrounds office, 1 Fairground Rd, Fairview, FR 00000',
                      poc_name='Wesley Coleman', poc_email='wcoleman@valleyproducers.example',
                      poc_phone='(540) 555-1199', topics=['Industry']),
        'fields': [
            ('title', 'Meeting with Valley Agricultural Producers Guild', 0.89, 'meet with the Congressman to discuss farm labor, equipment costs, and regional market access'),
            ('group', 'Valley Agricultural Producers Guild', 0.97, 'Valley Agricultural Producers Guild'),
            ('start_date', D16.isoformat(), 0.96, long_date(D16)),
            ('start_time', '09:00', 0.95, '9:00 AM'),
            ('end_time', '09:45', 0.95, '9:45 AM'),
            ('location', 'Cedar County Fairgrounds office, 1 Fairground Rd, Fairview, FR 00000', 0.95, 'Cedar County Fairgrounds office, 1 Fairground Rd, Fairview, FR 00000'),
            ('point_of_contact_name', 'Wesley Coleman', 0.94, 'Wesley Coleman'),
            ('point_of_contact_email', 'wcoleman@valleyproducers.example', 0.98, 'wcoleman@valleyproducers.example'),
            ('point_of_contact_phone', '(540) 555-1199', 0.95, '(540) 555-1199'),
            ('type', 'meeting', 0.92, 'meet with the Congressman'),
        ],
    })

    # 17 - Crime / Speaking / In Person / "next Tuesday" + duration
    body = """Dear Congressman Smith,

The Cedar First Responders Coalition would be honored to have you offer brief remarks at our annual First Responders Appreciation Day, recognizing local police, fire, and EMS personnel.

Could you join us next Tuesday at 5:00 PM at the Fairview Fire Department, 105 E Washington St, Fairview, FR 00000? We would ask for about ten minutes of remarks.

Thank you for honoring our first responders.

Sincerely,
Officer Raymond Bradford (Ret.)
President, Cedar First Responders Coalition
rbradford@rbfirstresponders.example
(540) 555-3322"""
    specs.append({
        'subject': 'Speaking invitation - First Responders Appreciation Day',
        'sender_name': 'Raymond Bradford', 'sender_email': 'rbradford@rbfirstresponders.example',
        'recv': (17, 28), 'confidence': 0.93, 'body': body,
        'event': dict(title='Remarks at First Responders Appreciation Day',
                      type='speaking', format='in-person',
                      group='Cedar First Responders Coalition',
                      description='Brief remarks at the annual First Responders Appreciation Day recognizing local police, fire, and EMS personnel.',
                      start_date=TUE, start_time=time(17, 0), end_time=time(17, 10),
                      location='Fairview Fire Department, 105 E Washington St, Fairview, FR 00000',
                      poc_name='Raymond Bradford', poc_email='rbradford@rbfirstresponders.example',
                      poc_phone='(540) 555-3322', topics=['Crime']),
        'fields': [
            ('title', 'Remarks at First Responders Appreciation Day', 0.88, 'brief remarks at our annual First Responders Appreciation Day'),
            ('group', 'Cedar First Responders Coalition', 0.97, 'Cedar First Responders Coalition'),
            ('start_date', TUE.isoformat(), 0.92, 'next Tuesday'),
            ('start_time', '17:00', 0.95, '5:00 PM'),
            ('end_time', '17:10', 0.87, 'about ten minutes of remarks'),
            ('location', 'Fairview Fire Department, 105 E Washington St, Fairview, FR 00000', 0.95, 'Fairview Fire Department, 105 E Washington St, Fairview, FR 00000'),
            ('point_of_contact_name', 'Raymond Bradford', 0.93, 'Raymond Bradford'),
            ('point_of_contact_email', 'rbradford@rbfirstresponders.example', 0.98, 'rbradford@rbfirstresponders.example'),
            ('point_of_contact_phone', '(540) 555-3322', 0.95, '(540) 555-3322'),
            ('type', 'speaking', 0.91, 'remarks'),
        ],
    })

    # 18 - Healthcare / Speaking / Virtual / duration
    body = f"""Good morning,

The Valley Telehealth Partnership is hosting a virtual panel on expanding telehealth access in rural communities and would be grateful if the Congressman could open the session with brief remarks.

The panel is on {long_date(D18)} at 12:00 PM and will be held over Zoom. We would ask for about one hour of your time, including a short Q&A.

Best,
Olivia Frost
Program Director, Valley Telehealth Partnership
ofrost@valleytelehealth.example"""
    specs.append({
        'subject': 'Virtual panel - rural telehealth access',
        'sender_name': 'Olivia Frost', 'sender_email': 'ofrost@valleytelehealth.example',
        'recv': (18, 7), 'confidence': 0.92, 'body': body,
        'event': dict(title='Opening Remarks at Valley Telehealth Partnership Panel',
                      type='speaking', format='virtual',
                      group='Valley Telehealth Partnership',
                      description='Opening remarks and short Q&A for a virtual panel on expanding telehealth access in rural communities.',
                      start_date=D18, start_time=time(12, 0), end_time=time(13, 0),
                      location='Virtual (Zoom)',
                      poc_name='Olivia Frost', poc_email='ofrost@valleytelehealth.example',
                      poc_phone='', topics=['Healthcare']),
        'fields': [
            ('title', 'Opening Remarks at Valley Telehealth Partnership Panel', 0.88, 'virtual panel on expanding telehealth access in rural communities'),
            ('group', 'Valley Telehealth Partnership', 0.97, 'Valley Telehealth Partnership'),
            ('start_date', D18.isoformat(), 0.96, long_date(D18)),
            ('start_time', '12:00', 0.94, '12:00 PM'),
            ('end_time', '13:00', 0.88, 'about one hour'),
            ('location', 'Virtual (Zoom)', 0.91, 'held over Zoom'),
            ('format', 'virtual', 0.93, 'virtual panel'),
            ('point_of_contact_name', 'Olivia Frost', 0.93, 'Olivia Frost'),
            ('point_of_contact_email', 'ofrost@valleytelehealth.example', 0.98, 'ofrost@valleytelehealth.example'),
            ('type', 'speaking', 0.90, 'open the session with brief remarks'),
        ],
    })

    # 19 - Foreign Relations / Meeting / Virtual / "next Tuesday" + 15 min (short, casual)
    body = """Hi! I'm the faculty advisor for the Cedar High School Diplomacy Club team. The students would love a quick 15-minute virtual chat with the Congressman about careers in foreign service and diplomacy.

Any chance he's free next Tuesday at 4:30 PM? We can send a Zoom link.

Thanks!
Megan Flynn
Faculty Advisor, Cedar High School Diplomacy Club
mflynn@rockbridgehs.example"""
    specs.append({
        'subject': 'Quick chat request - Model UN students',
        'sender_name': 'Megan Flynn', 'sender_email': 'mflynn@rockbridgehs.example',
        'recv': (19, 33), 'confidence': 0.89, 'body': body,
        'event': dict(title='Virtual Q&A with Cedar High School Diplomacy Club',
                      type='meeting', format='virtual',
                      group='Cedar High School Diplomacy Club',
                      description='Brief virtual chat with Model UN students about careers in foreign service and diplomacy.',
                      start_date=TUE, start_time=time(16, 30), end_time=time(16, 45),
                      location='Virtual (Zoom)',
                      poc_name='Megan Flynn', poc_email='mflynn@rockbridgehs.example',
                      poc_phone='', topics=['Foreign Relations']),
        'fields': [
            ('title', 'Virtual Q&A with Cedar High School Diplomacy Club', 0.86, 'quick 15-minute virtual chat with the Congressman about careers in foreign service and diplomacy'),
            ('group', 'Cedar High School Diplomacy Club', 0.96, 'Cedar High School Diplomacy Club'),
            ('start_date', TUE.isoformat(), 0.91, 'next Tuesday'),
            ('start_time', '16:30', 0.93, '4:30 PM'),
            ('end_time', '16:45', 0.88, '15-minute'),
            ('location', 'Virtual (Zoom)', 0.90, 'send a Zoom link'),
            ('format', 'virtual', 0.92, 'virtual chat'),
            ('point_of_contact_name', 'Megan Flynn', 0.92, 'Megan Flynn'),
            ('point_of_contact_email', 'mflynn@rockbridgehs.example', 0.98, 'mflynn@rockbridgehs.example'),
            ('type', 'meeting', 0.88, 'chat with the Congressman'),
        ],
    })

    # 20 - Education / Meeting / In Person / "in your office" + explicit times (formal, longer)
    body = f"""Dear Representative Smith,

On behalf of the Valley Association of School Leaders, I am writing to request a meeting with you to discuss federal education policy as it affects the Commonwealth's school divisions, with particular attention to the funding outlook for the upcoming school year.

Our association represents superintendents from all 132 of Franklin's school divisions, including the divisions within the First District. We would like to share a brief overview of enrollment and staffing trends, summarize the priorities our members have identified for the year ahead, and answer any questions your staff may have. We find these conversations most productive when they are focused and concrete, and we will come prepared with a one-page summary for your team.

We would be grateful to meet in your office on {long_date(D20)} from 10:30 AM to 11:15 AM. Our executive director and the superintendent of one Sixth District division would attend.

Thank you for your time and for your ongoing attention to public education in Franklin.

Respectfully,
Dr. Linda Cardenas
Director of Government Relations, Valley Association of School Leaders
lcardenas@valss.example
(804) 555-9988"""
    specs.append({
        'subject': 'Meeting request - federal education policy & funding outlook',
        'sender_name': 'Dr. Linda Cardenas', 'sender_email': 'lcardenas@valss.example',
        'recv': (20, 41), 'confidence': 0.94, 'body': body,
        'event': dict(title='Meeting with Valley Association of School Leaders',
                      type='meeting', format='in-person',
                      group='Valley Association of School Leaders',
                      description='Discussion of federal education policy affecting Franklin school divisions, including the funding outlook for the upcoming school year and member priorities.',
                      start_date=D20, start_time=time(10, 30), end_time=time(11, 15),
                      location=DC_OFFICE,
                      poc_name='Dr. Linda Cardenas', poc_email='lcardenas@valss.example',
                      poc_phone='(804) 555-9988', topics=['Education']),
        'fields': [
            ('title', 'Meeting with Valley Association of School Leaders', 0.90, "meeting with you to discuss federal education policy as it affects the Commonwealth's school divisions"),
            ('group', 'Valley Association of School Leaders', 0.98, 'Valley Association of School Leaders'),
            ('start_date', D20.isoformat(), 0.96, long_date(D20)),
            ('start_time', '10:30', 0.95, '10:30 AM'),
            ('end_time', '11:15', 0.95, '11:15 AM'),
            ('location', DC_OFFICE, 0.87, 'in your office'),
            ('point_of_contact_name', 'Dr. Linda Cardenas', 0.95, 'Dr. Linda Cardenas'),
            ('point_of_contact_email', 'lcardenas@valss.example', 0.98, 'lcardenas@valss.example'),
            ('point_of_contact_phone', '(804) 555-9988', 0.95, '(804) 555-9988'),
            ('type', 'meeting', 0.93, 'meeting'),
        ],
    })

    # Farm Bureau crop-insurance meeting. Pinned as the single most-recent
    # extraction (see realize_events). All parties/org are new to the directory,
    # so every review card exercises the "new record" path.
    body = """Dear Scheduler,

I hope this note finds you well. My name is Carl Whitmore and I serve as President of the Cedar Valley Farm Bureau, writing on behalf of a group of our members who live and farm in Elm County, all constituents of the Congressman's. We would be grateful for thirty minutes of his time to discuss the upcoming farm bill and, in particular, the crop insurance provisions that matter a great deal to growers back home.

We understand the Congressman keeps a full calendar, so I'll be direct about what we're hoping for. We will be up in Washington the first week of March and would like to come by the office on Monday the 2nd. Early afternoon works best for our group; if 1:30 in the afternoon is open on his schedule that day, that would suit us perfectly, though we can be flexible by half an hour either way if it helps you fit us in.

It would be myself and Joan Petty, who handles government affairs for the Bureau, attending in person. We had hoped to bring two of our county board members as well, but their plans fell through, so it will just be the two of us. We're happy to keep it small.

On substance, our members are most focused on protecting the crop insurance title as the farm bill moves forward, and we'd like to walk the Congressman through how the program plays out on the ground in the Valley — what's working, what the premium structure looks like for our row-crop and orchard folks, and a few priorities we hope his office will keep in mind during reauthorization. Nothing adversarial; we just want him to hear directly from constituents who depend on it.

If that Monday afternoon slot doesn't work, please let us know what does and we'll do our best to accommodate. You can reach me directly at 202-555-0118, or by email at cwhitmore@svfarmbureau.example, and I'll respond quickly.

Thank you for your time and for everything the office does for the First District.

Warm regards,

Carl Whitmore

President, Cedar Valley Farm Bureau"""
    specs.append({
        '_pin_recent': True,
        'subject': 'Meeting request — Cedar Valley Farm Bureau, Elm County constituents',
        'sender_name': 'Carl Whitmore', 'sender_email': 'cwhitmore@svfarmbureau.example',
        'recv': (0, 20), 'confidence': 0.93, 'body': body,
        'event': dict(title='Meeting with Cedar Valley Farm Bureau',
                      type='meeting', format='in-person',
                      group='Cedar Valley Farm Bureau',
                      description='Thirty-minute meeting with the Cedar Valley Farm Bureau on the upcoming farm bill and crop insurance provisions affecting Elm County growers.',
                      start_date=MAR2, start_time=time(13, 30), end_time=time(14, 0),
                      location=DC_OFFICE,
                      poc_name='Carl Whitmore', poc_email='cwhitmore@svfarmbureau.example',
                      poc_phone='202-555-0118', topics=['Agriculture']),
        'fields': [
            ('title', 'Meeting with Cedar Valley Farm Bureau', 0.88, 'discuss the upcoming farm bill'),
            ('group', 'Cedar Valley Farm Bureau', 0.97, 'Cedar Valley Farm Bureau'),
            ('start_date', MAR2.isoformat(), 0.82, 'Monday the 2nd'),
            ('start_time', '13:30', 0.9, '1:30 in the afternoon'),
            ('end_time', '14:00', 0.79, 'thirty minutes'),
            ('location', DC_OFFICE, 0.7, 'come by the office'),
            ('point_of_contact_name', 'Carl Whitmore', 0.96, 'Carl Whitmore'),
            ('point_of_contact_email', 'cwhitmore@svfarmbureau.example', 0.98, 'cwhitmore@svfarmbureau.example'),
            ('point_of_contact_phone', '202-555-0118', 0.95, '202-555-0118'),
            ('type', 'meeting', 0.9, 'discuss'),
        ],
    })

    return specs


# ---------------------------------------------------------------------------
# Review-queue specs (from build_specs above): all start as inbox items
# pending human review of the AI extraction. No routing yet.
# ---------------------------------------------------------------------------
def build_review_specs():
    specs = build_specs()
    for spec in specs:
        spec['event']['status'] = 'received'
        spec['routing_state'] = 'no_routing'
    return specs


# ---------------------------------------------------------------------------
# Calendar specs: 35 post-review events spread across last week / this week /
# next week. Each one already has a status and routing state baked in. These
# are the events a scheduler has already triaged out of the inbox.
# ---------------------------------------------------------------------------
def build_calendar_specs():
    """35 background calendar events. Each has status + routing pre-assigned.

    Workflow rule: routing exists only for post-review events. We use
    no_routing for terminal/interim states (canceled, passed, hold, fyied)
    where there is no active approval chain to display.
    """
    specs = []

    TITLE_BY_KIND = {
        'event':    '{group} Event',
        'meeting':  'Meeting with {group}',
        'speaking': 'Remarks at {group} Event',
        'hearing':  '{group} Public Hearing',
        'votes':    '{group} Vote',
    }

    def add(offset, group, topic, kind, fmt, hour, minute, dur_min,
            status, routing, location, poc):
        poc_first, poc_last, poc_phone = poc
        poc_full = f'{poc_first} {poc_last}'
        poc_email = f'{poc_first.lower().replace(". ", ".")}.{poc_last.lower()}@example.org'
        date_obj = TODAY + timedelta(days=offset)
        t_start = time(hour, minute)
        t_end = (datetime.combine(date_obj, t_start)
                 + timedelta(minutes=dur_min)).time()
        title = TITLE_BY_KIND.get(kind, f'{kind.title()} - {group}').format(group=group)

        body = f"""Dear Representative Smith,

We are writing on behalf of {group} to invite you to our {title.lower()} on {long_date(date_obj)} from {t_start.strftime('%I:%M %p')} to {t_end.strftime('%I:%M %p')} at {location}.

We hope you can join us and would be glad to provide additional details on request.

Best regards,
{poc_full}
{poc_email}
{poc_phone}"""

        specs.append({
            'subject': f'Invitation: {title}',
            'sender_name': poc_full,
            'sender_email': poc_email,
            'recv': (9 + (abs(offset) % 9), (abs(offset) * 13) % 60),
            'confidence': 0.88,
            'body': body,
            'event': dict(
                title=title, type=kind, format=fmt, group=group,
                description=f'Engagement with {group} concerning {topic}.',
                start_date=date_obj, start_time=t_start, end_time=t_end,
                location=location,
                poc_name=poc_full, poc_email=poc_email, poc_phone=poc_phone,
                topics=[topic],
                status=status,
            ),
            'fields': [
                ('title', title, 0.86, title.lower()),
                ('group', group, 0.95, group),
                ('start_date', date_obj.isoformat(), 0.92, long_date(date_obj)),
                ('start_time', t_start.strftime('%H:%M'), 0.93, t_start.strftime('%I:%M %p')),
                ('end_time', t_end.strftime('%H:%M'), 0.90, t_end.strftime('%I:%M %p')),
                ('location', location, 0.88, location),
                ('point_of_contact_name', poc_full, 0.93, poc_full),
                ('point_of_contact_email', poc_email, 0.97, poc_email),
                ('point_of_contact_phone', poc_phone, 0.92, poc_phone),
                ('type', kind, 0.89, kind),
            ],
            'routing_state': routing,
        })

    # === PAST (offsets -7..-1) - 12 events ===
    add(-7, 'Patriots Legion Post 9', 'Foreign Relations', 'speaking', 'in-person',
        18, 0, 30, 'scheduled', 'fully_approved',
        'Patriots Legion Post 9, 17 Diamond St, Fairview, FR 00000',
        ('Robert', 'Mason', '(540) 555-1111'))
    add(-7, 'RMA Alumni Association', 'Education', 'event', 'in-person',
        12, 0, 60, 'rsvped', 'fully_approved',
        'Cadet Hall, RMA, Fairview, FR 00000',
        ('Janet', 'Whitford', '(540) 555-2222'))
    add(-6, 'Fairview Community Service Club', 'Industry', 'speaking', 'in-person',
        12, 30, 45, 'scheduled', 'fully_approved',
        'Fairview Community Club Hall, 200 N Main St, Fairview, FR 00000',
        ('Frank', 'Powell', '(540) 555-3333'))
    add(-5, 'Cedar Substance Response Task Force', 'Crime', 'meeting', 'in-person',
        9, 30, 45, 'rsvped', 'fully_approved',
        DC_OFFICE,
        ('Sarah', 'Quill', '(540) 555-4444'))
    add(-5, 'Maple Ridge Community Hospital', 'Healthcare', 'event', 'in-person',
        14, 0, 90, 'scheduled', 'fully_approved',
        'Maple Ridge Community Hospital, 1 Health Cir, Fairview, FR 00000',
        ('Linda', 'Faust', '(540) 555-5555'))
    add(-4, 'Fairview Roundtable Club', 'Industry', 'speaking', 'in-person',
        7, 30, 30, 'scheduled', 'fully_approved',
        'The Palms Restaurant, 37 S Main St, Fairview, FR 00000',
        ('Theresa', 'Bains', '(540) 555-6666'))
    add(-3, 'Highland World Affairs Council', 'Foreign Relations', 'event', 'in-person',
        18, 0, 90, 'regrets_sent', 'fully_approved',
        'The Maplewood Inn, 301 Greenville Ave, Fairview, FR 00000',
        ('Charles', 'Truitt', '(540) 555-7777'))
    add(-3, 'Fairview College Alumni Office', 'Education', 'meeting', 'in-person',
        15, 0, 45, 'scheduled', 'fully_approved',
        'Founders Hall, Fairview College, Fairview, FR 00000',
        ('Allison', 'Veers', '(540) 555-8888'))
    add(-2, 'Fairview Police Support Foundation', 'Crime', 'event', 'in-person',
        17, 30, 60, 'rsvped', 'fully_approved',
        'Fairview Police HQ, 105 E Washington St, Fairview, FR 00000',
        ('Mark', 'Donlan', '(540) 555-9999'))
    add(-2, 'Cedar Area Support Services', 'Healthcare', 'meeting', 'in-person',
        10, 0, 60, 'scheduled', 'fully_approved',
        DISTRICT_OFFICE,
        ('Phillip', 'Ortez', '(540) 555-0011'))
    add(-1, 'Valley Veterans Post 5051', 'Foreign Relations', 'event', 'in-person',
        11, 0, 45, 'canceled', 'no_routing',
        'Valley Veterans Post 5051, Millbrook, FR 00000',
        ('James', 'Holcombe', '(540) 555-0022'))
    add(-1, 'Brookside Business Council', 'Industry', 'meeting', 'in-person',
        16, 0, 60, 'ignored', 'no_routing',
        'Brookside Business Council, 2330 Sycamore Ave, Brookside, FR 00000',
        ('Margaret', 'Allen', '(540) 555-0033'))

    # === CURRENT WEEK (offsets 0..6) - 12 events ===
    add(0, 'Safe Haven Center', 'Crime', 'meeting', 'in-person',
        9, 0, 60, 'scheduling_in_progress', 'stage1_done',
        DISTRICT_OFFICE,
        ('Renata', 'Vega', '(540) 555-0044'))
    add(0, 'Valley Cancer Society', 'Healthcare', 'event', 'hybrid',
        13, 0, 90, 'scheduled', 'fully_approved',
        'Cedar Public Library, 138 S Main St, Fairview, FR 00000',
        ('Henry', 'Wallace', '(540) 555-0055'))
    add(1, 'Cedar Education Trust', 'Education', 'meeting', 'virtual',
        14, 30, 30, 'hold', 'no_routing',
        'Virtual (Microsoft Teams)',
        ('Pam', 'Holcomb', '(540) 555-0066'))
    add(2, 'Highland Forestry Council', 'Industry', 'meeting', 'in-person',
        10, 30, 45, 'scheduling_in_progress', 'stage1_done',
        DC_OFFICE,
        ('Greg', 'Carter', '(540) 555-0077'))
    add(2, 'Cedar Visitors Bureau', 'Industry', 'speaking', 'in-person',
        17, 0, 30, 'scheduled', 'fully_approved',
        'Cedar Visitors Office, 100 E Washington St, Fairview, FR 00000',
        ('Belinda', 'Frias', '(540) 555-0088'))
    add(3, "Elm County Public Safety Office", 'Crime', 'meeting', 'in-person',
        15, 0, 60, 'scheduling_in_progress', 'stage1_done',
        'Elm County Public Safety HQ, 4 N Elm St, Westfield, FR 00000',
        ('Tom', 'Reeves', '(540) 555-0099'))
    add(3, 'Valley Mental Health Network', 'Healthcare', 'meeting', 'virtual',
        11, 30, 45, 'hold', 'no_routing',
        'Virtual (Zoom)',
        ('Anya', 'Solomon', '(540) 555-0110'))
    add(4, 'Fairview Sister Communities Commission', 'Foreign Relations', 'event', 'in-person',
        14, 0, 60, 'scheduled', 'fully_approved',
        'Fairview City Hall, 300 E Washington St, Fairview, FR 00000',
        ('Eleanor', 'Whittaker', '(540) 555-0220'))
    add(4, 'Cedar County Youth Farmers', 'Education', 'speaking', 'in-person',
        18, 0, 30, 'scheduling_in_progress', 'stage1_done',
        'Cedar County Youth Farmers Center, 250 S Main St, Fairview, FR 00000',
        ('Janelle', 'Cobb', '(540) 555-0330'))
    add(5, 'Cedar Valley Global Affairs Forum', 'Foreign Relations', 'meeting', 'virtual',
        12, 0, 60, 'rsvped', 'fully_approved',
        'Virtual (Zoom)',
        ('Henrik', 'Olsen', '(540) 555-0440'))
    add(5, 'Fairview Family Community Center', 'Healthcare', 'event', 'in-person',
        16, 30, 45, 'scheduled', 'fully_approved',
        'Fairview Family Community Center, 1000 Diamond St, Fairview, FR 00000',
        ('Tyrone', 'Briggs', '(540) 555-0550'))
    add(6, 'Cedar Heritage Society Education Programs', 'Education', 'event', 'in-person',
        10, 0, 60, 'fyied', 'no_routing',
        'Cedar Heritage Society, 101 E Washington St, Fairview, FR 00000',
        ('Drew', 'Eastman', '(540) 555-0660'))

    # === NEXT WEEK (offsets 7..14) - 11 events ===
    add(7, 'Cedar Senior Services Center', 'Healthcare', 'event', 'in-person',
        11, 0, 60, 'scheduling_in_progress', 'stage1_done',
        'Cedar Senior Services Center, 100 W Nelson St, Fairview, FR 00000',
        ('Elsa', 'Karnes', '(540) 555-0770'))
    add(8, 'Millbrook Town Merchants Council', 'Industry', 'meeting', 'in-person',
        9, 30, 45, 'scheduled', 'fully_approved',
        'Millbrook Town Hall, 1108 Cedar Ridge Rd, Millbrook, FR 00000',
        ('Jim', 'Petty', '(540) 555-0880'))
    add(8, 'Cedar Workforce Alliance', 'Industry', 'meeting', 'in-person',
        14, 0, 60, 'scheduling_in_progress', 'stage1_done',
        DISTRICT_OFFICE,
        ('Pricilla', 'Yates', '(540) 555-0990'))
    add(9, 'Brookside Community Library', 'Education', 'event', 'in-person',
        16, 0, 30, 'hold', 'no_routing',
        'Brookside Community Library, 2210 Magnolia Ave, Brookside, FR 00000',
        ('Sam', 'Ferris', '(540) 555-1100'))
    add(10, 'Pacific Friendship Foundation', 'Foreign Relations', 'event', 'in-person',
        18, 30, 90, 'scheduled', 'fully_approved',
        'The Riverside Conference Center, 1500 Wilson Blvd, Fairview, FR 00000',
        ('Jieun', 'Park', '(540) 555-1200'))
    add(10, 'ReadWell Project', 'Education', 'meeting', 'in-person',
        13, 0, 45, 'scheduling_in_progress', 'stage1_done',
        DISTRICT_OFFICE,
        ('Marisol', 'Tatum', '(540) 555-1300'))
    add(11, 'Fairview Visitors Board', 'Industry', 'meeting', 'in-person',
        10, 0, 45, 'scheduling_in_progress', 'stage1_done',
        'Fairview Visitors Office, 100 E Washington St, Fairview, FR 00000',
        ('Lina', 'Castro', '(540) 555-1400'))
    add(12, 'Cedar Family Safety Task Force', 'Crime', 'meeting', 'hybrid',
        15, 30, 60, 'scheduled', 'fully_approved',
        'Safe Haven Center Offices, 120 Varner Ln, Fairview, FR 00000',
        ('Carmen', 'Lopez', '(540) 555-1500'))
    add(12, 'Lakeside Regional Medical Center', 'Healthcare', 'meeting', 'in-person',
        9, 0, 60, 'hold', 'no_routing',
        'Lakeside Regional Medical Center, 78 Medical Center Dr, Lakeside, FR 00000',
        ('Marcus', 'Hyde', '(540) 555-1600'))
    add(13, 'Valley Lung Health Alliance', 'Healthcare', 'event', 'virtual',
        14, 0, 60, 'fyied', 'no_routing',
        'Virtual (Zoom)',
        ('Vincent', 'Krauss', '(540) 555-1700'))
    add(14, 'Fairview Book Festival', 'Education', 'speaking', 'in-person',
        19, 0, 45, 'scheduling_in_progress', 'stage1_done',
        'Cedar Public Library, 138 S Main St, Fairview, FR 00000',
        ('Cora', 'Eden', '(540) 555-1800'))

    assert len(specs) == 35, f'Expected 35 calendar specs, got {len(specs)}'
    return specs


# ---------------------------------------------------------------------------
# Undated specs: events that exist before a firm date is set — the "parking
# lot" a scheduler keeps for invitations accepted in principle but whose date
# is still being negotiated. (Congressional schedulers report most events are
# only dated at the last minute, yet must be tracked from the moment they come
# in.) Two flavors:
#   * truly undated (start_date=None) — no date proposed yet
#   * tentative date range (is_date_range=True, end_date != start_date) —
#     narrowed to a window but not a single day
# All are post-review calendar items: no inbox review, no approval routing.
# ---------------------------------------------------------------------------
def build_undated_specs():
    specs = []

    def add_undated(title, group, topic, kind, fmt, status, location, poc,
                    body_when, start=None, end=None):
        poc_first, poc_last, poc_phone = poc
        poc_full = f'{poc_first} {poc_last}'
        poc_email = f'{poc_first.lower()}.{poc_last.lower()}@example.org'
        is_range = start is not None and end is not None and start != end
        body = f"""Dear Representative Smith,

On behalf of {group}, we would like to invite you to our {title.lower()}. {body_when}

We will follow up to confirm timing as soon as our plans firm up. We did not want to wait to put this on your radar.

Best regards,
{poc_full}
{poc_email}
{poc_phone}"""
        specs.append({
            'subject': f'Invitation: {title}',
            'sender_name': poc_full,
            'sender_email': poc_email,
            'recv': (10, 20),
            'confidence': 0.83,
            'body': body,
            'event': dict(
                title=title, type=kind, format=fmt, group=group,
                description=f'Engagement with {group} concerning {topic}. '
                            f'Date not yet confirmed.',
                start_date=start, end_date=end, is_date_range=is_range,
                start_time=None, end_time=None,
                location=location,
                poc_name=poc_full, poc_email=poc_email, poc_phone=poc_phone,
                topics=[topic],
                status=status,
            ),
            'fields': [
                ('title', title, 0.85, title.lower()),
                ('group', group, 0.95, group),
                ('type', kind, 0.88, kind),
            ],
            'routing_state': 'no_routing',
        })

    # --- Truly undated (no date proposed yet) ---
    add_undated(
        'Sixth District Spring Town Hall', 'Cedar County Community League',
        'Education', 'event', 'in-person', 'scheduling_in_progress',
        'Cedar County Office, 150 S Main St, Fairview, FR 00000',
        ('Diane', 'Mercer', '(540) 555-2101'),
        'We are still settling on a date and will propose a few options once the venue confirms availability.')
    add_undated(
        'Veterans Services Roundtable', 'Valley Veterans Post 5051',
        'Foreign Relations', 'meeting', 'in-person', 'hold',
        DISTRICT_OFFICE,
        ('Howard', 'Pell', '(540) 555-2102'),
        'No date is fixed yet — we wanted to get on the schedule early and will coordinate a time that works for the Congressman.')
    add_undated(
        'Farm Bureau Facility Tour', 'Cedar Growers Association',
        'Industry', 'event', 'in-person', 'scheduling_in_progress',
        'Cedar Growers Association, 645 Waddell St, Fairview, FR 00000',
        ('Nora', 'Childs', '(540) 555-2103'),
        'The date is still open on our end; we are flexible and happy to work around the district work calendar.')

    # --- Tentative date ranges (window known, exact day not yet) ---
    add_undated(
        'Appropriations District Work Period Visit', 'Office of the Congressman',
        'Industry', 'meeting', 'in-person', 'scheduling_in_progress',
        DISTRICT_OFFICE,
        ('Grace', 'Holloway', '(540) 555-2104'),
        'We are targeting sometime during the upcoming district work period and will lock the exact day closer to the recess.',
        start=TODAY + timedelta(days=21), end=TODAY + timedelta(days=27))
    add_undated(
        'Business Council Annual Gala', 'Fairview Business Council',
        'Industry', 'event', 'in-person', 'hold',
        'The Riverside Hotel, 24 S Market St, Fairview, FR 00000',
        ('Victor', 'Reyna', '(540) 555-2105'),
        'The gala will fall somewhere in the second week of next month; the board is finalizing the exact evening now.',
        start=TODAY + timedelta(days=38), end=TODAY + timedelta(days=44))

    return specs


# ---------------------------------------------------------------------------
# Staff assignment + approval routing
# ---------------------------------------------------------------------------
def is_member_of_congress(user):
    """True if this user's linked staff profile is flagged as the Member of Congress."""
    profile = getattr(user, 'staff_profile', None)
    return bool(profile and profile.is_member_of_congress)


def resolve_assigned_users(topics, users):
    """Return up to 2 user objects whose legislative areas match the topics.

    The Member of Congress is never auto-assigned as an event approver.
    """
    candidate_usernames = []
    for t in topics:
        for username in TOPIC_TO_STAFF.get(t, []):
            if username not in candidate_usernames and not is_member_of_congress(users[username]):
                candidate_usernames.append(username)
    if not candidate_usernames:
        return [users['samuel']]
    return [users[u] for u in candidate_usernames[:2]]


def member_of_congress_name(office):
    """Name of the office's Member of Congress, or None if unset."""
    moc = office.staff_members.filter(is_member_of_congress=True).first()
    return moc.name if moc else None


# How many events the Member personally attends (drives the podium indicator).
MEMBER_ATTENDING_CALENDAR = 10
MEMBER_ATTENDING_REVIEW = 5


def assign_member_attendance(review_specs, calendar_specs, member_name):
    """Flag a deterministic subset of specs as personally attended by the Member.

    Attendance is independent of staff routing — the Member is never an approver,
    but appears in the event's ``staff`` list so the podium indicator renders.
    Selection is seeded so re-runs pick the same events.
    """
    for spec in review_specs + calendar_specs:
        spec['_member_attending'] = False
    if not member_name:
        return
    rng = random.Random(20260610)
    for specs, n in ((calendar_specs, MEMBER_ATTENDING_CALENDAR),
                     (review_specs, MEMBER_ATTENDING_REVIEW)):
        for idx in rng.sample(range(len(specs)), min(n, len(specs))):
            specs[idx]['_member_attending'] = True


def build_routing_json(assigned_users, scheduler_user):
    """Stage 1: assigned staff (parallel, all required). Stage 2: Samuel Cook."""
    return {
        'version': 1,
        'stages': [
            {
                'stage_id': 'stage-1',
                'order': 1,
                'type': 'parallel',
                'approvers': [
                    {'user_id': str(u.id), 'name': u.get_full_name() or u.username, 'required': True}
                    for u in assigned_users
                ],
                'all_required': True,
            },
            {
                'stage_id': 'stage-2',
                'order': 2,
                'type': 'sequential',
                'approvers': [
                    {'user_id': str(scheduler_user.id),
                     'name': scheduler_user.get_full_name() or scheduler_user.username,
                     'required': True},
                ],
            },
        ],
    }


def apply_routing_state(event, state):
    """Update the EventApproval rows to reflect demo routing state."""
    approvals = list(EventApproval.objects.filter(event=event).order_by('stage_order'))
    if not approvals:
        return

    if state == 'fully_approved':
        # All stages already approved in the recent past (1-5 days ago)
        for ap in approvals:
            decided = timezone.now() - timedelta(days=5 - (ap.stage_order % 5),
                                                  hours=(ap.stage_order * 2) % 12)
            ap.status = 'approved'
            ap.comment = 'Approved (demo data)'
            ap.decided_at = decided
            ap.save(update_fields=['status', 'comment', 'decided_at'])

    elif state == 'stage1_done':
        # Approve only stage 1; stage 2 (Samuel) remains pending
        for ap in approvals:
            if ap.stage_order == 1:
                ap.status = 'approved'
                ap.comment = 'Approved (demo data)'
                ap.decided_at = timezone.now() - timedelta(hours=12 + ap.stage_order)
                ap.save(update_fields=['status', 'comment', 'decided_at'])

    # 'pending' state: leave all approvals as-is (pending)


# ---------------------------------------------------------------------------
# Realization
# ---------------------------------------------------------------------------
def clear_event_data(office):
    print('Clearing existing event data for the Smith office...')
    event_qs = Event.objects.filter(created_by__office=office)
    # EventEmailLink / EventThreadLink rows cascade-delete with their Event and
    # their EmailProcessing, so they need no explicit handling here.
    EmailProcessing.objects.filter(event__in=event_qs).delete()
    EventApproval.objects.filter(event__in=event_qs).delete()
    EventChangeSuggestion.objects.filter(event__in=event_qs).delete()
    EventChangeHistory.objects.filter(event__in=event_qs).delete()
    EventReviewAuditLog.objects.filter(event__in=event_qs).delete()
    count = event_qs.count()
    event_qs.delete()
    EmailProcessing.objects.filter(event__isnull=True).delete()
    # Remove conversation threads orphaned by the email deletions above.
    EmailThread.objects.filter(emails__isnull=True).delete()
    # Normalized contacts/organizations are demo-global (no office FK). The
    # EventContact / EventOrganization links cascade with their events above;
    # clear the Contact/Organization rows themselves so re-runs rebuild a clean
    # directory rather than accumulating duplicates.
    Contact.objects.all().delete()
    Organization.objects.all().delete()
    print(f'  removed {count} prior event(s).')


def realize_events(office, users):
    samuel = users['samuel']
    service = ApprovalRoutingService()

    # Pre-seed a small existing directory (after clear_event_data wiped it) so
    # review cards can match. Review events themselves create no contacts.
    seed_directory(samuel)

    review_specs = build_review_specs()
    # Undated/range events ride the calendar bucket (post-review, no inbox item).
    calendar_specs = build_calendar_specs() + build_undated_specs()

    # Flag a subset of events as personally attended by the Member of Congress
    # so the podium indicator is visible across the demo.
    member_name = member_of_congress_name(office)
    assign_member_attendance(review_specs, calendar_specs, member_name)

    # Specs flagged _pin_recent sit out the shuffle/stagger and are stamped just
    # after `now`, so they remain the single most-recent extraction(s) at the top
    # of the inbox regardless of the deterministic shuffle.
    pinned_specs = [s for s in review_specs if s.get('_pin_recent')]
    review_specs = [s for s in review_specs if not s.get('_pin_recent')]

    all_specs = [(spec, 'review') for spec in review_specs] + \
                [(spec, 'calendar') for spec in calendar_specs]

    # Stagger received-times across the past 7 days so review (AI extraction)
    # and calendar (post-review approval) items interleave in the inbox sort
    # instead of appearing as two distinct blocks. Deterministic seed makes
    # re-runs produce the same ordering.
    rng = random.Random(20260603)
    rng.shuffle(all_specs)
    now = timezone.now()
    horizon = timedelta(days=7)
    span = len(all_specs)
    for i, (spec, _bucket) in enumerate(all_specs):
        frac = i / max(span - 1, 1)
        jitter_min = rng.randint(0, 90)
        # frac=0 -> 7 days ago, frac=1 -> ~now. Pinned specs land strictly after.
        spec['_received_at'] = (
            now - horizon * (1 - frac) - timedelta(minutes=jitter_min)
        )

    # Stamp pinned extraction(s) just past `now` so they sort newest-first.
    for offset, spec in enumerate(pinned_specs):
        spec['_received_at'] = now + timedelta(minutes=offset + 1)
        all_specs.append((spec, 'review'))

    created = 0
    for i, (spec, bucket) in enumerate(all_specs, start=1):
        ev = spec['event']
        body = spec['body']
        routing_state = spec['routing_state']
        is_review = (bucket == 'review')

        # Review-queue items are raw AI extractions: no staff assignment, no
        # approval routing, extracted_fields populated with 'pending' status.
        # Calendar items are post-review: staff/routing populated, no extraction
        # artifacts (those were accepted into the canonical event data).
        # The inbox API treats events with non-empty extracted_fields as
        # "resolved reviews" and surfaces them with the EXTRACTED: prefix, so
        # calendar events MUST keep extracted_fields={} to stay out of the inbox.
        # Always build the extracted-fields dict for the EmailProcessing record
        # (it's the historical "what the AI extracted" data). Only mirror it onto
        # the Event when the extraction still needs review — otherwise the inbox
        # API surfaces resolved-review events with the EXTRACTED: prefix.
        extracted = build_extracted_fields(spec['fields'], body)
        if is_review:
            assigned_users = []
            staff_names = []
            routing_json = {}
            # Contact/org fields move to v2 review cards (added after the event +
            # its normalized rows exist, below); keep only scalar fields here.
            event_extracted = build_extracted_fields(
                [f for f in spec['fields'] if f[0] not in CARD_FIELD_NAMES], body)
        else:
            assigned_users = resolve_assigned_users(ev['topics'], users)
            staff_names = [u.get_full_name() or u.username for u in assigned_users]
            routing_json = ({} if routing_state == 'no_routing'
                            else build_routing_json(assigned_users, samuel))
            event_extracted = {}

        # Member of Congress personally attending → add to staff list (not as an
        # approver) so the card renders the podium indicator.
        if spec.get('_member_attending') and member_name and member_name not in staff_names:
            staff_names.append(member_name)

        event = Event.objects.create(
            title=ev['title'],
            type=ev['type'],
            format=ev['format'],
            description=ev['description'],
            start_date=ev['start_date'],
            # Single-day events keep end_date == start_date. Date-range and
            # undated specs override end_date (and is_date_range) explicitly.
            end_date=ev.get('end_date', ev['start_date']),
            start_time=ev['start_time'],
            end_time=ev['end_time'],
            is_date_range=ev.get('is_date_range', False),
            location=ev['location'],
            legislative_topics=ev['topics'],
            staff=staff_names,
            status=ev['status'],
            requires_human_review=(ev['status'] == 'received'),
            extracted_fields=event_extracted,
            approval_routing=routing_json,
            created_by=samuel,
            modified_by=samuel,
        )

        # auto_now_add ignores the value we'd pass to create(), so back-date
        # the timestamps via update() to land at the staggered _received_at.
        Event.objects.filter(pk=event.pk).update(created=spec['_received_at'])

        received = spec['_received_at']
        email_id = f'demo-{uuid.uuid4()}'
        conversation_id = f'demo-conv-{uuid.uuid4()}'
        email = EmailProcessing.objects.create(
            email_id=email_id,
            subject=spec['subject'],
            sender=spec['sender_email'],
            sender_name=spec['sender_name'],
            received=received,
            is_scheduling_request=True,
            confidence=spec['confidence'],
            complete_email_data={
                'email_id': email_id,
                'email_type': 'original_request',
                'thread_id': conversation_id,  # Outlook conversationId -> EmailThread
                'subject': spec['subject'],
                'from': {'email': spec['sender_email'], 'name': spec['sender_name']},
                'to': [SCHEDULING_INBOX],
                'received': received.isoformat(),
                'body': {
                    'text': body,
                    'html': f'<div style="font-family: Arial, sans-serif; line-height: 1.6;">{body.replace(chr(10), "<br>")}</div>',
                    'preview': body[:200],
                },
            },
            extracted_data=extracted,
            status='processed',
            event=event,
        )

        # Link model (source of truth): record the Event<->Email link and
        # attach the originating conversation thread so later replies on the
        # same thread surface on the event automatically.
        event.attach_email(email, origin='ai_auto', user=samuel, is_primary=True)
        if email.thread_id:
            event.attach_thread(email.thread, user=samuel)

        # Calendar events are post-review: their contact/org links are
        # legitimately tied now (exact-email match or create a Contact, exact-name
        # match or create an Organization, then link both to the event + email).
        #
        # Review-bucket events tie NOTHING yet — per the human-in-the-loop rule,
        # links are created only when the reviewer completes the review. They
        # carry the v2 review cards instead, whose resolutions are computed
        # against the pre-seeded directory (resolve=True).
        if is_review:
            parties, orgs = derive_parties(spec)
            v2 = build_review_parties(parties, orgs, body, resolve=True)
            event.extracted_fields = {**event.extracted_fields, **v2}
            event.save(update_fields=['extracted_fields'])
        else:
            attach_contact_org_to_event(
                event,
                name=ev['poc_name'],
                email=ev['poc_email'],
                phone=ev['poc_phone'],
                group=ev['group'],
                user=samuel,
            )

        if routing_state != 'no_routing':
            service.initialize_approvals(event)
            # Back-date the approval rows to the staggered _received_at so the
            # inbox `approval.created_at` sort interleaves with extraction items.
            EventApproval.objects.filter(event=event).update(
                created_at=spec['_received_at']
            )
            apply_routing_state(event, routing_state)

        created += 1
        status_tag = ev['status'].ljust(22)
        topic_tag = ','.join(ev['topics'])[:18].ljust(18)
        assignees = ','.join(u.username for u in assigned_users) if assigned_users else '-'
        if spec.get('_member_attending'):
            assignees += ' +MoC'
        date_tag = ev['start_date'].isoformat() if ev['start_date'] else 'undated   '
        print(f'  [{i:2d}] {bucket:<8} {date_tag} '
              f'{status_tag} {routing_state:<15} {topic_tag} -> {assignees}')

    return created


# ---------------------------------------------------------------------------
# Email / thread showcase
# ---------------------------------------------------------------------------
def add_email_thread_showcase(office, users):
    """Demonstrate the new email/thread model on a couple of events:
      * a multi-message reply chain on one conversation thread (event A)
      * a standalone off-thread follow-up attached to the same event
      * a single email shared across two events (event A + event B)
    """
    samuel = users['samuel']
    received = list(
        Event.objects.filter(created_by__office=office, status='received')
        .order_by('title')[:2]
    )
    if len(received) < 2:
        print('  (showcase skipped: need two received events)')
        return

    event_a, event_b = received[0], received[1]
    primary = event_a.get_primary_email()
    if primary is None:
        print('  (showcase skipped: event has no primary email)')
        return

    base_time = primary.received
    conversation_id = primary.get_email_thread_id()

    # 1) Two replies on event A's ORIGINAL conversation thread. Event A already
    #    has that thread attached, so these surface on it automatically.
    replies = [
        ('Re: ' + primary.subject, SCHEDULING_INBOX['email'], SCHEDULING_INBOX['name'],
         'Thank you for the invitation. Could we confirm a few logistics before we hold the date?',
         'response_sent', 1),
        ('Re: ' + primary.subject, primary.sender, primary.sender_name,
         'Of course - we can be flexible on timing. The afternoon works well on our end.',
         'follow_up', 2),
    ]
    for subject, sender, sender_name, text, etype, hours in replies:
        ts = base_time + timedelta(hours=hours)
        eid = f'demo-{uuid.uuid4()}'
        EmailProcessing.objects.create(
            email_id=eid, subject=subject, sender=sender, sender_name=sender_name,
            received=ts, is_scheduling_request=False, confidence=0.0,
            complete_email_data={
                'email_id': eid, 'email_type': etype, 'thread_id': conversation_id,
                'subject': subject, 'from': {'email': sender, 'name': sender_name},
                'to': [SCHEDULING_INBOX], 'received': ts.isoformat(),
                'body': {'text': text, 'html': f'<p>{text}</p>', 'preview': text[:200]},
            },
            extracted_data={'email_type': etype}, status='processed', event=event_a,
        )

    # 2) A standalone follow-up on a SEPARATE thread, attached directly to A.
    standalone_subject = 'Follow-up: timing change for our visit'
    standalone_text = ('Quick separate note (not on the original thread): we may need to '
                       'shift the start 30 minutes later. Flagging so the event time can be updated.')
    s_ts = base_time + timedelta(days=1)
    s_eid = f'demo-{uuid.uuid4()}'
    standalone = EmailProcessing.objects.create(
        email_id=s_eid, subject=standalone_subject,
        sender=primary.sender, sender_name=primary.sender_name,
        received=s_ts, is_scheduling_request=False, confidence=0.0,
        complete_email_data={
            'email_id': s_eid, 'email_type': 'follow_up',
            'thread_id': f'demo-conv-{uuid.uuid4()}',  # its OWN, separate thread
            'subject': standalone_subject,
            'from': {'email': primary.sender, 'name': primary.sender_name},
            'to': [SCHEDULING_INBOX], 'received': s_ts.isoformat(),
            'body': {'text': standalone_text, 'html': f'<p>{standalone_text}</p>',
                     'preview': standalone_text[:200]},
        },
        extracted_data={'email_type': 'follow_up'}, status='processed', event=None,
    )
    event_a.attach_email(standalone, origin='manual', user=samuel)

    # 3) Share event A's primary email with event B (one email, two events).
    event_b.attach_email(primary, origin='manual', user=samuel)

    print(f'  showcase: reply chain + standalone follow-up on "{event_a.title[:28]}", '
          f'shared email -> "{event_b.title[:28]}"')


def recalc_threads():
    """Refresh denormalized counts/participants on every conversation thread."""
    for thread in EmailThread.objects.all():
        thread.recalc_metadata()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    try:
        office = Office.objects.get(name=OFFICE_NAME)
    except Office.DoesNotExist:
        print(f'ERROR: Office "{OFFICE_NAME}" not found.')
        print('Run "python scripts/create_demo_office.py" first.')
        sys.exit(1)

    users = {u.username: u for u in User.objects.filter(office=office)}
    required = ['samuel', 'elias', 'james', 'stepan', 'kaden', 'meaghan',
                'gibson', 'mac', 'amelia', 'ian', 'jack']
    missing = [u for u in required if u not in users]
    if missing:
        print(f'ERROR: Missing demo users: {missing}')
        print('Run "python scripts/create_demo_office.py" first.')
        sys.exit(1)

    with transaction.atomic():
        clear_event_data(office)
        created = realize_events(office, users)
        add_email_thread_showcase(office, users)
        recalc_threads()

    print('')
    print('=' * 60)
    print(f'Populated {created} demo events for {OFFICE_NAME}.')
    print('=' * 60)


if __name__ == '__main__':
    main()
