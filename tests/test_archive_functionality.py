# SPDX-License-Identifier: Apache-2.0
"""
Archive (soft-delete) behaviour.

Archiving is how HillDesk "deletes" an event: the row stays, is hidden from
active views, and appears in Settings -> Deleted events, where it can be
restored or permanently removed through the events API. (The older archive
pages with retention periods were removed; retention is not enforced by the
app; see docs/security-model.md.)
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.event_management.models import Event, EventChangeHistory
from tests.factories import create_event

User = get_user_model()


class ArchiveModelTests(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='archiver', email='archiver@example.com', password='testpass123'
        )
        self.event = create_event(
            type='meeting',
            start_date=timezone.now().date() - timedelta(days=30),
            location='Conference Room',
            group='Test Meeting',
            created_by=self.user,
            modified_by=self.user,
        )

    def test_archive_sets_fields_and_records_history(self) -> None:
        self.assertFalse(self.event.is_archived)
        self.assertTrue(self.event.archive(user=self.user))

        self.assertTrue(self.event.is_archived)
        self.assertIsNotNone(self.event.archived_date)
        self.assertEqual(self.event.archived_by, self.user)
        history = EventChangeHistory.objects.get(event=self.event, field='archived')
        self.assertEqual(history.user, self.user)
        self.assertEqual(history.new_value, 'True')

    def test_unarchive_clears_fields_and_records_history(self) -> None:
        self.event.archive(user=self.user)
        self.assertTrue(self.event.unarchive(user=self.user))

        self.assertFalse(self.event.is_archived)
        self.assertIsNone(self.event.archived_date)
        self.assertIsNone(self.event.archived_by)
        self.assertTrue(
            EventChangeHistory.objects.filter(event=self.event, field='unarchived').exists()
        )

    def test_archive_and_unarchive_are_idempotent(self) -> None:
        self.assertFalse(self.event.unarchive(user=self.user))
        self.event.archive(user=self.user)
        self.assertFalse(self.event.archive(user=self.user))

    def test_only_archived_events_can_be_deleted(self) -> None:
        self.assertFalse(self.event.can_be_deleted)
        self.event.archive(user=self.user)
        self.assertTrue(self.event.can_be_deleted)

    def test_archived_and_active_querysets(self) -> None:
        other = create_event(
            type='event', start_date=timezone.now().date(),
            created_by=self.user, modified_by=self.user,
        )
        self.event.archive(user=self.user)

        self.assertEqual(list(Event.get_archived_events()), [self.event])
        self.assertEqual(list(Event.get_events_for_deletion()), [self.event])
        self.assertIn(other, Event.get_active_events())
        self.assertNotIn(self.event, Event.get_active_events())

    def test_has_original_email_false_without_email(self) -> None:
        self.assertFalse(self.event.has_original_email)
        self.assertIsNone(self.event.original_email)
