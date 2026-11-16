# SPDX-License-Identifier: Apache-2.0
"""
Celery tasks for event management — currently export generation.

In development, CELERY_TASK_ALWAYS_EAGER = True runs tasks synchronously.
"""

import logging
import uuid

from celery import shared_task
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

logger = logging.getLogger('apps.event_management')


@shared_task(bind=True, max_retries=2, soft_time_limit=300)
def generate_export_async(
    self,
    template_type: str,
    event_ids: list,
    office_id: str | None = None,
    template_id: str | None = None,
    target_date: str | None = None,
    active_filters: list | None = None,
):
    """
    Generate a .docx export asynchronously for large result sets.

    Args:
        template_type: One of daily_briefing, weekly_overview, event_detail, filtered_list
        event_ids: List of Event UUID strings
        office_id: Office UUID string (optional)
        template_id: Specific ExportTemplate UUID string (optional)
        target_date: ISO date string for daily/weekly exports (optional)
        active_filters: List of human-readable filter strings (optional)

    Returns:
        dict with 'status' and 'file_path' keys
    """
    from datetime import date as date_type

    from apps.authentication.models import Office
    from apps.event_management.models import Event
    from apps.event_management.services.export_service import ExportService

    try:
        # Resolve objects
        queryset = Event.objects.filter(id__in=event_ids).order_by('start_date', 'start_time')

        office = None
        if office_id:
            try:
                office = Office.objects.get(id=office_id)
            except Office.DoesNotExist:
                pass

        parsed_date = None
        if target_date:
            parsed_date = date_type.fromisoformat(target_date)

        # Render
        service = ExportService()
        docx_bytes = service.render_docx(
            template_type=template_type,
            queryset=queryset,
            office=office,
            template_id=template_id,
            target_date=parsed_date,
            active_filters=active_filters,
        )

        # Save to storage
        task_id = self.request.id or str(uuid.uuid4())
        file_path = f'exports/{task_id}.docx'
        default_storage.save(file_path, ContentFile(docx_bytes))

        logger.info(f'Export task {task_id} completed: {file_path} ({len(docx_bytes)} bytes)')

        return {
            'status': 'complete',
            'file_path': file_path,
            'size_bytes': len(docx_bytes),
        }

    except Exception as exc:
        logger.error(f'Export task failed: {exc}', exc_info=True)
        raise self.retry(exc=exc, countdown=30)


@shared_task(bind=True, max_retries=3, soft_time_limit=60)
def fetch_house_floor_schedule(self, week_date: str | None = None):
    """
    Pull the docs.house.gov 'Bills This Week' XML and upsert the schedule.

    Args:
        week_date: ISO date string for the Monday of the target week. Defaults
            to the Monday of the current local date.

    Returns:
        dict with status and (when available) week_date / item count.
    """
    from datetime import date as date_type

    from apps.event_management.services.house_floor_service import (
        fetch_and_store,
        monday_of,
    )

    try:
        if week_date:
            target_monday = monday_of(date_type.fromisoformat(week_date))
        else:
            target_monday = None

        schedule = fetch_and_store(target_monday)
        if schedule is None:
            return {'status': 'no_schedule'}
        return {
            'status': 'ok',
            'week_date': schedule.week_date.isoformat(),
            'items': schedule.items.count(),
        }
    except Exception as exc:
        logger.error('House floor schedule fetch failed: %s', exc, exc_info=True)
        raise self.retry(exc=exc, countdown=120)


@shared_task(bind=True, max_retries=3, soft_time_limit=60)
def fetch_house_floor_proceedings(self, day: str | None = None):
    """
    Pull the Clerk's live floor proceedings XML (clerk.house.gov/floor/{date}.xml)
    and upsert the day's timestamped activity feed.

    Args:
        day: ISO date string for the target legislative day. Defaults to today;
            the service walks back to the most recent published day if needed.

    Returns:
        dict with status and (when available) legislative_day / action count.
    """
    from datetime import date as date_type

    from apps.event_management.services.house_floor_proceedings_service import (
        fetch_and_store as fetch_proceedings,
    )

    try:
        target = date_type.fromisoformat(day) if day else None
        proceedings = fetch_proceedings(target)
        if proceedings is None:
            return {'status': 'no_proceedings'}
        return {
            'status': 'ok',
            'legislative_day': proceedings.legislative_day.isoformat(),
            'actions': proceedings.actions.count(),
        }
    except Exception as exc:
        logger.error('House floor proceedings fetch failed: %s', exc, exc_info=True)
        raise self.retry(exc=exc, countdown=120)


@shared_task
def extend_series_horizon():
    """Monthly beat task: roll every active series' occurrence horizon forward
    (SERIES_HORIZON_DAYS from today). Materialization is idempotent, so this
    only fills the newly-visible window."""
    from apps.event_management.models import EventSeries

    extended = 0
    for series in EventSeries.objects.filter(is_active=True):
        try:
            created = series.materialize_occurrences()
            extended += 1
            if created:
                logger.info('Series %s horizon extended: %d occurrences created',
                            series.id, len(created))
        except Exception as exc:
            logger.error('Series %s horizon extension failed: %s', series.id, exc)
    return {'series_extended': extended}
