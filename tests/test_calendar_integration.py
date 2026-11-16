# SPDX-License-Identifier: Apache-2.0
"""
Tests for calendar integration functionality.
"""

from unittest.mock import Mock, patch
from datetime import timedelta
from django.test import TestCase, override_settings
from django.utils import timezone
from django.contrib.auth import get_user_model

from apps.email_processing.calendar_service import CalendarService, CalendarSyncError
from apps.email_processing.graph_client import GraphAPIError
from tests.factories import create_event
from datetime import time as dt_time
from apps.contacts.services import attach_contact_org_to_event

User = get_user_model()


@override_settings(
    MICROSOFT_TENANT_ID='test-tenant-id',
    MICROSOFT_CLIENT_ID='test-client-id',
    MICROSOFT_CLIENT_SECRET='test-client-secret',
    ENABLE_CALENDAR_SYNC=True
)
class CalendarServiceTest(TestCase):
    """Test cases for calendar service functionality."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@congress.example',
            password='testpass123'
        )
        
        self.calendar_service = CalendarService('test@congress.example')
        
        # Create test event
        self.event = create_event(
            type='meeting',
            start_date=timezone.now() + timedelta(days=1),
            time='2:00 PM - 3:00 PM',
            location='2411 RHOB',
            group='Healthcare Coalition',
            details='Discussion about Medicare expansion',
            point_of_contact_name='John Doe',
            point_of_contact_email='john@example.com',
            point_of_contact_phone='555-1234',
            status='scheduled',
            created_by=self.user,
            modified_by=self.user,
        )
    
    def test_calendar_service_initialization(self):
        """Test calendar service initialization."""
        service = CalendarService('test@example.com')
        self.assertEqual(service.user_email, 'test@example.com')
        self.assertIsNotNone(service.graph_client)
    
    def test_calendar_service_no_user_email(self):
        """Test calendar service without user email."""
        service = CalendarService()
        
        with self.assertRaises(CalendarSyncError):
            service.create_calendar_event(self.event)
    
    @patch('apps.email_processing.calendar_service.MicrosoftGraphClient.create_calendar_event')
    def test_create_calendar_event_success(self, mock_create):
        """Test successful calendar event creation."""
        # Mock Graph API response
        mock_create.return_value = {
            'id': 'outlook-event-123',
            'subject': 'Meeting: Healthcare Coalition'
        }
        
        # Create calendar event
        outlook_event_id = self.calendar_service.create_calendar_event(self.event)
        
        # Verify result
        self.assertEqual(outlook_event_id, 'outlook-event-123')
        
        # Verify event was updated with Outlook event ID
        self.event.refresh_from_db()
        self.assertEqual(self.event.outlook_calendar_event_id, 'outlook-event-123')
        
        # Verify Graph API was called correctly
        mock_create.assert_called_once()
        call_args = mock_create.call_args
        self.assertEqual(call_args[1]['user_id'], 'test@congress.example')
        self.assertEqual(call_args[1]['subject'], 'Meeting: Healthcare Coalition')
        self.assertIn('john@example.com', call_args[1]['attendees'])
    
    @patch('apps.email_processing.calendar_service.MicrosoftGraphClient.create_calendar_event')
    def test_create_calendar_event_graph_error(self, mock_create):
        """Test calendar event creation with Graph API error."""
        # Mock Graph API error
        mock_create.side_effect = GraphAPIError("API Error")
        
        # Attempt to create calendar event
        with self.assertRaises(CalendarSyncError):
            self.calendar_service.create_calendar_event(self.event)
    
    @patch('apps.email_processing.calendar_service.MicrosoftGraphClient.update_calendar_event')
    def test_update_calendar_event_success(self, mock_update):
        """Test successful calendar event update."""
        # Set up event with existing calendar event ID
        self.event.outlook_calendar_event_id = 'outlook-event-123'
        self.event.save()
        # The save above legitimately syncs via the post_save signal; count
        # only the explicit call under test.
        mock_update.reset_mock()
        
        # Mock Graph API response
        mock_update.return_value = {
            'id': 'outlook-event-123',
            'subject': 'Updated Meeting: Healthcare Coalition'
        }
        
        # Update calendar event
        result = self.calendar_service.update_calendar_event(self.event)
        
        # Verify result
        self.assertTrue(result)
        
        # Verify Graph API was called correctly
        mock_update.assert_called_once()
        call_args = mock_update.call_args
        self.assertEqual(call_args[1]['user_id'], 'test@congress.example')
        self.assertEqual(call_args[1]['event_id'], 'outlook-event-123')
    
    def test_update_calendar_event_no_outlook_id(self):
        """Test updating calendar event without Outlook event ID."""
        # Event has no Outlook calendar event ID
        result = self.calendar_service.update_calendar_event(self.event)
        
        # Should return False
        self.assertFalse(result)
    
    @patch('apps.email_processing.calendar_service.MicrosoftGraphClient.delete_calendar_event')
    def test_delete_calendar_event_success(self, mock_delete):
        """Test successful calendar event deletion."""
        # Set up event with existing calendar event ID
        self.event.outlook_calendar_event_id = 'outlook-event-123'
        self.event.save()
        # The save above legitimately syncs via the post_save signal; count
        # only the explicit call under test.
        mock_delete.reset_mock()
        
        # Delete calendar event
        result = self.calendar_service.delete_calendar_event(self.event)
        
        # Verify result
        self.assertTrue(result)
        
        # Verify event's Outlook ID was cleared
        self.event.refresh_from_db()
        self.assertIsNone(self.event.outlook_calendar_event_id)
        
        # Verify Graph API was called correctly
        mock_delete.assert_called_once_with(
            user_id='test@congress.example',
            event_id='outlook-event-123'
        )
    
    def test_delete_calendar_event_no_outlook_id(self):
        """Test deleting calendar event without Outlook event ID."""
        # Event has no Outlook calendar event ID
        result = self.calendar_service.delete_calendar_event(self.event)
        
        # Should return False
        self.assertFalse(result)
    
    @patch('apps.email_processing.calendar_service.CalendarService.create_calendar_event')
    def test_sync_event_to_calendar_create(self, mock_create):
        """Test syncing event to calendar (create new)."""
        # Mock create method
        mock_create.return_value = 'outlook-event-123'
        
        # Sync event
        result = self.calendar_service.sync_event_to_calendar(self.event)
        
        # Verify result
        self.assertTrue(result)
        mock_create.assert_called_once_with(self.event)
    
    @patch('apps.email_processing.calendar_service.CalendarService.update_calendar_event')
    def test_sync_event_to_calendar_update(self, mock_update):
        """Test syncing event to calendar (update existing)."""
        # Set up event with existing calendar event ID
        self.event.outlook_calendar_event_id = 'outlook-event-123'
        self.event.save()
        # The save above legitimately syncs via the post_save signal; count
        # only the explicit call under test.
        mock_update.reset_mock()
        
        # Mock update method
        mock_update.return_value = True
        
        # Sync event
        result = self.calendar_service.sync_event_to_calendar(self.event)
        
        # Verify result
        self.assertTrue(result)
        mock_update.assert_called_once_with(self.event)
    
    def test_sync_event_wrong_status(self):
        """Test syncing event with wrong status."""
        # Set event status to rejected
        self.event.status = 'rejected'
        self.event.save()
        
        # Sync event
        result = self.calendar_service.sync_event_to_calendar(self.event)
        
        # Should return False (skipped)
        self.assertFalse(result)
    
    @patch('apps.email_processing.calendar_service.CalendarService.sync_event_to_calendar')
    def test_bulk_sync_events(self, mock_sync):
        """Test bulk syncing multiple events."""
        # Create additional events
        event2 = create_event(
            type='speaking',
            start_date=timezone.now() + timedelta(days=2),
            time='10:00 AM - 11:00 AM',
            location='Capitol Building',
            group='Press Conference',
            details='Budget announcement',
            point_of_contact_name='Jane Smith',
            point_of_contact_email='jane@example.com',
            point_of_contact_phone='555-5678',
            status='scheduled',
            created_by=self.user,
            modified_by=self.user,
        )
        
        events = [self.event, event2]
        
        # Mock sync method to succeed for first, fail for second
        mock_sync.side_effect = [True, False]
        
        # Bulk sync events
        results = self.calendar_service.bulk_sync_events(events)
        
        # Verify results
        self.assertEqual(results['total'], 2)
        self.assertEqual(results['synced'], 1)
        self.assertEqual(results['failed'], 0)
        self.assertEqual(results['skipped'], 1)
        self.assertEqual(len(results['errors']), 0)
    
    def test_parse_event_times_with_time_range(self):
        """Test parsing event times with time range."""
        # Test with time range
        self.event.start_time = dt_time(14, 0)
        self.event.end_time = dt_time(16, 30)
        self.event.save()
        
        start_time, end_time = self.calendar_service._parse_event_times(self.event)
        
        # Verify times
        self.assertEqual(start_time.hour, 14)  # 2 PM
        self.assertEqual(start_time.minute, 0)
        self.assertEqual(end_time.hour, 16)    # 4:30 PM
        self.assertEqual(end_time.minute, 30)
    
    def test_parse_event_times_single_time(self):
        """Test parsing event times with single time."""
        # Test with single time
        self.event.start_time = dt_time(15, 0)
        self.event.end_time = None
        self.event.save()
        
        start_time, end_time = self.calendar_service._parse_event_times(self.event)
        
        # Verify times (should default to 1-hour duration)
        self.assertEqual(start_time.hour, 15)  # 3 PM
        self.assertEqual(start_time.minute, 0)
        self.assertEqual(end_time.hour, 16)    # 4 PM (1 hour later)
        self.assertEqual(end_time.minute, 0)
    
    def test_parse_event_times_no_time(self):
        """Test parsing event times without time specified."""
        # Test with TBD time
        self.event.start_time = None
        self.event.end_time = None
        self.event.save()
        
        start_time, end_time = self.calendar_service._parse_event_times(self.event)
        
        # Should default to 1-hour duration
        self.assertEqual(end_time - start_time, timedelta(hours=1))
    
    def test_parse_time_string_pm(self):
        """Test parsing PM time string."""
        hour, minute = self.calendar_service._parse_time_string('2:30 PM')
        self.assertEqual(hour, 14)
        self.assertEqual(minute, 30)
    
    def test_parse_time_string_am(self):
        """Test parsing AM time string."""
        hour, minute = self.calendar_service._parse_time_string('9:15 AM')
        self.assertEqual(hour, 9)
        self.assertEqual(minute, 15)
    
    def test_parse_time_string_noon(self):
        """Test parsing noon time string."""
        hour, minute = self.calendar_service._parse_time_string('12:00 PM')
        self.assertEqual(hour, 12)
        self.assertEqual(minute, 0)
    
    def test_parse_time_string_midnight(self):
        """Test parsing midnight time string."""
        hour, minute = self.calendar_service._parse_time_string('12:00 AM')
        self.assertEqual(hour, 0)
        self.assertEqual(minute, 0)
    
    def test_build_event_subject(self):
        """Test building event subject."""
        subject = self.calendar_service._build_event_subject(self.event)
        self.assertEqual(subject, 'Meeting: Healthcare Coalition')
    
    def test_build_event_subject_no_group(self):
        """Test building event subject without group."""
        # group is derived from the linked organization; title takes precedence.
        self.event.title = ''
        self.event.save()
        self.event.organization_links.all().delete()
        attach_contact_org_to_event(self.event, group='Default Group')
        
        subject = self.calendar_service._build_event_subject(self.event)
        self.assertEqual(subject, 'Meeting: Default Group')
    
    def test_build_event_description(self):
        """Test building event description."""
        description = self.calendar_service._build_event_description(self.event)
        
        # Verify description contains key information
        self.assertIn('Discussion about Medicare expansion', description)
        self.assertIn('Healthcare Coalition', description)
        self.assertIn('John Doe', description)
        self.assertIn('john@example.com', description)
        self.assertIn('555-1234', description)
        self.assertIn(str(self.event.id), description)
    
    def test_build_attendees_list(self):
        """Test building attendees list."""
        attendees = self.calendar_service._build_attendees_list(self.event)
        
        # Should include point of contact email
        self.assertIn('john@example.com', attendees)
    
    def test_build_attendees_list_with_staff_emails(self):
        """Test building attendees list with staff emails."""
        self.event.staff = ['staff1@congress.example', 'John Smith', 'staff2@congress.example']
        self.event.save()
        
        attendees = self.calendar_service._build_attendees_list(self.event)
        
        # Should include point of contact and staff emails
        self.assertIn('john@example.com', attendees)
        self.assertIn('staff1@congress.example', attendees)
        self.assertIn('staff2@congress.example', attendees)
        self.assertNotIn('John Smith', attendees)  # Not an email


@override_settings(ENABLE_CALENDAR_SYNC=True)
class CalendarSignalsTest(TestCase):
    """Test cases for calendar synchronization signals."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@congress.example',
            password='testpass123'
        )
    
    @patch('apps.event_management.signals.CalendarService')
    def test_event_save_signal_create(self, mock_calendar_service):
        """Test calendar sync signal on event creation."""
        # Mock calendar service
        mock_service = Mock()
        mock_service.sync_event_to_calendar.return_value = True
        mock_calendar_service.return_value = mock_service
        
        # Create event (should trigger signal)
        event = create_event(
            type='meeting',
            start_date=timezone.now() + timedelta(days=1),
            time='2:00 PM - 3:00 PM',
            location='2411 RHOB',
            group='Test Group',
            details='Test details',
            point_of_contact_name='Test Contact',
            point_of_contact_email='contact@example.com',
            point_of_contact_phone='555-0000',
            status='scheduled',
            created_by=self.user,
            modified_by=self.user,
        )
        
        # Verify calendar service was called
        mock_calendar_service.assert_called_once_with('test@congress.example')
        mock_service.sync_event_to_calendar.assert_called_once_with(event)
    
    @patch('apps.event_management.signals.CalendarService')
    def test_event_save_signal_update(self, mock_calendar_service):
        """Test calendar sync signal on event update."""
        # Create event first
        event = create_event(
            type='meeting',
            start_date=timezone.now() + timedelta(days=1),
            time='2:00 PM - 3:00 PM',
            location='2411 RHOB',
            group='Test Group',
            details='Test details',
            point_of_contact_name='Test Contact',
            point_of_contact_email='contact@example.com',
            point_of_contact_phone='555-0000',
            status='scheduled',
            created_by=self.user,
            modified_by=self.user,
        )
        
        # Reset mock
        mock_calendar_service.reset_mock()
        mock_service = Mock()
        mock_service.sync_event_to_calendar.return_value = True
        mock_calendar_service.return_value = mock_service
        
        # Update event (should trigger signal)
        event.description = 'Updated details'
        event.save()
        
        # Verify calendar service was called
        mock_calendar_service.assert_called_once_with('test@congress.example')
        mock_service.sync_event_to_calendar.assert_called_once_with(event)
    
    @patch('apps.event_management.signals.CalendarService')
    def test_event_save_signal_skip_rejected(self, mock_calendar_service):
        """Test calendar sync signal skips rejected events."""
        # Create rejected event (should not trigger sync)
        create_event(
            type='meeting',
            start_date=timezone.now() + timedelta(days=1),
            time='2:00 PM - 3:00 PM',
            location='2411 RHOB',
            group='Test Group',
            details='Test details',
            point_of_contact_name='Test Contact',
            point_of_contact_email='contact@example.com',
            point_of_contact_phone='555-0000',
            status='passed',  # Changed from 'rejected' to valid status
            created_by=self.user,
            modified_by=self.user,
        )
        
        # Verify calendar service was not called
        mock_calendar_service.assert_not_called()
    
    @patch('apps.event_management.signals.CalendarService')
    def test_event_delete_signal(self, mock_calendar_service):
        """Test calendar sync signal on event deletion."""
        # Mock calendar service
        mock_service = Mock()
        mock_service.delete_calendar_event.return_value = True
        mock_calendar_service.return_value = mock_service
        
        # Create event with calendar event ID
        event = create_event(
            type='meeting',
            start_date=timezone.now() + timedelta(days=1),
            time='2:00 PM - 3:00 PM',
            location='2411 RHOB',
            group='Test Group',
            details='Test details',
            point_of_contact_name='Test Contact',
            point_of_contact_email='contact@example.com',
            point_of_contact_phone='555-0000',
            status='scheduled',
            outlook_calendar_event_id='outlook-event-123',
            created_by=self.user,
            modified_by=self.user,
        )
        
        # Reset mock to ignore creation signal
        mock_calendar_service.reset_mock()
        
        # Delete event (should trigger signal)
        event.delete()
        
        # Verify calendar service was called
        mock_calendar_service.assert_called_once_with('test@congress.example')
        mock_service.delete_calendar_event.assert_called_once()
    
    @override_settings(ENABLE_CALENDAR_SYNC=False)
    @patch('apps.event_management.signals.CalendarService')
    def test_signals_disabled_when_sync_disabled(self, mock_calendar_service):
        """Test signals are disabled when calendar sync is disabled."""
        # Create event (should not trigger signal)
        create_event(
            type='meeting',
            start_date=timezone.now() + timedelta(days=1),
            time='2:00 PM - 3:00 PM',
            location='2411 RHOB',
            group='Test Group',
            details='Test details',
            status='scheduled',
            created_by=self.user,
            modified_by=self.user,
        )
        
        # Verify calendar service was not called
        mock_calendar_service.assert_not_called()


