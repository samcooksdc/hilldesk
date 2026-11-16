# SPDX-License-Identifier: Apache-2.0
"""
Tests for API endpoints implemented in task 7.1.

This module tests the comprehensive API system including event management,
email processing, SmartExtract functionality, and utility endpoints.
"""

from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework import status

from apps.event_management.models import Event, EmailTemplate, EventChangeHistory
from apps.email_processing.models import EmailProcessing
from tests.factories import create_event, make_office_member

User = get_user_model()


class EventAPITests(APITestCase):
    """Test cases for Event API endpoints."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        make_office_member(self.user)
        
        self.event = create_event(
            type='meeting',
            start_date=timezone.now() + timedelta(days=1),
            time='2:00 PM - 3:00 PM',
            location='Test Location',
            group='Test Group',
            details='Test event details',
            point_of_contact_name='Test Contact',
            point_of_contact_email='contact@example.com',
            status='received',
            created_by=self.user,
            modified_by=self.user
        )
        
        self.client.force_authenticate(user=self.user)
    
    def test_list_events(self):
        """Test listing events."""
        url = reverse('api:event-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['group'], 'Test Group')
    
    def test_list_events_with_search(self):
        """Test listing events with search parameter."""
        url = reverse('api:event-list')
        # Organization names are encrypted, so free-text search covers plain fields.
        response = self.client.get(url, {'search': 'Test Location'})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        
        # Test search with no results
        response = self.client.get(url, {'search': 'Nonexistent'})
        self.assertEqual(len(response.data['results']), 0)
    
    def test_list_events_with_filters(self):
        """Test listing events with various filters."""
        url = reverse('api:event-list')
        
        # Test status filter
        response = self.client.get(url, {'status': 'received'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        
        # Test type filter
        response = self.client.get(url, {'type': 'meeting'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        
        # Test date range filter
        start_date = (timezone.now() + timedelta(hours=12)).isoformat()
        response = self.client.get(url, {'start_date': start_date})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
    
    def test_retrieve_event(self):
        """Test retrieving a single event."""
        url = reverse('api:event-detail', kwargs={'pk': self.event.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], str(self.event.id))
        self.assertEqual(response.data['group'], 'Test Group')
        self.assertIn('created_by', response.data)
    
    def test_create_event(self):
        """Test creating a new event."""
        url = reverse('api:event-list')
        data = {
            'type': 'hearing',
            'start_date': (timezone.now() + timedelta(days=2)).date().isoformat(),
            'location': 'New Location',
            'group': 'New Group',
            'details': 'New event details',
            'point_of_contact_name': 'New Contact',
            'point_of_contact_email': 'newcontact@example.com',
            'status': 'received',
            'legislative_topics': ['Topic 1', 'Topic 2'],
            'participants': ['Person 1', 'Person 2'],
            'staff': ['Staff 1']
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        # group/contact are read-only here; they're linked via the contacts service.
        self.assertEqual(response.data['location'], 'New Location')
        self.assertEqual(str(response.data['created_by']['id']), str(self.user.id))
        
        # Verify event was created in database
        event = Event.objects.get(id=response.data['id'])
        self.assertEqual(event.location, 'New Location')
        self.assertEqual(event.created_by, self.user)
    
    def test_update_event(self):
        """Test updating an event."""
        url = reverse('api:event-detail', kwargs={'pk': self.event.id})
        data = {'location': 'Updated Location'}
        
        response = self.client.patch(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['location'], 'Updated Location')
        
        # Verify change history was created
        history = EventChangeHistory.objects.filter(event=self.event)
        self.assertTrue(history.exists())
    
    def test_delete_event(self):
        """Test deleting an event."""
        url = reverse('api:event-detail', kwargs={'pk': self.event.id})
        response = self.client.delete(url)
        
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        
        # Verify event was deleted
        with self.assertRaises(Event.DoesNotExist):
            Event.objects.get(id=self.event.id)
    
    def test_archive_event(self):
        """Test archiving an event."""
        url = reverse('api:event-archive', kwargs={'pk': self.event.id})
        data = {'reason': 'Test archive reason'}
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['success'])
        
        # Verify event was archived
        self.event.refresh_from_db()
        self.assertTrue(self.event.is_archived)
    
    def test_unarchive_event(self):
        """Test unarchiving an event."""
        # First archive the event
        self.event.archive(user=self.user)
        
        url = reverse('api:event-restore', kwargs={'pk': self.event.id})
        response = self.client.post(url, {}, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Verify event was unarchived
        self.event.refresh_from_db()
        self.assertFalse(self.event.is_archived)
    
    def test_editing_panel_data(self):
        """Test getting editing panel data."""
        # Create some related data
        email = EmailProcessing.objects.create(
            complete_email_data={'body': {'contentType': 'text', 'content': 'Test body'}},
            email_id='test-email-id',
            subject='Test Email',
            sender='test@example.com',
            received=timezone.now(),
            event=self.event,
            is_scheduling_request=True,
            confidence=0.9,
            extracted_data={'test': 'data'},
            processed_by=self.user
        )
        # Emails are linked through EventEmailLink, not the legacy FK.
        self.event.attach_email(email, user=self.user)
        
        EmailTemplate.objects.create(
            name='Test Template',
            subject='Test Subject',
            body='Test Body',
            is_default=True,
            created_by=self.user,
            modified_by=self.user
        )
        
        url = reverse('api:event-editing-panel-data', kwargs={'pk': self.event.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('event', response.data)
        self.assertIn('related_emails', response.data)
        self.assertIn('change_history', response.data)
        self.assertIn('email_templates', response.data)
        self.assertEqual(len(response.data['related_emails']), 1)
        self.assertEqual(len(response.data['email_templates']), 1)
    
    def test_unauthenticated_access(self):
        """Test that unauthenticated requests are rejected."""
        self.client.force_authenticate(user=None)
        
        url = reverse('api:event-list')
        response = self.client.get(url)
        
        # Session auth sends no WWW-Authenticate challenge, so DRF answers 403.
        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))


class EmailFetchAPITests(APITestCase):
    """Test cases for Email Fetch API endpoints."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        make_office_member(self.user)
        self.client.force_authenticate(user=self.user)
    
    def test_fetch_emails_missing_user_id(self):
        """Test email fetching without user_id parameter."""
        url = reverse('api:email-fetch')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('user_id parameter is required', response.data['error'])
    
    @patch('apps.api.views.MicrosoftGraphClient')
    def test_fetch_emails_success(self, mock_graph_client):
        """Test successful email fetching."""
        # Mock Graph client response
        mock_instance = mock_graph_client.return_value
        mock_instance.get_user_emails.return_value = {
            'value': [
                {
                    'id': 'email-1',
                    'subject': 'Test Email',
                    'sender': {'emailAddress': {'address': 'sender@example.com', 'name': 'Sender'}},
                    'receivedDateTime': '2024-01-01T10:00:00Z',
                    'body': {'content': 'Test content', 'contentType': 'text'},
                    'bodyPreview': 'Test preview'
                }
            ]
        }
        
        url = reverse('api:email-fetch')
        response = self.client.get(url, {'user_id': 'test@example.com'})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('emails', response.data)
        self.assertEqual(len(response.data['emails']), 1)
        self.assertEqual(response.data['emails'][0]['subject'], 'Test Email')
    
    def test_send_email_missing_required_fields(self):
        """Test email sending with missing required fields."""
        url = reverse('api:email-fetch')
        data = {
            'user_id': 'test@example.com',
            'subject': 'Test Subject'
            # Missing to_recipients and body
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('required', response.data['error'])


class EmailProcessingAPITests(APITestCase):
    """Test cases for Email Processing API endpoints."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        make_office_member(self.user)
        
        self.event = create_event(
            type='meeting',
            start_date=timezone.now() + timedelta(days=1),
            time='2:00 PM - 3:00 PM',
            location='Test Location',
            group='Test Group',
            details='Test event details',
            point_of_contact_name='Test Contact',
            point_of_contact_email='contact@example.com',
            created_by=self.user,
            modified_by=self.user
        )
        
        self.email_processing = EmailProcessing.objects.create(
            complete_email_data={'body': {'contentType': 'text', 'content': 'Test body'}},
            email_id='test-email-id',
            subject='Test Email Subject',
            sender='sender@example.com',
            sender_name='Test Sender',
            received=timezone.now(),
            is_scheduling_request=True,
            confidence=0.85,
            extracted_data={'location': 'Test Location'},
            event=self.event,
            processed_by=self.user
        )
        
        self.client.force_authenticate(user=self.user)
    
    def test_list_email_processing(self):
        """Test listing email processing records."""
        url = reverse('api:emailprocessing-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['subject'], 'Test Email Subject')
    
    def test_list_email_processing_with_event_filter(self):
        """Test listing email processing records filtered by event."""
        url = reverse('api:emailprocessing-list')
        response = self.client.get(url, {'event_id': str(self.event.id)})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        
        # Test with non-existent event
        response = self.client.get(url, {'event_id': str(uuid4())})
        self.assertEqual(len(response.data['results']), 0)
    
    def test_retrieve_email_processing(self):
        """Test retrieving a single email processing record."""
        url = reverse('api:emailprocessing-detail', kwargs={'pk': self.email_processing.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['subject'], 'Test Email Subject')
        self.assertEqual(response.data['confidence'], 0.85)
        self.assertIn('event', response.data)
        self.assertIn('processed_by', response.data)


class UtilityAPITests(APITestCase):
    """Test cases for utility API endpoints."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        make_office_member(self.user)
        self.client.force_authenticate(user=self.user)
    
    def test_event_choices(self):
        """Test getting event form choices."""
        url = reverse('api:event-choices')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('event_types', response.data)
        self.assertIn('event_statuses', response.data)
        self.assertIn('staff_recommendations', response.data)
        self.assertIn('hms_review_statuses', response.data)
        self.assertIn('data_classifications', response.data)
        
        # Verify choices are lists of tuples
        self.assertIsInstance(response.data['event_types'], list)
        if response.data['event_types']:
            self.assertIsInstance(response.data['event_types'][0], (list, tuple))
    
    def test_validate_event_data_valid(self):
        """Test validating valid event data."""
        url = reverse('api:validate-event')
        data = {
            'type': 'meeting',
            'start_date': (timezone.now() + timedelta(days=1)).date().isoformat(),
            'legislative_topics': ['Topic 1'],
            'participants': ['Person 1'],
            'staff': ['Staff 1']
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['valid'])
        self.assertIn('valid', response.data['message'])
    
    def test_validate_event_data_invalid(self):
        """Test validating invalid event data."""
        url = reverse('api:validate-event')
        data = {
            'type': 'invalid_type',
            'start_date': 'invalid_date',
            'legislative_topics': 'not_a_list'  # Should be a list
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data['valid'])
        self.assertIn('errors', response.data)


class APISerializerTests(TestCase):
    """Test cases for API serializers."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        make_office_member(self.user)
    
    def test_event_serializer_validation(self):
        """Test EventSerializer validation."""
        from apps.api.serializers import EventSerializer
        
        # Test valid data
        valid_data = {
            'type': 'meeting',
            'start_date': (timezone.now() + timedelta(days=1)).date(),
            'legislative_topics': ['Topic 1'],
            'participants': ['Person 1'],
            'staff': ['Staff 1']
        }
        
        serializer = EventSerializer(data=valid_data)
        self.assertTrue(serializer.is_valid())
        
        # Test invalid legislative_topics (not a list)
        invalid_data = valid_data.copy()
        invalid_data['legislative_topics'] = 'not a list'
        
        serializer = EventSerializer(data=invalid_data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('legislative_topics', serializer.errors)
    
    def test_email_processing_serializer_validation(self):
        """Test EmailProcessingSerializer validation."""
        from apps.api.serializers import EmailProcessingSerializer
        
        # Test valid data
        valid_data = {
            'email_id': 'test-email-id',
            'subject': 'Test Subject',
            'sender': 'test@example.com',
            'is_scheduling_request': True,
            'confidence': 0.85,
            'received': timezone.now(),
            'extracted_data': {'key': 'value'}
        }
        
        serializer = EmailProcessingSerializer(data=valid_data)
        self.assertTrue(serializer.is_valid())
        
        # Test invalid confidence (out of range)
        invalid_data = valid_data.copy()
        invalid_data['confidence'] = 1.5
        
        serializer = EmailProcessingSerializer(data=invalid_data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('confidence', serializer.errors)


class APIServiceTests(TestCase):
    """Test cases for API services."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        make_office_member(self.user)
        
        self.event = create_event(
            type='meeting',
            start_date=timezone.now() + timedelta(days=1),
            time='2:00 PM - 3:00 PM',
            location='Test Location',
            group='Test Group',
            details='Test event details',
            point_of_contact_name='Test Contact',
            point_of_contact_email='contact@example.com',
            original_email_id='test-email-id',
            created_by=self.user,
            modified_by=self.user
        )
    
    def test_smart_extract_service_generate_suggestions(self):
        """Test SmartExtractService suggestion generation (mock provider)."""
        from apps.api.services import SmartExtractService

        # LLM_PROVIDER defaults to 'mock' in tests; the deterministic mock
        # extracts from the provided content.
        service = SmartExtractService()
        suggestions = service.generate_suggestions(
            self.event,
            'Could we schedule a meeting on July 20 at 2pm in Conference Room A?'
        )

        self.assertIsInstance(suggestions, list)
        if suggestions:
            self.assertIn('field', suggestions[0])
            self.assertIn('value', suggestions[0])
            self.assertIn('confidence', suggestions[0])
    
    def test_smart_extract_service_approve_suggestion(self):
        """Test SmartExtractService suggestion approval."""
        from apps.api.services import SmartExtractService
        
        service = SmartExtractService()
        result = service.approve_suggestion(self.event, 'location', 'New Location', self.user)
        
        self.assertTrue(result)
        
        # Verify event was updated
        self.event.refresh_from_db()
        self.assertEqual(self.event.location, 'New Location')
        
        # Verify change history was created
        history = EventChangeHistory.objects.filter(event=self.event, field='location')
        self.assertTrue(history.exists())

class EmailTemplateModelTests(TestCase):
    """Regression: templates without placeholders must save (variables=[])."""

    def test_template_without_variables_saves(self) -> None:
        user = User.objects.create_user(username='tpl', email='tpl@example.com', password='x')
        template = EmailTemplate.objects.create(
            name='Plain reply', subject='Thanks', body='We received your request.',
            created_by=user, modified_by=user,
        )
        self.assertEqual(template.variables, [])
