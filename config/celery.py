# SPDX-License-Identifier: Apache-2.0
"""
Celery configuration for HillDesk.
"""

import os
from celery import Celery
from django.conf import settings

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')

app = Celery('congressional_scheduling')

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules from all registered Django apps.
app.autodiscover_tasks()

# Celery Beat Schedule for periodic tasks
app.conf.beat_schedule = {
    # Ingestion reconciliation sweep — the always-on front door. Replaces the
    # old per-user hourly polling; runs only over SCHEDULING_MAILBOXES.
    'ingestion-sweep': {
        'task': 'apps.email_processing.tasks.reception.ingestion_sweep',
        'schedule': float(getattr(settings, 'INGEST_SWEEP_MINUTES', 5)) * 60.0,
    },
    # Webhook subscription lifecycle (create/renew). No-op unless
    # GRAPH_WEBHOOK_ENABLED; runs every 15 minutes so renewals land well inside
    # the 24h window.
    'manage-subscriptions': {
        'task': 'apps.email_processing.tasks.reception.manage_subscriptions',
        'schedule': 900.0,
    },
    # Roll active event-series occurrence horizons forward (materialization is
    # idempotent; monthly cadence per the ingestion spec §3.3).
    'extend-series-horizon': {
        'task': 'apps.event_management.tasks.extend_series_horizon',
        'schedule': 30 * 24 * 3600.0,
    },
    # Weekly divert re-scoring: promote diverted mail that current anchors /
    # reputation now score pass-forward (divert-store safety must not depend
    # on a human scanning it).
    'rescore-diverted': {
        'task': 'apps.email_processing.tasks.rescoring.rescore_diverted',
        'schedule': 7 * 24 * 3600.0,
    },
    # Refresh House floor schedule every 30 minutes; XML is republished multiple
    # times per day when the House is in session.
    'refresh-house-floor-schedule': {
        'task': 'apps.event_management.tasks.fetch_house_floor_schedule',
        'schedule': 1800.0,
    },
    # Live floor proceedings change action-by-action while the House is in
    # session, so poll the Clerk's feed more often.
    'refresh-house-floor-proceedings': {
        'task': 'apps.event_management.tasks.fetch_house_floor_proceedings',
        'schedule': 300.0,  # every 5 minutes
    },
}

app.conf.timezone = 'America/New_York'

@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')