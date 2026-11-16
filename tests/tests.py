# SPDX-License-Identifier: Apache-2.0
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta
import uuid

from apps.email_processing.models import EmailProcessing

User = get_user_model()


class EmailProcessingModelTest(TestCase):
    """Test cases for the EmailProcessing model."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        self.email_data = {
            'email_id': 'AAMkAGVmMDEzMTM4LTZmYWUtNDdkNC1hMDZiLTU1OGY5OTZhYmY4OABGAAAAAAAiQ8W967B7TKBjgx9rVEURBwAiIsqMbYjsT5e-T7KzowPTAAAAAAEMAAAiIsqMbYjsT5e-T7KzowPTAAAYbvZDAAA=',
            'subject': 'Meeting Request - Healthcare Discussion',
            'sender': 'john.doe@healthcare.example',
            'sender_name': 'John Doe',
            'received': timezone.now() - timedelta(hours=2),
            'is_scheduling_request': True,
            'confidence': 0.95,
            'complete_email_data': {'body': {'contentType': 'text', 'content': 'Can we meet?'}},
            'extracted_data': {
                'type': 'meeting',
                'start_date': '2024-02-15',
                'time': '2:00 PM - 3:00 PM',
                'location': 'TBD',
                'group': 'Healthcare Coalition',
                'details': 'Discussion about Medicare expansion',
                'legislative_topics': ['Healthcare', 'Medicare'],
                'participants': ['Dr. Smith', 'Policy Director'],
                'point_of_contact': {
                    'name': 'John Doe',
                    'email': 'john.doe@healthcare.example',
                    'phone': '555-1234'
                }
            }
        }
    
    def test_create_email_processing(self):
        """Test creating an email processing record."""
        email = EmailProcessing.objects.create(**self.email_data)
        
        self.assertEqual(email.subject, 'Meeting Request - Healthcare Discussion')
        self.assertEqual(email.sender, 'john.doe@healthcare.example')
        self.assertEqual(email.sender_name, 'John Doe')
        self.assertTrue(email.is_scheduling_request)
        self.assertEqual(email.confidence, 0.95)
        self.assertEqual(email.status, 'pending')  # Default status
        self.assertEqual(email.data_classification, 'internal')  # Default classification
        self.assertIsInstance(email.id, uuid.UUID)
        self.assertIsInstance(email.extracted_data, dict)