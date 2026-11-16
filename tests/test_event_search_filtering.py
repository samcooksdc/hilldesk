# SPDX-License-Identifier: Apache-2.0
"""
Tests for event search and filtering functionality.
"""

import json
from datetime import timedelta
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone

from tests.factories import create_event, make_office_member

User = get_user_model()


class EventSearchFilteringTestCase(TestCase):
    """Test case for event search and filtering functionality."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        make_office_member(self.user)
        
        # Create test events with different attributes
        self.event1 = create_event(
            type='meeting',
            start_date=timezone.now() + timedelta(days=7),
            time='2:00 PM - 3:00 PM',
            location='Conference Room A',
            group='Healthcare Coalition',
            details='Discussion about healthcare policy',
            point_of_contact_name='John Doe',
            point_of_contact_email='john@healthcare.example',
            legislative_topics=['Healthcare', 'Insurance'],
            participants=['Dr. Smith', 'Nurse Johnson'],
            created_by=self.user,
            modified_by=self.user,
            status='received',
            staff_recommendation='3'
        )
        
        self.event2 = create_event(
            type='event',
            start_date=timezone.now() + timedelta(days=14),
            time='10:00 AM - 12:00 PM',
            location='Main Hall',
            group='Education Alliance',
            details='Education funding discussion',
            point_of_contact_name='Jane Smith',
            point_of_contact_email='jane@education.example',
            legislative_topics=['Education', 'Budget'],
            participants=['Principal Brown', 'Teacher Wilson'],
            created_by=self.user,
            modified_by=self.user,
            status='scheduled',
            staff_recommendation='1'
        )
        
        self.event3 = create_event(
            type='speaking',
            start_date=timezone.now() + timedelta(days=21),
            time='7:00 PM - 8:00 PM',
            location='Community Center',
            group='Environmental Group',
            details='Climate change presentation',
            point_of_contact_name='Bob Green',
            point_of_contact_email='bob@environment.example',
            legislative_topics=['Environment', 'Climate'],
            participants=['Scientist Davis', 'Activist Lee'],
            created_by=self.user,
            modified_by=self.user,
            status='hold',
            staff_recommendation='5'
        )
        
        self.client = Client()
        self.client.login(username='testuser', password='testpass123')
    
    def test_search_suggestions_api(self):
        """Test search suggestions API endpoint."""
        url = reverse('event_management:search_suggestions')
        
        # Organization names are encrypted, so suggestions cover location and topics.
        # Test location suggestions
        response = self.client.get(url, {'q': 'Conference', 'field': 'location'})
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertIn('Conference Room A', data['suggestions'])
        
        # Test topic suggestions
        response = self.client.get(url, {'q': 'Health', 'field': 'topic'})
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertIn('Healthcare', data['suggestions'])
    
    def test_filter_stats_api(self):
        """Test filter statistics API endpoint."""
        url = reverse('event_management:filter_stats')
        
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        
        self.assertIn('total_filtered', data)
        self.assertIn('status_breakdown', data)
        self.assertIn('type_breakdown', data)
        self.assertEqual(data['total_filtered'], 3)  # All three events
        
        # Test with filters applied
        response = self.client.get(url, {'status': 'received'})
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data['total_filtered'], 1)  # Only one received event
    
    def test_advanced_search_api(self):
        """Test advanced search API endpoint."""
        url = reverse('event_management:advanced_search')
        
        # Test basic search
        response = self.client.get(url, {'q': 'Healthcare'})
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        
        self.assertIn('events', data)
        self.assertIn('pagination', data)
        self.assertEqual(len(data['events']), 1)
        self.assertEqual(data['events'][0]['group'], 'Healthcare Coalition')
        
        # Test with filters
        response = self.client.get(url, {'status': 'scheduled'})
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(len(data['events']), 1)
        self.assertEqual(data['events'][0]['group'], 'Education Alliance')
    
    def test_export_functionality(self):
        """Test CSV export functionality."""
        url = reverse('event_management:export_events')
        
        # Test basic export
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv')
        self.assertIn('attachment', response['Content-Disposition'])
        
        # Check CSV content
        content = response.content.decode('utf-8')
        self.assertIn('Healthcare Coalition', content)
        self.assertIn('Education Alliance', content)
        self.assertIn('Environmental Group', content)
        
        # Test export with filters
        response = self.client.get(url, {'status': 'received'})
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertIn('Healthcare Coalition', content)
        self.assertNotIn('Education Alliance', content)

    def test_search_endpoints_respect_role_scope(self):
        """A signed-in user with no role sees no events through search or export."""
        outsider = User.objects.create_user(username='outsider', email='o@example.com', password='pw12345678')
        self.client.force_login(outsider)
        data = json.loads(self.client.get(reverse('event_management:advanced_search'), {'q': ''}).content)
        self.assertEqual(data['pagination']['total_count'], 0)
        stats = json.loads(self.client.get(reverse('event_management:filter_stats')).content)
        self.assertEqual(stats['total_filtered'], 0)
        csv_body = self.client.get(reverse('event_management:export_events')).content.decode()
        self.assertEqual(len(csv_body.strip().splitlines()), 1)  # header only
