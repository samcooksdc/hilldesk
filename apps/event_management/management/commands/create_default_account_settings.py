# SPDX-License-Identifier: Apache-2.0
"""
Management command to create default account event settings for existing users.
"""

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.conf import settings
from apps.event_management.models import AccountEventSettings

User = get_user_model()


class Command(BaseCommand):
    help = 'Create default account event settings for all existing users'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force update existing settings',
        )

    def handle(self, *args, **options):
        force = options['force']
        
        users = User.objects.all()
        created_count = 0
        updated_count = 0
        
        self.stdout.write(f"Processing {users.count()} users...")
        
        for user in users:
            settings_obj, created = AccountEventSettings.objects.get_or_create(
                user=user,
                defaults={
                    'event_format_choices': settings.DEFAULT_EVENT_FORMAT_CHOICES,
                    'event_duration_choices': settings.DEFAULT_EVENT_DURATION_CHOICES,
                    'reminder_time_choices': settings.DEFAULT_REMINDER_TIME_CHOICES,
                }
            )
            
            if created:
                created_count += 1
                self.stdout.write(f"Created settings for user: {user.username}")
            elif force:
                # Update existing settings with defaults
                settings_obj.event_format_choices = settings.DEFAULT_EVENT_FORMAT_CHOICES
                settings_obj.event_duration_choices = settings.DEFAULT_EVENT_DURATION_CHOICES
                settings_obj.reminder_time_choices = settings.DEFAULT_REMINDER_TIME_CHOICES
                settings_obj.save()
                updated_count += 1
                self.stdout.write(f"Updated settings for user: {user.username}")
        
        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully processed {users.count()} users. "
                f"Created: {created_count}, Updated: {updated_count}"
            )
        )