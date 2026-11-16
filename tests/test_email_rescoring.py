# SPDX-License-Identifier: Apache-2.0
"""Phase 6 (hardening loop) tests: divert re-scoring and reconciliation
metrics on the triage page."""
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.authentication.models import User
from apps.email_processing.models import SenderReputation, SubscriptionState
from apps.email_processing.tasks.pipeline import run_pipeline
from apps.email_processing.tasks.rescoring import rescore_diverted

from .test_email_funnel import make_raw


class RescoringTests(TestCase):
    def _diverted_zero_signal(self, sender='quiet@newgroup.example'):
        raw = make_raw(sender=sender, subject='Hello',
                       body='Just wanted to say thank you for everything.')
        result = run_pipeline(str(raw.id))
        assert result['status'] == 'divert', result
        return raw

    @patch('apps.email_processing.tasks.rescoring.run_pipeline')
    def test_newly_allowlisted_sender_is_promoted(self, mock_pipeline):
        raw = self._diverted_zero_signal()
        # The office later adds the sender to the allowlist.
        SenderReputation.objects.create(sender_email='quiet@newgroup.example',
                                        list='allow')
        result = rescore_diverted()
        self.assertEqual(result['promoted'], 1)
        mock_pipeline.delay.assert_called_once_with(str(raw.id), force_extract=True)

    @patch('apps.email_processing.tasks.rescoring.run_pipeline')
    def test_unqualified_divert_stays_diverted_and_is_not_rescanned(self, mock_pipeline):
        self._diverted_zero_signal()
        result = rescore_diverted()
        self.assertEqual(result, {'checked': 1, 'promoted': 0})
        mock_pipeline.delay.assert_not_called()
        # Second run: the rescore_checked marker prevents endless rescanning.
        self.assertEqual(rescore_diverted(), {'checked': 0, 'promoted': 0})

    @patch('apps.email_processing.tasks.rescoring.run_pipeline')
    def test_header_diverted_machine_mail_never_reenters(self, mock_pipeline):
        raw = make_raw(sender='digest@list.example',
                       headers={'List-Unsubscribe': '<mailto:u@x>'},
                       body='Can we schedule a meeting next Thursday at 2pm?')
        self.assertEqual(run_pipeline(str(raw.id))['status'], 'divert')
        result = rescore_diverted()
        self.assertEqual(result['checked'], 0)  # header diverts aren't rescored
        mock_pipeline.delay.assert_not_called()

    @patch('apps.email_processing.tasks.rescoring.run_pipeline')
    def test_blocked_sender_stays_blocked(self, mock_pipeline):
        SenderReputation.objects.create(sender_email='spam@bulk.example', list='block')
        raw = make_raw(sender='spam@bulk.example',
                       body='Can we schedule a meeting next Thursday?')
        self.assertEqual(run_pipeline(str(raw.id))['status'], 'divert')
        result = rescore_diverted()
        self.assertEqual(result['promoted'], 0)
        mock_pipeline.delay.assert_not_called()


class TriageHealthMetricsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='triage_user',
                                             email='t@office.example', password='pw')
        self.client.force_login(self.user)

    def test_lapsed_subscription_shows_p1_banner(self):
        SubscriptionState.objects.create(
            mailbox='scheduling@mail.example.com', status='lapsed',
            last_renewal_error='403 from Graph',
        )
        resp = self.client.get(reverse('email_processing:triage_list'))
        self.assertContains(resp, 'P1')
        self.assertContains(resp, 'scheduling@mail.example.com')

    @override_settings(GRAPH_WEBHOOK_ENABLED=True)
    def test_gap_count_shown_when_webhooks_enabled(self):
        make_raw(body='hello')  # source='sweep' → counts as a gap
        resp = self.client.get(reverse('email_processing:triage_list'))
        self.assertContains(resp, 'Webhook gaps caught by sweep')

    def test_sweep_only_mode_labelled(self):
        resp = self.client.get(reverse('email_processing:triage_list'))
        self.assertContains(resp, 'sweep-only')
