# SPDX-License-Identifier: Apache-2.0
"""
Management command to create demo users for testing role-based permissions.

Creates a demo office with users of different roles:
- 1 admin user
- 2 scheduler users
- 3 staff users
- Staff profiles linked to users
- Sample events with approval routing

Usage:
    python manage.py create_demo_users

Options:
    --office-name: Name of the demo office (default: "Demo Office")
    --reset: Delete existing demo users before creating new ones
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from django.conf import settings
from datetime import date, time, timedelta
from apps.authentication.devtools import require_dev_environment


class Command(BaseCommand):
    help = 'Create demo users with different roles for testing'

    def add_arguments(self, parser):
        parser.add_argument(
            '--office-name',
            type=str,
            default='Demo Office',
            help='Name of the demo office to create'
        )
        parser.add_argument(
            '--reset',
            action='store_true',
            help='Delete existing demo users before creating new ones'
        )
        parser.add_argument(
            '--no-events',
            action='store_true',
            help='Skip creating sample events'
        )

    def handle(self, *args, **options):
        require_dev_environment('create_demo_users')
        from apps.authentication.models import User, Office, OfficeStaff
        from apps.event_management.models import Event

        office_name = options['office_name']
        reset = options['reset']
        create_events = not options['no_events']

        self.stdout.write(f'Creating demo users for "{office_name}"...')

        try:
            with transaction.atomic():
                # Reset if requested
                if reset:
                    self.stdout.write('Resetting existing demo data...')
                    try:
                        office = Office.objects.get(name=office_name)
                        User.objects.filter(office=office).delete()
                        OfficeStaff.objects.filter(office=office).delete()
                        Event.objects.filter(created_by__office=office).delete()
                        office.delete()
                        self.stdout.write(self.style.SUCCESS('Existing demo data deleted'))
                    except Office.DoesNotExist:
                        pass

                # Create or get office
                office, created = Office.objects.get_or_create(
                    name=office_name,
                    defaults={
                        'member_name': 'Rep. Demo Smith',
                        'district': 'XX-99',
                        'dc_office_address': '123 Capitol Building\nWashington, DC 20515',
                        'district_office_address': '456 Main Street\nHometown, XX 12345',
                        'is_setup_complete': True,
                        'setup_completed_at': timezone.now(),
                        'event_status_choices': settings.DEFAULT_EVENT_STATUS_CHOICES,
                        'event_type_choices': settings.DEFAULT_EVENT_TYPE_CHOICES,
                        'event_format_choices': settings.DEFAULT_EVENT_FORMAT_CHOICES,
                        'default_tags': [],
                    }
                )

                if created:
                    self.stdout.write(self.style.SUCCESS(f'Created office: {office_name}'))
                else:
                    self.stdout.write(f'Using existing office: {office_name}')

                # Ensure the office has its default roles (Admin/Scheduler/Staff)
                office.create_default_roles()

                # Create staff profiles
                staff_profiles = self._create_staff_profiles(office)

                # Create users
                users = self._create_users(office, staff_profiles)

                # Create sample events
                if create_events:
                    self._create_sample_events(office, users)

                # Summary
                self.stdout.write('')
                self.stdout.write(self.style.SUCCESS('Demo users created successfully!'))
                self.stdout.write('')
                self.stdout.write('Login credentials (password: demo123!):')
                self.stdout.write('-' * 50)

                for username, user_data in users.items():
                    role = user_data['role']
                    email = user_data['email']
                    self.stdout.write(f'  {username:15} {role:12} {email}')

                self.stdout.write('')
                self.stdout.write('To test role-based permissions:')
                self.stdout.write('  - Admin: Full access, can manage roles')
                self.stdout.write('  - Scheduler: Can change status, approve suggestions')
                self.stdout.write('  - Staff: Limited access, edits require review')

        except Exception as e:
            raise CommandError(f'Error creating demo users: {e}')

    def _create_staff_profiles(self, office):
        """Create staff profiles for the demo office."""
        from apps.authentication.models import OfficeStaff

        profiles = {}
        staff_data = [
            {
                'name': 'Samuel Cook',
                'position': 'Chief of Staff',
                'email': 'admin@demo.example.com',
                'phone': '202-555-0001',
                'legislative_areas': ['Policy', 'Administration'],
            },
            {
                'name': 'Sam Scheduler',
                'position': 'Scheduler',
                'email': 'scheduler1@demo.example.com',
                'phone': '202-555-0002',
                'legislative_areas': ['Scheduling'],
            },
            {
                'name': 'Sara Scheduler',
                'position': 'Deputy Scheduler',
                'email': 'scheduler2@demo.example.com',
                'phone': '202-555-0003',
                'legislative_areas': ['Scheduling', 'Correspondence'],
            },
            {
                'name': 'Taylor Staff',
                'position': 'Legislative Assistant',
                'email': 'staff1@demo.example.com',
                'phone': '202-555-0004',
                'legislative_areas': ['Healthcare', 'Education'],
            },
            {
                'name': 'Jordan Staff',
                'position': 'Legislative Assistant',
                'email': 'staff2@demo.example.com',
                'phone': '202-555-0005',
                'legislative_areas': ['Defense', 'Veterans Affairs'],
            },
            {
                'name': 'Casey Staff',
                'position': 'Legislative Correspondent',
                'email': 'staff3@demo.example.com',
                'phone': '202-555-0006',
                'legislative_areas': ['Environment', 'Energy'],
            },
        ]

        for i, data in enumerate(staff_data):
            profile, created = OfficeStaff.objects.get_or_create(
                office=office,
                email=data['email'],
                defaults={
                    'name': data['name'],
                    'position': data['position'],
                    'phone': data['phone'],
                    'legislative_areas': data['legislative_areas'],
                    'order': i,
                    'is_active': True,
                }
            )

            profiles[data['email']] = profile

            if created:
                self.stdout.write(f'  Created staff profile: {data["name"]}')

        return profiles

    def _create_users(self, office, staff_profiles):
        """Create demo users with different roles."""
        from apps.authentication.models import User

        users = {}
        user_data = [
            # Admin
            {
                'username': 'demo_admin',
                'email': 'admin@demo.example.com',
                'first_name': 'Samuel',
                'last_name': 'Cook',
                'role': 'admin',
            },
            # Schedulers
            {
                'username': 'demo_scheduler1',
                'email': 'scheduler1@demo.example.com',
                'first_name': 'Sam',
                'last_name': 'Scheduler',
                'role': 'scheduler',
            },
            {
                'username': 'demo_scheduler2',
                'email': 'scheduler2@demo.example.com',
                'first_name': 'Sara',
                'last_name': 'Scheduler',
                'role': 'scheduler',
            },
            # Staff
            {
                'username': 'demo_staff1',
                'email': 'staff1@demo.example.com',
                'first_name': 'Taylor',
                'last_name': 'Staff',
                'role': 'staff',
            },
            {
                'username': 'demo_staff2',
                'email': 'staff2@demo.example.com',
                'first_name': 'Jordan',
                'last_name': 'Staff',
                'role': 'staff',
            },
            {
                'username': 'demo_staff3',
                'email': 'staff3@demo.example.com',
                'first_name': 'Casey',
                'last_name': 'Staff',
                'role': 'staff',
            },
        ]

        # Map role slug -> Role for this office (source of truth for permissions)
        from apps.authentication.models import Role
        roles_by_slug = {r.slug: r for r in Role.objects.filter(office=office)}

        for data in user_data:
            role_obj = roles_by_slug.get(data['role']) or roles_by_slug.get('staff')
            user, created = User.objects.get_or_create(
                username=data['username'],
                defaults={
                    'email': data['email'],
                    'first_name': data['first_name'],
                    'last_name': data['last_name'],
                    'role': data['role'],
                    'office_role': role_obj,
                    'office': office,
                    'staff_profile': staff_profiles.get(data['email']),
                }
            )

            if created:
                user.set_password('demo123!')
                user.save()
                self.stdout.write(f'  Created user: {data["username"]} ({data["role"]})')
            else:
                # Update existing user
                user.assign_role(role_obj)
                user.office = office
                user.staff_profile = staff_profiles.get(data['email'])
                user.save()

            users[data['username']] = {
                'user': user,
                'role': data['role'],
                'email': data['email'],
            }

        return users

    def _create_sample_events(self, office, users):
        """Create sample events with approval routing for testing."""
        from apps.event_management.models import Event

        admin_user = users['demo_admin']['user']
        today = date.today()

        # Sample events with different configurations
        events_data = [
            {
                'title': 'Healthcare Roundtable',
                'type': 'event',
                'format': 'in_person',
                'group': 'American Medical Association',
                'description': 'Discussion on healthcare policy priorities',
                'start_date': today + timedelta(days=7),
                'start_time': time(10, 0),
                'end_time': time(12, 0),
                'location': 'Rayburn HOB Room 2154',
                'legislative_topics': ['Healthcare', 'Insurance'],
                'staff': [
                    {'name': 'Taylor Staff', 'email': 'staff1@demo.example.com'}
                ],
                'status': 'received',
            },
            {
                'title': 'Veterans Town Hall',
                'type': 'event',
                'format': 'hybrid',
                'group': 'Veterans of Foreign Wars',
                'description': 'Town hall with local veterans',
                'start_date': today + timedelta(days=14),
                'start_time': time(14, 0),
                'end_time': time(16, 0),
                'location': 'District Office',
                'legislative_topics': ['Veterans Affairs', 'Defense'],
                'staff': [
                    {'name': 'Jordan Staff', 'email': 'staff2@demo.example.com'}
                ],
                'status': 'tentative',
            },
            {
                'title': 'Climate Action Coalition Meeting',
                'type': 'meeting',
                'format': 'virtual',
                'group': 'Climate Action Coalition',
                'description': 'Virtual meeting to discuss climate legislation',
                'start_date': today + timedelta(days=3),
                'start_time': time(15, 0),
                'end_time': time(16, 0),
                'location': 'Zoom',
                'legislative_topics': ['Environment', 'Energy'],
                'staff': [
                    {'name': 'Casey Staff', 'email': 'staff3@demo.example.com'}
                ],
                'status': 'confirmed',
            },
            {
                'title': 'Unassigned Event (for suggestion testing)',
                'type': 'event',
                'format': 'in_person',
                'group': 'Community Group',
                'description': 'This event has no staff assigned - edits by staff will create suggestions',
                'start_date': today + timedelta(days=10),
                'start_time': time(9, 0),
                'end_time': time(10, 0),
                'location': 'Capitol Visitor Center',
                'legislative_topics': ['General'],
                'staff': [],  # No staff assigned
                'status': 'received',
            },
            {
                'title': 'Event with Approval Routing',
                'type': 'event',
                'format': 'in_person',
                'group': 'Important Stakeholder',
                'description': 'This event has approval routing configured',
                'start_date': today + timedelta(days=21),
                'start_time': time(11, 0),
                'end_time': time(12, 0),
                'location': 'DC Office',
                'legislative_topics': ['Policy'],
                'staff': [
                    {'name': 'Taylor Staff', 'email': 'staff1@demo.example.com'}
                ],
                'status': 'tentative',
                'approval_routing': {
                    'version': 1,
                    'stages': [
                        {
                            'stage_id': 'stage-1',
                            'order': 1,
                            'type': 'parallel',
                            'approvers': [
                                {
                                    'user_id': str(users['demo_scheduler1']['user'].id),
                                    'name': 'Sam Scheduler',
                                    'required': True
                                },
                                {
                                    'user_id': str(users['demo_scheduler2']['user'].id),
                                    'name': 'Sara Scheduler',
                                    'required': True
                                }
                            ],
                            'all_required': True
                        },
                        {
                            'stage_id': 'stage-2',
                            'order': 2,
                            'type': 'sequential',
                            'approvers': [
                                {
                                    'user_id': str(users['demo_admin']['user'].id),
                                    'name': 'Samuel Cook',
                                    'required': True
                                }
                            ]
                        }
                    ]
                },
            },
        ]

        created_count = 0
        for data in events_data:
            # Check if event already exists
            existing = Event.objects.filter(
                title=data['title'],
                created_by__office=office
            ).first()

            if existing:
                continue

            event = Event.objects.create(
                title=data['title'],
                type=data['type'],
                format=data['format'],
                description=data['description'],
                start_date=data['start_date'],
                start_time=data['start_time'],
                end_time=data.get('end_time'),
                end_date=data['start_date'],
                location=data['location'],
                legislative_topics=data.get('legislative_topics', []),
                staff=data.get('staff', []),
                status=data.get('status', 'received'),
                approval_routing=data.get('approval_routing', {}),
                created_by=admin_user,
                modified_by=admin_user,
            )

            from apps.contacts.services import attach_contact_org_to_event
            attach_contact_org_to_event(
                event,
                name='',
                email='',
                phone='',
                group=data['group'],
                user=admin_user,
            )

            # Initialize approval records if routing exists
            if data.get('approval_routing'):
                from apps.api.services import ApprovalRoutingService
                service = ApprovalRoutingService()
                service.initialize_approvals(event)

            created_count += 1

        if created_count > 0:
            self.stdout.write(f'  Created {created_count} sample events')
        else:
            self.stdout.write('  Sample events already exist')
