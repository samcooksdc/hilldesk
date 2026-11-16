# SPDX-License-Identifier: Apache-2.0
"""
Calendar integration service for HillDesk.
Handles synchronization between app events and Outlook calendar.
"""

import logging
from datetime import datetime, time as dt_time, timedelta
from html import escape
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Dict, List, Optional, Any
from django.utils import timezone
from django.db import transaction

from .graph_client import MicrosoftGraphClient, GraphAPIError
from apps.event_management.models import Event

logger = logging.getLogger('apps.email_processing')
security_logger = logging.getLogger('security_audit')


class CalendarSyncError(Exception):
    """Exception raised for calendar synchronization errors."""
    pass


class CalendarService:
    """
    Service for managing calendar integration with Microsoft Outlook.
    Handles creating, updating, and deleting calendar events.
    """
    
    def __init__(self, user_email: str = None):
        """
        Initialize calendar service.
        
        Args:
            user_email: Email address of the user for calendar operations
        """
        self.user_email = user_email
        self.graph_client = MicrosoftGraphClient()
    
    def create_calendar_event(self, event: Event) -> Optional[str]:
        """
        Create a calendar event in Outlook for the given app event.
        
        Args:
            event: Event model instance
            
        Returns:
            Outlook calendar event ID if successful, None otherwise
            
        Raises:
            CalendarSyncError: If calendar event creation fails
        """
        if not self.user_email:
            raise CalendarSyncError("User email not provided for calendar service")
        
        try:
            # Parse event time information
            start_time, end_time = self._parse_event_times(event)
            
            # Build event description
            description = self._build_event_description(event)
            
            # Create attendees list
            attendees = self._build_attendees_list(event)
            
            # Create calendar event via Graph API
            calendar_event = self.graph_client.create_calendar_event(
                user_id=self.user_email,
                subject=self._build_event_subject(event),
                start_time=start_time,
                end_time=end_time,
                location=event.location or 'TBD',
                body=description,
                attendees=attendees
            )
            
            outlook_event_id = calendar_event.get('id')
            
            if outlook_event_id:
                # Update the event with the Outlook calendar event ID
                with transaction.atomic():
                    event.outlook_calendar_event_id = outlook_event_id
                    event.save(update_fields=['outlook_calendar_event_id', 'modified'])
                
                security_logger.info(
                    'Calendar event created and synced',
                    extra={
                        'user_email': self.user_email,
                        'app_event_id': str(event.id),
                        'outlook_event_id': outlook_event_id,
                        'event_type': event.type,
                        'event_subject': (event.title or event.description or '')[:100],
                        'timestamp': timezone.now().isoformat(),
                    }
                )
                
                return outlook_event_id
            
        except GraphAPIError as e:
            logger.error(f"Failed to create calendar event for event {event.id}: {e}")
            raise CalendarSyncError(f"Calendar event creation failed: {e}")
        except Exception as e:
            logger.error(f"Unexpected error creating calendar event for event {event.id}: {e}")
            raise CalendarSyncError(f"Unexpected error: {e}")
        
        return None
    
    def update_calendar_event(self, event: Event) -> bool:
        """
        Update an existing calendar event in Outlook.
        
        Args:
            event: Event model instance with updated information
            
        Returns:
            True if update was successful, False otherwise
            
        Raises:
            CalendarSyncError: If calendar event update fails
        """
        if not event.outlook_calendar_event_id:
            logger.warning(f"Event {event.id} has no associated Outlook calendar event")
            return False
        
        if not self.user_email:
            raise CalendarSyncError("User email not provided for calendar service")
        
        try:
            # Parse event time information
            start_time, end_time = self._parse_event_times(event)
            
            # Build update data
            updates = {
                'subject': self._build_event_subject(event),
                'start': {
                    'dateTime': start_time.isoformat(),
                    'timeZone': 'UTC'
                },
                'end': {
                    'dateTime': end_time.isoformat(),
                    'timeZone': 'UTC'
                },
                'body': {
                    'contentType': 'HTML',
                    'content': self._build_event_description(event)
                }
            }
            
            if event.location:
                updates['location'] = {'displayName': event.location}
            
            # Build attendees list
            attendees = self._build_attendees_list(event)
            if attendees:
                updates['attendees'] = [
                    {
                        'emailAddress': {'address': email},
                        'type': 'required'
                    }
                    for email in attendees
                ]
            
            # Update calendar event via Graph API
            self.graph_client.update_calendar_event(
                user_id=self.user_email,
                event_id=event.outlook_calendar_event_id,
                updates=updates
            )
            
            security_logger.info(
                'Calendar event updated',
                extra={
                    'user_email': self.user_email,
                    'app_event_id': str(event.id),
                    'outlook_event_id': event.outlook_calendar_event_id,
                    'updated_fields': list(updates.keys()),
                    'timestamp': timezone.now().isoformat(),
                }
            )
            
            return True
            
        except GraphAPIError as e:
            logger.error(f"Failed to update calendar event for event {event.id}: {e}")
            raise CalendarSyncError(f"Calendar event update failed: {e}")
        except Exception as e:
            logger.error(f"Unexpected error updating calendar event for event {event.id}: {e}")
            raise CalendarSyncError(f"Unexpected error: {e}")
    
    def delete_calendar_event(self, event: Event) -> bool:
        """
        Delete a calendar event from Outlook.
        
        Args:
            event: Event model instance
            
        Returns:
            True if deletion was successful, False otherwise
            
        Raises:
            CalendarSyncError: If calendar event deletion fails
        """
        if not event.outlook_calendar_event_id:
            logger.warning(f"Event {event.id} has no associated Outlook calendar event")
            return False
        
        if not self.user_email:
            raise CalendarSyncError("User email not provided for calendar service")
        
        try:
            # Delete calendar event via Graph API
            self.graph_client.delete_calendar_event(
                user_id=self.user_email,
                event_id=event.outlook_calendar_event_id
            )
            
            # Clear the Outlook calendar event ID from the app event
            with transaction.atomic():
                event.outlook_calendar_event_id = None
                event.save(update_fields=['outlook_calendar_event_id', 'modified'])
            
            security_logger.info(
                'Calendar event deleted',
                extra={
                    'user_email': self.user_email,
                    'app_event_id': str(event.id),
                    'outlook_event_id': event.outlook_calendar_event_id,
                    'timestamp': timezone.now().isoformat(),
                }
            )
            
            return True
            
        except GraphAPIError as e:
            logger.error(f"Failed to delete calendar event for event {event.id}: {e}")
            raise CalendarSyncError(f"Calendar event deletion failed: {e}")
        except Exception as e:
            logger.error(f"Unexpected error deleting calendar event for event {event.id}: {e}")
            raise CalendarSyncError(f"Unexpected error: {e}")
    
    def sync_event_to_calendar(self, event: Event, force_update: bool = False) -> bool:
        """
        Synchronize an app event to Outlook calendar.
        Creates new calendar event if none exists, updates if it does.
        
        Args:
            event: Event model instance
            force_update: Force update even if event hasn't changed
            
        Returns:
            True if sync was successful, False otherwise
        """
        try:
            # Only sync events that are scheduled or confirmed
            if event.status not in ['scheduled', 'rsvped']:
                logger.debug(f"Skipping calendar sync for event {event.id} with status {event.status}")
                return False
            
            # Check if calendar event already exists
            if event.outlook_calendar_event_id:
                # Update existing calendar event
                return self.update_calendar_event(event)
            else:
                # Create new calendar event
                outlook_event_id = self.create_calendar_event(event)
                return outlook_event_id is not None
                
        except CalendarSyncError:
            # Re-raise calendar sync errors
            raise
        except Exception as e:
            logger.error(f"Unexpected error syncing event {event.id} to calendar: {e}")
            raise CalendarSyncError(f"Sync failed: {e}")
    
    def bulk_sync_events(self, events: List[Event]) -> Dict[str, Any]:
        """
        Synchronize multiple events to calendar in bulk.
        
        Args:
            events: List of Event model instances
            
        Returns:
            Dictionary with sync results
        """
        results = {
            'total': len(events),
            'synced': 0,
            'failed': 0,
            'skipped': 0,
            'errors': []
        }
        
        for event in events:
            try:
                if self.sync_event_to_calendar(event):
                    results['synced'] += 1
                else:
                    results['skipped'] += 1
            except Exception as e:
                results['failed'] += 1
                results['errors'].append({
                    'event_id': str(event.id),
                    'error': str(e)
                })
                logger.error(f"Failed to sync event {event.id}: {e}")
        
        security_logger.info(
            'Bulk calendar sync completed',
            extra={
                'user_email': self.user_email,
                'total_events': results['total'],
                'synced': results['synced'],
                'failed': results['failed'],
                'skipped': results['skipped'],
                'timestamp': timezone.now().isoformat(),
            }
        )
        
        return results
    
    def _parse_event_times(self, event: Event) -> tuple[datetime, datetime]:
        """
        Parse event start and end times from the event data.
        
        Args:
            event: Event model instance
            
        Returns:
            Tuple of (start_time, end_time) as datetime objects
        """
        # Event stores date and time separately (start_date/start_time,
        # end_date/end_time); a missing start time means midnight and a missing
        # end means a one-hour block.
        tz = self._event_timezone(event)
        start_time = datetime.combine(event.start_date, event.start_time or dt_time.min)
        start_time = timezone.make_aware(start_time, tz)

        if event.end_time:
            end_time = datetime.combine(event.end_date or event.start_date, event.end_time)
            end_time = timezone.make_aware(end_time, tz)
            if end_time <= start_time and not event.end_date:
                end_time += timedelta(days=1)
        elif event.end_date and event.end_date != event.start_date:
            end_time = timezone.make_aware(
                datetime.combine(event.end_date, start_time.time()), tz
            ) + timedelta(hours=1)
        else:
            end_time = start_time + timedelta(hours=1)

        return start_time, end_time
    
    @staticmethod
    def _event_timezone(event: Event):
        """The event's IANA timezone if set and valid, else the project default."""
        name = getattr(event, 'timezone', '') or ''
        if name:
            try:
                return ZoneInfo(name)
            except (ZoneInfoNotFoundError, ValueError):
                pass
        return timezone.get_default_timezone()

    def _parse_time_string(self, time_str: str) -> tuple[int, int]:
        """
        Parse a time string like "2:00 PM" into hour and minute.
        
        Args:
            time_str: Time string to parse
            
        Returns:
            Tuple of (hour, minute) in 24-hour format
        """
        time_str = time_str.strip().lower()
        
        # Handle AM/PM
        is_pm = 'pm' in time_str or 'p.m.' in time_str
        is_am = 'am' in time_str or 'a.m.' in time_str
        
        # Remove AM/PM indicators
        time_str = time_str.replace('pm', '').replace('am', '').replace('p.m.', '').replace('a.m.', '').strip()
        
        # Parse hour and minute
        if ':' in time_str:
            hour_str, minute_str = time_str.split(':', 1)
            hour = int(hour_str)
            minute = int(minute_str)
        else:
            hour = int(time_str)
            minute = 0
        
        # Convert to 24-hour format
        if is_pm and hour != 12:
            hour += 12
        elif is_am and hour == 12:
            hour = 0
        
        return hour, minute
    
    def _build_event_subject(self, event: Event) -> str:
        """
        Build calendar event subject from app event data.
        
        Args:
            event: Event model instance
            
        Returns:
            Event subject string
        """
        if event.title:
            return event.title
        if event.group:
            return f"{event.type.title()}: {event.group}"
        return f"{event.type.title()}: {event.description[:50] if event.description else 'Scheduling Request'}"
    
    def _build_event_description(self, event: Event) -> str:
        """
        Build calendar event description from app event data.
        
        Args:
            event: Event model instance
            
        Returns:
            HTML-formatted event description
        """
        # Every value may originate in inbound email: escape before it goes
        # into the HTML body of the Outlook calendar entry.
        def row(label: str, value: Any) -> str:
            return f"<p><strong>{label}:</strong> {escape(str(value))}</p>"

        description_parts = []

        if event.description:
            description_parts.append(row('Details', event.description))
        if event.group:
            description_parts.append(row('Group', event.group))
        if event.legislative_topics:
            description_parts.append(row('Legislative Topics', ', '.join(map(str, event.legislative_topics))))
        if event.participants:
            description_parts.append(row('Participants', ', '.join(map(str, event.participants))))

        if event.point_of_contact_name or event.point_of_contact_email:
            contact_info = []
            if event.point_of_contact_name:
                contact_info.append(escape(event.point_of_contact_name))
            if event.point_of_contact_email:
                email = escape(event.point_of_contact_email, quote=True)
                contact_info.append(f"<a href='mailto:{email}'>{email}</a>")
            if event.point_of_contact_phone:
                contact_info.append(escape(event.point_of_contact_phone))
            description_parts.append(f"<p><strong>Point of Contact:</strong> {' - '.join(contact_info)}</p>")

        if event.time_notes:
            description_parts.append(row('Time Notes', event.time_notes))
        if event.notes:
            description_parts.append(row('Notes', event.notes))

        description_parts.append(row('Status', event.get_status_display_from_office()))
        description_parts.append(f"<p><em>App Event ID: {event.id}</em></p>")
        
        return '\n'.join(description_parts) if description_parts else '<p>HillDesk scheduling event</p>'
    
    def _build_attendees_list(self, event: Event) -> List[str]:
        """
        Build list of attendee email addresses from event data.
        
        Args:
            event: Event model instance
            
        Returns:
            List of email addresses
        """
        attendees = []
        
        # Add point of contact if they have an email
        if event.point_of_contact_email:
            attendees.append(event.point_of_contact_email)
        
        # Add staff members if they have emails
        if event.staff:
            for staff_member in event.staff:
                # If staff member is an email address, add it
                if '@' in staff_member:
                    attendees.append(staff_member)
        
        # Remove duplicates and return
        return list(set(attendees))


def sync_event_to_calendar(event: Event, user_email: str) -> bool:
    """
    Convenience function to sync a single event to calendar.
    
    Args:
        event: Event model instance
        user_email: Email address of the user
        
    Returns:
        True if sync was successful, False otherwise
    """
    calendar_service = CalendarService(user_email)
    return calendar_service.sync_event_to_calendar(event)


def bulk_sync_events_to_calendar(events: List[Event], user_email: str) -> Dict[str, Any]:
    """
    Convenience function to sync multiple events to calendar.
    
    Args:
        events: List of Event model instances
        user_email: Email address of the user
        
    Returns:
        Dictionary with sync results
    """
    calendar_service = CalendarService(user_email)
    return calendar_service.bulk_sync_events(events)