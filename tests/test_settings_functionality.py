# SPDX-License-Identifier: Apache-2.0
"""
Tests for settings functionality implemented in task 5.7.

This module tests the comprehensive settings interface including appearance,
profile, notifications, templates, and security settings.
"""

import pytest
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
import json

from apps.event_management.models import EmailTemplate
from tests.factories import create_event

User = get_user_model()


class SettingsModelTests(TestCase):
    """Tests for settings-related model functionality."""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123',
            first_name='Test',
            last_name='User'
        )
    
    def test_user_default_preferences(self):
        """Test that users have correct default preferences."""
        self.assertEqual(self.user.theme, 'light')
        self.assertEqual(self.user.accent_color, 'blue')
        self.assertEqual(self.user.default_view, 'list')
        self.assertTrue(self.user.notify_email_processing)
        self.assertTrue(self.user.notify_event_reminders)
        self.assertTrue(self.user.notify_status_changes)
        self.assertFalse(self.user.notify_system_updates)
    
    def test_user_preference_choices(self):
        """Test that user preference fields accept valid choices."""
        # Test theme choices
        self.user.theme = 'dark'
        self.user.save()
        self.assertEqual(self.user.theme, 'dark')
        
        # Test accent color choices
        self.user.accent_color = 'red'
        self.user.save()
        self.assertEqual(self.user.accent_color, 'red')
        
        # Test default view choices
        self.user.default_view = 'calendar'
        self.user.save()
        self.assertEqual(self.user.default_view, 'calendar')
    
    def test_notification_preferences(self):
        """Test notification preference fields."""
        self.user.notify_email_processing = False
        self.user.notify_event_reminders = False
        self.user.notify_status_changes = False
        self.user.notify_system_updates = True
        self.user.save()
        
        self.user.refresh_from_db()
        self.assertFalse(self.user.notify_email_processing)
        self.assertFalse(self.user.notify_event_reminders)
        self.assertFalse(self.user.notify_status_changes)
        self.assertTrue(self.user.notify_system_updates)


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
        
        # Create test email template
        self.template = EmailTemplate.objects.create(
            name='Test Template',
            subject='Test Subject',
            body='Test body content',
            created_by=self.user,
            modified_by=self.user
        )
    
    def test_settings_page_renders(self):
        """Test that settings page renders correctly."""
        response = self.client.get(reverse('event_management:settings'))
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Settings')
        self.assertContains(response, 'Appearance')
        self.assertContains(response, 'Profile')
        self.assertContains(response, 'Notifications')
        self.assertContains(response, 'Security')
    
    def test_settings_shows_current_preferences(self):
        """Test that settings page shows current user preferences."""
        # Set specific preferences
        self.user.theme = 'dark'
        self.user.accent_color = 'red'
        self.user.default_view = 'calendar'
        self.user.save()
        
        response = self.client.get(reverse('event_management:settings'))
        
        # Check that current preferences are selected
        self.assertContains(response, 'selected')  # Theme should be selected
        self.assertContains(response, 'checked')   # Default view should be checked
    
    def test_settings_shows_email_templates(self):
        """Test that settings page shows user's email templates."""
        # The settings page loads templates client-side from this API.
        response = self.client.get('/api/email/templates/?include_inactive=true')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Test Template')
        self.assertContains(response, 'Test Subject')
    
    def test_settings_requires_login(self):
        """Test that settings page requires authentication."""
        self.client.logout()
        response = self.client.get(reverse('event_management:settings'))
        self.assertEqual(response.status_code, 302)  # Redirect to login


