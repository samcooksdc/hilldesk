# SPDX-License-Identifier: Apache-2.0
"""Phase 2 (funnel) tests for the email ingestion pipeline.

Per-stage behavior with realistic header/body fixtures, channel bypasses, the
rate gate's one-triage-item-per-burst rule, promotion from the divert store,
and the pipeline's terminal record creation.
"""
import uuid

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.email_processing import thread_text
from apps.email_processing.models import (
    EmailProcessing, FilterLog, RawMessage, SenderReputation,
)
from apps.email_processing.tasks.pipeline import run_pipeline


def make_raw(sender='jane@advocacy.example', subject='Meeting request',
             body='Could we schedule a meeting next Thursday at 2pm?',
             headers=None, mailbox='office@mail.example.com', **overrides):
    """Persist a RawMessage the way reception would."""
    fields = dict(
        graph_message_id=f"GRAPH-{uuid.uuid4()}",
        internet_message_id=f"<{uuid.uuid4()}@ext.example>",
        conversation_id=f"CONV-{uuid.uuid4()}",
        mailbox=mailbox,
        received_at=timezone.now(),
        source='sweep',
        sender=sender,
        sender_name='',
        subject=subject,
        headers=headers or {},
        body_text=body,
        body_html='',
        attachments=[],
        has_calendar_part=False,
    )
    fields.update(overrides)
    raw = RawMessage(**fields)
    raw.save()
    return raw


def outcome_of(raw):
    return run_pipeline(str(raw.id))


class Stage1HeaderTests(TestCase):
    def test_list_unsubscribe_diverts(self):
        raw = make_raw(headers={'List-Unsubscribe': '<mailto:u@x>', 'X-Foo': '1'})
        result = outcome_of(raw)
        self.assertEqual(result['status'], 'divert')
        self.assertEqual(result['terminal_stage'], '1_headers')
        log = FilterLog.objects.get(raw_message=raw, stage='1_headers')
        self.assertIn('list-unsubscribe', log.signals['bulk_headers'])

    def test_precedence_bulk_diverts(self):
        raw = make_raw(headers={'Precedence': 'bulk'})
        self.assertEqual(outcome_of(raw)['status'], 'divert')

    def test_auto_submitted_diverts(self):
        raw = make_raw(headers={'Auto-Submitted': 'auto-generated'})
        self.assertEqual(outcome_of(raw)['status'], 'divert')

    def test_noreply_sender_diverts(self):
        raw = make_raw(sender='no-reply@newsletter.example')
        self.assertEqual(outcome_of(raw)['status'], 'divert')

    def test_dmarc_failure_escalates_with_triage_record(self):
        raw = make_raw(headers={
            'Authentication-Results': 'mx.example.com; spf=fail smtp.mailfrom=evil.example; dmarc=fail'
        })
        result = outcome_of(raw)
        self.assertEqual(result['status'], 'escalate')
        self.assertEqual(result['terminal_stage'], '1_headers')
        record = EmailProcessing.objects.get(raw_message=raw)
        self.assertEqual(record.status, 'escalated')

    def test_softfail_is_not_a_failure(self):
        raw = make_raw(headers={
            'Authentication-Results': 'mx.example.com; spf=softfail; dkim=pass; dmarc=pass'
        })
        self.assertEqual(outcome_of(raw)['status'], 'extract')


class Stage2ReputationTests(TestCase):
    def test_blocked_sender_diverts(self):
        SenderReputation.objects.create(sender_email='spammer@bulk.example', list='block')
        raw = make_raw(sender='spammer@bulk.example')
        result = outcome_of(raw)
        self.assertEqual(result['status'], 'divert')
        self.assertEqual(result['terminal_stage'], '2_reputation')

    def test_blocked_domain_diverts(self):
        SenderReputation.objects.create(domain='bulk.example', list='block')
        raw = make_raw(sender='anyone@bulk.example')
        self.assertEqual(outcome_of(raw)['status'], 'divert')

    def test_allowlisted_sender_bypasses_content_scoring(self):
        # Zero scheduling content from a known stakeholder must still extract:
        # the allowlist overrides thresholds.
        SenderReputation.objects.create(sender_email='chief@partner.example', list='allow')
        raw = make_raw(sender='chief@partner.example', subject='hello',
                       body='Just checking in, nothing urgent.')
        result = outcome_of(raw)
        self.assertEqual(result['status'], 'extract')
        log = FilterLog.objects.get(raw_message=raw, stage='4_content')
        self.assertEqual(log.signals.get('bypass'), 'allowlist')


