#!/usr/bin/env python
# SPDX-License-Identifier: Apache-2.0
"""
Create a demo event with extracted fields for video demonstration.
This creates a realistic-looking AI-extracted event in the inbox.

Usage:
    python create_demo_event.py
"""

import os
import sys
import uuid
from datetime import date, time

# Make the project root importable (this script lives in scripts/).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')

import django
django.setup()

from apps.authentication.devtools import require_dev_environment  # noqa: E402
require_dev_environment('scripts/create_demo_event.py')

from django.utils import timezone
from django.contrib.auth import get_user_model
from apps.email_processing.models import EmailProcessing
from apps.event_management.models import Event

User = get_user_model()


# The lengthy email body
EMAIL_BODY = """Dear Congresswoman Smith,

I hope this message finds you well. My name is Jonathan Crawford, and I am the Executive Director of the American Tech Founders Alliance (ATFA), a nonprofit organization representing over 2,400 technology startup founders, entrepreneurs, and early-stage investors across the United States.

I am reaching out to respectfully request a meeting with you and your staff to discuss critical policy issues affecting the technology startup ecosystem, particularly regarding regulatory frameworks that impact emerging companies in the artificial intelligence, fintech, and clean technology sectors.

As you may know, the American Tech Founders Alliance has been at the forefront of advocating for balanced regulations that protect innovation while ensuring responsible development of new technologies. Our member companies collectively employ over 45,000 workers nationwide, with a significant concentration in Franklin and the greater Fairview area. Many of our members have expressed concern about recent legislative proposals that, while well-intentioned, could inadvertently create barriers to entry for new market participants and consolidate power among established technology giants.

We would like to schedule this meeting for Thursday, April 2nd, 2026 at 10:00 AM in your office if that works with your schedule. The meeting should last one and a half hours to allow adequate time for a comprehensive discussion of these important issues.

During our meeting, we would like to address the following key topics:

1. The Impact of AI Regulation on Startups: We have prepared detailed analysis showing how certain proposed AI governance frameworks could disproportionately burden smaller companies that lack the compliance infrastructure of larger corporations. We believe there are alternative approaches that can achieve safety goals while preserving the innovative capacity of emerging firms.

2. Access to Capital and Securities Regulations: Many of our member companies have encountered significant challenges in raising early-stage funding due to regulatory complexities. We would like to share data on how modernizing certain aspects of securities law could unlock billions in investment for American innovation.

3. Data Privacy Frameworks: While we strongly support consumer privacy protections, we are concerned that some proposed legislation could create a patchwork of inconsistent state-level requirements that would be particularly challenging for resource-constrained startups to navigate.

4. Workforce Development and Immigration: The technology sector continues to face significant talent shortages. We would appreciate the opportunity to discuss policies that could help American startups compete for global talent while also investing in domestic workforce development.

Our delegation would include myself, our Director of Policy Research Dr. Sarah Mitchell, and two founding members of Franklin-based technology companies who can speak firsthand about the challenges and opportunities facing entrepreneurs in your district.

We have also prepared a comprehensive policy brief that we would be happy to share with your team in advance of our meeting. This document includes specific legislative recommendations, economic impact analyses, and case studies from our member companies.

The American Tech Founders Alliance has a strong track record of working constructively with legislators on both sides of the aisle to develop policies that support American innovation and competitiveness. We believe that with thoughtful engagement, we can help craft regulations that protect consumers and national interests while ensuring that the United States remains the global leader in technological innovation.

Please let me know if the proposed date and time work for your schedule, or if there is an alternative time that would be more convenient. My assistant, Rebecca Torres, can be reached at rtorres@techfoundersalliance.example or (202) 555-8847 to coordinate scheduling details.

Thank you for your continued leadership on issues affecting American innovation and entrepreneurship. We greatly appreciate your willingness to engage with stakeholders on these important matters and look forward to a productive conversation.

With warm regards,

Jonathan Crawford
Executive Director
American Tech Founders Alliance
1200 K Street NW, Suite 850
Washington, DC 20005

Phone: (202) 555-4420
Email: jcrawford@techfoundersalliance.example
Website: www.techfoundersalliance.example

---
The American Tech Founders Alliance is a 501(c)(4) nonprofit organization dedicated to promoting policies that support technology entrepreneurship and innovation in the United States.
"""

