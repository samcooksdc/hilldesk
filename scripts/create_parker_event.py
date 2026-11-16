#!/usr/bin/env python
# SPDX-License-Identifier: Apache-2.0
"""
Create a demo event from Parker Wilkinson with approval routing
that requires Samuel Cook (Admin) and Alex (Scheduler) to review.

Usage:
    python create_parker_event.py
"""

import os
import sys
import uuid
from datetime import date, time

# Make the project root importable (this script lives in scripts/).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')

import django
django.setup()

from apps.authentication.devtools import require_dev_environment  # noqa: E402
require_dev_environment('scripts/create_parker_event.py')

from django.utils import timezone
from django.contrib.auth import get_user_model
from apps.email_processing.models import EmailProcessing
from apps.event_management.models import Event, EventApproval

User = get_user_model()


EMAIL_BODY = """Dear Scheduling Team,

I hope you're doing well. My name is Parker Wilkinson and I serve as the Government Relations Director for the Tri-County Manufacturing Coalition, a regional trade association representing 340 manufacturing firms across Franklin and neighboring states.

I am writing to request a meeting with the Congresswoman to discuss the upcoming reauthorization of the Manufacturing Extension Partnership (MEP) program and its direct impact on small and mid-size manufacturers in the district.

We would like to schedule this meeting for Wednesday, April 1st, 2026 at 2:30 PM at the district office in Fairview. We anticipate the meeting will last approximately one hour.

As you may be aware, the MEP program provides critical technical assistance to small manufacturers, helping them modernize operations, adopt new technologies, and compete in global markets. In Franklin alone, MEP centers have helped over 1,200 companies in the past three years, supporting an estimated 8,500 jobs and generating $1.4 billion in new and retained sales.

Our delegation will include:
- Myself, Parker Wilkinson (Government Relations Director)
- Maria Gonzalez, CEO of Precision Components Inc. (Fairview, FR)
- David Kim, Owner of Great Lakes Tool & Die (Sterling Heights, FR)
- Dr. Linda Chen, Director of the Franklin Manufacturing Technology Center

During our meeting, we would like to discuss:

1. MEP Reauthorization: The current authorization expires at the end of FY2026. We are advocating for a five-year reauthorization with increased funding to meet growing demand from manufacturers seeking to adopt AI and advanced robotics.

2. Workforce Pipeline Programs: Franklin manufacturers continue to face a skilled labor shortage. We would like to discuss expanding apprenticeship tax credits and community college partnerships.

3. Supply Chain Resilience: Many of our member companies are Tier 2 and Tier 3 automotive suppliers. Recent disruptions have highlighted the need for federal support in supply chain mapping and diversification.

4. Clean Manufacturing Incentives: Several of our members are investing in energy-efficient processes and would benefit from expanded Section 48C tax credits for advanced manufacturing facilities.

We have prepared a one-page summary of our policy priorities and economic impact data specific to the district that we can share in advance.

Please let me know if February 11th works, or if there is a more convenient time. I can be reached directly at pwilkinson@greatlakesmfg.example or (248) 555-7193.

Thank you for the Congresswoman's continued support of American manufacturing. We look forward to a productive discussion.

Best regards,

Parker Wilkinson
Government Relations Director
Tri-County Manufacturing Coalition
2500 Executive Hills Drive, Suite 200
Fairview, FR 48083

Phone: (248) 555-7193
Email: pwilkinson@greatlakesmfg.example
"""


def find_text_position(needle: str, haystack: str):
    """Find the start and end position of text in the email body."""
    start = haystack.find(needle)
    if start == -1:
        return None, None
    return start, start + len(needle)


