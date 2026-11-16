# SPDX-License-Identifier: Apache-2.0
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import timedelta
import uuid

from .models import Event, EventChangeHistory, EmailTemplate
from tests.factories import build_event, create_event

User = get_user_model()


class EventModelTest(TestCase):
    """Test cases for the Event model."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        self.event_data = {
            'type': 'meeting',
            'start_date': timezone.now() + timedelta(days=1),
            'time': '2:00 PM - 3:00 PM',
            'location': '2411 RHOB',
            'group': 'Healthcare Coalition',
            'details': 'Discussion about healthcare policy',
            'legislative_topics': ['Healthcare', 'Medicare'],
            'participants': ['Dr. Smith', 'Nurse Johnson'],
            'point_of_contact_name': 'John Doe',
            'point_of_contact_email': 'john@example.com',
            'point_of_contact_phone': '555-1234',
            'created_by': self.user,
            'modified_by': self.user,
        }
    
    def test_create_event(self):
        """Test creating an event with required fields."""
        event = create_event(**self.event_data)
        
        self.assertEqual(event.type, 'meeting')
        self.assertEqual(event.location, '2411 RHOB')
        self.assertEqual(event.group, 'Healthcare Coalition')
        self.assertEqual(event.status, 'received')  # Default status
        self.assertEqual(event.data_classification, 'internal')  # Default classification
        self.assertIsInstance(event.id, uuid.UUID)
        self.assertIsInstance(event.legislative_topics, list)
        self.assertIsInstance(event.participants, list)
        self.assertIsInstance(event.staff, list)
    
    def test_event_str_representation(self):
        """Test the string representation of the event."""
        event = create_event(**self.event_data)
        expected_str = f"Meeting: Healthcare Coalition - {event.start_date.strftime('%Y-%m-%d')}"
        self.assertEqual(str(event), expected_str)
    
    def test_event_uuid_primary_key(self):
        """Test that event uses UUID as primary key."""
        event = create_event(**self.event_data)
        self.assertIsInstance(event.id, uuid.UUID)
        self.assertIsInstance(event.pk, uuid.UUID)
    
    def test_event_audit_fields(self):
        """Test that audit fields are automatically populated."""
        event = create_event(**self.event_data)
        
        self.assertIsNotNone(event.created)
        self.assertIsNotNone(event.modified)
        self.assertEqual(event.created_by, self.user)
        self.assertEqual(event.modified_by, self.user)
        self.assertLessEqual(event.created, event.modified)
    
    def test_event_json_fields_default(self):
        """Test that JSON fields have proper default values."""
        event = create_event(**self.event_data)
        
        self.assertIsInstance(event.legislative_topics, list)
        self.assertIsInstance(event.participants, list)
        self.assertIsInstance(event.staff, list)
        
        # Test with custom values
        event.legislative_topics = ['Topic 1', 'Topic 2']
        event.participants = ['Person 1', 'Person 2']
        event.staff = ['Staff 1', 'Staff 2']
        event.save()
        
        event.refresh_from_db()
        self.assertEqual(event.legislative_topics, ['Topic 1', 'Topic 2'])
        self.assertEqual(event.participants, ['Person 1', 'Person 2'])
        self.assertEqual(event.staff, ['Staff 1', 'Staff 2'])
    
    def test_event_validation_end_date_after_start_date(self):
        """Test that end_date must be after start_date."""
        event_data = self.event_data.copy()
        event_data['end_date'] = event_data['start_date'] - timedelta(hours=1)
        
        event = build_event(**event_data)
        with self.assertRaises(ValidationError):
            event.clean()
    
    def test_event_validation_json_fields(self):
        """Test validation of JSON fields."""
        event = create_event(**self.event_data)
        
        # Test invalid legislative_topics
        event.legislative_topics = "not a list"
        with self.assertRaises(ValidationError):
            event.clean()
        
        # Test invalid participants
        event.legislative_topics = []  # Reset to valid
        event.participants = "not a list"
        with self.assertRaises(ValidationError):
            event.clean()
        
        # Test invalid staff
        event.participants = []  # Reset to valid
        event.staff = "not a list"
        with self.assertRaises(ValidationError):
            event.clean()
    
    def test_event_save_calls_clean(self):
        """Test that save() calls clean() for validation."""
        event_data = self.event_data.copy()
        # start/end are date-only fields, so the end must fall on an earlier day.
        event_data['end_date'] = event_data['start_date'] - timedelta(days=1)
        
        event = build_event(**event_data)
        with self.assertRaises(ValidationError):
            event.save()
    
    def test_event_is_upcoming_property(self):
        """Test the is_upcoming property."""
        # Future event
        future_event_data = self.event_data.copy()
        future_event_data['start_date'] = timezone.now() + timedelta(days=1)
        future_event = create_event(**future_event_data)
        self.assertTrue(future_event.is_upcoming)
        
        # Past event
        past_event_data = self.event_data.copy()
        past_event_data['start_date'] = timezone.now() - timedelta(days=1)
        past_event = create_event(**past_event_data)
        self.assertFalse(past_event.is_upcoming)
        
        # Today's event
        today_event_data = self.event_data.copy()
        today_event_data['start_date'] = timezone.now().replace(hour=23, minute=59)
        today_event = create_event(**today_event_data)
        self.assertTrue(today_event.is_upcoming)
    
    def test_event_is_past_property(self):
        """Test the is_past property."""
        # Future event
        future_event_data = self.event_data.copy()
        future_event_data['start_date'] = timezone.now() + timedelta(days=1)
        future_event = create_event(**future_event_data)
        self.assertFalse(future_event.is_past)
        
        # Past event
        past_event_data = self.event_data.copy()
        past_event_data['start_date'] = timezone.now() - timedelta(days=1)
        past_event = create_event(**past_event_data)
        self.assertTrue(past_event.is_past)
    
    def test_event_status_choices(self):
        """Test event status field choices."""
        event = create_event(**self.event_data)
        
        # Test valid statuses
        valid_statuses = [
            'received', 'hold', 'referred', 'fyied', 'scheduling_in_progress',
            'scheduled', 'rsvped', 'regrets_sent', 'passed', 'canceled',
            'requires_hms_review'
        ]
        
        for status in valid_statuses:
            event.status = status
            event.save()
            event.refresh_from_db()
            self.assertEqual(event.status, status)
    
    def test_event_type_choices(self):
        """Test event type field choices."""
        event = create_event(**self.event_data)
        
        # Test valid types
        valid_types = ['event', 'meeting', 'speaking']
        
        for event_type in valid_types:
            event.type = event_type
            event.save()
            event.refresh_from_db()
            self.assertEqual(event.type, event_type)
    
    def test_event_data_classification_choices(self):
        """Test event data classification field choices."""
        event = create_event(**self.event_data)
        
        # Test valid classifications
        valid_classifications = ['public', 'internal', 'sensitive', 'restricted']
        
        for classification in valid_classifications:
            event.data_classification = classification
            event.save()
            event.refresh_from_db()
            self.assertEqual(event.data_classification, classification)
    
    def test_event_staff_recommendation_choices(self):
        """Test staff recommendation field choices."""
        event = create_event(**self.event_data)
        
        # Test valid recommendations
        valid_recommendations = ['1', '2', '3', '4', '5', '6', '7', '8', '9', 'pass']
        
        for recommendation in valid_recommendations:
            event.staff_recommendation = recommendation
            event.save()
            event.refresh_from_db()
            self.assertEqual(event.staff_recommendation, recommendation)
    
    def test_event_hms_review_status_choices(self):
        """Test HMS review status field choices."""
        event = create_event(**self.event_data)
        
        # Test valid HMS review statuses
        valid_statuses = ['yes', 'complete']
        
        for status in valid_statuses:
            event.hms_review_status = status
            event.save()
            event.refresh_from_db()
            self.assertEqual(event.hms_review_status, status)
    
    def test_event_meta_options(self):
        """Test Event model meta options."""
        create_event(**self.event_data)
        
        # Test db_table
        self.assertEqual(Event._meta.db_table, 'events')
        
        # Test verbose names
        self.assertEqual(Event._meta.verbose_name, 'Event')
        self.assertEqual(Event._meta.verbose_name_plural, 'Events')
        
        # Test ordering
        self.assertEqual(Event._meta.ordering, ['-start_date'])
    
    def test_event_indexes(self):
        """Test that proper indexes are created."""
        # This test verifies that the model defines indexes
        # The actual index creation is tested by Django's migration system
        indexes = Event._meta.indexes
        index_fields = [index.fields for index in indexes]
        
        self.assertIn(['start_date', 'start_time'], index_fields)
        self.assertIn(['status'], index_fields)
        self.assertIn(['type'], index_fields)
        self.assertIn(['data_classification'], index_fields)
        self.assertIn(['created'], index_fields)


class EventChangeHistoryModelTest(TestCase):
    """Test cases for the EventChangeHistory model."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        self.event = create_event(
            type='meeting',
            start_date=timezone.now() + timedelta(days=1),
            time='2:00 PM - 3:00 PM',
            location='2411 RHOB',
            details='Test details',
            created_by=self.user,
            modified_by=self.user,
        )
        from apps.contacts.services import attach_contact_org_to_event
        attach_contact_org_to_event(
            self.event,
            name='John Doe',
            email='john@example.com',
            phone='',
            group='Test Group',
            user=self.user,
        )
        
        self.change_data = {
            'event': self.event,
            'user': self.user,
            'field': 'status',
            'old_value': 'received',
            'new_value': 'scheduled',
            'ip_address': '192.168.1.1',
            'user_agent': 'Mozilla/5.0 Test Browser'
        }
    
    def test_create_change_history(self):
        """Test creating a change history record."""
        change = EventChangeHistory.objects.create(**self.change_data)
        
        self.assertEqual(change.event, self.event)
        self.assertEqual(change.user, self.user)
        self.assertEqual(change.field, 'status')
        self.assertEqual(change.old_value, 'received')
        self.assertEqual(change.new_value, 'scheduled')
        self.assertEqual(change.ip_address, '192.168.1.1')
        self.assertIsInstance(change.id, uuid.UUID)
        self.assertIsNotNone(change.timestamp)
    
    def test_change_history_str_representation(self):
        """Test the string representation of change history."""
        change = EventChangeHistory.objects.create(**self.change_data)
        expected_str = f"{self.event} - status changed by {self.user} at {change.timestamp}"
        self.assertEqual(str(change), expected_str)
    
    def test_change_history_cascade_delete(self):
        """Test that change history is deleted when event is deleted."""
        change = EventChangeHistory.objects.create(**self.change_data)
        change_id = change.id
        
        # Verify change exists
        self.assertTrue(EventChangeHistory.objects.filter(id=change_id).exists())
        
        # Delete event
        self.event.delete()
        
        # Verify change is also deleted
        self.assertFalse(EventChangeHistory.objects.filter(id=change_id).exists())
    
    def test_change_history_user_protect(self):
        """Test that user cannot be deleted if change history exists."""
        EventChangeHistory.objects.create(**self.change_data)
        
        # Attempting to delete user should raise ProtectedError
        from django.db.models import ProtectedError
        with self.assertRaises(ProtectedError):
            self.user.delete()
    
    def test_change_history_meta_options(self):
        """Test EventChangeHistory model meta options."""
        # Test db_table
        self.assertEqual(EventChangeHistory._meta.db_table, 'event_change_history')
        
        # Test verbose names
        self.assertEqual(EventChangeHistory._meta.verbose_name, 'Event Change History')
        self.assertEqual(EventChangeHistory._meta.verbose_name_plural, 'Event Change Histories')
        
        # Test ordering
        self.assertEqual(EventChangeHistory._meta.ordering, ['-timestamp'])


