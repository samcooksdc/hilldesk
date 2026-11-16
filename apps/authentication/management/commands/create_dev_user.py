# SPDX-License-Identifier: Apache-2.0
"""
Management command to create (or reset) a local development superuser.

Credentials come from the environment, never from source:

    DJANGO_DEV_USERNAME   (default: "dev")
    DJANGO_DEV_EMAIL      (default: "<username>@example.com")
    DJANGO_DEV_PASSWORD   (required; prompted for if unset and interactive)

Refuses to run unless DEBUG=True.
"""
import getpass
import os
import sys
from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.authentication.devtools import require_dev_environment

User = get_user_model()


class Command(BaseCommand):
    help = 'Create or reset a local development superuser (DEBUG only)'

    def handle(self, *args: Any, **options: Any) -> None:
        require_dev_environment('create_dev_user')

        username = os.environ.get('DJANGO_DEV_USERNAME', 'dev')
        email = os.environ.get('DJANGO_DEV_EMAIL', f'{username}@example.com')
        password = os.environ.get('DJANGO_DEV_PASSWORD')

        if not password:
            if not sys.stdin.isatty():
                raise CommandError(
                    'Set DJANGO_DEV_PASSWORD (or run interactively to be prompted).'
                )
            password = getpass.getpass(f'Password for {username}: ')
            if not password:
                raise CommandError('A password is required.')

        user = User.objects.filter(username=username).first()
        if user:
            user.set_password(password)
            user.is_active = True
            user.is_staff = True
            user.is_superuser = True
            user.save()
            self.stdout.write(self.style.SUCCESS(f'Updated existing user: {username}'))
        else:
            User.objects.create_superuser(username=username, email=email, password=password)
            self.stdout.write(self.style.SUCCESS(f'Created new superuser: {username}'))
