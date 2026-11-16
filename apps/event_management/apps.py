# SPDX-License-Identifier: Apache-2.0
from django.apps import AppConfig


class EventManagementConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.event_management'
    
    def ready(self):
        """Import signals when the app is ready."""
        # Side-effect import: registers the calendar-sync post_save handlers.
        import apps.event_management.signals  # noqa: F401
