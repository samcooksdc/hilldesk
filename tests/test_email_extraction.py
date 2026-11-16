# SPDX-License-Identifier: Apache-2.0
"""Phase 4 (single extraction call) tests.

Covers: the mock provider's deterministic candidate sets, schema validation as
the trust boundary (fuzz: malformed/injection-shaped output must escalate and
never reach candidates), the repair retry, the pipeline's candidate
persistence, the ICS-covers-the-message rule, and the Bedrock provider's forced
tool-use parsing against a faked boto3 client.
"""
import io
import json
from unittest.mock import MagicMock, patch

from django.test import TestCase

from apps.email_processing.llm_providers import validate_candidate_set
from apps.email_processing.llm_providers.mock import MockProvider
from apps.email_processing.llm_providers.schema import MessageBundle
from apps.email_processing.models import EmailProcessing, ExtractionCandidate
from apps.email_processing.tasks.pipeline import run_pipeline

from .test_email_channels import ICS_REQUEST, make_raw_with_ics
from .test_email_funnel import make_raw


def bundle(subject='Meeting request', content='', **kw):
    defaults = dict(
        subject=subject, new_content=content,
        sender_email='jane@mma.example', sender_name='Jane Doe',
        received_at_iso='2026-07-06T14:00:00+00:00',
        office_timezone='America/New_York',
    )
    defaults.update(kw)
    return MessageBundle(**defaults)


class MockProviderTests(TestCase):
    def setUp(self):
        self.provider = MockProvider()

    def test_new_event_extraction_is_schema_valid(self):
        out = self.provider.extract_candidates(bundle(
            content='Could we schedule a meeting on July 20 at 2pm in the '
                    'Fairview Community Center? On behalf of the Franklin '
                    'Manufacturing Alliance.\n(517) 555-0140'
        ))
        self.assertEqual(validate_candidate_set(out.data), [])
        c = out.data['candidates'][0]
        self.assertEqual(c['intent'], 'NEW_EVENT')
        self.assertEqual(c['event']['start_date'], '2026-07-20')
        self.assertEqual(c['event']['start_time'], '14:00')
        self.assertIn('Franklin Manufacturing Alliance', c['organizations'][0]['name'])
        self.assertEqual(c['contacts'][0]['role'], 'point_of_contact')
        self.assertEqual(c['contacts'][0]['email'], 'jane@mma.example')
        self.assertEqual(c['verbatim']['date_text'], 'July 20')

    def test_multi_event_fanout(self):
        out = self.provider.extract_candidates(bundle(content=(
            'EVENT: Ribbon cutting on August 3 at 10am in Fairview.\n\n'
            'EVENT: Veterans roundtable on August 5 at 1pm in Fairview.'
        )))
        self.assertEqual(len(out.data['candidates']), 2)
        dates = {c['event']['start_date'] for c in out.data['candidates']}
        self.assertEqual(dates, {'2026-08-03', '2026-08-05'})

    def test_recurring_with_and_without_end(self):
        open_ended = self.provider.extract_candidates(bundle(
            content='We meet weekly on Mondays at 9am — please add the Congresswoman.'
        )).data['candidates'][0]
        self.assertEqual(open_ended['intent'], 'RECURRING_EVENT')
        self.assertFalse(open_ended['recurrence']['has_end'])

        bounded = self.provider.extract_candidates(bundle(
            content='A weekly briefing at 9am for 6 weeks starting July 13.'
        )).data['candidates'][0]
        self.assertEqual(bounded['intent'], 'RECURRING_EVENT')
        self.assertTrue(bounded['recurrence']['has_end'])
        self.assertIn('COUNT=6', bounded['recurrence']['rrule'])

    def test_cancellation_and_reschedule(self):
        cancel = self.provider.extract_candidates(bundle(
            subject='RE: Factory tour',
            content='Unfortunately we need to cancel the factory tour.'
        )).data['candidates'][0]
        self.assertEqual(cancel['intent'], 'CANCELLATION')
        self.assertTrue(cancel['cancellation_target_hint'])

        move = self.provider.extract_candidates(bundle(
            subject='RE: Factory tour',
            content='Can we move it to 3pm instead?'
        )).data['candidates'][0]
        self.assertEqual(move['intent'], 'RESCHEDULE')

    def test_no_signal_is_uncertain(self):
        c = self.provider.extract_candidates(bundle(
            subject='Question', content='What is your position on the farm bill?'
        )).data['candidates'][0]
        self.assertEqual(c['intent'], 'UNCERTAIN')
        self.assertLess(c['confidence'], 0.5)