class Stage4ContentTests(TestCase):
    def test_scheduling_request_extracts(self):
        raw = make_raw(body='Would you be available for a briefing on July 20 at 2pm?')
        result = outcome_of(raw)
        self.assertEqual(result['status'], 'extract')
        record = EmailProcessing.objects.get(raw_message=raw)
        self.assertEqual(record.status, 'processed')  # extraction ran (mock provider)
        self.assertTrue(record.is_scheduling_request)
        # Standardized payload the inbox reads.
        self.assertEqual(record.complete_email_data['thread_id'], raw.conversation_id)

    def test_dateless_legislative_anchor_passes(self):
        raw = make_raw(subject='Visit when you are back',
                       body='We would love to host the Congresswoman after recess '
                            'at our facility in Fairview.')
        result = outcome_of(raw)
        self.assertEqual(result['status'], 'extract')
        log = FilterLog.objects.get(raw_message=raw, stage='4_content')
        self.assertIn('legislative', log.signals['anchors'])

    @override_settings(DIGEST_TOKEN_THRESHOLD=5)
    def test_digest_escalates(self):
        lines = [f"July {d} - Community event number {d}" for d in range(1, 10)]
        raw = make_raw(subject='Weekly events digest', body='\n'.join(lines))
        result = outcome_of(raw)
        self.assertEqual(result['status'], 'escalate')
        log = FilterLog.objects.get(raw_message=raw, stage='4_content')
        self.assertTrue(log.signals.get('digest_suspect'))

    def test_zero_signal_diverts(self):
        raw = make_raw(subject='Thank you',
                       body='Thank you so much for everything you do for our community.')
        result = outcome_of(raw)
        self.assertEqual(result['status'], 'divert')
        self.assertEqual(result['terminal_stage'], '4_content')

    def test_newsletter_shape_diverts(self):
        body = ('Check out our latest updates and stories from around the state. '
                'Read more at https://ex.example/a and https://ex.example/b and '
                'https://ex.example/c and https://ex.example/d and '
                'https://ex.example/e. ') * 4
        raw = make_raw(subject='Community update', body=body)
        result = outcome_of(raw)
        self.assertEqual(result['status'], 'divert')
        log = FilterLog.objects.get(raw_message=raw, stage='4_content')
        self.assertEqual(log.signals['divert_reason'], 'newsletter_shape')

    def test_action_words_set_intent_hint(self):
        raw = make_raw(subject='Change of plans',
                       body='We need to reschedule — can we move it to Friday?')
        result = outcome_of(raw)
        self.assertEqual(result['status'], 'extract')
        log = FilterLog.objects.get(raw_message=raw, stage='4_content')
        self.assertIn('reschedule', log.signals['action_keywords'])


class ChannelBypassTests(TestCase):
    def test_calendar_part_bypasses_content_scoring(self):
        # No stored ICS payload → the funnel bypasses stage 4 for the calendar
        # channel, then extraction escalates the unparseable calendar part.
        raw = make_raw(body='', has_calendar_part=True)
        result = outcome_of(raw)
        log = FilterLog.objects.get(raw_message=raw, stage='4_content')
        self.assertEqual(log.signals.get('bypass'), 'calendar_part')
        self.assertEqual(result['status'], 'escalate')
        record = EmailProcessing.objects.get(raw_message=raw)
        self.assertEqual(record.extracted_data['escalation']['reason'],
                         'unparseable_calendar')

    def test_document_attachment_bypasses_content_scoring(self):
        from apps.email_processing.models import AttachmentBlob
        # Imported inside the test: test_email_channels imports make_raw from
        # this module, so a top-level import would be circular.
        from .test_email_channels import MINIMAL_PDF
        raw = make_raw(
            body='Please see attached.',
            attachments=[{'name': 'invitation.pdf', 'content_type': 'application/pdf',
                          'size': len(MINIMAL_PDF), 'is_inline': False}],
        )
        AttachmentBlob.objects.create(
            raw_message=raw, name='invitation.pdf',
            content_type='application/pdf', size=len(MINIMAL_PDF),
            payload=MINIMAL_PDF,
        )
        result = outcome_of(raw)
        self.assertEqual(result['status'], 'extract')
        log = FilterLog.objects.get(raw_message=raw, stage='4_content')
        self.assertEqual(log.signals.get('bypass'), 'document_attachments')


@override_settings(RATE_GATE_SENDER_LIMIT=3, RATE_GATE_WINDOW_MINUTES=60)
class RateGateTests(TestCase):
    def test_burst_escalates_once(self):
        body = 'Please schedule a meeting next week.'
        sender = 'blast@campaign.example'
        first_three = [make_raw(sender=sender, body=body,
                                subject=f'Request {i}') for i in range(3)]
        for raw in first_three:
            self.assertEqual(outcome_of(raw)['status'], 'extract')

        # 4th message pushes the sender over the limit -> primary escalation.
        fourth = make_raw(sender=sender, body=body, subject='Request 4')
        result = outcome_of(fourth)
        self.assertEqual(result['status'], 'escalate')
        self.assertEqual(result['terminal_stage'], 'rate_gate')
        self.assertIsNotNone(result['email_processing_id'])

        # 5th message: escalates in the ledger but folds into the same triage
        # item — no second EmailProcessing record.
        fifth = make_raw(sender=sender, body=body, subject='Request 5')
        result5 = outcome_of(fifth)
        self.assertEqual(result5['status'], 'escalate')
        self.assertIsNone(result5['email_processing_id'])
        log5 = FilterLog.objects.get(raw_message=fifth, stage='rate_gate')
        self.assertFalse(log5.signals['burst_primary'])


