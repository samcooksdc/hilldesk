#!/usr/bin/env python
# SPDX-License-Identifier: Apache-2.0
"""
Create the HillDesk demo office: Office of Rep. James Smith (fictional district FR-1).

Wipes ALL existing offices, users (non-superuser), staff profiles, events,
emails, approvals, and email templates, then creates:
  - 1 Office (Smith, with full status / type / format choice config)
  - 11 OfficeStaff profiles
  - 11 User accounts (passwords all "demo", development only)
  - 14 EmailTemplates (2 per category x 7 categories)

Run after this script:
    python scripts/populate_office_demo_info.py
to seed 35 events with attached emails and approval routing.

Usage:
    python scripts/create_demo_office.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')

import django
django.setup()

from apps.authentication.devtools import require_dev_environment  # noqa: E402
require_dev_environment('scripts/create_demo_office.py')

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from apps.authentication.models import Office, OfficeStaff
from apps.contacts.models import Contact, Organization
from apps.email_processing.models import EmailProcessing, EmailResponse
from apps.event_management.models import (
    EmailTemplate,
    Event,
    EventApproval,
    EventChangeHistory,
    EventChangeSuggestion,
    EventReviewAuditLog,
    EventSeries,
    ExportTemplate,
)

User = get_user_model()


OFFICE_NAME = 'Office of Rep. James Smith'
DEMO_PASSWORD = 'demo'


# ---------------------------------------------------------------------------
# 1. Wipe
# ---------------------------------------------------------------------------
def wipe_all():
    """Delete every record this demo controls. Superusers are preserved."""
    print('Wiping existing demo data...')
    EmailResponse.objects.all().delete()
    EmailProcessing.objects.all().delete()
    EventApproval.objects.all().delete()
    EventChangeSuggestion.objects.all().delete()
    EventChangeHistory.objects.all().delete()
    EventReviewAuditLog.objects.all().delete()
    Event.objects.all().delete()
    # Series (created by the ingestion simulation) PROTECT their creator User.
    EventSeries.objects.all().delete()
    # Normalized contacts/organizations are demo-global (no office FK); clear
    # them on a full reset so re-runs start from a clean directory.
    Contact.objects.all().delete()
    Organization.objects.all().delete()
    EmailTemplate.objects.all().delete()
    ExportTemplate.objects.all().delete()
    # Detach any surviving superuser from offices/staff before nuking those tables
    User.objects.filter(is_superuser=True).update(office=None, staff_profile=None)
    User.objects.filter(is_superuser=False).delete()
    OfficeStaff.objects.all().delete()
    Office.objects.all().delete()
    print('  done.')


# ---------------------------------------------------------------------------
# 2. Office
# ---------------------------------------------------------------------------
def create_office():
    # Status choices match the user's original prompt list. The customization
    # menu in Settings is the source of truth and pulls from this directly.
    # `scheduling_in_progress` uses teal per the prompt.
    status_choices = [
        {'value': 'received',               'label': 'Received',                    'color': '#3b82f6', 'bg_color': '#dbeafe', 'is_active': True, 'order': 1},
        {'value': 'hold',                   'label': 'Hold',                        'color': '#f59e0b', 'bg_color': '#fef3c7', 'is_active': True, 'order': 2},
        {'value': 'fyied',                  'label': "FYI'ed",                      'color': '#f97316', 'bg_color': '#ffedd5', 'is_active': True, 'order': 3},
        {'value': 'scheduling_in_progress', 'label': 'Scheduling in Progress',      'color': '#14b8a6', 'bg_color': '#ccfbf1', 'is_active': True, 'order': 4},
        {'value': 'scheduled',              'label': 'Scheduled',                   'color': '#10b981', 'bg_color': '#d1fae5', 'is_active': True, 'order': 5},
        {'value': 'rsvped',                 'label': "RSVP'ed",                     'color': '#06b6d4', 'bg_color': '#cffafe', 'is_active': True, 'order': 6},
        {'value': 'regrets_sent',           'label': 'Regrets Sent',                'color': '#ef4444', 'bg_color': '#fee2e2', 'is_active': True, 'order': 7},
        {'value': 'ignored',                'label': 'Ignored',                     'color': '#64748b', 'bg_color': '#f1f5f9', 'is_active': True, 'order': 8},
        {'value': 'canceled',               'label': 'Canceled / Request Withdrawn','color': '#6b7280', 'bg_color': '#f3f4f6', 'is_active': True, 'order': 9},
    ]
    type_choices = list(settings.DEFAULT_EVENT_TYPE_CHOICES) + [
        {'value': 'hearing', 'label': 'Hearing', 'is_active': True, 'order': 4},
        {'value': 'votes', 'label': 'Votes', 'is_active': True, 'order': 5},
    ]
    format_choices = list(settings.DEFAULT_EVENT_FORMAT_CHOICES)

    office = Office.objects.create(
        name=OFFICE_NAME,
        member_name='Rep. James Smith',
        district='FR-1',
        dc_office_address='4340 Rayburn House Office Building\nWashington, DC 20515',
        district_office_address='215 E Main St\nFairview, FR 00000',
        is_setup_complete=True,
        setup_completed_at=timezone.now(),
        event_status_choices=status_choices,
        event_type_choices=type_choices,
        event_format_choices=format_choices,
        default_tags=[],
    )
    office.create_default_roles()
    print(f'Created office: {office.name}')
    return office


# ---------------------------------------------------------------------------
# 3. Staff profiles + Users
# ---------------------------------------------------------------------------
# username -> (first, last, role, position, areas, phone, is_moc)
# is_moc flags the single Member of Congress for this office.
STAFF_SPEC = [
    ('james',   'James',   'Smith',     'admin',   'Member of Congress',                    [],                                       '(202) 555-0100', True),
    ('elias',   'Elias',   'Bennett',     'admin',   'Chief of Staff',                        [],                                       '(202) 555-0101', False),
    ('samuel',  'Samuel',  'Cook',        'admin',   'Scheduler',                             [],                                       '(202) 555-0102', False),
    ('stepan',  'Stepan',  'Varga',   'staff',   'Legislative Assistant',                 ['Foreign Relations'],                    '(202) 555-0103', False),
    ('kaden',   'Kaden',   'Boyd',        'staff',   'Legislative Assistant',                 ['Education', 'Industry'],                '(202) 555-0104', False),
    ('meaghan', 'Meaghan', 'Doyle',      'staff',   'Legislative Assistant',                 ['Education', 'Crime'],                   '(202) 555-0105', False),
    ('gibson',  'Gibson',  'Reed',        'staff',   'Legislative Correspondent',             ['Healthcare', 'Foreign Relations'],      '(202) 555-0106', False),
    ('mac',     'Mac',     'Russo',    'staff',   'Legislative Correspondent',             ['Industry', 'Foreign Relations'],        '(202) 555-0107', False),
    ('amelia',  'Amelia',  'Glover',     'staff',   'Legislative Correspondent',             ['Healthcare', 'Foreign Relations'],      '(202) 555-0108', False),
    ('ian',     'Ian',     'Nash',     'staff',   'Staff Assistant',                       [],                                       '(202) 555-0109', False),
    ('jack',    'Jack',    'Quinn',     'staff',   'Staff Assistant',                       [],                                       '(202) 555-0110', False),
]


def create_staff_profiles(office):
    """Create one OfficeStaff per spec row, keyed by username."""
    profiles = {}
    for i, (username, first, last, _role, position, areas, phone, is_moc) in enumerate(STAFF_SPEC):
        profile = OfficeStaff.objects.create(
            office=office,
            name=f'{first} {last}',
            position=position,
            email=f'{username}@smith.example.com',
            phone=phone,
            legislative_areas=areas,
            order=i,
            is_active=True,
            is_member_of_congress=is_moc,
        )
        profiles[username] = profile
    print(f'Created {len(profiles)} staff profiles.')
    return profiles


def create_users(office, profiles):
    """Create one User per spec row, keyed by username."""
    from apps.authentication.models import Role
    roles_by_slug = {r.slug: r for r in Role.objects.filter(office=office)}

    users = {}
    for username, first, last, role, _position, _areas, _phone, _is_moc in STAFF_SPEC:
        role_obj = roles_by_slug.get(role) or roles_by_slug.get('staff')
        user = User.objects.create(
            username=username,
            first_name=first,
            last_name=last,
            email=f'{username}@smith.example.com',
            role=role,
            office_role=role_obj,
            office=office,
            staff_profile=profiles[username],
            # Demo offices default to the blue accent; set explicitly so a
            # rebuild always lands on blue regardless of the model default.
            accent_color='blue',
        )
        user.set_password(DEMO_PASSWORD)
        user.save()
        users[username] = user
    print(f'Created {len(users)} users.')
    return users


# ---------------------------------------------------------------------------
# 4. Email templates (2 per category x 7 categories, all HTML)
# ---------------------------------------------------------------------------
# Note: EmailResponseService.render_bracket_variables uses regex {(\w+)} —
# single braces, no spaces. Stick to {sender_name} not {{ sender_name }}.
COMMON_VARS = [
    'sender_name', 'recipient_name', 'staffer_name', 'office_name',
    'original_subject', 'event_date', 'event_time', 'event_location',
]


def _build_template_specs():
    return [
        # ----- Acknowledge -----
        {
            'name': 'Standard Acknowledgment',
            'category': 'acknowledge',
            'subject': 'RE: {original_subject} - Request Received',
            'body': '''<p>Dear {sender_name},</p>

<p>Thank you for your email to the Office of Rep. James Smith. We have received your request and are reviewing it carefully.</p>

<p>Our scheduling team will follow up shortly once we have had a chance to review the Congressman's calendar. If we need additional information, we will reach out directly.</p>

<p>Thank you for your patience.</p>

<p>Best regards,<br>
{staffer_name}</p>''',
        },
        {
            'name': 'Acknowledgment with Two-Week Timeline',
            'category': 'acknowledge',
            'subject': 'RE: {original_subject} - Received',
            'body': '''<p>Dear {sender_name},</p>

<p>Thank you for reaching out to the Office of Rep. James Smith. Your request has been logged and assigned to a staff member for review.</p>

<p>Given the volume of correspondence our office receives, please allow up to two weeks for a substantive response. If your request is time-sensitive, please reply to this email and note the deadline so we can prioritize accordingly.</p>

<p>We appreciate your engagement with our office.</p>

<p>Sincerely,<br>
{staffer_name}</p>''',
        },

        # ----- RSVP -----
        {
            'name': 'RSVP Confirmed - Attending with Remarks',
            'category': 'rsvp',
            'subject': 'RE: {original_subject} - RSVP Confirmed',
            'body': '''<p>Dear {sender_name},</p>

<p>Thank you for the kind invitation. Rep. James Smith is pleased to confirm his attendance on {event_date} at {event_time}, at {event_location}, and is glad to offer brief remarks as you suggested.</p>

<p>Please send along the run-of-show, any preferred talking points, and your press protocol when you have a chance. Our office will follow up directly with logistical questions.</p>

<p>We look forward to the event.</p>

<p>Best regards,<br>
{staffer_name}</p>''',
        },
        {
            'name': 'RSVP Confirmed - Attending Only',
            'category': 'rsvp',
            'subject': 'RE: {original_subject} - RSVP Confirmed',
            'body': '''<p>Dear {sender_name},</p>

<p>Thank you for the invitation to your event on {event_date}. Rep. James Smith is pleased to attend at {event_time}, at {event_location}, in a non-speaking capacity.</p>

<p>Please reach out if there are arrival logistics or seating preferences we should know about in advance.</p>

<p>We look forward to joining you.</p>

<p>Best regards,<br>
{staffer_name}</p>''',
        },

        # ----- Scheduling -----
        {
            'name': 'Meeting Confirmed',
            'category': 'scheduling',
            'subject': 'RE: {original_subject} - Meeting Confirmed',
            'body': '''<p>Dear {sender_name},</p>

<p>We are pleased to confirm a meeting with Rep. James Smith on {event_date} at {event_time}, at {event_location}.</p>

<p>If you have materials you would like the Congressman to review in advance, please send them to our office at your convenience.</p>

<p>Should you need to make any changes to this appointment, please contact our scheduling team directly.</p>

<p>Best regards,<br>
{staffer_name}</p>''',
        },
        {
            'name': 'Alternative Times Offered',
            'category': 'scheduling',
            'subject': 'RE: {original_subject} - Alternative Times',
            'body': '''<p>Dear {sender_name},</p>

<p>Thank you for your meeting request. Unfortunately, Rep. James Smith is not available at the time you proposed. We would like to offer the following alternatives instead:</p>

<ul>
    <li>[ALTERNATIVE DATE / TIME 1]</li>
    <li>[ALTERNATIVE DATE / TIME 2]</li>
    <li>[ALTERNATIVE DATE / TIME 3]</li>
</ul>

<p>If none of these work for you, please share two or three windows that fit your schedule and we will do our best to accommodate.</p>

<p>Thank you for your flexibility.</p>

<p>Best regards,<br>
{staffer_name}</p>''',
        },

        # ----- Decline -----
        {
            'name': 'Decline - Schedule Conflict',
            'category': 'decline',
            'subject': 'RE: {original_subject} - Unable to Attend',
            'body': '''<p>Dear {sender_name},</p>

<p>Thank you for your invitation. Unfortunately, due to prior commitments on the requested date, Rep. James Smith will not be able to participate.</p>

<p>The Congressman appreciates the work your organization is doing in the First District and would welcome the opportunity to engage in the future. If you have materials you would like our staff to review, please feel free to share them.</p>

<p>Thank you again for thinking of our office.</p>

<p>Best regards,<br>
{staffer_name}</p>''',
        },
        {
            'name': 'Decline - Staff Will Attend',
            'category': 'decline',
            'subject': 'RE: {original_subject} - Staff Attending in Congressman\'s Place',
            'body': '''<p>Dear {sender_name},</p>

<p>Thank you for the invitation. Rep. James Smith is unable to attend in person on {event_date}, but he has asked a member of our legislative staff to attend on his behalf so the office stays engaged with the issues you have raised.</p>

<p>We will be in touch shortly to coordinate logistics and confirm which staff member will be present.</p>

<p>Thank you for your understanding.</p>

<p>Best regards,<br>
{staffer_name}</p>''',
        },

        # ----- Follow Up -----
        {
            'name': 'Post-Meeting Thank You with Action Items',
            'category': 'follow_up',
            'subject': 'Follow-up: Meeting on {event_date}',
            'body': '''<p>Dear {sender_name},</p>

<p>Thank you for meeting with Rep. James Smith on {event_date}. The Congressman appreciated the conversation and the perspectives you and your team shared.</p>

<p>As a follow-up, our office will [action item summary]. If you can share [requested materials] in the coming week, that will help us move this forward on our end.</p>

<p>Please don't hesitate to reach out if anything else comes up.</p>

<p>Best regards,<br>
{staffer_name}</p>''',
        },
        {
            'name': 'Pending Information Request',
            'category': 'follow_up',
            'subject': 'Following up - {original_subject}',
            'body': '''<p>Dear {sender_name},</p>

<p>I wanted to circle back on our earlier exchange regarding {original_subject}. We are still waiting on the materials you mentioned, and they will help us determine the right next steps.</p>

<p>Once we have those in hand, we will be in touch with our office's response. Please let me know if there is anything we can do on our end to help move things along.</p>

<p>Thank you,<br>
{staffer_name}</p>''',
        },

        # ----- Thank You -----
        {
            'name': 'Thank You for Hosting',
            'category': 'thank_you',
            'subject': 'Thank you - {event_date}',
            'body': '''<p>Dear {sender_name},</p>

<p>On behalf of Rep. James Smith and our entire office, thank you for hosting the Congressman on {event_date}. The hospitality your team showed was greatly appreciated.</p>

<p>The Congressman left the event with a clearer understanding of the issues you raised and looks forward to staying in touch.</p>

<p>With gratitude,<br>
{staffer_name}</p>''',
        },
        {
            'name': 'Thank You for Service / Recognition',
            'category': 'thank_you',
            'subject': 'With gratitude - {event_date}',
            'body': '''<p>Dear {sender_name},</p>

<p>Rep. James Smith asked me to write and thank you personally for your service and the work you do for the people of the First District. The recognition on {event_date} was well-deserved.</p>

<p>Please know that you have an ongoing partner in our office. If there is anything you need from us, do not hesitate to call.</p>

<p>With deep gratitude,<br>
{staffer_name}</p>''',
        },

        # ----- Custom -----
        {
            'name': 'General Response Template',
            'category': 'custom',
            'subject': 'RE: {original_subject}',
            'body': '''<p>Dear {sender_name},</p>

<p>Thank you for reaching out to the Office of Rep. James Smith.</p>

<p>[Body of your message here]</p>

<p>If you have any questions, please do not hesitate to contact our office.</p>

<p>Best regards,<br>
{staffer_name}</p>''',
        },
        {
            'name': 'Brief Auto-Reply',
            'category': 'custom',
            'subject': 'Auto-reply: {original_subject}',
            'body': '''<p>Dear {sender_name},</p>

<p>This message confirms that your email has reached the Office of Rep. James Smith. A staff member will review your note and respond as soon as possible.</p>

<p>If you have a constituent services matter that needs urgent attention, please call our district office at (540) 555-0100.</p>

<p>Thank you,<br>
{staffer_name}</p>''',
        },
    ]


def create_email_templates(office, samuel_user):
    specs = _build_template_specs()
    for spec in specs:
        EmailTemplate.objects.create(
            name=spec['name'],
            category=spec['category'],
            subject=spec['subject'],
            body=spec['body'],
            variables=list(COMMON_VARS),
            is_default=False,
            is_active=True,
            is_html=True,
            office=office,
            created_by=samuel_user,
            modified_by=samuel_user,
        )
    print(f'Created {len(specs)} email templates.')


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    with transaction.atomic():
        wipe_all()
        office = create_office()
        profiles = create_staff_profiles(office)
        users = create_users(office, profiles)
        create_email_templates(office, users['samuel'])

    print('')
    print('=' * 60)
    print(f'Demo office ready: {OFFICE_NAME}')
    print('=' * 60)
    print(f'Password for every account: {DEMO_PASSWORD}')
    print('')
    print(f'  {"username":<10} {"role":<10} {"name":<22} email')
    print('  ' + '-' * 70)
    for username, first, last, role, _pos, _areas, _phone, is_moc in STAFF_SPEC:
        name = f'{first} {last}'
        marker = '  (Member of Congress)' if is_moc else ''
        print(f'  {username:<10} {role:<10} {name:<22} {username}@smith.example.com{marker}')
    print('')
    print('Next: python scripts/populate_office_demo_info.py')


if __name__ == '__main__':
    main()
