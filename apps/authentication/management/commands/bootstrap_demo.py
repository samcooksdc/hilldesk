# SPDX-License-Identifier: Apache-2.0
"""
One command for a working demo: migrate, then seed the fictional demo office,
its events and a batch of simulated inbound mail (mock AI provider).

    python manage.py bootstrap_demo            # full demo
    python manage.py bootstrap_demo --no-mail  # skip the ingestion simulation

Development only: refuses to run unless DEBUG=True. Re-running resets the
demo office to a clean state.
"""
import runpy
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandParser

from apps.authentication.devtools import require_dev_environment

SCRIPTS_DIR = Path(settings.BASE_DIR) / 'scripts'
STEPS = (
    ('Creating demo office and accounts', 'create_demo_office.py'),
    ('Populating demo events', 'populate_office_demo_info.py'),
)
MAIL_STEP = ('Simulating inbound email', 'simulate_email_ingestion.py')


class Command(BaseCommand):
    help = 'Migrate and seed the fictional demo office (DEBUG only)'

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument('--no-mail', action='store_true',
                            help='Skip the simulated email ingestion step')

    def handle(self, *args: Any, **options: Any) -> None:
        require_dev_environment('bootstrap_demo')

        self.stdout.write(self.style.MIGRATE_HEADING('Applying migrations'))
        call_command('migrate', interactive=False, verbosity=0)

        steps = list(STEPS) if options['no_mail'] else [*STEPS, MAIL_STEP]
        for label, script in steps:
            self.stdout.write(self.style.MIGRATE_HEADING(label))
            runpy.run_path(str(SCRIPTS_DIR / script), run_name='__main__')

        self.stdout.write(self.style.SUCCESS(
            '\nDemo ready. Run "python manage.py runserver" and sign in as '
            '"samuel" with password "demo".'
        ))
