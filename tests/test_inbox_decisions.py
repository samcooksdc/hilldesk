# SPDX-License-Identifier: Apache-2.0
"""Emails the pipeline set aside appear in the inbox as "Needs a decision"
items (feed + actions), count toward the inbox totals, and are restricted to
users who can see the inbox."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.email_processing.models import EmailProcessing, FilterLog
from apps.email_processing.tasks.pipeline import run_pipeline
from tests.factories import make_office_member
from tests.test_email_funnel import make_raw

User = get_user_model()

SPOOFED = {'Authentication-Results': 'mx.example.com; spf=fail smtp.mailfrom=evil.example; dmarc=fail'}


class InboxDecisionTests(TestCase):
    def setUp(self) -> None:
        self.scheduler = make_office_member(
            User.objects.create_user(username='sched', email='sched@example.com', password='pw-for-tests')
        )
        self.raw = make_raw(subject='URGENT meeting about your account', headers=SPOOFED,
                            body='Verify your credentials today.')
        run_pipeline(str(self.raw.id))
        self.client.force_login(self.scheduler)

    def _feed(self):
        return self.client.get(reverse('email_processing:triage_items_api'), HTTP_ACCEPT='application/json')

    def test_feed_lists_set_aside_email_with_plain_reason(self) -> None:
        data = self._feed().json()
        self.assertEqual(data['count'], 1)
        item = data['results'][0]
        self.assertEqual(item['id'], str(self.raw.id))
        self.assertEqual(item['reason'], 'auth_failure')
        self.assertEqual(item['reason_label'], 'Sender failed authentication')
        self.assertIn('Verify your credentials', item['body_text'])

    def test_divert_removes_it_from_the_feed(self) -> None:
        url = reverse('email_processing:triage_divert', kwargs={'raw_message_id': self.raw.id})
        response = self.client.post(url, HTTP_ACCEPT='application/json')
        self.assertEqual(response.json(), {'success': True, 'action': 'divert'})
        self.assertEqual(self._feed().json()['count'], 0)
        self.assertEqual(EmailProcessing.objects.get(raw_message=self.raw).status, 'rejected')
        self.assertTrue(FilterLog.objects.filter(raw_message=self.raw, signals__reason='triage_divert').exists())

    def test_extract_anyway_returns_json(self) -> None:
        url = reverse('email_processing:triage_extract_anyway', kwargs={'raw_message_id': self.raw.id})
        response = self.client.post(url, HTTP_ACCEPT='application/json')
        self.assertEqual(response.json(), {'success': True, 'action': 'extract'})

    def test_feed_and_actions_require_inbox_permission(self) -> None:
        from apps.authentication.models import Role
        from apps.authentication.permissions import Permissions
        outsider = User.objects.create_user(username='noinbox', email='n@example.com', password='pw-for-tests')
        outsider.office = self.scheduler.office
        outsider.assign_role(Role.objects.create(
            office=outsider.office, name='Viewer', slug='viewer-no-inbox',
            permissions=sorted(Permissions.expand_permissions({Permissions.VIEW_ALL_EVENTS})),
        ))
        outsider.save()
        self.assertFalse(Permissions.has_permission(outsider, Permissions.VIEW_INBOX))
        self.client.force_login(outsider)
        self.assertEqual(self._feed().status_code, 403)
        url = reverse('email_processing:triage_divert', kwargs={'raw_message_id': self.raw.id})
        self.assertEqual(self.client.post(url, HTTP_ACCEPT='application/json').status_code, 403)

    def test_dashboard_lists_and_counts_decisions(self) -> None:
        response = self.client.get(reverse('event_management:dashboard'))
        self.assertContains(response, 'NEEDS A DECISION:')
        self.assertContains(response, 'URGENT meeting about your account')
        self.assertEqual(len(response.context['decision_preview']), 1)
        self.assertGreaterEqual(response.context['inbox_count'], 1)

    def test_inbox_script_loads_the_decision_feed(self) -> None:
        from pathlib import Path
        from django.conf import settings
        js = (Path(settings.BASE_DIR) / 'static' / 'js' / 'inbox-redesign.js').read_text(encoding='utf-8')
        self.assertIn("triageApiUrl: config.triageApiUrl || '/email/api/triage/'", js)
        self.assertIn('renderDecisionCard', js)
        base = (Path(settings.BASE_DIR) / 'templates' / 'base.html').read_text(encoding='utf-8')
        self.assertIn('/email/api/triage/', base)  # sidebar badge counts decisions
