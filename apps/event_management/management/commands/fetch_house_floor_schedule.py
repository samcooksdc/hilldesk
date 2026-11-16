# SPDX-License-Identifier: Apache-2.0
"""
Management command to fetch the docs.house.gov 'Bills This Week' floor schedule.

Useful in development (where Celery beat isn't running) and for one-off backfills.
"""

from datetime import date

from django.core.management.base import BaseCommand, CommandError

from apps.event_management.services.house_floor_service import (
    fetch_and_store,
    monday_of,
)


class Command(BaseCommand):
    help = "Fetch this week's House floor schedule from docs.house.gov and store it."

    def add_arguments(self, parser):
        parser.add_argument(
            '--week',
            type=str,
            default=None,
            help='Target week as YYYY-MM-DD. Any day in the week works; the Monday is computed. Defaults to current week.',
        )

    def handle(self, *args, **options):
        week_arg = options.get('week')
        if week_arg:
            try:
                target = monday_of(date.fromisoformat(week_arg))
            except ValueError as exc:
                raise CommandError(f'Invalid --week value: {exc}')
        else:
            target = None

        schedule = fetch_and_store(target)
        if schedule is None:
            self.stdout.write(self.style.WARNING(
                'No schedule published for that week (404). Nothing stored.'
            ))
            return

        count = schedule.items.count()
        self.stdout.write(self.style.SUCCESS(
            f'Stored {count} floor item(s) for week of {schedule.week_date}.'
        ))