class EmailTemplateModelTest(TestCase):
    """Test cases for the EmailTemplate model."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        self.template_data = {
            'name': 'Meeting Request Response',
            'subject': 'Re: Meeting Request - {{group}}',
            'body': 'Dear {{contact_name}},\n\nThank you for your meeting request regarding {{details}}.\n\nBest regards,\nCongressional Staff',
            'variables': ['group', 'contact_name', 'details'],
            'created_by': self.user,
            'modified_by': self.user,
        }
    
    def test_create_email_template(self):
        """Test creating an email template."""
        template = EmailTemplate.objects.create(**self.template_data)
        
        self.assertEqual(template.name, 'Meeting Request Response')
        self.assertEqual(template.subject, 'Re: Meeting Request - {{group}}')
        self.assertIn('{{contact_name}}', template.body)
        self.assertEqual(template.variables, ['group', 'contact_name', 'details'])
        self.assertFalse(template.is_default)
        self.assertIsInstance(template.id, uuid.UUID)
    
    def test_template_str_representation(self):
        """Test the string representation of the template."""
        template = EmailTemplate.objects.create(**self.template_data)
        self.assertEqual(str(template), 'Meeting Request Response')
    
    def test_template_validation_variables_list(self):
        """Test that variables field must be a list."""
        template = EmailTemplate.objects.create(**self.template_data)
        
        # Test invalid variables
        template.variables = "not a list"
        with self.assertRaises(ValidationError):
            template.clean()
        
        # Test valid variables
        template.variables = ['var1', 'var2']
        template.clean()  # Should not raise
    
    def test_template_save_calls_clean(self):
        """Test that save() calls clean() for validation."""
        template_data = self.template_data.copy()
        template_data['variables'] = "not a list"
        
        template = EmailTemplate(**template_data)
        with self.assertRaises(ValidationError):
            template.save()
    
    def test_template_default_flag(self):
        """Test the is_default flag functionality."""
        template = EmailTemplate.objects.create(**self.template_data)
        self.assertFalse(template.is_default)
        
        template.is_default = True
        template.save()
        template.refresh_from_db()
        self.assertTrue(template.is_default)
    
    def test_template_audit_fields(self):
        """Test that audit fields are automatically populated."""
        template = EmailTemplate.objects.create(**self.template_data)
        
        self.assertIsNotNone(template.created)
        self.assertIsNotNone(template.modified)
        self.assertEqual(template.created_by, self.user)
        self.assertEqual(template.modified_by, self.user)
        self.assertLessEqual(template.created, template.modified)
    
    def test_template_user_protect(self):
        """Test that user cannot be deleted if template exists."""
        EmailTemplate.objects.create(**self.template_data)
        
        # Attempting to delete user should raise ProtectedError
        from django.db.models import ProtectedError
        with self.assertRaises(ProtectedError):
            self.user.delete()
    
    def test_template_meta_options(self):
        """Test EmailTemplate model meta options."""
        # Test db_table
        self.assertEqual(EmailTemplate._meta.db_table, 'email_templates')
        
        # Test verbose names
        self.assertEqual(EmailTemplate._meta.verbose_name, 'Email Template')
        self.assertEqual(EmailTemplate._meta.verbose_name_plural, 'Email Templates')
        
        # Test ordering
        self.assertEqual(EmailTemplate._meta.ordering, ['category', 'name'])


class EventModelSecurityTest(TestCase):
    """Test cases for Event model security features."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='securitytest',
            email='security@example.com',
            password='testpass123'
        )
        
        self.event = create_event(
            type='meeting',
            start_date=timezone.now() + timedelta(days=1),
            time='2:00 PM - 3:00 PM',
            location='2411 RHOB',
            details='Security test details',
            data_classification='sensitive',
            created_by=self.user,
            modified_by=self.user,
        )
        from apps.contacts.services import attach_contact_org_to_event
        attach_contact_org_to_event(
            self.event,
            name='Security Contact',
            email='security@example.com',
            phone='',
            group='Security Test Group',
            user=self.user,
        )
    
    def test_data_classification_enforcement(self):
        """Test data classification field enforcement."""
        # Test all valid classifications
        classifications = ['public', 'internal', 'sensitive', 'restricted']
        
        for classification in classifications:
            self.event.data_classification = classification
            self.event.save()
            self.event.refresh_from_db()
            self.assertEqual(self.event.data_classification, classification)
    
    def test_audit_trail_creation(self):
        """Test that audit trail is maintained."""
        original_modified = self.event.modified
        
        # Update event
        self.event.status = 'scheduled'
        self.event.save()
        
        # Check that modified timestamp was updated
        self.event.refresh_from_db()
        self.assertGreater(self.event.modified, original_modified)
    
    def test_user_protection_on_delete(self):
        """Test that users are protected from deletion when referenced."""
        from django.db.models import ProtectedError
        
        # User should be protected because event references them
        with self.assertRaises(ProtectedError):
            self.user.delete()
    
    def test_sensitive_data_handling(self):
        """Test handling of sensitive data fields."""
        # Test that sensitive fields can store appropriate data
        self.event.details = "Sensitive meeting details about classified topic"
        self.event.hms_notes = "Confidential notes from HMS"
        self.event.campaign_notes = "Internal campaign strategy notes"
        self.event.data_classification = 'restricted'
        self.event.save()
        
        self.event.refresh_from_db()
        self.assertEqual(self.event.data_classification, 'restricted')
        self.assertIn("Sensitive", self.event.details)
        self.assertIn("Confidential", self.event.hms_notes)
        self.assertIn("Internal", self.event.campaign_notes)