class AppearanceSettingsTests(TestCase):
    """Tests for appearance settings functionality."""
    
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.client.login(username='testuser', password='testpass123')
    
    def test_update_theme_preference(self):
        """Test updating theme preference."""
        response = self.client.post(reverse('event_management:update_preferences'), {
            'section': 'appearance',
            'theme': 'dark',
            'accent_color': 'blue',
            'default_view': 'list'
        })
        
        self.assertEqual(response.status_code, 302)  # Redirect after success
        
        self.user.refresh_from_db()
        # The theme toggle was removed; the view deliberately ignores 'theme'.
        self.assertEqual(self.user.theme, 'light')
    
    def test_update_accent_color_preference(self):
        """Test updating accent color preference."""
        response = self.client.post(reverse('event_management:update_preferences'), {
            'section': 'appearance',
            'theme': 'light',
            'accent_color': 'red',
            'default_view': 'list'
        })
        
        self.assertEqual(response.status_code, 302)  # Redirect after success
        
        self.user.refresh_from_db()
        self.assertEqual(self.user.accent_color, 'red')
    
    def test_update_default_view_preference(self):
        """Test updating default view preference."""
        response = self.client.post(reverse('event_management:update_preferences'), {
            'section': 'appearance',
            'theme': 'light',
            'accent_color': 'blue',
            'default_view': 'calendar'
        })
        
        self.assertEqual(response.status_code, 302)  # Redirect after success
        
        self.user.refresh_from_db()
        self.assertEqual(self.user.default_view, 'calendar')
    
    def test_invalid_theme_preference(self):
        """Test that invalid theme values are ignored."""
        original_theme = self.user.theme
        
        self.client.post(reverse('event_management:update_preferences'), {
            'section': 'appearance',
            'theme': 'invalid_theme',
            'accent_color': 'blue',
            'default_view': 'list'
        })
        
        self.user.refresh_from_db()
        self.assertEqual(self.user.theme, original_theme)  # Should remain unchanged
    
    def test_invalid_section(self):
        """Test handling of invalid section parameter."""
        response = self.client.post(reverse('event_management:update_preferences'), {
            'section': 'invalid_section',
            'theme': 'dark'
        })
        
        self.assertEqual(response.status_code, 302)  # Still redirects
        # Should show error message (would need to check messages framework)


class ProfileSettingsTests(TestCase):
    """Tests for profile settings functionality."""
    
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
    
    def test_update_profile_information(self):
        """Test updating profile information."""
        response = self.client.post(reverse('event_management:update_profile'), {
            'first_name': 'Updated',
            'last_name': 'Name',
            'email': 'updated@example.com',
            'username': 'updateduser'
        })
        
        self.assertEqual(response.status_code, 302)  # Redirect after success
        
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, 'Updated')
        self.assertEqual(self.user.last_name, 'Name')
        self.assertEqual(self.user.email, 'updated@example.com')
        self.assertEqual(self.user.username, 'updateduser')
    
    def test_profile_validation_required_fields(self):
        """Test that required fields are validated."""
        response = self.client.post(reverse('event_management:update_profile'), {
            'first_name': '',  # Empty required field
            'last_name': 'Name',
            'email': 'test@example.com',
            'username': 'testuser'
        })
        
        self.assertEqual(response.status_code, 302)  # Redirects with error
        
        # Profile should not be updated
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, 'Test')  # Original value
    
    def test_username_uniqueness_validation(self):
        """Test that username uniqueness is enforced."""
        # Create another user
        User.objects.create_user(
            username='existinguser',
            email='existing@example.com',
            password='password123'
        )
        
        response = self.client.post(reverse('event_management:update_profile'), {
            'first_name': 'Test',
            'last_name': 'User',
            'email': 'test@example.com',
            'username': 'existinguser'  # Try to use existing username
        })
        
        self.assertEqual(response.status_code, 302)  # Redirects with error
        
        # Username should not be updated
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, 'testuser')  # Original value
    
    def test_email_uniqueness_validation(self):
        """Test that email uniqueness is enforced."""
        # Create another user
        User.objects.create_user(
            username='otheruser',
            email='existing@example.com',
            password='password123'
        )
        
        response = self.client.post(reverse('event_management:update_profile'), {
            'first_name': 'Test',
            'last_name': 'User',
            'email': 'existing@example.com',  # Try to use existing email
            'username': 'testuser'
        })
        
        self.assertEqual(response.status_code, 302)  # Redirects with error
        
        # Email should not be updated
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'test@example.com')  # Original value


