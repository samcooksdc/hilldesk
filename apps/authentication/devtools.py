# SPDX-License-Identifier: Apache-2.0
"""
Guards for development-only tooling.

Demo/seed commands create superusers with shared, documented passwords and
wipe office data. They must never run against a real deployment, so every
such command or script calls ``require_dev_environment()`` before doing
anything.
"""
from django.conf import settings
from django.core.management.base import CommandError


def require_dev_environment(tool_name: str) -> None:
    """Abort unless the project is running with ``DEBUG=True``.

    Raises:
        CommandError: when ``settings.DEBUG`` is false (production/staging).
    """
    if not getattr(settings, 'DEBUG', False):
        raise CommandError(
            f"{tool_name} is a development-only tool and refuses to run when "
            f"DEBUG is False. It creates demo accounts with shared passwords "
            f"and may wipe office data."
        )