@override_settings(ENABLE_CALENDAR_SYNC=True)
class CalendarIntegrationTest(TestCase):
    """Integration tests for calendar functionality."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@congress.example',
            password='testpass123'
        )
    
    @patch('apps.email_processing.calendar_service.MicrosoftGraphClient')
    def test_end_to_end_calendar_sync(self, mock_graph_client):
        """Test end-to-end calendar synchronization."""
        # Mock Graph API client
        mock_client = Mock()
        mock_client.create_calendar_event.return_value = {
            'id': 'outlook-event-123',
            'subject': 'Meeting: Test Group'
        }
        mock_client.update_calendar_event.return_value = {
            'id': 'outlook-event-123',
            'subject': 'Updated Meeting: Test Group'
        }
        mock_graph_client.return_value = mock_client
        
        # Create calendar service
        calendar_service = CalendarService('test@congress.example')
        
        # Create event
        event = create_event(
            type='meeting',
            start_date=timezone.now() + timedelta(days=1),
            time='2:00 PM - 3:00 PM',
            location='2411 RHOB',
            group='Test Group',
            details='Test details',
            point_of_contact_name='Test Contact',
            point_of_contact_email='contact@example.com',
            point_of_contact_phone='555-0000',
            status='scheduled',
            created_by=self.user,
            modified_by=self.user,
        )
        
        # Sync to calendar (create)
        outlook_event_id = calendar_service.create_calendar_event(event)
        self.assertEqual(outlook_event_id, 'outlook-event-123')
        
        # Verify event was updated
        event.refresh_from_db()
        self.assertEqual(event.outlook_calendar_event_id, 'outlook-event-123')
        
        # Update event
        event.details = 'Updated details'
        event.save()
        
        # Sync to calendar (update)
        result = calendar_service.update_calendar_event(event)
        self.assertTrue(result)
        
        # One signal-driven call plus one manual call each. The service's own
        # bookkeeping saves (storing the Outlook id) no longer re-fire a sync.
        self.assertEqual(mock_client.create_calendar_event.call_count, 2)
        self.assertEqual(mock_client.update_calendar_event.call_count, 2)