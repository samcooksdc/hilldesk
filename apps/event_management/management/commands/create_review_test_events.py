# SPDX-License-Identifier: Apache-2.0
"""
Management command to create test events requiring human review.
Creates 5 events dated within the current week with AI-extracted fields in
pending status, each with an associated EmailProcessing record containing the
source email (so the reply system can be exercised end-to-end).
"""

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta, time
import uuid

from apps.event_management.models import Event
from apps.email_processing.models import EmailProcessing
from apps.authentication.devtools import require_dev_environment

User = get_user_model()


class Command(BaseCommand):
    help = 'Create 5 test events in the future that require human review, with source emails'

    def handle(self, *args, **options):
        require_dev_environment('create_review_test_events')
        # Get or create a test user
        user, created = User.objects.get_or_create(
            username='test_user',
            defaults={
                'email': 'test@example.com',
                'first_name': 'Test',
                'last_name': 'User',
            }
        )
        if created:
            user.set_password('testpass123')
            user.save()
            self.stdout.write(self.style.SUCCESS(f'Created test user: {user.username}'))

        # Test data - events with source emails
        test_data = [
            {
                'email': {
                    'subject': 'Meeting Request: Franklin Chamber of Commerce Quarterly Discussion',
                    'sender': 'sjohnson@michamber.example',
                    'sender_name': 'Sarah Johnson',
                    'body_text': '''Dear Representative,

I hope this message finds you well. On behalf of the Franklin Chamber of Commerce, I would like to request a meeting with the Franklin Chamber of Commerce to discuss economic development initiatives and manufacturing policy affecting our state.

We would like to meet on January 8th, 2026 at 10:00 AM in your Rayburn office if that works for your schedule. The meeting should last approximately one hour.

Please let me know if this time works, or if you would prefer an alternative date.

Best regards,
Sarah Johnson
Director of Government Relations
Franklin Chamber of Commerce
Phone: (517) 555-1234
Email: sjohnson@michamber.example''',
                },
                'event': {
                    'title': 'Meeting with Franklin Chamber of Commerce',
                    'group': 'Franklin Chamber of Commerce',
                    'type': 'meeting',
                    'format': 'in-person',
                    'location': '2400 Rayburn House Office Building',
                    'start_date_offset': 3,
                    'start_time': time(10, 0),
                    'end_time': time(11, 0),
                    'description': 'Quarterly meeting to discuss economic development initiatives and manufacturing policy.',
                    'point_of_contact_name': 'Sarah Johnson',
                    'point_of_contact_email': 'sjohnson@michamber.example',
                    'point_of_contact_phone': '(517) 555-1234',
                },
                'extracted_fields': {
                    'title': {
                        'value': 'Meeting with Franklin Chamber of Commerce',
                        'confidence': 0.92,
                        'status': 'pending',
                        'start_index': 156,
                        'end_index': 200,
                        'text_snippet': 'meeting with the Franklin Chamber of Commerce',
                    },
                    'start_date': {
                        'value': None,  # Will be set dynamically
                        'confidence': 0.88,
                        'status': 'pending',
                        'start_index': 270,
                        'end_index': 295,
                        'text_snippet': 'January 8th, 2026 at 10:00 AM',
                    },
                    'start_time': {
                        'value': '10:00',
                        'confidence': 0.95,
                        'status': 'pending',
                        'start_index': 285,
                        'end_index': 295,
                        'text_snippet': '10:00 AM',
                    },
                    'location': {
                        'value': '2400 Rayburn House Office Building',
                        'confidence': 0.78,
                        'status': 'pending',
                        'start_index': 300,
                        'end_index': 320,
                        'text_snippet': 'in your Rayburn office',
                    },
                    'point_of_contact_name': {
                        'value': 'Sarah Johnson',
                        'confidence': 0.91,
                        'status': 'pending',
                        'start_index': 480,
                        'end_index': 493,
                        'text_snippet': 'Sarah Johnson',
                    },
                }
            },
            {
                'email': {
                    'subject': 'Town Hall Invitation - Workers Local 100',
                    'sender': 'mthompson@uaw652.example',
                    'sender_name': 'Mike Thompson',
                    'body_text': '''Representative,

The Fairview Workers Local 100 would like to invite you to a town hall with Workers Local 100 members next Friday evening at the union hall in Fairview.

We're hoping to discuss labor policy, manufacturing jobs, and the future of the auto industry in Franklin. The event will be a hybrid format with both in-person attendance and virtual participation available.

The town hall is scheduled from 6:00 PM to 8:00 PM. We expect approximately 150 members to attend.

Please RSVP at your earliest convenience.

In solidarity,
Mike Thompson
President, Workers Local 100
mthompson@uaw652.example
(517) 555-4567''',
                },
                'event': {
                    'title': 'Workers Local 100 Town Hall',
                    'group': 'Fairview Workers Local 100',
                    'type': 'event',
                    'format': 'hybrid',
                    'location': 'Workers Local 100 Hall, Fairview, FR',
                    'start_date_offset': 5,
                    'start_time': time(18, 0),
                    'end_time': time(20, 0),
                    'description': 'Town hall meeting with union members to discuss labor policy and manufacturing jobs.',
                    'point_of_contact_name': 'Mike Thompson',
                    'point_of_contact_email': 'mthompson@uaw652.example',
                    'point_of_contact_phone': '(517) 555-4567',
                },
                'extracted_fields': {
                    'title': {
                        'value': 'Workers Local 100 Town Hall',
                        'confidence': 0.85,
                        'status': 'pending',
                        'start_index': 70,
                        'end_index': 110,
                        'text_snippet': 'town hall with Workers Local 100 members',
                    },
                    'start_date': {
                        'value': None,
                        'confidence': 0.82,
                        'status': 'pending',
                        'start_index': 111,
                        'end_index': 131,
                        'text_snippet': 'next Friday evening',
                    },
                    'location': {
                        'value': 'Workers Local 100 Hall, Fairview, FR',
                        'confidence': 0.90,
                        'status': 'pending',
                        'start_index': 135,
                        'end_index': 160,
                        'text_snippet': 'at the union hall in Fairview',
                    },
                    'group': {
                        'value': 'Fairview Workers Local 100',
                        'confidence': 0.94,
                        'status': 'pending',
                        'start_index': 5,
                        'end_index': 35,
                        'text_snippet': 'Fairview Workers Local 100',
                    },
                }
            },
            {
                'email': {
                    'subject': 'STEM Education Roundtable - Virtual Meeting Request',
                    'sender': 'lchen@oaklandschools.example',
                    'sender_name': 'Dr. Linda Chen',
                    'body_text': '''Dear Congresswoman,

The Elm County Schools Coalition is organizing a STEM education roundtable discussion and we would be honored to have you participate.

The roundtable will focus on STEM education funding, workforce development pipelines, and preparing students for careers in technology and manufacturing.

We are proposing to hold this meeting next week on Tuesday at 2:00 PM via Zoom. The discussion should last approximately 90 minutes.

Participants will include superintendents from Elm County school districts, community college representatives, and local industry partners.

Please let me know if you are available to join us.

Best regards,
Dr. Linda Chen
Superintendent, Elm County Schools Coalition
lchen@oaklandschools.example
(248) 555-7890''',
                },
                'event': {
                    'title': 'STEM Education Roundtable',
                    'group': 'Elm County Schools Coalition',
                    'type': 'meeting',
                    'format': 'virtual',
                    'location': 'Zoom Meeting',
                    'start_date_offset': 7,
                    'start_time': time(14, 0),
                    'end_time': time(15, 30),
                    'description': 'Roundtable discussion on STEM education funding and workforce development.',
                    'point_of_contact_name': 'Dr. Linda Chen',
                    'point_of_contact_email': 'lchen@oaklandschools.example',
                    'point_of_contact_phone': '(248) 555-7890',
                },
                'extracted_fields': {
                    'title': {
                        'value': 'STEM Education Roundtable',
                        'confidence': 0.88,
                        'status': 'pending',
                        'start_index': 65,
                        'end_index': 105,
                        'text_snippet': 'STEM education roundtable discussion',
                    },
                    'start_date': {
                        'value': None,
                        'confidence': 0.75,
                        'status': 'pending',
                        'start_index': 295,
                        'end_index': 320,
                        'text_snippet': 'next week on Tuesday at 2:00 PM',
                    },
                    'format': {
                        'value': 'virtual',
                        'confidence': 0.96,
                        'status': 'pending',
                        'start_index': 321,
                        'end_index': 330,
                        'text_snippet': 'via Zoom',
                    },
                    'point_of_contact_email': {
                        'value': 'lchen@oaklandschools.example',
                        'confidence': 0.99,
                        'status': 'pending',
                        'start_index': 620,
                        'end_index': 644,
                        'text_snippet': 'lchen@oaklandschools.example',
                    },
                }
            },
            {
                'email': {
                    'subject': 'Small Business Listening Session - Fairview',
                    'sender': 'jwilliams@rhsba.example',
                    'sender_name': 'James Williams',
                    'body_text': '''Good morning,

The Fairview Small Business Association would like to invite you to a small business listening session on January 15th at 9 AM.

The event will be held at City Hall in Fairview and will give local small business owners the opportunity to share their experiences regarding regulatory challenges, access to capital, and workforce issues.

We anticipate approximately 40 business owners will attend. Light refreshments will be served.

This is an excellent opportunity to hear directly from the small business community in your district.

Please confirm your availability at your earliest convenience.

Thank you,
James Williams
Executive Director
Fairview Small Business Association
jwilliams@rhsba.example
(248) 555-2345''',
                },
                'event': {
                    'title': 'Small Business Listening Session',
                    'group': 'Fairview Small Business Association',
                    'type': 'event',
                    'format': 'in-person',
                    'location': 'Fairview City Hall',
                    'start_date_offset': 10,
                    'start_time': time(9, 0),
                    'end_time': time(11, 0),
                    'description': 'Listening session with small business owners on regulatory challenges and access to capital.',
                    'point_of_contact_name': 'James Williams',
                    'point_of_contact_email': 'jwilliams@rhsba.example',
                    'point_of_contact_phone': '(248) 555-2345',
                },
                'extracted_fields': {
                    'title': {
                        'value': 'Small Business Listening Session',
                        'confidence': 0.91,
                        'status': 'pending',
                        'start_index': 75,
                        'end_index': 110,
                        'text_snippet': 'small business listening session',
                    },
                    'start_date': {
                        'value': None,
                        'confidence': 0.80,
                        'status': 'pending',
                        'start_index': 114,
                        'end_index': 128,
                        'text_snippet': 'January 15th at 9 AM',
                    },
                    'start_time': {
                        'value': '09:00',
                        'confidence': 0.93,
                        'status': 'pending',
                        'start_index': 125,
                        'end_index': 129,
                        'text_snippet': '9 AM',
                    },
                    'location': {
                        'value': 'Fairview City Hall',
                        'confidence': 0.87,
                        'status': 'pending',
                        'start_index': 160,
                        'end_index': 190,
                        'text_snippet': 'City Hall in Fairview',
                    },
                    'group': {
                        'value': 'Fairview Small Business Association',
                        'confidence': 0.89,
                        'status': 'pending',
                        'start_index': 20,
                        'end_index': 63,
                        'text_snippet': 'Fairview Small Business Association',
                    },
                }
            },
            {
                'email': {
                    'subject': 'Veterans Affairs Briefing Request',
                    'sender': 'rmartinez@michigan.example',
                    'sender_name': 'Col. Robert Martinez (Ret.)',
                    'body_text': '''Congresswoman,

The Franklin Veterans Affairs Agency respectfully requests a briefing on veterans affairs with you and your staff two weeks from now.

We would like to discuss veterans healthcare access in Franklin, benefits processing times, and pending legislation affecting our veteran community.

Colonel Robert Martinez (Ret.), our Deputy Director, will lead the briefing. He will provide remarks and Q&A on current initiatives and challenges.

The briefing would take place at your office in the Rayburn Building, room 2154. We are proposing 11:00 AM and expect the session to last approximately one hour.

Please advise if this works for your schedule.

Respectfully,
Col. Robert Martinez (Ret.)
Deputy Director
MI Veterans Affairs Agency
rmartinez@michigan.example
(517) 555-6789''',
                },
                'event': {
                    'title': 'Veterans Affairs Committee Briefing',
                    'group': 'MI Veterans Affairs Agency',
                    'type': 'speaking',
                    'format': 'in-person',
                    'location': '2154 Rayburn House Office Building',
                    'start_date_offset': 14,
                    'start_time': time(11, 0),
                    'end_time': time(12, 0),
                    'description': 'Briefing on veterans healthcare access and benefits processing times.',
                    'point_of_contact_name': 'Col. Robert Martinez (Ret.)',
                    'point_of_contact_email': 'rmartinez@michigan.example',
                    'point_of_contact_phone': '(517) 555-6789',
                },
                'extracted_fields': {
                    'title': {
                        'value': 'Veterans Affairs Committee Briefing',
                        'confidence': 0.86,
                        'status': 'pending',
                        'start_index': 70,
                        'end_index': 100,
                        'text_snippet': 'briefing on veterans affairs',
                    },
                    'start_date': {
                        'value': None,
                        'confidence': 0.79,
                        'status': 'pending',
                        'start_index': 130,
                        'end_index': 150,
                        'text_snippet': 'two weeks from now',
                    },
                    'type': {
                        'value': 'speaking',
                        'confidence': 0.72,
                        'status': 'pending',
                        'start_index': 340,
                        'end_index': 360,
                        'text_snippet': 'remarks and Q&A',
                    },
                    'point_of_contact_name': {
                        'value': 'Col. Robert Martinez (Ret.)',
                        'confidence': 0.94,
                        'status': 'pending',
                        'start_index': 295,
                        'end_index': 325,
                        'text_snippet': 'Colonel Robert Martinez (Ret.)',
                    },
                }
            },
        ]

        # Anchor all events to the current week (Monday of this week), then
        # spread them across Tue–Sat so the dates are always "this week".
        today = timezone.now().date()
        week_monday = today - timedelta(days=today.weekday())

        created_count = 0
        for i, data in enumerate(test_data):
            email_data = data['email']
            event_data = data['event']
            extracted_fields = data['extracted_fields']

            # Place this event on a day within the current week
            event_data.pop('start_date_offset', None)
            start_date = week_monday + timedelta(days=(i % 5) + 1)

            # Update extracted_fields with actual date value
            if 'start_date' in extracted_fields:
                extracted_fields['start_date']['value'] = str(start_date)

            # Create the Event first
            event = Event.objects.create(
                title=event_data['title'],
                type=event_data['type'],
                format=event_data['format'],
                location=event_data['location'],
                start_date=start_date,
                start_time=event_data['start_time'],
                end_time=event_data['end_time'],
                description=event_data['description'],
                requires_human_review=True,
                extracted_fields=extracted_fields,
                status='received',
                created_by=user,
                modified_by=user,
            )

            from apps.contacts.services import attach_contact_org_to_event
            attach_contact_org_to_event(
                event,
                name=event_data['point_of_contact_name'],
                email=event_data['point_of_contact_email'],
                phone=event_data['point_of_contact_phone'],
                group=event_data['group'],
                user=user,
            )

            # Create the associated EmailProcessing record
            email_id = f"test-email-{uuid.uuid4()}"
            email_processing = EmailProcessing.objects.create(
                email_id=email_id,
                subject=email_data['subject'],
                sender=email_data['sender'],
                sender_name=email_data['sender_name'],
                received=timezone.now() - timedelta(hours=2),  # Received 2 hours ago
                is_scheduling_request=True,
                confidence=0.92,
                complete_email_data={
                    'email_id': email_id,
                    'subject': email_data['subject'],
                    'from': {
                        'email': email_data['sender'],
                        'name': email_data['sender_name'],
                    },
                    'to': [{'email': 'office@example.com', 'name': 'Congressional Office'}],
                    'received': timezone.now().isoformat(),
                    'body': {
                        'text': email_data['body_text'],
                        'html': f"<html><body><pre>{email_data['body_text']}</pre></body></html>",
                        'preview': email_data['body_text'][:200],
                    },
                    'attachments': [],
                    'thread_id': f"thread-{uuid.uuid4()}",
                    'email_type': 'scheduling_request',
                },
                extracted_data={
                    'is_scheduling_request': True,
                    'event_type': event_data['type'],
                    'group': event_data['group'],
                    'location': event_data['location'],
                    'start_date': str(start_date),
                    'point_of_contact': {
                        'name': event_data['point_of_contact_name'],
                        'email': event_data['point_of_contact_email'],
                        'phone': event_data['point_of_contact_phone'],
                    },
                },
                status='processed',
                event=event,  # Link to the created event
            )

            created_count += 1
            self.stdout.write(
                self.style.SUCCESS(
                    f'Created event: {event.title} (ID: {event.id})\n'
                    f'  - {len(extracted_fields)} fields pending review\n'
                    f'  - Source email: {email_processing.subject}'
                )
            )

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'Successfully created {created_count} test events with source emails'
        ))
        self.stdout.write(self.style.NOTICE(
            'Use the Review button on the calendar to open these events for review.'
        ))