def create_event():
    """Create the event with approval routing for Samuel Cook and Alex."""

    # Find Samuel Cook (admin)
    samuel = User.objects.filter(first_name='Samuel', last_name='Cook').first()
    if not samuel:
        samuel = User.objects.filter(role='admin').first()
    if not samuel:
        print("Error: No admin user found. Run 'create_demo_users' first.")
        return

    # Find a scheduler user to act as "Alex"
    # Create Alex if not present
    from apps.authentication.models import Office
    office = samuel.office
    if not office:
        office = Office.objects.first()

    alex, alex_created = User.objects.get_or_create(
        username='demo_alex',
        defaults={
            'email': 'alex@demo.example.com',
            'first_name': 'Alex',
            'last_name': 'Rivera',
            'role': 'scheduler',
            'office': office,
        }
    )
    if alex_created:
        alex.set_password('demo123!')
        alex.save()
        print("Created scheduler user: Alex Rivera (demo_alex / demo123!)")

    # Create Parker Wilkinson as the submitting user (staff role)
    parker, parker_created = User.objects.get_or_create(
        username='demo_parker',
        defaults={
            'email': 'pwilkinson@greatlakesmfg.example',
            'first_name': 'Parker',
            'last_name': 'Wilkinson',
            'role': 'staff',
            'office': office,
        }
    )
    if parker_created:
        parker.set_password('demo123!')
        parker.save()
        print("Created staff user: Parker Wilkinson (demo_parker / demo123!)")

    print(f"Admin reviewer: {samuel.get_full_name()} ({samuel.username})")
    print(f"Scheduler reviewer: {alex.get_full_name()} ({alex.username})")
    print(f"Submitted by: {parker.get_full_name()} ({parker.username})")

    # Text positions for source highlighting
    group_text = "Tri-County Manufacturing Coalition"
    date_text = "Wednesday, April 1st, 2026"
    time_text = "2:30 PM"
    duration_text = "last approximately one hour"
    location_text = "the district office in Fairview"
    poc_name_text = "Parker Wilkinson"
    poc_email_text = "pwilkinson@greatlakesmfg.example"
    poc_phone_text = "(248) 555-7193"

    extracted_fields = {
        'title': {
            'value': 'Meeting with Tri-County Manufacturing Coalition',
            'confidence': 0.93,
            'status': 'pending',
            'start_index': None,
            'end_index': None,
            'text_snippet': 'request a meeting with the Congresswoman to discuss the upcoming reauthorization',
        },
        'group': {
            'value': 'Tri-County Manufacturing Coalition',
            'confidence': 0.97,
            'status': 'pending',
            'start_index': find_text_position(group_text, EMAIL_BODY)[0],
            'end_index': find_text_position(group_text, EMAIL_BODY)[1],
            'text_snippet': group_text,
        },
        'start_date': {
            'value': '2026-04-01',
            'confidence': 0.96,
            'status': 'pending',
            'start_index': find_text_position(date_text, EMAIL_BODY)[0],
            'end_index': find_text_position(date_text, EMAIL_BODY)[1],
            'text_snippet': date_text,
        },
        'start_time': {
            'value': '14:30',
            'confidence': 0.96,
            'status': 'pending',
            'start_index': find_text_position(time_text, EMAIL_BODY)[0],
            'end_index': find_text_position(time_text, EMAIL_BODY)[1],
            'text_snippet': time_text,
        },
        'end_time': {
            'value': '15:30',
            'confidence': 0.87,
            'status': 'pending',
            'start_index': find_text_position(duration_text, EMAIL_BODY)[0],
            'end_index': find_text_position(duration_text, EMAIL_BODY)[1],
            'text_snippet': duration_text,
        },
        'location': {
            'value': 'District Office, Fairview, FR',
            'confidence': 0.90,
            'status': 'pending',
            'start_index': find_text_position(location_text, EMAIL_BODY)[0],
            'end_index': find_text_position(location_text, EMAIL_BODY)[1],
            'text_snippet': location_text,
        },
        'description': {
            'value': (
                'Meeting to discuss MEP program reauthorization, workforce pipeline programs, '
                'supply chain resilience for automotive suppliers, and clean manufacturing incentives. '
                'The Tri-County Manufacturing Coalition represents 340 manufacturing firms across MI, OH, and IN.'
            ),
            'confidence': 0.91,
            'status': 'pending',
            'start_index': None,
            'end_index': None,
            'text_snippet': 'discuss the upcoming reauthorization of the Manufacturing Extension Partnership',
        },
        'point_of_contact_name': {
            'value': 'Parker Wilkinson',
            'confidence': 0.96,
            'status': 'pending',
            'start_index': find_text_position(poc_name_text, EMAIL_BODY)[0],
            'end_index': find_text_position(poc_name_text, EMAIL_BODY)[1],
            'text_snippet': poc_name_text,
        },
        'point_of_contact_email': {
            'value': 'pwilkinson@greatlakesmfg.example',
            'confidence': 0.98,
            'status': 'pending',
            'start_index': find_text_position(poc_email_text, EMAIL_BODY)[0],
            'end_index': find_text_position(poc_email_text, EMAIL_BODY)[1],
            'text_snippet': poc_email_text,
        },
        'point_of_contact_phone': {
            'value': '(248) 555-7193',
            'confidence': 0.95,
            'status': 'pending',
            'start_index': find_text_position(poc_phone_text, EMAIL_BODY)[0],
            'end_index': find_text_position(poc_phone_text, EMAIL_BODY)[1],
            'text_snippet': poc_phone_text,
        },
        'type': {
            'value': 'meeting',
            'confidence': 0.94,
            'status': 'pending',
            'start_index': None,
            'end_index': None,
            'text_snippet': 'meeting',
        },
    }

    # Build approval routing: Stage 1 = Alex (scheduler), Stage 2 = Samuel Cook (admin)
    approval_routing = {
        'version': 1,
        'stages': [
            {
                'stage_id': 'stage-creator',
                'order': 0,
                'type': 'sequential',
                'approvers': [
                    {
                        'user_id': str(parker.id),
                        'name': 'Parker Wilkinson',
                        'required': True,
                    }
                ],
            },
            {
                'stage_id': 'stage-1',
                'order': 1,
                'type': 'sequential',
                'approvers': [
                    {
                        'user_id': str(alex.id),
                        'name': 'Alex Rivera',
                        'required': True,
                    }
                ],
            },
            {
                'stage_id': 'stage-2',
                'order': 2,
                'type': 'sequential',
                'approvers': [
                    {
                        'user_id': str(samuel.id),
                        'name': 'Samuel Cook',
                        'required': True,
                    }
                ],
            },
        ],
    }

    # Create the event
    event = Event.objects.create(
        title='Meeting with Tri-County Manufacturing Coalition',
        type='meeting',
        format='in_person',
        description=(
            'Meeting to discuss MEP program reauthorization, workforce pipeline programs, '
            'supply chain resilience for automotive suppliers, and clean manufacturing incentives. '
            'The Tri-County Manufacturing Coalition represents 340 manufacturing firms across MI, OH, and IN.'
        ),
        start_date=date(2026, 4, 1),
        start_time=time(14, 30),
        end_time=time(15, 30),
        location='District Office, Fairview, FR',
        legislative_topics=['Manufacturing', 'Workforce Development', 'Supply Chain', 'Clean Energy'],
        participants=[
            'Parker Wilkinson - Government Relations Director',
            'Maria Gonzalez - CEO, Precision Components Inc.',
            'David Kim - Owner, Great Lakes Tool & Die',
            'Dr. Linda Chen - Director, FR Manufacturing Technology Center',
        ],
        expected_attendees=4,
        status='received',
        requires_human_review=True,
        extracted_fields=extracted_fields,
        approval_routing=approval_routing,
        created_by=parker,
        modified_by=parker,
    )

    # Normalized contact / organization (group + point_of_contact).
    from apps.contacts.services import attach_contact_org_to_event
    attach_contact_org_to_event(
        event,
        name='Parker Wilkinson',
        email='pwilkinson@greatlakesmfg.example',
        phone='(248) 555-7193',
        group='Tri-County Manufacturing Coalition',
        user=parker,
    )

    print(f"\nCreated event: {event.title}")
    print(f"Event ID: {event.id}")
    print(f"Date: {event.start_date} {event.start_time} - {event.end_time}")

    # Initialize approval records
    from apps.api.services import ApprovalRoutingService
    service = ApprovalRoutingService()
    result = service.initialize_approvals(event)
    print(f"Approval routing initialized: {result}")

    # Auto-approve the creator stage (Parker submitted it)
    creator_approval = EventApproval.objects.filter(
        event=event,
        approver=parker,
        stage_id='stage-creator',
    ).first()
    if creator_approval:
        creator_approval.approve(comment='Submitted for review')
        print("Auto-approved creator stage for Parker Wilkinson")

    # Create the email processing record
    email_id = f'parker-demo-{uuid.uuid4()}'
    email_processing = EmailProcessing.objects.create(
        email_id=email_id,
        subject='Meeting Request: Tri-County Manufacturing Coalition - MEP Reauthorization',
        sender='pwilkinson@greatlakesmfg.example',
        sender_name='Parker Wilkinson',
        received=timezone.now(),
        is_scheduling_request=True,
        confidence=0.96,
        complete_email_data={
            'email_id': email_id,
            'subject': 'Meeting Request: Tri-County Manufacturing Coalition - MEP Reauthorization',
            'from': {
                'email': 'pwilkinson@greatlakesmfg.example',
                'name': 'Parker Wilkinson',
            },
            'to': [{'email': 'scheduling@smith.example.com', 'name': 'Office of Rep. Smith'}],
            'received': timezone.now().isoformat(),
            'body': {
                'text': EMAIL_BODY,
                'html': f'<div style="font-family: Arial, sans-serif; line-height: 1.6;">{EMAIL_BODY.replace(chr(10), "<br>")}</div>',
                'preview': EMAIL_BODY[:200],
            },
        },
        extracted_data=extracted_fields,
        status='processed',
        event=event,
    )

    print(f"Created email record: {email_processing.email_id}")

    # Print approval chain status
    print("\n--- Approval Chain ---")
    approvals = EventApproval.objects.filter(event=event).order_by('stage_order')
    for a in approvals:
        print(f"  Stage {a.stage_order} ({a.stage_id}): {a.approver.get_full_name()} - {a.status}")

    print("\nEvent is now waiting for Alex Rivera (scheduler) to review.")
    print("After Alex approves, Samuel Cook (admin) will need to review.")
    print("\nLogin as demo_alex / demo123! or demo_admin / demo123! to review.")


if __name__ == '__main__':
    create_event()
