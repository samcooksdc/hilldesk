# SPDX-License-Identifier: Apache-2.0
from django.apps import AppConfig


class AuthenticationConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.authentication'
    verbose_name = 'Authentication and Security'
    
    def ready(self):
        """Initialize app and register signals."""
        # Detach Django's default update_last_login receiver so our first-login
        # handler in signals.py sees user.last_login == None and can branch on
        # it. We reconnect update_last_login immediately after, leaving it as
        # the LAST receiver for user_logged_in.
        from django.contrib.auth.signals import user_logged_in
        from django.contrib.auth.models import update_last_login

        user_logged_in.disconnect(update_last_login)
        import apps.authentication.signals  # noqa: F401
        user_logged_in.connect(update_last_login)
