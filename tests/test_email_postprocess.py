# SPDX-License-Identifier: Apache-2.0
"""Phase 5 (post-processing + materialization) tests.

End-to-end on the mock provider: candidates become the review surfaces the
inbox renders — draft Events with extracted_fields v2 + meta, inactive
EventSeries, grouped EventChangeSuggestions — plus series semantics (horizon,
exceptions, regeneration, end-bound enforcement), the cap collapse, the
enumerated fold, matching, the change-suggestions feed, series activation, and
the reputation feedback loop.
"""
from datetime import date, datetime, timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone as dj_tz
from rest_framework.test import APIClient

from apps.authentication.models import Office, User
from apps.event_management.models import (
    Event, EventChangeSuggestion, EventEmailLink, EventSeries, EventThreadLink,
)
from apps.email_processing.models import EmailProcessing, ExtractionCandidate, SenderReputation
from apps.email_processing.postprocess import (
    fold_enumerated_recurrence, get_pipeline_user, resolve_timezone,
)
from apps.email_processing.tasks.pipeline import run_pipeline

from .test_email_funnel import make_raw as _make_raw

# Fixtures mention yearless dates ("July 20") and assert 2026. The pipeline
# resolves yearless dates forward from the message's received date, so pin it
# instead of using "now" (which made these tests fail after July 2026).
FIXED_RECEIVED_AT = dj_tz.make_aware(datetime(2026, 6, 1, 9, 0))


def make_raw(**kwargs):
    kwargs.setdefault('received_at', FIXED_RECEIVED_AT)
    return _make_raw(**kwargs)
from tests.factories import create_event


def reviewer():
    office = Office.objects.create(name='Postprocess Test Office')
    roles = office.create_default_roles()
    user = User.objects.create_user(username='reviewer_pp', email='rev@office.example',
                                    password='pw')
    user.office = office
    user.assign_role(roles['admin'])
    user.save()
    return user


class NewEventMaterializationTests(TestCase):
    def test_scheduling_email_becomes_inbox_draft_event(self):
        raw = make_raw(
            subject='Meeting request — MMA',
            body='Could we schedule a meeting on July 20 at 2pm in the '
                 'Fairview Community Center? On behalf of the Franklin '
                 'Manufacturing Alliance.',
        )
        result = run_pipeline(str(raw.id))
        self.assertEqual(result['status'], 'extract')

        cand = ExtractionCandidate.objects.get(raw_message=raw)
        self.assertEqual(cand.status, 'materialized')
        event = cand.created_event
        self.assertIsNotNone(event)

        # The existing inbox feed lists it with zero changes.
        self.assertTrue(Event.objects.filter(requires_human_review=True,
                                             pk=event.pk).exists())
        self.assertEqual(event.start_date, date(2026, 7, 20))
        self.assertEqual(event.start_time.strftime('%H:%M'), '14:00')

        # extracted_fields v2 + additive meta block.
        ef = event.extracted_fields
        self.assertEqual(ef['schema_version'], 2)
        self.assertEqual(ef['start_date']['status'], 'pending')
        self.assertEqual(ef['meta']['intent'], 'NEW_EVENT')
        self.assertEqual(ef['meta']['origin'], 'email_ingestion')
        self.assertTrue(ef['contacts'])
        self.assertEqual(ef['contacts'][0]['fields']['email']['value'],
                         'jane@advocacy.example')

        # Source attached the way the review UI expects.
        record = EmailProcessing.objects.get(raw_message=raw)
        link = EventEmailLink.objects.get(event=event)
        self.assertEqual(link.email, record)
        self.assertEqual(link.origin, 'ai_auto')
        self.assertTrue(EventThreadLink.objects.filter(
            event=event, thread=record.thread).exists())

    def test_meta_is_not_a_reviewable_field(self):
        from apps.api.services import FieldReviewService
        raw = make_raw(body='Could we schedule a meeting on July 20 at 2pm?')
        run_pipeline(str(raw.id))
        event = ExtractionCandidate.objects.get(raw_message=raw).created_event
        service = FieldReviewService()
        self.assertNotIn('meta', dict(service._scalar_fields(event)))

    def test_multi_event_email_becomes_multiple_drafts(self):
        raw = make_raw(subject='Two events', body=(
            'EVENT: Ribbon cutting meeting on August 3 at 10am in Fairview.\n\n'
            'EVENT: Veterans roundtable on August 5 at 1pm in Fairview.'
        ))
        run_pipeline(str(raw.id))
        events = Event.objects.filter(requires_human_review=True,
                                      email_links__email__raw_message=raw)
        self.assertEqual(events.count(), 2)

    def test_matched_new_event_is_duplicate_suspect_not_dropped(self):
        actor = get_pipeline_user()
        existing = create_event(
            title='Meeting with the Franklin Manufacturing Alliance',
            type='meeting', status='scheduled',
            start_date=date(2026, 7, 20),
            created_by=actor, modified_by=actor,
        )
        raw = make_raw(
            subject='Meeting with the Franklin Manufacturing Alliance',
            body='Could we schedule our meeting on July 20 at 2pm?',
        )
        run_pipeline(str(raw.id))
        cand = ExtractionCandidate.objects.get(raw_message=raw)
        self.assertEqual(cand.matched_event, existing)
        # Still a draft card — the human resolves the duplicate.
        self.assertIsNotNone(cand.created_event)
        self.assertEqual(
            cand.created_event.extracted_fields['meta']['duplicate_of']['event_id'],
            str(existing.id),
        )


