# SPDX-License-Identifier: Apache-2.0
"""
Management command to add 10 diverse test events for calendar testing.
"""

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta
from apps.event_management.models import Event
from apps.authentication.devtools import require_dev_environment

User = get_user_model()


class Command(BaseCommand):
    help = 'Add 10 diverse test events for calendar testing'

    def add_arguments(self, parser):
        parser.add_argument(
            '--username',
            type=str,
            default='dev',
            help='Username to assign as creator of the events'
        )
        parser.add_argument(
            '--clear-existing',
            action='store_true',
            help='Clear existing events before adding new ones'
        )

    def handle(self, *args, **options):
        require_dev_environment('add_calendar_test_events')
        username = options['username']
        clear_existing = options['clear_existing']
        
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(f'User "{username}" not found')
            )
            return

        # Clear existing events if requested
        if clear_existing:
            existing_count = Event.objects.count()
            Event.objects.all().delete()
            self.stdout.write(
                self.style.WARNING(f'Cleared {existing_count} existing events')
            )

        # Define 10 diverse test events
        test_events = [
            {
                'type': 'meeting',
                'start_date': timezone.now() + timedelta(days=2),
                'time': '9:00 AM - 10:00 AM',
                'location': 'Capitol Building, Room 205',
                'group': 'Healthcare Coalition of America',
                'details': 'Discussion on upcoming healthcare legislation and Medicare expansion.',
                'legislative_topics': ['Healthcare Reform', 'Medicare Expansion'],
                'participants': ['Dr. Sarah Johnson', 'Mark Thompson', 'Policy Team'],
                'point_of_contact_name': 'Jennifer Martinez',
                'point_of_contact_email': 'j.martinez@healthcarecoalition.example',
                'point_of_contact_phone': '(202) 555-0123',
                'staff_recommendation': '3',
                'status': 'scheduled',
                'data_classification': 'internal'
            },
            {
                'type': 'event',
                'start_date': timezone.now() + timedelta(days=5),
                'time': '6:00 PM - 8:00 PM',
                'location': 'Community Center, 123 Main Street',
                'group': 'Local Chamber of Commerce',
                'details': 'Annual business awards ceremony and networking event.',
                'legislative_topics': ['Small Business Support', 'Economic Development'],
                'participants': ['Chamber Members', 'Local Business Owners'],
                'point_of_contact_name': 'Robert Chen',
                'point_of_contact_email': 'r.chen@localchamber.example',
                'point_of_contact_phone': '(555) 123-4567',
                'staff_recommendation': '2',
                'status': 'hold',
                'data_classification': 'public'
            },
            {
                'type': 'speaking',
                'start_date': timezone.now() + timedelta(days=8),
                'time': '10:00 AM - 10:45 AM',
                'location': 'University Auditorium, State University',
                'group': 'Student Government Association',
                'details': 'Keynote address at Student Leadership Conference on youth engagement.',
                'legislative_topics': ['Youth Engagement', 'Education Policy'],
                'participants': ['Student Leaders', 'Faculty Members'],
                'point_of_contact_name': 'Alex Rivera',
                'point_of_contact_email': 'a.rivera@stateuniversity.example',
                'point_of_contact_phone': '(555) 987-6543',
                'staff_recommendation': '1',
                'status': 'scheduled',
                'data_classification': 'public'
            },
            {
                'type': 'meeting',
                'start_date': timezone.now() + timedelta(days=12),
                'time': '2:00 PM - 3:30 PM',
                'location': 'District Office, Conference Room A',
                'group': 'Environmental Protection Alliance',
                'details': 'Climate change policy discussion and renewable energy initiatives.',
                'legislative_topics': ['Climate Change', 'Renewable Energy', 'Environmental Policy'],
                'participants': ['Environmental Scientists', 'Policy Advocates'],
                'point_of_contact_name': 'Maria Gonzalez',
                'point_of_contact_email': 'm.gonzalez@epa-alliance.example',
                'point_of_contact_phone': '(555) 234-5678',
                'staff_recommendation': '2',
                'status': 'received',
                'data_classification': 'internal'
            },
            {
                'type': 'event',
                'start_date': timezone.now() + timedelta(days=15),
                'time': '7:00 PM - 9:00 PM',
                'location': 'Town Hall, 456 Oak Avenue',
                'group': 'Veterans Affairs Committee',
                'details': 'Town hall meeting on veterans benefits and healthcare services.',
                'legislative_topics': ['Veterans Affairs', 'Healthcare', 'Benefits'],
                'participants': ['Veterans', 'Military Families', 'VA Representatives'],
                'point_of_contact_name': 'James Wilson',
                'point_of_contact_email': 'j.wilson@veteranscommittee.example',
                'point_of_contact_phone': '(555) 345-6789',
                'staff_recommendation': '1',
                'status': 'rsvped',
                'data_classification': 'public'
            },
            {
                'type': 'meeting',
                'start_date': timezone.now() + timedelta(days=18),
                'time': '11:00 AM - 12:00 PM',
                'location': 'Capitol Building, Room 310',
                'group': 'Technology Innovation Council',
                'details': 'Discussion on cybersecurity legislation and digital privacy rights.',
                'legislative_topics': ['Cybersecurity', 'Digital Privacy', 'Technology Policy'],
                'participants': ['Tech Industry Leaders', 'Cybersecurity Experts'],
                'point_of_contact_name': 'David Kim',
                'point_of_contact_email': 'd.kim@techinnovation.example',
                'point_of_contact_phone': '(555) 456-7890',
                'staff_recommendation': '3',
                'status': 'canceled',
                'data_classification': 'sensitive'
            },
            {
                'type': 'speaking',
                'start_date': timezone.now() + timedelta(days=22),
                'time': '3:00 PM - 4:00 PM',
                'location': 'Labor Union Hall, 789 Industrial Blvd',
                'group': 'United Workers Federation',
                'details': 'Address to union members on labor rights and workplace safety.',
                'legislative_topics': ['Labor Rights', 'Workplace Safety', 'Union Relations'],
                'participants': ['Union Members', 'Labor Leaders', 'Safety Inspectors'],
                'point_of_contact_name': 'Lisa Thompson',
                'point_of_contact_email': 'l.thompson@unitedworkers.example',
                'point_of_contact_phone': '(555) 567-8901',
                'staff_recommendation': '2',
                'status': 'scheduling_in_progress',
                'data_classification': 'internal'
            },
            {
                'type': 'event',
                'start_date': timezone.now() + timedelta(days=25),
                'time': '5:30 PM - 7:30 PM',
                'location': 'Senior Center, 321 Elm Street',
                'group': 'Senior Citizens Advisory Board',
                'details': 'Community forum on Social Security and Medicare benefits.',
                'legislative_topics': ['Social Security', 'Medicare', 'Senior Services'],
                'participants': ['Senior Citizens', 'Healthcare Providers', 'Social Workers'],
                'point_of_contact_name': 'Margaret Davis',
                'point_of_contact_email': 'm.davis@senioradvisory.example',
                'point_of_contact_phone': '(555) 678-9012',
                'staff_recommendation': '1',
                'status': 'passed',
                'data_classification': 'public'
            },
            {
                'type': 'meeting',
                'start_date': timezone.now() + timedelta(days=28),
                'time': '1:00 PM - 2:30 PM',
                'location': 'District Office, Meeting Room B',
                'group': 'Agricultural Producers Association',
                'details': 'Farm bill discussion and agricultural subsidies review.',
                'legislative_topics': ['Agriculture', 'Farm Bill', 'Rural Development'],
                'participants': ['Farmers', 'Agricultural Economists', 'Rural Advocates'],
                'point_of_contact_name': 'Tom Anderson',
                'point_of_contact_email': 't.anderson@agproducers.example',
                'point_of_contact_phone': '(555) 789-0123',
                'staff_recommendation': '2',
                'status': 'referred',
                'data_classification': 'internal'
            },
            {
                'type': 'speaking',
                'start_date': timezone.now() + timedelta(days=32),
                'time': '12:00 PM - 1:00 PM',
                'location': 'Rotary Club, Grand Hotel Ballroom',
                'group': 'Downtown Rotary Club',
                'details': 'Luncheon speech on infrastructure investment and economic growth.',
                'legislative_topics': ['Infrastructure', 'Economic Growth', 'Transportation'],
                'participants': ['Rotary Members', 'Business Leaders', 'City Officials'],
                'point_of_contact_name': 'Patricia White',
                'point_of_contact_email': 'p.white@downtownrotary.example',
                'point_of_contact_phone': '(555) 890-1234',
                'staff_recommendation': '3',
                'status': 'requires_hms_review',
                'data_classification': 'public'
            }
        ]

        created_events = []
        
        for i, event_data in enumerate(test_events):
            # Add some variation to times and dates
            base_date = event_data['start_date']
            
            # Create end_date if not specified
            if 'end_date' not in event_data:
                event_data['end_date'] = base_date + timedelta(hours=1)
            
            # Add default values for required fields
            event_data.update({
                'created_by': user,
                'modified_by': user,
                'schedule_notes': event_data.get('schedule_notes', 'Standard scheduling notes.'),
                'campaign_notes': event_data.get('campaign_notes', 'Relevant to campaign priorities.'),
                'hms_notes': event_data.get('hms_notes', 'For HMS review and consideration.'),
                'staff': event_data.get('staff', ['Policy Team', 'Communications', 'Scheduler'])
            })
            
            # Normalized contact/org fields are no longer Event columns; pull them
            # out and link them after the event is created.
            poc_name = event_data.pop('point_of_contact_name', '')
            poc_email = event_data.pop('point_of_contact_email', '')
            poc_phone = event_data.pop('point_of_contact_phone', '')
            group = event_data.pop('group', '')

            try:
                event = Event.objects.create(**event_data)

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
                        f'✓ Created: "{event.group}" - {event.get_type_display()} '
                        f'on {event.start_date.strftime("%Y-%m-%d")} ({event.get_status_display_from_office()})'
                    )
                )
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(
                        f'✗ Failed to create event {i+1}: {str(e)}'
                    )
                )

        self.stdout.write(
            self.style.SUCCESS(
                f'\n🎉 Successfully created {len(created_events)} test events for calendar!'
            )
        )
        
        # Display summary by status
        self.stdout.write('\n📊 Event Summary by Status:')
        status_counts = {}
        for event in created_events:
            status = event.get_status_display_from_office()
            status_counts[status] = status_counts.get(status, 0) + 1
        
        for status, count in status_counts.items():
            self.stdout.write(f'  • {status}: {count} events')
        
        # Display summary by type
        self.stdout.write('\n📋 Event Summary by Type:')
        type_counts = {}
        for event in created_events:
            event_type = event.get_type_display()
            type_counts[event_type] = type_counts.get(event_type, 0) + 1
        
        for event_type, count in type_counts.items():
            self.stdout.write(f'  • {event_type}: {count} events')
        
        self.stdout.write(
            self.style.SUCCESS(
                '\n✅ Calendar test data is ready! Visit the calendar page to see the events.'
            )
        )