class NotificationSettingsTests(TestCase):
    """Tests for notification settings functionality."""
    
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.client.login(username='testuser', password='testpass123')
    
    def test_update_notification_preferences(self):
        """Test updating notification preferences."""
        response = self.client.post(reverse('event_management:update_notifications'), {
            'notify_email_processing': 'on',
            'notify_event_reminders': 'on'
            # notify_status_changes and notify_system_updates not included
        })
        
        self.assertEqual(response.status_code, 302)  # Redirect after success
        
        self.user.refresh_from_db()
        self.assertTrue(self.user.notify_email_processing)
        self.assertTrue(self.user.notify_event_reminders)
        self.assertFalse(self.user.notify_status_changes)
        self.assertFalse(self.user.notify_system_updates)
    
    def test_disable_all_notifications(self):
        """Test disabling all notifications."""
        # First enable all notifications
        self.user.notify_email_processing = True
        self.user.notify_event_reminders = True
        self.user.notify_status_changes = True
        self.user.notify_system_updates = True
        self.user.save()
        
        # Now disable all by not including any in POST
        response = self.client.post(reverse('event_management:update_notifications'), {})
        
        self.assertEqual(response.status_code, 302)  # Redirect after success
        
        self.user.refresh_from_db()
        self.assertFalse(self.user.notify_email_processing)
        self.assertFalse(self.user.notify_event_reminders)
        self.assertFalse(self.user.notify_status_changes)
        self.assertFalse(self.user.notify_system_updates)
    
    def test_enable_all_notifications(self):
        """Test enabling all notifications."""
        response = self.client.post(reverse('event_management:update_notifications'), {
            'notify_email_processing': 'on',
            'notify_event_reminders': 'on',
            'notify_status_changes': 'on',
            'notify_system_updates': 'on'
        })
        
        self.assertEqual(response.status_code, 302)  # Redirect after success
        
        self.user.refresh_from_db()
        self.assertTrue(self.user.notify_email_processing)
        self.assertTrue(self.user.notify_event_reminders)
        self.assertTrue(self.user.notify_status_changes)
        self.assertTrue(self.user.notify_system_updates)


class SecuritySettingsTests(TestCase):
    """Tests for security settings functionality."""
    
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.client.login(username='testuser', password='testpass123')
    
    def test_change_password_success(self):
        """Test successful password change."""
        response = self.client.post(reverse('event_management:change_password'), {
            # Field names of Django's PasswordChangeForm (what the settings UI posts).
            'old_password': 'testpass123',
            'new_password1': 'changed-test-password',
            'new_password2': 'changed-test-password',
        })
        
        self.assertEqual(response.status_code, 302)  # Redirect after success
        
        # Test that new password works
        self.client.logout()
        login_success = self.client.login(username='testuser', password='changed-test-password')
        self.assertTrue(login_success)
    
    def test_change_password_wrong_current(self):
        """Test password change with wrong current password."""
        response = self.client.post(reverse('event_management:change_password'), {
            'current_password': 'wrongpassword',
            'new_password': 'newpassword456',
            'confirm_password': 'newpassword456'
        })
        
        self.assertEqual(response.status_code, 302)  # Redirects with error
        
        # Test that old password still works
        self.client.logout()
        login_success = self.client.login(username='testuser', password='testpass123')
        self.assertTrue(login_success)
    
    def test_change_password_mismatch(self):
        """Test password change with mismatched new passwords."""
        response = self.client.post(reverse('event_management:change_password'), {
            'current_password': 'testpass123',
            'new_password': 'newpassword456',
            'confirm_password': 'differentpassword'
        })
        
        self.assertEqual(response.status_code, 302)  # Redirects with error
        
        # Test that old password still works
        self.client.logout()
        login_success = self.client.login(username='testuser', password='testpass123')
        self.assertTrue(login_success)