class SchemaFuzzTests(TestCase):
    """Malformed / injection-shaped model output must fail validation."""

    def test_valid_minimal_set_passes(self):
        data = {'candidates': [{
            'intent': 'NEW_EVENT', 'confidence': 0.8,
            'event': {'title': 'Meeting'},
            'recurrence': {'rrule': None, 'has_end': False},
        }]}
        self.assertEqual(validate_candidate_set(data), [])

    def test_rejects_shapes(self):
        cases = [
            'just some text the model produced',                      # not an object
            {'candidates': 'DROP TABLE events'},                       # wrong type
            {'candidates': [{'intent': 'DELETE_ALL', 'confidence': 1,  # bad enum
                             'event': {'title': 'x'},
                             'recurrence': {'rrule': None, 'has_end': False}}]},
            {'candidates': [{'intent': 'NEW_EVENT', 'confidence': 5,   # bad range
                             'event': {'title': 'x'},
                             'recurrence': {'rrule': None, 'has_end': False}}]},
            {'candidates': [{'intent': 'NEW_EVENT', 'confidence': 0.5}]},  # missing keys
            {'notes': 'no candidates key'},
        ]
        for data in cases:
            self.assertNotEqual(validate_candidate_set(data), [], data)


class PipelineExtractionTests(TestCase):
    def test_scheduling_email_produces_candidates(self):
        raw = make_raw(body='Could we schedule a briefing on July 20 at 2pm '
                            'in the district office?')
        result = run_pipeline(str(raw.id))
        self.assertEqual(result['status'], 'extract')

        record = EmailProcessing.objects.get(raw_message=raw)
        self.assertEqual(record.status, 'processed')
        self.assertEqual(record.extracted_data['schema'], 'candidate_set_v1')

        cand = ExtractionCandidate.objects.get(raw_message=raw)
        self.assertEqual(cand.intent, 'NEW_EVENT')
        # Post-processing (Phase 5) routes the candidate immediately.
        self.assertEqual(cand.status, 'materialized')
        self.assertEqual(cand.email_processing, record)
        self.assertEqual(cand.thread, record.thread)
        self.assertEqual(cand.provenance['channel'], 'body')

    def test_multi_event_email_fans_out(self):
        raw = make_raw(subject='Two August events', body=(
            'EVENT: Ribbon cutting on August 3 at 10am in Fairview. A meeting.\n\n'
            'EVENT: Veterans roundtable on August 5 at 1pm in Fairview.'
        ))
        run_pipeline(str(raw.id))
        self.assertEqual(ExtractionCandidate.objects.filter(raw_message=raw).count(), 2)

    def test_open_ended_recurrence_flags_needs_end(self):
        raw = make_raw(body='Our board meets monthly and would love a standing '
                            'briefing meeting at 8am.')
        run_pipeline(str(raw.id))
        cand = ExtractionCandidate.objects.get(raw_message=raw)
        self.assertEqual(cand.intent, 'RECURRING_EVENT')
        self.assertTrue(cand.recurrence_needs_end)
        self.assertTrue(cand.recurrence_rule.startswith('FREQ='))

    def test_ics_message_skips_model_call(self):
        raw = make_raw_with_ics(ICS_REQUEST, body='Please see attached.')
        with patch('apps.email_processing.llm_providers.get_llm_provider') as factory:
            result = run_pipeline(str(raw.id))
        self.assertEqual(result['status'], 'extract')
        factory.assert_not_called()

        cand = ExtractionCandidate.objects.get(raw_message=raw)
        self.assertEqual(cand.intent, 'NEW_EVENT')
        self.assertEqual(cand.confidence, 1.0)
        self.assertIn('uid', cand.provenance)

    def test_ics_with_substantial_prose_also_extracts_body(self):
        prose = ('Beyond the invite, we would also like to discuss the pending '
                 'workforce bill and introduce our new executive director, who '
                 'will join the meeting along with two board members from the '
                 'Fairview chapter. Please let us know about press availability '
                 'and whether photos afterward would be possible.')
        raw = make_raw_with_ics(ICS_REQUEST, body=prose)
        run_pipeline(str(raw.id))
        channels = set(ExtractionCandidate.objects.filter(raw_message=raw)
                       .values_list('provenance__channel', flat=True))
        self.assertEqual(len(channels), 2)  # ics attachment + body

    def test_unreadable_attachment_escalates(self):
        from apps.email_processing.models import AttachmentBlob
        raw = make_raw(
            body='Invitation attached — can the Congresswoman join us?',
            attachments=[{'name': 'invite.pdf', 'content_type': 'application/pdf',
                          'size': 11, 'is_inline': False}],
        )
        AttachmentBlob.objects.create(raw_message=raw, name='invite.pdf',
                                      content_type='application/pdf', size=11,
                                      payload=b'%PDF-broken')
        result = run_pipeline(str(raw.id))
        self.assertEqual(result['status'], 'escalate')
        record = EmailProcessing.objects.get(raw_message=raw)
        self.assertEqual(record.status, 'escalated')
        self.assertEqual(record.extracted_data['escalation']['reason'],
                         'attachment_unreadable')
        self.assertFalse(ExtractionCandidate.objects.filter(raw_message=raw).exists())

    def test_malformed_output_escalates_after_repair_retry(self):
        from apps.email_processing.llm_providers.schema import RawModelOutput
        garbage = RawModelOutput(data={'candidates': 'not-a-list'})
        provider = MagicMock()
        provider.extract_candidates.return_value = garbage

        raw = make_raw(body='Can we schedule a meeting next Thursday?')
        with patch('apps.email_processing.llm_providers.get_llm_provider',
                   return_value=provider):
            result = run_pipeline(str(raw.id))

        self.assertEqual(result['status'], 'escalate')
        self.assertEqual(provider.extract_candidates.call_count, 2)  # one repair retry
        record = EmailProcessing.objects.get(raw_message=raw)
        self.assertEqual(record.extracted_data['escalation']['reason'],
                         'malformed_model_output')
        self.assertFalse(ExtractionCandidate.objects.filter(raw_message=raw).exists())

    def test_repair_retry_recovers(self):
        from apps.email_processing.llm_providers.schema import RawModelOutput
        good = RawModelOutput(data={'candidates': [{
            'intent': 'NEW_EVENT', 'confidence': 0.9,
            'event': {'title': 'Repaired meeting'},
            'recurrence': {'rrule': None, 'has_end': False},
        }]})
        provider = MagicMock()
        provider.extract_candidates.side_effect = [
            RawModelOutput(data={'oops': True}), good,
        ]

        raw = make_raw(body='Can we schedule a meeting next Thursday?')
        with patch('apps.email_processing.llm_providers.get_llm_provider',
                   return_value=provider):
            result = run_pipeline(str(raw.id))

        self.assertEqual(result['status'], 'extract')
        cand = ExtractionCandidate.objects.get(raw_message=raw)
        self.assertEqual(cand.payload['event']['title'], 'Repaired meeting')
        # The retry carried the validation errors back to the provider.
        retry_bundle = provider.extract_candidates.call_args_list[1].args[0]
        self.assertTrue(retry_bundle.repair_error)


