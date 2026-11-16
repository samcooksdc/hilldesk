# SPDX-License-Identifier: Apache-2.0
"""
Management command to clean up orphaned calendar events.

This command helps maintain calendar hygiene by removing calendar events
that no longer have corresponding events in the application.
"""

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

from apps.event_management.models import Event
from apps.email_processing.calendar_service import CalendarService, CalendarSyncError

User = get_user_model()


class Command(BaseCommand):
    help = 'Clean up orphaned calendar events'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--user-email',
            type=str,
            help='Email address of the user to clean up calendar for'
        )
        
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be cleaned up without actually doing it'
        )
        
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force cleanup without confirmation prompts'
        )
    
    def handle(self, *args, **options):
        """Handle the command execution."""
        user_email = options.get('user_email')
        dry_run = options.get('dry_run', False)
        force = options.get('force', False)
        
        if user_email:
            users = [user_email]
        else:
            # Get all users who have created events
            users = list(
                Event.objects.filter(created_by__isnull=False)
                .values_list('created_by__email', flat=True)
                .distinct()
            )
        
        if not users:
            self.stdout.write(
                self.style.WARNING('No users found with events')
            )
            return
        
        self.stdout.write(f"Checking calendar cleanup for {len(users)} user(s)")
        
        if dry_run:
            self.stdout.write(
                self.style.WARNING("DRY RUN - No actual cleanup will be performed")
            )
        
        total_cleaned = 0
        
        for user_email in users:
            if not user_email:
                continue
                
            self.stdout.write(f"\nChecking calendar for {user_email}...")
            
            try:
                # Get events with calendar event IDs for this user
                user_events = Event.objects.filter(
                    created_by__email=user_email,
                    outlook_calendar_event_id__isnull=False
                ).exclude(outlook_calendar_event_id='')
                
                if not user_events.exists():
                    self.stdout.write("  No events with calendar IDs found")
                    continue
                
                service = CalendarService(user_email)
                
                # Check each event's calendar status
                orphaned_events = []
                
                for event in user_events:
                    # For now, we'll just report events that have calendar IDs
                    # In a more advanced implementation, we could check if the
                    # calendar event actually exists in Outlook
                    
                    # Check if event should still be in calendar
                    if event.status in ['rejected', 'canceled', 'passed']:
                        orphaned_events.append(event)
                
                if not orphaned_events:
                    self.stdout.write("  No orphaned calendar events found")
                    continue
                
                self.stdout.write(
                    f"  Found {len(orphaned_events)} orphaned calendar event(s)"
                )
                
                if dry_run:
                    for event in orphaned_events:
                        self.stdout.write(
                            f"    Would remove: {event.id} - {event.type} with {event.group} "
                            f"(Status: {event.status})"
                        )
                    continue
                
                # Confirm cleanup unless force is used
                if not force:
                    confirm = input(
                        f"Remove {len(orphaned_events)} calendar events for {user_email}? (y/N): "
                    )
                    if confirm.lower() != 'y':
                        self.stdout.write("  Skipped")
                        continue
                
                # Clean up orphaned events
                cleaned_count = 0
                for event in orphaned_events:
                    try:
                        service.delete_calendar_event(event)
                        cleaned_count += 1
                        self.stdout.write(
                            f"    Removed: {event.id} - {event.type} with {event.group}"
                        )
                    except CalendarSyncError as e:
                        self.stdout.write(
                            self.style.ERROR(
                                f"    Failed to remove {event.id}: {e}"
                            )
                        )
                
                total_cleaned += cleaned_count
                self.stdout.write(f"  Cleaned up {cleaned_count} calendar events")
                
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f"  Error processing {user_email}: {e}")
                )
        
        # Summary
        if dry_run:
            self.stdout.write(
                self.style.SUCCESS(
                    "\nDry run completed. Found calendar events that could be cleaned up."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"\nCleanup completed: {total_cleaned} calendar events removed"
                )
            )