class PipelineBehaviorTests(TestCase):
    def test_pipeline_is_idempotent_per_message(self):
        raw = make_raw()
        first = outcome_of(raw)
        second = outcome_of(raw)
        self.assertEqual(first['status'], 'extract')
        self.assertEqual(second['status'], 'already_processed')

    def test_promotion_forces_extraction(self):
        raw = make_raw(subject='Thank you', body='Thanks for all you do.')
        self.assertEqual(outcome_of(raw)['status'], 'divert')

        result = run_pipeline(str(raw.id), force_extract=True)
        self.assertEqual(result['status'], 'extract')
        record = EmailProcessing.objects.get(raw_message=raw)
        self.assertEqual(record.status, 'processed')  # extraction ran on promotion
        # Override is recorded in the ledger.
        self.assertTrue(FilterLog.objects.filter(
            raw_message=raw, stage='extraction', signals__forced=True).exists())

    def test_every_stage_is_logged(self):
        raw = make_raw()
        outcome_of(raw)
        stages = set(FilterLog.objects.filter(raw_message=raw)
                     .values_list('stage', flat=True))
        self.assertEqual(stages, {'0_scope', '1_headers', '2_reputation',
                                  '3_dedup', 'rate_gate', '4_content',
                                  'extraction', 'postprocess'})

    def test_invalid_sender_gets_fallback(self):
        raw = make_raw(sender='', body='Can we schedule a briefing next week?')
        result = outcome_of(raw)
        self.assertEqual(result['status'], 'extract')
        record = EmailProcessing.objects.get(raw_message=raw)
        self.assertEqual(record.sender, 'unknown@sender.invalid')


class DivertStoreViewTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        self.user = get_user_model().objects.create_user(
            username='reviewer', email='rev@office.example', password='pw')
        self.client.force_login(self.user)

    def test_diverted_messages_listed_and_searchable(self):
        from django.urls import reverse
        diverted = make_raw(subject='Weekly newsletter blast',
                            headers={'List-Unsubscribe': '<mailto:u@x>'})
        run_pipeline(str(diverted.id))
        extracted = make_raw(subject='Real meeting request')
        run_pipeline(str(extracted.id))

        api = reverse('email_processing:diverted_items_api')
        subjects = [r['subject'] for r in self.client.get(api).json()['results']]
        self.assertIn('Weekly newsletter blast', subjects)
        self.assertNotIn('Real meeting request', subjects)

        # Subject search narrows; sender search goes through the blind index.
        self.assertEqual(self.client.get(api, {'search': 'newsletter'}).json()['count'], 1)
        self.assertEqual(self.client.get(api, {'search': 'jane@advocacy.example'}).json()['count'], 1)

    def test_promote_action_queues_forced_run(self):
        from unittest.mock import patch
        from django.urls import reverse
        diverted = make_raw(subject='Set-aside message',
                            headers={'Precedence': 'bulk'})
        run_pipeline(str(diverted.id))

        with patch('apps.email_processing.tasks.pipeline.run_pipeline.delay') as mock_delay:
            resp = self.client.post(reverse('email_processing:promote_diverted',
                                            args=[diverted.id]))
        self.assertEqual(resp.status_code, 302)
        mock_delay.assert_called_once_with(str(diverted.id), force_extract=True)


class ThreadTextTests(TestCase):
    def test_gmail_marker_strips_history(self):
        text = ("Can we move it to 3pm?\n\n"
                "On Mon, Jul 6, 2026 at 2:14 PM Jane Doe <jane@x.example> wrote:\n"
                "> Confirming your meeting on Thursday at 2pm\n"
                "> with the Congresswoman.")
        self.assertEqual(thread_text.strip_quoted_history(text), 'Can we move it to 3pm?')

    def test_outlook_header_block_strips_history(self):
        text = ("Works for us, thank you!\n\n"
                "From: Office Scheduler <sched@mail.example.com>\n"
                "Sent: Monday, July 6, 2026 2:14 PM\n"
                "To: Jane Doe\n"
                "Subject: RE: Meeting request\n\n"
                "Confirming your meeting on Thursday.")
        self.assertEqual(thread_text.strip_quoted_history(text), 'Works for us, thank you!')

    def test_from_in_prose_is_not_a_marker(self):
        text = ("From: my perspective, Thursday works best.\n"
                "Let me know what you think.")
        self.assertEqual(thread_text.strip_quoted_history(text), text)

    def test_subject_normalization(self):
        self.assertEqual(thread_text.normalize_subject('RE: Re: FW: Meeting  Request'),
                         'meeting request')

    def test_html_to_text(self):
        html = '<div><p>Hello <b>there</b></p><style>.x{color:red}</style><p>Line 2</p></div>'
        text = thread_text.html_to_text(html)
        self.assertIn('Hello there', text)
        self.assertIn('Line 2', text)
        self.assertNotIn('color:red', text)
