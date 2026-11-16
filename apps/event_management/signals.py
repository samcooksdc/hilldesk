# SPDX-License-Identifier: Apache-2.0
"""
Django signals for automatic calendar synchronization.

This module handles automatic synchronization of events with Outlook calendar
when events are created, updated, or deleted in the application.
"""

import logging
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.conf import settings

from .models import Event, EventAttachmentVersion
from apps.email_processing.calendar_service import CalendarService, CalendarSyncError

# Alias for backward compatibility with tests
CalendarIntegrationService = CalendarService

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Event)
def sync_event_to_calendar_on_save(sender, instance, created, **kwargs):
    """
    Automatically sync event to Outlook calendar when saved.
    
    Args:
        sender: The Event model class
        instance: The Event instance being saved
        created: Boolean indicating if this is a new instance
        **kwargs: Additional keyword arguments
    """
    # Skip sync if calendar integration is disabled
    if not getattr(settings, 'ENABLE_CALENDAR_SYNC', True):
        return

    # The calendar service itself saves the Outlook id after create/update.
    # That bookkeeping save must not trigger a second (redundant) Graph call.
    update_fields = kwargs.get('update_fields')
    if update_fields and set(update_fields) <= {'outlook_calendar_event_id', 'modified'}:
        return

    # Skip sync if no user email available
    if not instance.created_by or not instance.created_by.email:
        logger.warning(f"Skipping calendar sync for event {instance.id}: no user email")
        return

    # Archived (soft-deleted) events must be REMOVED from the calendar, not
    # synced. This mirrors the old hard-delete behaviour: a deleted event should
    # not linger on the user's Outlook calendar. Restoring the event re-syncs it.
    if instance.is_archived:
        if instance.outlook_calendar_event_id:
            try:
                service = CalendarService(instance.created_by.email)
                # delete_calendar_event clears outlook_calendar_event_id and saves,
                # which re-fires this signal — but the id is then None, so we no-op.
                service.delete_calendar_event(instance)
                logger.info(f"Event {instance.id} removed from calendar (archived)")
            except CalendarSyncError as e:
                logger.error(f"Failed to remove archived event {instance.id} from calendar: {e}")
            except Exception as e:
                logger.error(f"Unexpected error removing archived event {instance.id} from calendar: {e}")
        return

    # Skip sync for events that are not scheduled or confirmed
    if instance.status in ['rejected', 'canceled', 'passed']:
        logger.info(f"Skipping calendar sync for event {instance.id}: status is {instance.status}")
        return
    
    try:
        service = CalendarService(instance.created_by.email)
        calendar_event_id = service.sync_event_to_calendar(instance)
        
        if created:
            logger.info(f"Event {instance.id} created and synced to calendar: {calendar_event_id}")
        else:
            logger.info(f"Event {instance.id} updated and synced to calendar: {calendar_event_id}")
            
    except CalendarSyncError as e:
        logger.error(f"Failed to sync event {instance.id} to calendar: {e}")
        # Don't raise the exception to avoid breaking the save operation
    except Exception as e:
        logger.error(f"Unexpected error syncing event {instance.id} to calendar: {e}")


@receiver(post_delete, sender=Event)
def delete_event_from_calendar_on_delete(sender, instance, **kwargs):
    """
    Automatically delete event from Outlook calendar when deleted.
    
    Args:
        sender: The Event model class
        instance: The Event instance being deleted
        **kwargs: Additional keyword arguments
    """
    # Skip sync if calendar integration is disabled
    if not getattr(settings, 'ENABLE_CALENDAR_SYNC', True):
        return
    
    # Skip if no calendar event ID
    if not instance.outlook_calendar_event_id:
        return
    
    # Skip if no user email available
    if not instance.created_by or not instance.created_by.email:
        logger.warning(f"Skipping calendar deletion for event {instance.id}: no user email")
        return
    
    try:
        service = CalendarService(instance.created_by.email)
        service.delete_calendar_event(instance)
        
        logger.info(f"Event {instance.id} deleted from calendar")
        
    except CalendarSyncError as e:
        logger.error(f"Failed to delete event {instance.id} from calendar: {e}")
        # Don't raise the exception to avoid breaking the delete operation
    except Exception as e:
        logger.error(f"Unexpected error deleting event {instance.id} from calendar: {e}")


@receiver(post_delete, sender=EventAttachmentVersion)
def delete_attachment_file_on_delete(sender, instance, **kwargs):
    """Remove the underlying file blob when an attachment version row is deleted.

    Deleting an Event cascades to EventAttachment and its versions, but Django
    does not remove the stored files (S3 object or local blob). Without this the
    storage backend accumulates orphaned files — a cost and a data-retention
    concern for a system holding constituent PII. ``save=False`` avoids touching
    the row that is already being deleted.
    """
    if not instance.file:
        return
    try:
        instance.file.delete(save=False)
        logger.info(f"Deleted attachment file for version {instance.id}")
    except Exception as e:
        # Never let storage cleanup break the delete operation.
        logger.error(f"Failed to delete attachment file for version {instance.id}: {e}")