class RecurrenceMaterializationTests(TestCase):
    def test_recurring_email_creates_pending_inactive_series(self):
        raw = make_raw(body='Our board would love a weekly briefing meeting at '
                            '9am starting July 13.')
        run_pipeline(str(raw.id))
        cand = ExtractionCandidate.objects.get(raw_message=raw)
        self.assertEqual(cand.intent, 'RECURRING_EVENT')
        series = EventSeries.objects.get(source_candidate=cand)
        self.assertFalse(series.is_active)
        self.assertEqual(cand.created_event.series, series)
        # Open-ended rule: only the draft first occurrence exists.
        self.assertEqual(series.events.count(), 1)

    def test_series_activation_requires_end_bound(self):
        user = reviewer()
        client = APIClient()
        client.force_authenticate(user)
        raw = make_raw(body='A weekly briefing meeting at 9am please.')
        run_pipeline(str(raw.id))
        series = EventSeries.objects.get()

        url = reverse('api:activate-series', args=[series.id])
        resp = client.post(url, {}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('end bound', resp.json()['error'])

        resp = client.post(url, {'count': 4}, format='json')
        self.assertEqual(resp.status_code, 200)
        series.refresh_from_db()
        self.assertTrue(series.is_active)
        self.assertEqual(series.events.count(), 4)  # first occurrence + 3 more

    def _pending_series(self) -> tuple[APIClient, EventSeries]:
        user = reviewer()
        client = APIClient()
        client.force_authenticate(user)
        raw = make_raw(body='A weekly briefing meeting at 9am please.')
        run_pipeline(str(raw.id))
        return client, EventSeries.objects.get()

    def test_reviewer_end_date_replaces_extracted_count(self):
        client, series = self._pending_series()
        series.count = 10
        series.save()
        until = series.dtstart_date + timedelta(days=14)

        resp = client.post(reverse('api:activate-series', args=[series.id]),
                           {'rrule': 'FREQ=WEEKLY', 'until_date': until.isoformat()},
                           format='json')
        self.assertEqual(resp.status_code, 200)
        series.refresh_from_db()
        self.assertIsNone(series.count)
        self.assertEqual(series.until_date, until)
        self.assertEqual(series.events.count(), 3)  # weeks 0..2

    def test_reviewer_picked_weekdays_are_applied(self):
        client, series = self._pending_series()
        resp = client.post(reverse('api:activate-series', args=[series.id]),
                           {'rrule': 'FREQ=WEEKLY;BYDAY=MO,WE', 'count': 4},
                           format='json')
        self.assertEqual(resp.status_code, 200)
        series.refresh_from_db()
        self.assertIsNone(series.until_date)
        weekdays = {d.weekday() for d in series.events.values_list(
            'series_occurrence_date', flat=True)}
        self.assertEqual(weekdays, {0, 2})


class SeriesModelTests(TestCase):
    def _series(self, **overrides):
        actor = get_pipeline_user()
        fields = dict(
            rrule='FREQ=WEEKLY',
            dtstart_date=dj_tz.now().date() + timedelta(days=7),
            timezone='America/New_York',
            count=5,
            title_template='Weekly Ag Sync',
            created_by=actor,
            is_active=True,
        )
        fields.update(overrides)
        return EventSeries.objects.create(**fields)

    def test_materialization_and_idempotency(self):
        series = self._series()
        created = series.materialize_occurrences()
        self.assertEqual(len(created), 5)
        self.assertEqual(series.events.count(), 5)
        # Idempotent: re-running fills nothing.
        self.assertEqual(series.materialize_occurrences(), [])

    def test_open_ended_series_cannot_activate(self):
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            self._series(count=None, until_date=None)

    def test_exception_survives_regeneration(self):
        series = self._series()
        series.materialize_occurrences()
        occurrences = list(series.events.order_by('series_occurrence_date'))
        exception = occurrences[2]
        exception.is_series_exception = True
        exception.location = 'Moved to the district office'
        exception.save()

        series.rrule = 'FREQ=WEEKLY'
        series.count = 4
        series.save()
        series.regenerate_future(from_date=series.dtstart_date)

        self.assertTrue(Event.objects.filter(pk=exception.pk).exists())
        # 4 rule occurrences; the exception's slot isn't double-filled.
        dates = list(series.events.order_by('series_occurrence_date')
                     .values_list('series_occurrence_date', flat=True))
        self.assertEqual(len(dates), len(set(dates)))
        self.assertEqual(series.events.filter(is_series_exception=False).count(), 3)

    def test_until_date_bounds_occurrences(self):
        start = dj_tz.now().date() + timedelta(days=7)
        series = self._series(count=None, until_date=start + timedelta(days=21))
        created = series.materialize_occurrences()
        self.assertEqual(len(created), 4)  # weeks 0..3


class ChangeSuggestionMaterializationTests(TestCase):
    def _original_event(self, title='Factory tour', start=date(2026, 7, 16)):
        actor = get_pipeline_user()
        return create_event(
            title=title, type='meeting', status='scheduled',
            start_date=start, created_by=actor, modified_by=actor,
        )

    def test_matched_reschedule_creates_grouped_suggestions(self):
        self._original_event()
        raw = make_raw(
            subject='Factory tour',
            body='We need to reschedule the factory tour to July 17 at 3pm.',
        )
        result = run_pipeline(str(raw.id))
        self.assertEqual(result['status'], 'extract')

        cand = ExtractionCandidate.objects.get(raw_message=raw)
        self.assertEqual(cand.intent, 'RESCHEDULE')
        self.assertEqual(cand.status, 'materialized')

        rows = EventChangeSuggestion.objects.filter(source_candidate=cand)
        by_field = {s.field_name: s for s in rows}
        self.assertIn('start_date', by_field)
        self.assertEqual(by_field['start_date'].suggested_value, '2026-07-17')
        self.assertIn('start_time', by_field)
        self.assertEqual(by_field['start_time'].suggested_value, '15:00')
        for row in rows:
            self.assertEqual(row.origin, 'email_ingestion')
            self.assertIsNone(row.suggested_by)
        # No draft event for a reschedule.
        self.assertIsNone(cand.created_event)

    def test_approving_suggestion_applies_via_existing_machinery(self):
        event = self._original_event()
        raw = make_raw(subject='Factory tour',
                       body='We need to reschedule the factory tour to July 17.')
        run_pipeline(str(raw.id))
        suggestion = EventChangeSuggestion.objects.get(field_name='start_date')
        self.assertTrue(suggestion.approve(reviewer()))
        event.refresh_from_db()
        self.assertEqual(event.start_date, date(2026, 7, 17))

    def test_matched_cancellation_suggests_status_change(self):
        # Original request materializes a draft event + thread link; the
        # cancellation in the same conversation matches it via the thread.
        original = make_raw(
            subject='Factory tour',
            body='Could we schedule a factory tour meeting on July 16 at 10am?',
        )
        run_pipeline(str(original.id))

        cancel = make_raw(
            subject='RE: Factory tour',
            body='Unfortunately we must cancel the factory tour.',
            conversation_id=original.conversation_id,
        )
        run_pipeline(str(cancel.id))

        cand = ExtractionCandidate.objects.get(raw_message=cancel)
        self.assertEqual(cand.intent, 'CANCELLATION')
        suggestion = EventChangeSuggestion.objects.get(source_candidate=cand)
        self.assertEqual(suggestion.field_name, 'status')
        self.assertEqual(suggestion.suggested_value, 'cancelled')
        self.assertEqual(cand.match_basis.get('method'), 'thread')

    def test_unmatched_cancellation_escalates_to_triage(self):
        raw = make_raw(subject='Cancellation',
                       body='Please cancel the quantum breakfast summit.')
        run_pipeline(str(raw.id))
        cand = ExtractionCandidate.objects.get(raw_message=raw)
        self.assertEqual(cand.status, 'escalated')
        self.assertFalse(EventChangeSuggestion.objects.exists())

        # And the triage page lists it.
        user = reviewer()
        self.client.force_login(user)
        resp = self.client.get(reverse('email_processing:triage_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'cancellation_of_unknown_event')


class CapAndFoldTests(TestCase):
    @override_settings(CANDIDATE_CAP=2)
    def test_cap_collapses_to_one_triage_item(self):
        raw = make_raw(subject='Big digest', body=(
            'EVENT: Meeting A on August 3 at 10am.\n\n'
            'EVENT: Meeting B on August 4 at 10am.\n\n'
            'EVENT: Meeting C on August 5 at 10am.'
        ))
        result = run_pipeline(str(raw.id))
        self.assertEqual(result['status'], 'escalate')
        record = EmailProcessing.objects.get(raw_message=raw)
        self.assertEqual(record.status, 'escalated')
        self.assertEqual(record.extracted_data['escalation']['reason'], 'candidate_cap')
        self.assertFalse(Event.objects.filter(requires_human_review=True).exists())

    def test_enumerated_fold_synthesizes_series_candidate(self):
        raw = make_raw(body='placeholder')
        record = EmailProcessing.objects.create(
            email_id=f'{raw.graph_message_id}-pp', subject='Enumerated',
            sender='jane@advocacy.example', received=dj_tz.now(),
            status='processed', is_scheduling_request=True, confidence=0.8,
            complete_email_data={'email_id': 'x', 'body': {'text': 'enumerated'}},
            extracted_data={'seed': True}, raw_message=raw,
        )
        base = date(2026, 8, 3)
        members = []
        for i in range(3):
            members.append(ExtractionCandidate.objects.create(
                raw_message=raw, email_processing=record, intent='NEW_EVENT',
                confidence=0.8,
                payload={
                    'intent': 'NEW_EVENT', 'confidence': 0.8,
                    'event': {'title': 'Kiwanis Breakfast',
                              'start_date': (base + timedelta(days=7 * i)).isoformat()},
                    'contacts': [{'name': 'Jane Doe', 'email': 'jane@advocacy.example'}],
                    'recurrence': {'rrule': None, 'has_end': False},
                },
            ))
        result = fold_enumerated_recurrence(record, members)
        self.assertEqual(len(result), 1)
        folded = result[0]
        self.assertEqual(folded.intent, 'RECURRING_EVENT')
        self.assertEqual(folded.recurrence_rule, 'FREQ=WEEKLY;COUNT=3')
        self.assertFalse(folded.recurrence_needs_end)
        self.assertEqual(folded.provenance['channel'], 'fold')
        for member in members:
            member.refresh_from_db()
            self.assertEqual(member.status, 'superseded')


class TimezoneResolutionTests(TestCase):
    def test_valid_proposed_zone_is_used(self):
        tz, basis, ambiguous = resolve_timezone(
            {'timezone': {'proposed': 'America/Chicago', 'basis': 'signature'}})
        self.assertEqual(tz, 'America/Chicago')
        self.assertFalse(ambiguous)

    def test_unavailable_zone_falls_back_flagged(self):
        tz, basis, ambiguous = resolve_timezone(
            {'timezone': {'proposed': 'Europe/Paris', 'basis': 'body'}})
        self.assertEqual(tz, 'America/New_York')
        self.assertTrue(ambiguous)

    def test_no_zone_uses_office_default_unflagged(self):
        tz, basis, ambiguous = resolve_timezone({})
        self.assertEqual(tz, 'America/New_York')
        self.assertFalse(ambiguous)


class ChangeSuggestionFeedTests(TestCase):
    def setUp(self):
        self.user = reviewer()
        self.client_api = APIClient()
        self.client_api.force_authenticate(self.user)

    def test_feed_groups_rows_per_candidate(self):
        actor = get_pipeline_user()
        create_event(title='Factory tour', type='meeting',
                             status='scheduled', start_date=date(2026, 7, 16),
                             created_by=actor, modified_by=actor)
        raw = make_raw(subject='Factory tour',
                       body='We need to reschedule the factory tour to July 17 at 3pm.')
        run_pipeline(str(raw.id))

        resp = self.client_api.get(reverse('api:change-suggestions-feed'))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['count'], 1)   # one card, multiple field rows
        group = data['results'][0]
        self.assertEqual(group['intent'], 'RESCHEDULE')
        self.assertEqual(group['event']['title'], 'Factory tour')
        fields = {s['field_name'] for s in group['suggestions']}
        self.assertEqual(fields, {'start_date', 'start_time'})


class ChangeRequestReviewPanelTests(TestCase):
    """The per-field review flow behind the change-request panel: accept with
    an edited value, reject, and revert (restore original + reopen)."""

    def setUp(self):
        self.user = reviewer()
        self.client_api = APIClient()
        self.client_api.force_authenticate(self.user)
        self.event = create_event(
            title='Factory tour', type='meeting', status='scheduled',
            start_date=date(2026, 7, 16),
            created_by=get_pipeline_user(), modified_by=get_pipeline_user(),
        )
        raw = make_raw(subject='Factory tour',
                       body='We need to reschedule the factory tour to July 17 at 3pm.')
        run_pipeline(str(raw.id))
        self.date_row = EventChangeSuggestion.objects.get(field_name='start_date')

    def _review(self, suggestion, body):
        return self.client_api.post(
            reverse('api:review-suggestion', args=[suggestion.id]),
            body, format='json')

    def test_accept_with_edited_value_applies_the_edit(self):
        # Reviewer tweaks the suggested date before accepting.
        resp = self._review(self.date_row, {'action': 'approve', 'value': '2026-07-18'})
        self.assertEqual(resp.status_code, 200)
        self.event.refresh_from_db()
        self.assertEqual(self.event.start_date, date(2026, 7, 18))
        self.date_row.refresh_from_db()
        self.assertEqual(self.date_row.status, 'approved')
        # The model's original proposal is preserved for audit.
        self.assertIn("'2026-07-17'", self.date_row.review_comment)

    def test_revert_restores_original_and_reopens(self):
        self._review(self.date_row, {'action': 'approve'})
        self.event.refresh_from_db()
        self.assertEqual(self.event.start_date, date(2026, 7, 17))

        resp = self._review(self.date_row, {'action': 'revert'})
        self.assertEqual(resp.status_code, 200)
        self.event.refresh_from_db()
        self.assertEqual(self.event.start_date, date(2026, 7, 16))  # original back
        self.date_row.refresh_from_db()
        self.assertEqual(self.date_row.status, 'pending')           # reopened
        self.assertIsNone(self.date_row.reviewed_by)

    def test_revert_of_rejected_suggestion_reopens_without_touching_event(self):
        self._review(self.date_row, {'action': 'reject'})
        resp = self._review(self.date_row, {'action': 'revert'})
        self.assertEqual(resp.status_code, 200)
        self.event.refresh_from_db()
        self.assertEqual(self.event.start_date, date(2026, 7, 16))
        self.date_row.refresh_from_db()
        self.assertEqual(self.date_row.status, 'pending')

    def test_revert_of_unset_time_field_restores_none(self):
        time_row = EventChangeSuggestion.objects.get(field_name='start_time')
        self.assertEqual(time_row.current_value, '')  # event had no time set
        self._review(time_row, {'action': 'approve'})
        self.event.refresh_from_db()
        self.assertIsNotNone(self.event.start_time)

        self._review(time_row, {'action': 'revert'})
        self.event.refresh_from_db()
        self.assertIsNone(self.event.start_time)

    def test_revert_requires_a_resolved_suggestion(self):
        resp = self._review(self.date_row, {'action': 'revert'})
        self.assertEqual(resp.status_code, 400)

    def test_feed_keeps_group_whole_while_any_row_pending(self):
        # Resolve one of the two rows; the feed group must still show both,
        # with per-row status, so the panel can render mixed state.
        self._review(self.date_row, {'action': 'approve'})
        resp = self.client_api.get(reverse('api:change-suggestions-feed'))
        group = resp.json()['results'][0]
        statuses = {s['field_name']: s['status'] for s in group['suggestions']}
        self.assertEqual(statuses['start_date'], 'approved')
        self.assertEqual(statuses['start_time'], 'pending')

    def test_fully_resolved_group_leaves_the_feed(self):
        for row in EventChangeSuggestion.objects.all():
            self._review(row, {'action': 'approve'})
        resp = self.client_api.get(reverse('api:change-suggestions-feed'))
        self.assertEqual(resp.json()['count'], 0)

    def test_editing_modal_embeds_change_suggestions(self):
        # The Event Editing Modal is the review surface: its server-rendered
        # HTML must carry the #change-suggestions-data JSON block AND the
        # source email (attached during materialization) for the email pane.
        self.client.force_login(self.user)
        resp = self.client.get(
            reverse('event_management:event_editing_interface', args=[self.event.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'change-suggestions-data')
        self.assertContains(resp, '2026-07-17')             # suggested date
        self.assertContains(resp, 'reschedule the factory tour')  # email body in pane

    def test_editing_modal_omits_block_when_no_suggestions(self):
        other = create_event(
            title='Quiet event', type='meeting', status='scheduled',
            start_date=date(2026, 8, 1),
            created_by=get_pipeline_user(), modified_by=get_pipeline_user(),
        )
        self.client.force_login(self.user)
        resp = self.client.get(
            reverse('event_management:event_editing_interface', args=[other.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'change-suggestions-data')


class ReputationFeedbackTests(TestCase):
    def setUp(self):
        self.user = reviewer()
        self.client_api = APIClient()
        self.client_api.force_authenticate(self.user)

    def _draft_event(self):
        raw = make_raw(body='Could we schedule a meeting on July 20 at 2pm?')
        run_pipeline(str(raw.id))
        return ExtractionCandidate.objects.get(raw_message=raw).created_event

    def test_junk_dismiss_counts_against_sender_and_offers_block(self):
        event = self._draft_event()
        url = reverse('api:dismiss-review', args=[event.id])
        resp = self.client_api.post(url, {'action': 'dismiss', 'junk': True},
                                    format='json')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get('offer_block_sender'))
        rep = SenderReputation.objects.exclude(sender_key='').get()
        self.assertEqual(rep.reject_count, 1)

    def test_block_sender_endpoint(self):
        resp = self.client_api.post(reverse('api:block-sender'),
                                    {'sender_email': 'spam@bulk.example'},
                                    format='json')
        self.assertEqual(resp.status_code, 200)
        rep = SenderReputation.objects.exclude(sender_key='').get()
        self.assertEqual(rep.list, 'block')

    def test_accept_all_bumps_approve_count(self):
        from apps.api.services import FieldReviewService
        event = self._draft_event()
        FieldReviewService().accept_all_fields(event, self.user)
        rep = SenderReputation.objects.exclude(sender_key='').get()
        self.assertEqual(rep.approve_count, 1)