class BedrockProviderTests(TestCase):
    """Forced tool-use invocation against a faked boto3 runtime client."""

    def _provider_with_response(self, response_body):
        from apps.email_processing.llm_providers.bedrock import BedrockProvider
        provider = BedrockProvider()
        fake_client = MagicMock()
        fake_client.invoke_model.return_value = {
            'body': io.BytesIO(json.dumps(response_body).encode('utf-8')),
        }
        provider._runtime_client = fake_client
        return provider, fake_client

    def test_tool_use_block_is_parsed(self):
        candidate_set = {'candidates': [], 'notes': None}
        provider, fake_client = self._provider_with_response({
            'content': [{'type': 'tool_use', 'name': 'record_candidates',
                         'input': candidate_set}],
        })
        out = provider.extract_candidates(bundle(content='hello'))
        self.assertEqual(out.data, candidate_set)
        self.assertFalse(out.error)

        request = json.loads(fake_client.invoke_model.call_args.kwargs['body'])
        self.assertEqual(request['tool_choice'],
                         {'type': 'tool', 'name': 'record_candidates'})
        self.assertEqual(request['tools'][0]['name'], 'record_candidates')

    def test_missing_tool_use_reports_error(self):
        provider, _ = self._provider_with_response({
            'content': [{'type': 'text', 'text': 'I refuse to use the tool'}],
        })
        out = provider.extract_candidates(bundle(content='hello'))
        self.assertIsNone(out.data)
        self.assertEqual(out.error, 'no_tool_use_block')

    def test_image_blocks_ride_along(self):
        provider, fake_client = self._provider_with_response({
            'content': [{'type': 'tool_use', 'name': 'record_candidates',
                         'input': {'candidates': []}}],
        })
        provider.extract_candidates(bundle(
            content='flyer attached',
            image_blocks=[{'name': 'flyer.png', 'content_type': 'image/png',
                           'data_b64': 'aGk='}],
        ))
        request = json.loads(fake_client.invoke_model.call_args.kwargs['body'])
        content = request['messages'][0]['content']
        self.assertEqual(content[0]['type'], 'image')
        self.assertEqual(content[0]['source']['media_type'], 'image/png')
        self.assertEqual(content[-1]['type'], 'text')
