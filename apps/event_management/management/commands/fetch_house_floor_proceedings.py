# SPDX-License-Identifier: Apache-2.0
"""
Management command to fetch the Clerk's live House floor proceedings feed.

Useful in development (where Celery beat isn't running) and for one-off backfills.
"""

from datetime import date

from django.core.management.base import BaseCommand, CommandError

from apps.event_management.services.house_floor_proceedings_service import (
    fetch_and_store,
)


class Command(BaseCommand):
    help = "Fetch the latest House floor proceedings from clerk.house.gov and store them."

    def add_arguments(self, parser):
        parser.add_argument(
            '--day',
            type=str,
            default=None,
            help='Target legislative day as YYYY-MM-DD. Defaults to today; walks '
                 'back to the most recent published day if that file is missing.',
        )

    def handle(self, *args, **options):
        day_arg = options.get('day')
        if day_arg:
            try:
                target = date.fromisoformat(day_arg)
            except ValueError as exc:
                raise CommandError(f'Invalid --day value: {exc}')
        else:
            target = None

        proceedings = fetch_and_store(target)
        if proceedings is None:
            self.stdout.write(self.style.WARNING(
                'No floor proceedings found for that day (or recent days). Nothing stored.'
            ))
            return

        count = proceedings.actions.count()
        self.stdout.write(self.style.SUCCESS(
            f'Stored {count} floor action(s) for {proceedings.legislative_day}.'
        ))
