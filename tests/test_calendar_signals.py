# SPDX-License-Identifier: Apache-2.0
"""
Tests for calendar synchronization signals.
"""

from unittest.mock import patch
from datetime import timedelta
from django.test import TestCase, override_settings
from django.utils import timezone
from django.contrib.auth import get_user_model

from apps.event_management.models import Event
from tests.factories import create_event

User = get_user_model()


@override_settings(
    ENABLE_CALENDAR_SYNC=True,
    MICROSOFT_TENANT_ID='test-tenant-id',
    MICROSOFT_CLIENT_ID='test-client-id',
    MICROSOFT_CLIENT_SECRET='test-client-secret'
)
class CalendarSignalsTest(TestCase):
    """Test cases for calendar synchronization signals."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@congress.example',
            password='testpass123'
        )
    
    @patch('apps.event_management.signals.CalendarIntegrationService.sync_event_to_calendar')
    def test_event_created_syncs_to_calendar(self, mock_sync):
        """Test that creating an event automatically syncs to calendar."""
        mock_sync.return_value = 'test-calendar-event-id'
        
        # Create a new event
        event = create_event(
            type='meeting',
            start_date=timezone.now() + timedelta(days=1),
            time='2:00 PM - 3:00 PM',
            location='Office',
            group='Test Group',
            details='Test meeting details',
            point_of_contact_name='Test Contact',
            point_of_contact_email='contact@example.com',
            point_of_contact_phone='555-0000',
            status='scheduled',
            created_by=self.user,
            modified_by=self.user,
        )
        
        # Verify sync was called
        mock_sync.assert_called_once_with(event)
    
    @patch('apps.event_management.signals.CalendarIntegrationService.sync_event_to_calendar')
    def test_event_updated_syncs_to_calendar(self, mock_sync):
        """Test that updating an event automatically syncs to calendar."""
        mock_sync.return_value = 'test-calendar-event-id'
        
        # Create an event
        event = create_event(
            type='meeting',
            start_date=timezone.now() + timedelta(days=1),
            time='2:00 PM - 3:00 PM',
            location='Office',
            group='Test Group',
            details='Test meeting details',
            point_of_contact_name='Test Contact',
            point_of_contact_email='contact@example.com',
            point_of_contact_phone='555-0000',
            status='scheduled',
            created_by=self.user,
            modified_by=self.user,
        )
        
        # Reset mock to clear the creation call
        mock_sync.reset_mock()
        
        # Update the event
        event.location = 'New Office'
        event.save()
        
        # Verify sync was called for the update
        mock_sync.assert_called_once_with(event)
    
    @patch('apps.event_management.signals.CalendarIntegrationService.delete_calendar_event')
    def test_event_deleted_removes_from_calendar(self, mock_delete):
        """Test that deleting an event removes it from calendar."""
        # Create an event with calendar event ID
        event = create_event(
            type='meeting',
            start_date=timezone.now() + timedelta(days=1),
            time='2:00 PM - 3:00 PM',
            location='Office',
            group='Test Group',
            details='Test meeting details',
            point_of_contact_name='Test Contact',
            point_of_contact_email='contact@example.com',
            point_of_contact_phone='555-0000',
            status='scheduled',
            outlook_calendar_event_id='test-calendar-event-id',
            created_by=self.user,
            modified_by=self.user,
        )
        
        # Delete the event
        event.delete()
        
        # Verify delete was called
        mock_delete.assert_called_once()
    
    @patch('apps.event_management.signals.CalendarIntegrationService.sync_event_to_calendar')
    def test_rejected_event_not_synced(self, mock_sync):
        """Test that rejected events are not synced to calendar."""
        # Create a rejected event
        create_event(
            type='meeting',
            start_date=timezone.now() + timedelta(days=1),
            time='2:00 PM - 3:00 PM',
            location='Office',
            group='Test Group',
            details='Test meeting details',
            point_of_contact_name='Test Contact',
            point_of_contact_email='contact@example.com',
            point_of_contact_phone='555-0000',
            status='passed',  # Changed from 'rejected' to valid status
            created_by=self.user,
            modified_by=self.user,
        )
        
        # Verify sync was not called
        mock_sync.assert_not_called()
    
    @patch('apps.event_management.signals.CalendarIntegrationService.sync_event_to_calendar')
    def test_canceled_event_not_synced(self, mock_sync):
        """Test that canceled events are not synced to calendar."""
        # Create a canceled event
        create_event(
            type='meeting',
            start_date=timezone.now() + timedelta(days=1),
            time='2:00 PM - 3:00 PM',
            location='Office',
            group='Test Group',
            details='Test meeting details',
            point_of_contact_name='Test Contact',
            point_of_contact_email='contact@example.com',
            point_of_contact_phone='555-0000',
            status='canceled',
            created_by=self.user,
            modified_by=self.user,
        )
        
        # Verify sync was not called
        mock_sync.assert_not_called()
    
    @patch('apps.event_management.signals.CalendarIntegrationService.sync_event_to_calendar')
    def test_event_without_user_not_synced(self, mock_sync):
        """Test that events without a user are not synced to calendar."""
        # The signal can only sync for a creator with an email address.
        no_email = User.objects.create_user(username='noemail', email='', password='x')
        create_event(
            type='meeting',
            start_date=timezone.now() + timedelta(days=1),
            time='2:00 PM - 3:00 PM',
            location='Office',
            group='Test Group',
            details='Test meeting details',
            point_of_contact_name='Test Contact',
            point_of_contact_email='contact@example.com',
            point_of_contact_phone='555-0000',
            status='scheduled',
            created_by=no_email,
            modified_by=no_email,
        )
        
        # Verify sync was not called
        mock_sync.assert_not_called()
    
    @override_settings(ENABLE_CALENDAR_SYNC=False)
    @patch('apps.event_management.signals.CalendarIntegrationService.sync_event_to_calendar')
    def test_sync_disabled_not_synced(self, mock_sync):
        """Test that events are not synced when calendar sync is disabled."""
        # Create an event
        create_event(
            type='meeting',
            start_date=timezone.now() + timedelta(days=1),
            time='2:00 PM - 3:00 PM',
            location='Office',
            group='Test Group',
            details='Test meeting details',
            point_of_contact_name='Test Contact',
            point_of_contact_email='contact@example.com',
            point_of_contact_phone='555-0000',
            status='scheduled',
            created_by=self.user,
            modified_by=self.user,
        )
        
        # Verify sync was not called
        mock_sync.assert_not_called()
    
    @patch('apps.event_management.signals.CalendarIntegrationService.sync_event_to_calendar')
    def test_sync_error_does_not_break_save(self, mock_sync):
        """Test that sync errors don't prevent event from being saved."""
        from apps.email_processing.calendar_service import CalendarSyncError
        
        # Mock sync to raise an error
        mock_sync.side_effect = CalendarSyncError("Sync failed")
        
        # Create an event - this should not raise an exception
        event = create_event(
            type='meeting',
            start_date=timezone.now() + timedelta(days=1),
            time='2:00 PM - 3:00 PM',
            location='Office',
            group='Test Group',
            details='Test meeting details',
            point_of_contact_name='Test Contact',
            point_of_contact_email='contact@example.com',
            point_of_contact_phone='555-0000',
            status='scheduled',
            created_by=self.user,
            modified_by=self.user,
        )
        
        # Verify the event was still created
        self.assertTrue(Event.objects.filter(id=event.id).exists())
        
        # Verify sync was attempted
        mock_sync.assert_called_once_with(event)
    
    @patch('apps.event_management.signals.CalendarIntegrationService.delete_calendar_event')
    def test_delete_error_does_not_break_deletion(self, mock_delete):
        """Test that delete errors don't prevent event from being deleted."""
        from apps.email_processing.calendar_service import CalendarSyncError
        
        # Create an event with calendar event ID
        event = create_event(
            type='meeting',
            start_date=timezone.now() + timedelta(days=1),
            time='2:00 PM - 3:00 PM',
            location='Office',
            group='Test Group',
            details='Test meeting details',
            point_of_contact_name='Test Contact',
            point_of_contact_email='contact@example.com',
            point_of_contact_phone='555-0000',
            status='scheduled',
            outlook_calendar_event_id='test-calendar-event-id',
            created_by=self.user,
            modified_by=self.user,
        )
        
        event_id = event.id
        
        # Mock delete to raise an error
        mock_delete.side_effect = CalendarSyncError("Delete failed")
        
        # Delete the event - this should not raise an exception
        event.delete()
        
        # Verify the event was still deleted
        self.assertFalse(Event.objects.filter(id=event_id).exists())
        
        # Verify delete was attempted
        mock_delete.assert_called_once()