def find_text_position(needle, haystack):
    """Find the start and end position of text in the email body."""
    start = haystack.find(needle)
    if start == -1:
        return None, None
    return start, start + len(needle)


def create_demo_event():
    """Create the demo event with extracted fields."""

    # Get admin user to create the event
    admin_user = User.objects.filter(role='admin').first()
    if not admin_user:
        admin_user = User.objects.first()

    if not admin_user:
        print("Error: No users found in database")
        return

    print(f"Creating demo event as user: {admin_user.username}")

    # Create the email processing record
    email_id = f'demo-{uuid.uuid4()}'

    # Find text positions for highlighting
    title_text = "meeting with you and your staff to discuss critical policy issues affecting the technology startup ecosystem"
    group_text = "American Tech Founders Alliance"
    date_text = "Thursday, April 2nd, 2026"
    time_text = "10:00 AM"
    duration_text = "should last one and a half hours"
    location_text = "in your office"
    poc_name_text = "Jonathan Crawford"
    poc_email_text = "jcrawford@techfoundersalliance.example"
    poc_phone_text = "(202) 555-4420"
    description_text = "discuss critical policy issues affecting the technology startup ecosystem, particularly regarding regulatory frameworks that impact emerging companies in the artificial intelligence, fintech, and clean technology sectors"

    # Build extracted fields with source positions
    extracted_fields = {
        'title': {
            'value': 'Meeting with American Tech Founders Alliance',
            'confidence': 0.92,
            'status': 'pending',
            'start_index': find_text_position(title_text, EMAIL_BODY)[0],
            'end_index': find_text_position(title_text, EMAIL_BODY)[1],
            'text_snippet': title_text,
        },
        'group': {
            'value': 'American Tech Founders Alliance',
            'confidence': 0.98,
            'status': 'pending',
            'start_index': find_text_position(group_text, EMAIL_BODY)[0],
            'end_index': find_text_position(group_text, EMAIL_BODY)[1],
            'text_snippet': group_text,
        },
        'start_date': {
            'value': '2026-04-02',
            'confidence': 0.95,
            'status': 'pending',
            'start_index': find_text_position(date_text, EMAIL_BODY)[0],
            'end_index': find_text_position(date_text, EMAIL_BODY)[1],
            'text_snippet': date_text,
        },
        'start_time': {
            'value': '10:00',
            'confidence': 0.95,
            'status': 'pending',
            'start_index': find_text_position(time_text, EMAIL_BODY)[0],
            'end_index': find_text_position(time_text, EMAIL_BODY)[1],
            'text_snippet': time_text,
        },
        'end_time': {
            'value': '11:30',
            'confidence': 0.88,
            'status': 'pending',
            'start_index': find_text_position(duration_text, EMAIL_BODY)[0],
            'end_index': find_text_position(duration_text, EMAIL_BODY)[1],
            'text_snippet': duration_text,
        },
        'location': {
            'value': '2411 Rayburn House Office Building, Washington, DC 20515',
            'confidence': 0.85,
            'status': 'pending',
            'start_index': find_text_position(location_text, EMAIL_BODY)[0],
            'end_index': find_text_position(location_text, EMAIL_BODY)[1],
            'text_snippet': location_text,
        },
        'description': {
            'value': 'Meeting to discuss critical policy issues affecting the technology startup ecosystem, including AI regulation impact on startups, access to capital and securities regulations, data privacy frameworks, and workforce development. The American Tech Founders Alliance represents over 2,400 technology startup founders and entrepreneurs.',
            'confidence': 0.90,
            'status': 'pending',
            'start_index': find_text_position(description_text, EMAIL_BODY)[0],
            'end_index': find_text_position(description_text, EMAIL_BODY)[1],
            'text_snippet': description_text,
        },
        'point_of_contact_name': {
            'value': 'Jonathan Crawford',
            'confidence': 0.95,
            'status': 'pending',
            'start_index': find_text_position(poc_name_text, EMAIL_BODY)[0],
            'end_index': find_text_position(poc_name_text, EMAIL_BODY)[1],
            'text_snippet': poc_name_text,
        },
        'point_of_contact_email': {
            'value': 'jcrawford@techfoundersalliance.example',
            'confidence': 0.98,
            'status': 'pending',
            'start_index': find_text_position(poc_email_text, EMAIL_BODY)[0],
            'end_index': find_text_position(poc_email_text, EMAIL_BODY)[1],
            'text_snippet': poc_email_text,
        },
        'point_of_contact_phone': {
            'value': '(202) 555-4420',
            'confidence': 0.95,
            'status': 'pending',
            'start_index': find_text_position(poc_phone_text, EMAIL_BODY)[0],
            'end_index': find_text_position(poc_phone_text, EMAIL_BODY)[1],
            'text_snippet': poc_phone_text,
        },
        'type': {
            'value': 'meeting',
            'confidence': 0.92,
            'status': 'pending',
            'start_index': None,
            'end_index': None,
            'text_snippet': 'meeting',
        },
    }

    # Create the event
    event = Event.objects.create(
        title='Meeting with American Tech Founders Alliance',
        type='meeting',
        format='in_person',
        description='Meeting to discuss critical policy issues affecting the technology startup ecosystem, including AI regulation impact on startups, access to capital and securities regulations, data privacy frameworks, and workforce development. The American Tech Founders Alliance represents over 2,400 technology startup founders and entrepreneurs.',
        start_date=date(2026, 4, 2),
        start_time=time(10, 0),
        end_time=time(11, 30),
        location='2411 Rayburn House Office Building, Washington, DC 20515',
        legislative_topics=['Technology', 'Small Business', 'Regulation'],
        status='received',
        requires_human_review=True,
        extracted_fields=extracted_fields,
        created_by=admin_user,
        modified_by=admin_user,
    )

    # Normalized contact / organization (group + point_of_contact).
    from apps.contacts.services import attach_contact_org_to_event
    attach_contact_org_to_event(
        event,
        name='Jonathan Crawford',
        email='jcrawford@techfoundersalliance.example',
        phone='(202) 555-4420',
        group='American Tech Founders Alliance',
        user=admin_user,
    )

    print(f"Created event: {event.title} (ID: {event.id})")

    # Create the email processing record
    email_processing = EmailProcessing.objects.create(
        email_id=email_id,
        subject='Meeting Request: American Tech Founders Alliance - Policy Discussion',
        sender='jcrawford@techfoundersalliance.example',
        sender_name='Jonathan Crawford',
        received=timezone.now(),
        is_scheduling_request=True,
        confidence=0.95,
        complete_email_data={
            'email_id': email_id,
            'email_type': 'original_request',
            'thread_id': f'demo-conv-{uuid.uuid4()}',  # Outlook conversationId -> EmailThread
            'subject': 'Meeting Request: American Tech Founders Alliance - Policy Discussion',
            'from': {
                'email': 'jcrawford@techfoundersalliance.example',
                'name': 'Jonathan Crawford',
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

    # Link model (source of truth): record the Event<->Email link and attach the
    # originating conversation thread so later replies surface automatically.
    event.attach_email(email_processing, origin='ai_auto', user=admin_user, is_primary=True)
    if email_processing.thread_id:
        event.attach_thread(email_processing.thread, user=admin_user)
    if email_processing.thread:
        email_processing.thread.recalc_metadata()

    print(f"Created email processing record: {email_processing.email_id}")
    print("\nDemo event ready for review in the Inbox!")
    print(f"Event ID: {event.id}")


if __name__ == '__main__':
    create_demo_event()
