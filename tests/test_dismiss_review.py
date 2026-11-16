# SPDX-License-Identifier: Apache-2.0
"""
Tests for dismissing AI-extracted events as false positives.

Covers the FieldReviewService dismiss/undo_dismiss methods, the dismiss API
endpoint, and the inbox queryset's inclusion of dismissed events (including
false positives that carry no extracted_fields).
"""
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.api.services import FieldReviewService
from apps.authentication.models import Office, User
from apps.event_management.models import EventReviewAuditLog
from tests.factories import create_event


class DismissReviewTestBase(TestCase):
    def setUp(self):
        self.office = Office.objects.create(name='Dismiss Test Office')
        self.roles = self.office.create_default_roles()
        self.user = User.objects.create_user(
            username='scheduler_u', email='sched@e.example', password='pw'
        )
        self.user.office = self.office
        self.user.assign_role(self.roles['admin'])
        self.user.save()

    def _make_review_event(self, group='Needs Review', extracted_fields=None):
        return create_event(
            type='meeting',
            group=group,
            status='received',
            start_date=timezone.now().date() + timedelta(days=5),
            requires_human_review=True,
            extracted_fields=extracted_fields if extracted_fields is not None else {},
            created_by=self.user,
            modified_by=self.user,
        )


class DismissServiceTests(DismissReviewTestBase):
    def setUp(self):
        super().setUp()
        self.service = FieldReviewService()

    def test_dismiss_sets_decision_and_clears_review_flag(self):
        event = self._make_review_event()
        result = self.service.dismiss_event(event, self.user, ip_address='1.2.3.4')

        self.assertTrue(result['success'])
        event.refresh_from_db()
        self.assertEqual(event.review_decision, 'dismissed')
        self.assertFalse(event.requires_human_review)
        self.assertIsNotNone(event.dismissed_at)
        self.assertEqual(event.dismissed_by, self.user)

    def test_dismiss_writes_audit_log(self):
        event = self._make_review_event()
        self.service.dismiss_event(event, self.user)

        log = EventReviewAuditLog.objects.get(event=event, action='dismiss')
        self.assertEqual(log.user, self.user)

    def test_double_dismiss_is_rejected(self):
        event = self._make_review_event()
        self.service.dismiss_event(event, self.user)
        result = self.service.dismiss_event(event, self.user)

        self.assertFalse(result['success'])

    def test_undo_dismiss_restores_to_review_queue(self):
        event = self._make_review_event()
        self.service.dismiss_event(event, self.user)

        result = self.service.undo_dismiss(event, self.user)
        self.assertTrue(result['success'])
        event.refresh_from_db()
        self.assertEqual(event.review_decision, '')
        self.assertTrue(event.requires_human_review)
        self.assertIsNone(event.dismissed_at)
        self.assertIsNone(event.dismissed_by)
        self.assertTrue(
            EventReviewAuditLog.objects.filter(event=event, action='undo_dismiss').exists()
        )

    def test_undo_dismiss_on_non_dismissed_is_rejected(self):
        event = self._make_review_event()
        result = self.service.undo_dismiss(event, self.user)
        self.assertFalse(result['success'])


class DismissApiTests(DismissReviewTestBase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_dismiss_endpoint_dismisses_event(self):
        event = self._make_review_event()
        url = reverse('api:dismiss-review', args=[event.id])

        resp = self.client.post(url, {'action': 'dismiss'}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['review_decision'], 'dismissed')

        event.refresh_from_db()
        self.assertEqual(event.review_decision, 'dismissed')
        self.assertFalse(event.requires_human_review)

    def test_undo_dismiss_endpoint_restores_event(self):
        event = self._make_review_event()
        FieldReviewService().dismiss_event(event, self.user)
        url = reverse('api:dismiss-review', args=[event.id])

        resp = self.client.post(url, {'action': 'undo_dismiss'}, format='json')
        self.assertEqual(resp.status_code, 200)

        event.refresh_from_db()
        self.assertEqual(event.review_decision, '')
        self.assertTrue(event.requires_human_review)

    def test_invalid_action_is_rejected(self):
        event = self._make_review_event()
        url = reverse('api:dismiss-review', args=[event.id])

        resp = self.client.post(url, {'action': 'bogus'}, format='json')
        self.assertEqual(resp.status_code, 400)


class InboxFilterTests(DismissReviewTestBase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _inbox_ids(self):
        resp = self.client.get(
            '/api/events/',
            {'requires_human_review': 'true', 'include_resolved_reviews': 'true'},
        )
        self.assertEqual(resp.status_code, 200)
        return {str(e['id']) for e in resp.data['results']}

    def test_dismissed_false_positive_appears_in_inbox(self):
        # A false positive with no extracted_fields must still surface so it can
        # be shown under the inbox's "Show resolved" filter and later restored.
        event = self._make_review_event(group='False Positive', extracted_fields={})
        FieldReviewService().dismiss_event(event, self.user)

        self.assertIn(str(event.id), self._inbox_ids())

    def test_pending_review_event_appears_in_inbox(self):
        event = self._make_review_event(group='Still Pending')
        self.assertIn(str(event.id), self._inbox_ids())
