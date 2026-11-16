# SPDX-License-Identifier: Apache-2.0
"""
Management command to sync existing EmailProcessing records to their associated events
using the new attached_emails field.
"""

from django.core.management.base import BaseCommand
from apps.email_processing.services import EmailIntegrationService


class Command(BaseCommand):
    help = 'Sync existing EmailProcessing records to their associated events using attached_emails field'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be synced without making changes',
        )
    
    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        if dry_run:
            self.stdout.write(
                self.style.WARNING('DRY RUN MODE - No changes will be made')
            )
        
        self.stdout.write('Starting email sync to events...')
        
        if not dry_run:
            processed_count, error_count = EmailIntegrationService.sync_existing_emails_to_events()
            
            self.stdout.write(
                self.style.SUCCESS(
                    f'Sync completed: {processed_count} emails synced, {error_count} errors'
                )
            )
        else:
            # For dry run, just count what would be processed
            from apps.email_processing.models import EmailProcessing
            
            email_processings = EmailProcessing.objects.filter(
                event__isnull=False,
                status='verified'
            ).select_related('event')
            
            count_to_sync = 0
            for email_processing in email_processings:
                event = email_processing.event
                email_already_attached = any(
                    email.get('email_id') == email_processing.email_id 
                    for email in event.attached_emails
                )
                
                if not email_already_attached:
                    count_to_sync += 1
                    self.stdout.write(
                        f'Would sync: {email_processing.email_id} -> Event {event.id}'
                    )
            
            self.stdout.write(
                self.style.SUCCESS(
                    f'DRY RUN: Would sync {count_to_sync} emails to events'
                )
            )