# SPDX-License-Identifier: Apache-2.0
"""
Management command to add events for today with some overlapping times.
"""

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta
from apps.event_management.models import Event
from apps.authentication.devtools import require_dev_environment

User = get_user_model()


class Command(BaseCommand):
    help = 'Add events for today with some overlapping times to test calendar display'

    def add_arguments(self, parser):
        parser.add_argument(
            '--username',
            type=str,
            default='dev',
            help='Username to assign as creator of the events'
        )

    def handle(self, *args, **options):
        require_dev_environment('add_today_events')
        username = options['username']
        
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(f'User "{username}" not found')
            )
            return

        # Get today's date
        today = timezone.now().date()
        
        # Define today's events with some overlapping times
        today_events = [
            {
                'type': 'meeting',
                'start_date': timezone.now().replace(hour=9, minute=0, second=0, microsecond=0),
                'end_date': timezone.now().replace(hour=10, minute=0, second=0, microsecond=0),
                'time': '9:00 AM - 10:00 AM',
                'location': 'Capitol Building, Room 205',
                'group': 'Morning Staff Briefing',
                'details': 'Daily staff briefing to review schedule and priorities for the day.',
                'legislative_topics': ['Daily Planning', 'Schedule Review'],
                'participants': ['Chief of Staff', 'Policy Director', 'Communications Director'],
                'point_of_contact_name': 'Sarah Johnson',
                'point_of_contact_email': 's.johnson@congress.example',
                'point_of_contact_phone': '(202) 555-0101',
                'staff_recommendation': '1',
                'status': 'scheduled',
                'data_classification': 'internal'
            },
            {
                'type': 'meeting',
                'start_date': timezone.now().replace(hour=9, minute=30, second=0, microsecond=0),
                'end_date': timezone.now().replace(hour=10, minute=30, second=0, microsecond=0),
                'time': '9:30 AM - 10:30 AM',  # OVERLAPS with staff briefing
                'location': 'District Office, Conference Room A',
                'group': 'Constituent Services Review',
                'details': 'Review of pending constituent cases and service requests.',
                'legislative_topics': ['Constituent Services', 'Case Management'],
                'participants': ['Constituent Services Director', 'Case Workers'],
                'point_of_contact_name': 'Michael Chen',
                'point_of_contact_email': 'm.chen@congress.example',
                'point_of_contact_phone': '(202) 555-0102',
                'staff_recommendation': '2',
                'status': 'hold',  # Different status for testing
                'data_classification': 'internal'
            },
            {
                'type': 'meeting',
                'start_date': timezone.now().replace(hour=11, minute=0, second=0, microsecond=0),
                'end_date': timezone.now().replace(hour=12, minute=0, second=0, microsecond=0),
                'time': '11:00 AM - 12:00 PM',
                'location': 'Capitol Building, Room 310',
                'group': 'Budget Committee Prep',
                'details': 'Preparation for upcoming budget committee hearing on infrastructure spending.',
                'legislative_topics': ['Budget', 'Infrastructure', 'Committee Preparation'],
                'participants': ['Budget Analyst', 'Policy Staff', 'Legislative Director'],
                'point_of_contact_name': 'Lisa Rodriguez',
                'point_of_contact_email': 'l.rodriguez@congress.example',
                'point_of_contact_phone': '(202) 555-0103',
                'staff_recommendation': '1',
                'status': 'scheduled',
                'data_classification': 'sensitive'
            },
            {
                'type': 'event',
                'start_date': timezone.now().replace(hour=14, minute=0, second=0, microsecond=0),
                'end_date': timezone.now().replace(hour=15, minute=30, second=0, microsecond=0),
                'time': '2:00 PM - 3:30 PM',
                'location': 'Community Center, Main Hall',
                'group': 'Town Hall: Healthcare Access',
                'details': 'Public town hall meeting focused on healthcare access and affordability in the district.',
                'legislative_topics': ['Healthcare', 'Public Engagement', 'Town Hall'],
                'participants': ['Constituents', 'Healthcare Advocates', 'Medical Professionals'],
                'point_of_contact_name': 'Dr. Amanda White',
                'point_of_contact_email': 'a.white@healthcareaccess.example',
                'point_of_contact_phone': '(555) 234-5678',
                'staff_recommendation': '1',
                'status': 'scheduled',
                'data_classification': 'public'
            },
            {
                'type': 'meeting',
                'start_date': timezone.now().replace(hour=14, minute=30, second=0, microsecond=0),
                'end_date': timezone.now().replace(hour=15, minute=0, second=0, microsecond=0),
                'time': '2:30 PM - 3:00 PM',  # OVERLAPS with town hall
                'location': 'Capitol Building, Room 150',
                'group': 'Press Strategy Meeting',
                'details': 'Quick strategy session with communications team about upcoming press conference.',
                'legislative_topics': ['Communications', 'Press Strategy', 'Media Relations'],
                'participants': ['Press Secretary', 'Communications Director', 'Media Advisor'],
                'point_of_contact_name': 'James Wilson',
                'point_of_contact_email': 'j.wilson@congress.example',
                'point_of_contact_phone': '(202) 555-0104',
                'staff_recommendation': '3',
                'status': 'received',  # Different status
                'data_classification': 'internal'
            },
            {
                'type': 'speaking',
                'start_date': timezone.now().replace(hour=16, minute=0, second=0, microsecond=0),
                'end_date': timezone.now().replace(hour=17, minute=0, second=0, microsecond=0),
                'time': '4:00 PM - 5:00 PM',
                'location': 'Local High School, Auditorium',
                'group': 'Student Leadership Conference',
                'details': 'Keynote address to high school student leaders about civic engagement and democracy.',
                'legislative_topics': ['Youth Engagement', 'Civic Education', 'Democracy'],
                'participants': ['High School Students', 'Teachers', 'School Administrators'],
                'point_of_contact_name': 'Principal Maria Garcia',
                'point_of_contact_email': 'm.garcia@localhighschool.example',
                'point_of_contact_phone': '(555) 345-6789',
                'staff_recommendation': '2',
                'status': 'rsvped',
                'data_classification': 'public'
            },
            {
                'type': 'meeting',
                'start_date': timezone.now().replace(hour=17, minute=30, second=0, microsecond=0),
                'end_date': timezone.now().replace(hour=18, minute=30, second=0, microsecond=0),
                'time': '5:30 PM - 6:30 PM',
                'location': 'District Office, Private Office',
                'group': 'End of Day Wrap-up',
                'details': 'Daily wrap-up meeting to review accomplishments and plan for tomorrow.',
                'legislative_topics': ['Daily Review', 'Planning', 'Staff Coordination'],
                'participants': ['Chief of Staff', 'Scheduler', 'Key Staff'],
                'point_of_contact_name': 'David Kim',
                'point_of_contact_email': 'd.kim@congress.example',
                'point_of_contact_phone': '(202) 555-0105',
                'staff_recommendation': '1',
                'status': 'scheduled',
                'data_classification': 'internal'
            }
        ]

        created_events = []
        overlapping_pairs = []
        
        for i, event_data in enumerate(today_events):
            # Add default values for required fields
            event_data.update({
                'created_by': user,
                'modified_by': user,
                'schedule_notes': event_data.get('schedule_notes', f'Event scheduled for {today.strftime("%B %d, %Y")}.'),
                'campaign_notes': event_data.get('campaign_notes', 'Relevant to daily operations and constituent engagement.'),
                'hms_notes': event_data.get('hms_notes', 'Part of daily schedule - please review.'),
                'staff': event_data.get('staff', ['Scheduler', 'Policy Team', 'Communications'])
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

                # Check for overlaps with previously created events
                for prev_event in created_events[:-1]:
                    if self.events_overlap(prev_event, event):
                        overlapping_pairs.append((prev_event, event))
                
                self.stdout.write(
                    self.style.SUCCESS(
                        f'✓ Created: "{event.group}" - {event.get_type_display()} '
                        f'at {event.time_display} ({event.get_status_display_from_office()})'
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
                f'\n🎉 Successfully created {len(created_events)} events for today ({today.strftime("%B %d, %Y")})!'
            )
        )
        
        # Display overlapping events
        if overlapping_pairs:
            self.stdout.write(
                self.style.WARNING(
                    f'\n⚠️  Found {len(overlapping_pairs)} overlapping time conflicts:'
                )
            )
            for i, (event1, event2) in enumerate(overlapping_pairs, 1):
                self.stdout.write(
                    f'  {i}. "{event1.group}" ({event1.time_display}) overlaps with '
                    f'"{event2.group}" ({event2.time_display})'
                )
        else:
            self.stdout.write(
                self.style.SUCCESS('\n✅ No time conflicts detected.')
            )
        
        # Display summary by status
        self.stdout.write('\n📊 Today\'s Events by Status:')
        status_counts = {}
        for event in created_events:
            status = event.get_status_display_from_office()
            status_counts[status] = status_counts.get(status, 0) + 1
        
        for status, count in status_counts.items():
            self.stdout.write(f'  • {status}: {count} events')
        
        # Display summary by type
        self.stdout.write('\n📋 Today\'s Events by Type:')
        type_counts = {}
        for event in created_events:
            event_type = event.get_type_display()
            type_counts[event_type] = type_counts.get(event_type, 0) + 1
        
        for event_type, count in type_counts.items():
            self.stdout.write(f'  • {event_type}: {count} events')
        
        self.stdout.write(
            self.style.SUCCESS(
                '\n✅ Today\'s calendar is ready! Check the daily view to see overlapping events.'
            )
        )

    def events_overlap(self, event1, event2):
        """Check if two events have overlapping times."""
        start1 = event1.start_date
        end1 = event1.end_date or (event1.start_date + timedelta(hours=1))
        start2 = event2.start_date
        end2 = event2.end_date or (event2.start_date + timedelta(hours=1))
        
        # Events overlap if one starts before the other ends
        return start1 < end2 and start2 < end1