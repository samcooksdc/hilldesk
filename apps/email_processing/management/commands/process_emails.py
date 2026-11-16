# SPDX-License-Identifier: Apache-2.0
"""Management command to drive the email ingestion sweep.

Replaces the old per-user polling command. Triggers a reconciliation sweep over
the configured SCHEDULING_MAILBOXES (or a single mailbox) and can report
ingestion status. Runs the sweep synchronously (in-process) by default so it is
usable without a Celery worker; pass --async to enqueue instead.
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.email_processing.models import RawMessage, SubscriptionState
from apps.email_processing.tasks.reception import sweep_mailbox


class Command(BaseCommand):
    help = 'Run the email ingestion reconciliation sweep'

    def add_arguments(self, parser):
        parser.add_argument(
            '--mailbox', type=str,
            help='Sweep a single mailbox (defaults to all SCHEDULING_MAILBOXES)'
        )
        parser.add_argument(
            '--async', action='store_true', dest='is_async',
            help='Enqueue the sweep via Celery instead of running it in-process'
        )
        parser.add_argument(
            '--status', action='store_true',
            help='Show ingestion status instead of sweeping'
        )

    def handle(self, *args, **options):
        if options.get('status'):
            self._show_status()
            return

        mailbox = options.get('mailbox')
        is_async = options.get('is_async')

        if mailbox:
            targets = [mailbox]
        else:
            targets = getattr(settings, 'SCHEDULING_MAILBOXES', []) or []
            if not targets:
                raise CommandError(
                    'No SCHEDULING_MAILBOXES configured. Set the env var or pass --mailbox.'
                )

        for mb in targets:
            if is_async:
                sweep_mailbox.delay(mb)
                self.stdout.write(f"Queued sweep for {mb}")
            else:
                result = sweep_mailbox(mb)
                self.stdout.write(
                    f"{mb}: ingested={result['ingested']} gaps={result['gaps']} "
                    f"fallback={result['fallback']}"
                )
        self.stdout.write(self.style.SUCCESS(f"Sweep dispatched for {len(targets)} mailbox(es)"))

    def _show_status(self):
        self.stdout.write("\nIngestion status:")
        self.stdout.write(f"  Raw messages stored: {RawMessage.objects.count()}")
        self.stdout.write(f"  With calendar part:  {RawMessage.objects.filter(has_calendar_part=True).count()}")
        self.stdout.write("\nPer-mailbox subscription/sweep state:")
        for state in SubscriptionState.objects.all():
            self.stdout.write(
                f"  {state.mailbox}: status={state.status} "
                f"last_sweep={state.last_sweep_at} expires={state.expires_at}"
            )
        if not SubscriptionState.objects.exists():
            self.stdout.write("  (none yet — run a sweep first)")
