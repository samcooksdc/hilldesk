# SPDX-License-Identifier: Apache-2.0
"""
Management command to add sample events for testing and demonstration.
"""

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta
from apps.event_management.models import Event
from apps.authentication.devtools import require_dev_environment

User = get_user_model()


class Command(BaseCommand):
    help = 'Add sample events for testing and demonstration'

    def add_arguments(self, parser):
        parser.add_argument(
            '--username',
            type=str,
            default='dev',
            help='Username to assign as creator of the event'
        )
        parser.add_argument(
            '--count',
            type=int,
            default=1,
            help='Number of sample events to create'
        )

    def handle(self, *args, **options):
        require_dev_environment('add_sample_event')
        username = options['username']
        count = options['count']
        
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(f'User "{username}" not found')
            )
            return

        # Sample event data
        sample_events = [
            {
                'type': 'meeting',
                'start_date': timezone.now() + timedelta(days=7),
                'end_date': timezone.now() + timedelta(days=7, hours=1),
                'time': '2:00 PM - 3:00 PM',
                'location': 'Capitol Building, Room 205',
                'group': 'Healthcare Coalition of America',
                'details': 'Discussion on upcoming healthcare legislation and its impact on rural communities. The coalition will present their position on Medicare expansion and prescription drug pricing reforms.',
                'legislative_topics': [
                    'Healthcare Reform',
                    'Medicare Expansion',
                    'Prescription Drug Pricing',
                    'Rural Healthcare Access'
                ],
                'participants': [
                    'Dr. Sarah Johnson - Coalition Director',
                    'Mark Thompson - Policy Analyst',
                    'Rep. Smith - Healthcare Subcommittee',
                    'Staff: Policy Team'
                ],
                'point_of_contact_name': 'Jennifer Martinez',
                'point_of_contact_email': 'j.martinez@healthcarecoalition.example',
                'point_of_contact_phone': '(202) 555-0123',
                'schedule_notes': 'No conflicts identified. Recommend scheduling during regular business hours.',
                'staff_recommendation': '3',
                'campaign_notes': 'Aligns with healthcare platform priorities. Good opportunity for constituent engagement.',
                'hms_notes': 'Important meeting for healthcare agenda. Please prioritize.',
                'staff': [
                    'Healthcare Policy Director',
                    'Legislative Correspondent',
                    'Communications Director'
                ],
                'status': 'scheduling_in_progress',
                'data_classification': 'internal'
            },
            {
                'type': 'event',
                'start_date': timezone.now() + timedelta(days=14),
                'end_date': timezone.now() + timedelta(days=14, hours=2),
                'time': '6:00 PM - 8:00 PM',
                'location': 'Community Center, 123 Main Street',
                'group': 'Local Chamber of Commerce',
                'details': 'Annual business awards ceremony and networking event. Opportunity to recognize local businesses and discuss economic development initiatives.',
                'legislative_topics': [
                    'Small Business Support',
                    'Economic Development',
                    'Tax Policy',
                    'Infrastructure Investment'
                ],
                'participants': [
                    'Chamber Members (50+ expected)',
                    'Local Business Owners',
                    'Economic Development Officials',
                    'Media Representatives'
                ],
                'point_of_contact_name': 'Robert Chen',
                'point_of_contact_email': 'r.chen@localchamber.example',
                'point_of_contact_phone': '(555) 123-4567',
                'schedule_notes': 'Evening event, check for scheduling conflicts with other commitments.',
                'staff_recommendation': '2',
                'campaign_notes': 'Excellent visibility opportunity with local business community.',
                'hms_notes': 'Good community engagement opportunity.',
                'staff': [
                    'Economic Policy Advisor',
                    'Communications Team',
                    'Scheduler'
                ],
                'status': 'received',
                'data_classification': 'public'
            },
            {
                'type': 'speaking',
                'start_date': timezone.now() + timedelta(days=21),
                'end_date': timezone.now() + timedelta(days=21, minutes=45),
                'time': '10:00 AM - 10:45 AM',
                'location': 'University Auditorium, State University',
                'group': 'Student Government Association',
                'details': 'Keynote address at the annual Student Leadership Conference. Topic: "The Future of Democracy and Youth Engagement in Politics"',
                'legislative_topics': [
                    'Youth Engagement',
                    'Democratic Participation',
                    'Education Policy',
                    'Student Loan Reform'
                ],
                'participants': [
                    'Student Leaders (200+ expected)',
                    'Faculty Members',
                    'University Administration',
                    'Local Media'
                ],
                'point_of_contact_name': 'Alex Rivera',
                'point_of_contact_email': 'a.rivera@stateuniversity.example',
                'point_of_contact_phone': '(555) 987-6543',
                'schedule_notes': 'Morning event, allows for afternoon schedule flexibility.',
                'staff_recommendation': '1',
                'campaign_notes': 'Critical youth outreach opportunity. Aligns with education priorities.',
                'hms_notes': 'High priority - important for youth engagement strategy.',
                'staff': [
                    'Education Policy Director',
                    'Youth Outreach Coordinator',
                    'Press Secretary'
                ],
                'status': 'scheduled',
                'data_classification': 'public'
            }
        ]

        created_events = []
        
        for i in range(min(count, len(sample_events))):
            event_data = sample_events[i].copy()

            # Normalized contact/org fields are no longer Event columns; pull them
            # out and link them after the event is created.
            poc_name = event_data.pop('point_of_contact_name', '')
            poc_email = event_data.pop('point_of_contact_email', '')
            poc_phone = event_data.pop('point_of_contact_phone', '')
            group = event_data.pop('group', '')

            # Create the event
            event = Event.objects.create(
                created_by=user,
                modified_by=user,
                **event_data
            )

            from apps.contacts.services import attach_contact_org_to_event
            attach_contact_org_to_event(
                event,
                name=poc_name,
                email=poc_email,
                phone=poc_phone,
                group=group,
                user=user,
            )

            created_events.append(event)
            
            self.stdout.write(
                self.style.SUCCESS(
                    f'Created event: "{event.group}" - {event.type.title()} '
                    f'on {event.start_date.strftime("%Y-%m-%d %H:%M")}'
                )
            )

        self.stdout.write(
            self.style.SUCCESS(
                f'\nSuccessfully created {len(created_events)} sample event(s) '
                f'for user "{username}"'
            )
        )
        
        # Display summary
        self.stdout.write('\nEvent Summary:')
        for event in created_events:
            self.stdout.write(
                f'  • {event.group} ({event.get_type_display()}) - '
                f'{event.get_status_display_from_office()}'
            )