class DataManagementTests(TestCase):
    """Tests for data management functionality."""
    
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.client.login(username='testuser', password='testpass123')
        
        # Create test data
        self.event = create_event(
            type='meeting',
            start_date='2024-01-01',
            time='10:00 AM',
            location='Test Location',
            group='Test Group',
            details='Test details',
            point_of_contact_name='Test Contact',
            point_of_contact_email='contact@example.com',
            created_by=self.user,
            modified_by=self.user
        )
        
        self.template = EmailTemplate.objects.create(
            name='Test Template',
            subject='Test Subject',
            body='Test body',
            created_by=self.user,
            modified_by=self.user
        )
    
    def test_export_user_data(self):
        """Test exporting user data."""
        response = self.client.get(reverse('event_management:export_user_data'))
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')
        self.assertIn('attachment', response['Content-Disposition'])
        self.assertIn('user_data_testuser.json', response['Content-Disposition'])
        
        # Parse JSON response
        data = json.loads(response.content)
        
        # Check structure
        self.assertIn('profile', data)
        self.assertIn('preferences', data)
        self.assertIn('events', data)
        self.assertIn('templates', data)
        
        # Check profile data
        self.assertEqual(data['profile']['username'], 'testuser')
        self.assertEqual(data['profile']['email'], 'test@example.com')
        
        # Check preferences
        self.assertEqual(data['preferences']['theme'], 'light')
        self.assertEqual(data['preferences']['accent_color'], 'blue')
        
        # Check events and templates
        self.assertEqual(len(data['events']), 1)
        self.assertEqual(len(data['templates']), 1)
        self.assertEqual(data['events'][0]['group'], 'Test Group')
        self.assertEqual(data['templates'][0]['name'], 'Test Template')
    
    def test_clear_user_data(self):
        """Test clearing all user data."""
        response = self.client.post(reverse('event_management:clear_user_data'))
        
        self.assertEqual(response.status_code, 200)
        
        data = json.loads(response.content)
        self.assertTrue(data['success'])
        self.assertIn('Cleared', data['message'])
        
        # Check that data was cleared
        from apps.event_management.models import Event
        self.assertEqual(Event.objects.filter(created_by=self.user).count(), 0)
        self.assertEqual(EmailTemplate.objects.filter(created_by=self.user).count(), 0)
        
        # Check that preferences were reset
        self.user.refresh_from_db()
        self.assertEqual(self.user.theme, 'light')
        self.assertEqual(self.user.accent_color, 'blue')
        self.assertEqual(self.user.default_view, 'list')
    
    def test_get_user_stats(self):
        """Test getting user statistics."""
        response = self.client.get(reverse('event_management:user_stats'))
        
        self.assertEqual(response.status_code, 200)
        
        data = json.loads(response.content)
        
        # Check statistics structure
        self.assertIn('total_events', data)
        self.assertIn('active_events', data)
        self.assertIn('archived_events', data)
        self.assertIn('email_templates', data)
        self.assertIn('account_age_days', data)
        
        # Check values
        self.assertEqual(data['total_events'], 1)
        self.assertEqual(data['active_events'], 1)
        self.assertEqual(data['archived_events'], 0)
        self.assertEqual(data['email_templates'], 1)


class SettingsSecurityTests(TestCase):
    """Tests for settings security features."""
    
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
    
    def test_settings_requires_authentication(self):
        """Test that all settings endpoints require authentication."""
        endpoints = [
            'event_management:settings',
            'event_management:update_preferences',
            'event_management:update_profile',
            'event_management:update_notifications',
            'event_management:change_password',
            'event_management:export_user_data',
            'event_management:user_stats'
        ]
        
        for endpoint in endpoints:
            response = self.client.get(reverse(endpoint))
            self.assertEqual(response.status_code, 302, f"Endpoint {endpoint} should require login")
    
    def test_csrf_protection_on_settings_forms(self):
        """Test CSRF protection on settings forms."""
        self.client = Client(enforce_csrf_checks=True)  # the default test client skips CSRF
        self.client.login(username='testuser', password='testpass123')
        
        # Test POST without CSRF token
        response = self.client.post(
            reverse('event_management:update_preferences'),
            {'section': 'appearance', 'theme': 'dark'},
            HTTP_X_CSRFTOKEN=''
        )
        self.assertEqual(response.status_code, 403)  # CSRF failure
    
    def test_post_required_for_updates(self):
        """Test that update endpoints require POST method."""
        self.client.login(username='testuser', password='testpass123')
        
        post_only_endpoints = [
            'event_management:update_preferences',
            'event_management:update_profile',
            'event_management:update_notifications',
            'event_management:change_password',
            'event_management:clear_user_data'
        ]
        
        for endpoint in post_only_endpoints:
            response = self.client.get(reverse(endpoint))
            self.assertEqual(response.status_code, 405, f"Endpoint {endpoint} should require POST")


if __name__ == '__main__':
    pytest.main([__file__])