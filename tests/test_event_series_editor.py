# SPDX-License-Identifier: Apache-2.0
"""The event editing modal's "Repeats" section: POST/DELETE
/api/events/<id>/series/ creates, confirms or discards a recurring series
anchored at the event, and is locked while human review is pending."""
from datetime import date, time

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.authentication.models import User
from apps.email_processing.postprocess import get_pipeline_user
from apps.event_management.models import Event, EventSeries
from tests.factories import create_event, make_office_member


class EventSeriesEditorTests(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='series_editor', email='series@office.example', password='pw')
        make_office_member(self.user, role='admin', office_name='Series Test Office')
        self.client_api = APIClient()
        self.client_api.force_authenticate(self.user)
        # Thursday, 2027-07-15 at 8:00.
        self.event = create_event(
            title='Standing civics briefing', type='meeting', status='received',
            start_date=date(2027, 7, 15), start_time=time(8, 0),
            created_by=self.user, modified_by=self.user,
        )
        self.url = reverse('api:event-series', args=[self.event.id])

    def test_creates_series_with_event_as_first_occurrence(self) -> None:
        resp = self.client_api.post(
            self.url, {'rrule': 'FREQ=WEEKLY;BYDAY=TU,TH', 'count': 4}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)

        self.event.refresh_from_db()
        series = self.event.series
        self.assertIsNotNone(series)
        self.assertTrue(series.is_active)
        self.assertEqual(series.dtstart_date, date(2027, 7, 15))
        self.assertEqual(self.event.series_occurrence_date, date(2027, 7, 15))

        dates = sorted(series.events.values_list('series_occurrence_date', flat=True))
        # Thu 15, Tue 20, Thu 22, Tue 27 — the event itself is not duplicated.
        self.assertEqual(dates, [date(2027, 7, 15), date(2027, 7, 20),
                                 date(2027, 7, 22), date(2027, 7, 27)])
        self.assertEqual(resp.json()['occurrences_created'], 3)

    def test_end_bound_is_required(self) -> None:
        resp = self.client_api.post(self.url, {'rrule': 'FREQ=WEEKLY'}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('end bound', resp.json()['error'])
        self.assertFalse(EventSeries.objects.exists())

    def test_locked_while_human_review_pending(self) -> None:
        Event.objects.filter(pk=self.event.pk).update(requires_human_review=True)
        resp = self.client_api.post(
            self.url, {'rrule': 'FREQ=WEEKLY', 'count': 3}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('human review', resp.json()['error'])
        self.assertFalse(EventSeries.objects.exists())

    def _pending_series(self) -> EventSeries:
        series = EventSeries.objects.create(
            rrule='FREQ=WEEKLY;COUNT=6', dtstart_date=date(2027, 7, 14),
            title_template='Standing civics briefing', created_by=get_pipeline_user(),
            is_active=False,
        )
        self.event.series = series
        self.event.series_occurrence_date = date(2027, 7, 14)
        self.event.save()
        return series

    def test_confirming_pending_series_uses_current_start_date(self) -> None:
        # The model anchored the series on the 14th; the reviewer corrected
        # the event to the 15th. Confirming re-anchors on the event.
        series = self._pending_series()
        resp = self.client_api.post(
            self.url, {'rrule': 'FREQ=WEEKLY;BYDAY=TH', 'until_date': '2027-07-29'},
            format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        series.refresh_from_db()
        self.assertTrue(series.is_active)
        self.assertEqual(series.dtstart_date, date(2027, 7, 15))
        self.assertIsNone(series.count)  # the extracted COUNT=6 no longer applies
        self.assertEqual(series.rrule, 'FREQ=WEEKLY;BYDAY=TH')
        dates = sorted(series.events.values_list('series_occurrence_date', flat=True))
        self.assertEqual(dates, [date(2027, 7, 15), date(2027, 7, 22), date(2027, 7, 29)])

    def test_delete_discards_pending_series(self) -> None:
        series = self._pending_series()
        resp = self.client_api.delete(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['deleted'])
        self.event.refresh_from_db()
        self.assertIsNone(self.event.series)
        self.assertFalse(EventSeries.objects.filter(pk=series.pk).exists())

    def test_active_series_is_not_changed_or_deleted(self) -> None:
        self.client_api.post(self.url, {'rrule': 'FREQ=WEEKLY', 'count': 2}, format='json')
        for method in (self.client_api.post, self.client_api.delete):
            resp = method(self.url, {'rrule': 'FREQ=DAILY', 'count': 9}, format='json')
            self.assertEqual(resp.status_code, 400)
        self.event.refresh_from_db()
        self.assertEqual(self.event.series.rrule, 'FREQ=WEEKLY')
        self.assertEqual(self.event.series.events.count(), 2)
