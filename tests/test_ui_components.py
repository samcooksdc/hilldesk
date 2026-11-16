# SPDX-License-Identifier: Apache-2.0
"""
Tests for UI components implemented in tasks 5.1-5.7.

This module tests the user interface components including base templates,
dashboard, inbox, schedule views, calendar, archive, and settings.
"""

import pytest
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta

from tests.factories import create_event, make_office_member

User = get_user_model()


class BaseTemplateTests(TestCase):
    """Tests for base template and layout functionality."""
    
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123',
            first_name='Test',
            last_name='User'
        )
        self.client.login(username='testuser', password='testpass123')
    
    def test_base_template_renders(self):
        """Test that base template renders correctly."""
        response = self.client.get(reverse('event_management:dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Congressional Staff Scheduling')
        self.assertContains(response, 'Test User')  # User name in header
    
    def test_navigation_links(self):
        """Test that navigation links are present."""
        response = self.client.get(reverse('event_management:dashboard'))
        for label in ('Dashboard', 'Inbox', 'Calendar', 'Events', 'Contacts', 'Settings'):
            self.assertContains(response, label)
    
    
    def test_accent_color_application(self):
        """Test that accent color preferences are applied."""
        # Test blue accent (default)
        # base.html seeds the client-side accent from the saved preference.
        response = self.client.get(reverse('event_management:dashboard'))
        self.assertContains(response, "var accent = 'blue'")
        
        # Change to red accent
        self.user.accent_color = 'red'
        self.user.save()
        
        response = self.client.get(reverse('event_management:dashboard'))
        self.assertContains(response, "var accent = 'red'")


class DashboardViewTests(TestCase):
    """Tests for dashboard view functionality."""
    
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        make_office_member(self.user)  # dashboard lists only events the role may see
        self.client.login(username='testuser', password='testpass123')
        
        # Create test events
        self.upcoming_event = create_event(
            type='meeting',
            start_date=timezone.now() + timedelta(days=1),
            time='2:00 PM',
            location='Conference Room',
            group='Test Group',
            details='Test meeting',
            point_of_contact_name='John Doe',
            point_of_contact_email='john@example.com',
            created_by=self.user,
            modified_by=self.user
        )
        
        self.past_event = create_event(
            type='event',
            start_date=timezone.now() - timedelta(days=1),
            time='10:00 AM',
            location='Main Hall',
            group='Past Group',
            details='Past event',
            point_of_contact_name='Jane Doe',
            point_of_contact_email='jane@example.com',
            created_by=self.user,
            modified_by=self.user
        )
    
    def test_dashboard_renders(self):
        """Test that dashboard renders correctly."""
        response = self.client.get(reverse('event_management:dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Dashboard')
    
    
    def test_upcoming_events_display(self):
        """Test that upcoming events are displayed correctly."""
        response = self.client.get(reverse('event_management:dashboard'))
        
        # Should show upcoming event
        self.assertContains(response, 'Test Group')
        self.assertContains(response, 'Conference Room')
        
        # Should not show past event in upcoming section
        self.assertNotContains(response, 'Past Group')
    


class ScheduleViewTests(TestCase):
    """Tests for schedule view functionality."""
    
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.client.login(username='testuser', password='testpass123')
        
        # Create test events
        self.event1 = create_event(
            type='meeting',
            start_date=timezone.now() + timedelta(days=1),
            time='2:00 PM',
            location='Room A',
            group='Group A',
            details='Meeting A',
            status='received',
            point_of_contact_name='Contact A',
            point_of_contact_email='a@example.com',
            created_by=self.user,
            modified_by=self.user
        )
        
        self.event2 = create_event(
            type='event',
            start_date=timezone.now() + timedelta(days=2),
            time='10:00 AM',
            location='Room B',
            group='Group B',
            details='Event B',
            status='scheduled',
            point_of_contact_name='Contact B',
            point_of_contact_email='b@example.com',
            created_by=self.user,
            modified_by=self.user
        )
    
    def test_schedule_list_view(self):
        """Test schedule list view renders correctly."""
        response = self.client.get(reverse('event_management:events'))
        # Rows are loaded client-side from the events API (covered by the API tests).
        self.assertEqual(response.status_code, 200)
    
    
    


class CalendarViewTests(TestCase):
    """Tests for calendar view functionality."""
    
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.client.login(username='testuser', password='testpass123')
        
        # Create test event
        self.event = create_event(
            type='meeting',
            start_date=timezone.now() + timedelta(days=1),
            time='2:00 PM',
            location='Conference Room',
            group='Test Meeting',
            details='Test meeting details',
            point_of_contact_name='John Doe',
            point_of_contact_email='john@example.com',
            created_by=self.user,
            modified_by=self.user
        )
    
    def test_calendar_view_renders(self):
        """Test that calendar view renders correctly."""
        response = self.client.get(reverse('event_management:event_calendar'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Calendar')
    




class SettingsViewTests(TestCase):
    """Tests for settings view functionality."""
    
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123',
            first_name='Test',
            last_name='User'
        )
        self.client.login(username='testuser', password='testpass123')
    
    def test_settings_page_renders(self):
        """Test that settings page renders correctly."""
        response = self.client.get(reverse('event_management:settings'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Settings')
        self.assertContains(response, 'Appearance')
        self.assertContains(response, 'Profile')
        self.assertContains(response, 'Notifications')
    
    def test_update_preferences(self):
        """Test updating user preferences."""
        response = self.client.post(reverse('event_management:update_preferences'), {
            'section': 'appearance',
            'theme': 'dark',
            'accent_color': 'red',
            'default_view': 'calendar'
        })
        
        self.assertEqual(response.status_code, 302)  # Redirect after success
        
        # Check that preferences were updated
        self.user.refresh_from_db()
        # The theme toggle was removed; the view deliberately ignores 'theme'.
        self.assertEqual(self.user.theme, 'light')
        self.assertEqual(self.user.accent_color, 'red')
        self.assertEqual(self.user.default_view, 'calendar')
    
    def test_update_profile(self):
        """Test updating user profile."""
        response = self.client.post(reverse('event_management:update_profile'), {
            'first_name': 'Updated',
            'last_name': 'Name',
            'email': 'updated@example.com',
            'username': 'updateduser'
        })
        
        self.assertEqual(response.status_code, 302)  # Redirect after success
        
        # Check that profile was updated
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, 'Updated')
        self.assertEqual(self.user.last_name, 'Name')
        self.assertEqual(self.user.email, 'updated@example.com')
        self.assertEqual(self.user.username, 'updateduser')
    
    def test_update_notifications(self):
        """Test updating notification preferences."""
        response = self.client.post(reverse('event_management:update_notifications'), {
            'notify_email_processing': 'on',
            'notify_event_reminders': 'on'
            # notify_status_changes and notify_system_updates not included (should be False)
        })
        
        self.assertEqual(response.status_code, 302)  # Redirect after success
        
        # Check that notification preferences were updated
        self.user.refresh_from_db()
        self.assertTrue(self.user.notify_email_processing)
        self.assertTrue(self.user.notify_event_reminders)
        self.assertFalse(self.user.notify_status_changes)
        self.assertFalse(self.user.notify_system_updates)
    
    def test_export_user_data(self):
        """Test exporting user data."""
        # Create some test data
        create_event(
            type='meeting',
            start_date=timezone.now() + timedelta(days=1),
            time='2:00 PM',
            location='Test Location',
            group='Test Group',
            details='Test details',
            point_of_contact_name='Test Contact',
            point_of_contact_email='contact@example.com',
            created_by=self.user,
            modified_by=self.user
        )
        
        response = self.client.get(reverse('event_management:export_user_data'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')
        self.assertIn('attachment', response['Content-Disposition'])


class ResponsiveDesignTests(TestCase):
    """Tests for responsive design functionality."""
    
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.client.login(username='testuser', password='testpass123')
    
    def test_mobile_viewport(self):
        """Test that mobile viewport meta tag is present."""
        response = self.client.get(reverse('event_management:dashboard'))
        self.assertContains(response, 'viewport')
        self.assertContains(response, 'width=device-width')
    


class AccessibilityTests(TestCase):
    """Tests for accessibility compliance."""
    
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.client.login(username='testuser', password='testpass123')
    
    def test_semantic_html(self):
        """Test that semantic HTML elements are used."""
        response = self.client.get(reverse('event_management:dashboard'))
        self.assertContains(response, '<main')
        self.assertContains(response, '<nav')
    
    def test_form_labels(self):
        """Test that form elements have proper labels."""
        response = self.client.get(reverse('event_management:settings'))
        self.assertContains(response, '<label')
        self.assertContains(response, 'for=')
    
    def test_alt_attributes(self):
        """Test that images have alt attributes."""
        response = self.client.get(reverse('event_management:dashboard'))
        # Check that any img tags have alt attributes
        if '<img' in response.content.decode():
            self.assertContains(response, 'alt=')
    
    def test_aria_labels(self):
        """Test that ARIA labels are used where appropriate."""
        response = self.client.get(reverse('event_management:settings'))
        # Check for ARIA attributes in complex UI elements
        if 'tab' in response.content.decode():
            self.assertContains(response, 'role=')


class SecurityTests(TestCase):
    """Tests for security features in UI components."""
    
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
    
    def test_login_required(self):
        """Test that login is required for all views."""
        # Test without login
        response = self.client.get(reverse('event_management:dashboard'))
        self.assertEqual(response.status_code, 302)  # Redirect to login
        
        response = self.client.get(reverse('event_management:settings'))
        self.assertEqual(response.status_code, 302)  # Redirect to login
    
    def test_csrf_protection(self):
        """Test that CSRF protection is enabled."""
        from django.test import Client
        self.client = Client(enforce_csrf_checks=True)  # the default test client skips CSRF
        self.client.login(username='testuser', password='testpass123')
        
        # Test POST without CSRF token
        response = self.client.post(reverse('event_management:update_preferences'), {
            'section': 'appearance',
            'theme': 'dark'
        })
        self.assertEqual(response.status_code, 403)  # CSRF failure
    
    def test_user_isolation(self):
        """Test that users can only access their own data."""
        # Create another user
        other_user = User.objects.create_user(
            username='otheruser',
            email='other@example.com',
            password='otherpass123'
        )
        
        # Create event for other user
        other_event = create_event(
            type='meeting',
            start_date=timezone.now() + timedelta(days=1),
            time='2:00 PM',
            location='Other Room',
            group='Other Group',
            details='Other details',
            point_of_contact_name='Other Contact',
            point_of_contact_email='other@example.com',
            created_by=other_user,
            modified_by=other_user
        )
        
        # Login as first user
        self.client.login(username='testuser', password='testpass123')
        
        # Try to access other user's event
        response = self.client.get(reverse('event_management:event_detail', kwargs={'pk': other_event.pk}))
        # Event pages use the role scope: a user who isn't assigned can't open it.
        self.assertEqual(response.status_code, 404)


if __name__ == '__main__':
    pytest.main([__file__])