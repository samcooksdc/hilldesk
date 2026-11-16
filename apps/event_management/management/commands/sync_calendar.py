# SPDX-License-Identifier: Apache-2.0
"""
Management command to synchronize events with Outlook calendar.

This command can be used to manually sync events to calendar, useful for
initial setup or recovering from sync failures.
"""

from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django.db.models import Q

from apps.event_management.models import Event
from apps.email_processing.calendar_service import CalendarService

User = get_user_model()


class Command(BaseCommand):
    help = 'Synchronize events with Outlook calendar'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--user-email',
            type=str,
            help='Email address of the user to sync events for'
        )
        
        parser.add_argument(
            '--event-id',
            type=str,
            help='Specific event ID to sync (UUID format)'
        )
        
        parser.add_argument(
            '--unsynced-only',
            action='store_true',
            help='Only sync events that have not been synced to calendar yet'
        )
        
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force sync even for events with existing calendar event IDs'
        )
        
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be synced without actually syncing'
        )
    
    def handle(self, *args, **options):
        """Handle the command execution."""
        user_email = options.get('user_email')
        event_id = options.get('event_id')
        unsynced_only = options.get('unsynced_only', False)
        force = options.get('force', False)
        dry_run = options.get('dry_run', False)
        
        # Build query for events to sync
        query = Q()
        
        # Filter by user if specified
        if user_email:
            try:
                user = User.objects.get(email=user_email)
                query &= Q(created_by=user)
            except User.DoesNotExist:
                raise CommandError(f"User with email '{user_email}' not found")
        
        # Filter by specific event if specified
        if event_id:
            query &= Q(id=event_id)
        
        # Filter unsynced events if requested
        if unsynced_only and not force:
            query &= Q(outlook_calendar_event_id__isnull=True) | Q(outlook_calendar_event_id='')
        
        # Exclude events that shouldn't be synced
        query &= ~Q(status__in=['rejected', 'canceled', 'passed'])
        
        # Get events to sync
        events = Event.objects.filter(query).select_related('created_by')
        
        if not events.exists():
            self.stdout.write(
                self.style.WARNING('No events found matching the criteria')
            )
            return
        
        self.stdout.write(
            f"Found {events.count()} event(s) to sync"
        )
        
        if dry_run:
            self.stdout.write(
                self.style.WARNING("DRY RUN - No actual syncing will be performed")
            )
            for event in events:
                user_email = event.created_by.email if event.created_by else 'Unknown'
                sync_status = "UPDATE" if event.outlook_calendar_event_id else "CREATE"
                self.stdout.write(
                    f"  [{sync_status}] Event {event.id} - {event.type} with {event.group} "
                    f"(User: {user_email})"
                )
            return
        
        # Group events by user for efficient processing
        events_by_user = {}
        for event in events:
            if not event.created_by or not event.created_by.email:
                self.stdout.write(
                    self.style.WARNING(
                        f"Skipping event {event.id}: no user email available"
                    )
                )
                continue
            
            user_email = event.created_by.email
            if user_email not in events_by_user:
                events_by_user[user_email] = []
            events_by_user[user_email].append(event)
        
        # Sync events for each user
        total_synced = 0
        total_failed = 0
        
        for user_email, user_events in events_by_user.items():
            self.stdout.write(f"\nSyncing {len(user_events)} events for {user_email}...")
            
            try:
                service = CalendarService(user_email)
                results = service.bulk_sync_events(user_events)
                
                total_synced += results['synced']
                total_failed += results['failed']
                
                self.stdout.write(
                    f"  Synced: {results['synced']}, Failed: {results['failed']}"
                )
                
                # Show errors if any
                for error in results['errors']:
                    self.stdout.write(
                        self.style.ERROR(
                            f"  Error syncing event {error['event_id']}: {error['error']}"
                        )
                    )
                    
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f"  Failed to sync events for {user_email}: {e}")
                )
                total_failed += len(user_events)
        
        # Summary
        self.stdout.write(
            self.style.SUCCESS(
                f"\nSync completed: {total_synced} synced, {total_failed} failed"
            )
        )
        
        if total_failed > 0:
            self.stdout.write(
                self.style.WARNING(
                    "Some events failed to sync. Check the logs for more details."
                )
            )