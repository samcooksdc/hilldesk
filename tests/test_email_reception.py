# SPDX-License-Identifier: Apache-2.0
"""Phase 1 (reception spine) tests for the email ingestion pipeline.

Covers: RawMessage persistence + blind index + calendar detection, attachment
blob storage vs the size cap, RawMessage immutability, the sweep (including the
reconciliation-gap detection the spec calls out), and the webhook handshake /
clientState gate.
"""
import base64
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.contacts.crypto import email_blind_index
from apps.email_processing.models import (
    AttachmentBlob, RawMessage, SubscriptionState,
)
from apps.email_processing import reception
from apps.email_processing.tasks import reception as reception_tasks


def _fake_message(**overrides):
    msg = {
        'id': 'GRAPH-AAA-1',
        'internetMessageId': '<msg1@advocacy.example>',
        'conversationId': 'CONV-1',
        'receivedDateTime': '2026-07-01T14:00:00Z',
        'sender': {'emailAddress': {'address': 'Jane@advocacy.example', 'name': 'Jane Doe'}},
        'subject': 'Meeting request for next week',
        'body': {'contentType': 'text', 'content': 'Can we meet next Thursday at 2pm?'},
        'internetMessageHeaders': [
            {'name': 'Authentication-Results', 'value': 'spf=pass dkim=pass'},
        ],
        'hasAttachments': False,
    }
    msg.update(overrides)
    return msg


class ReceptionIngestTests(TestCase):
    def _client_returning(self, message, attachments=None):
        client = MagicMock()
        client.get_message_full.return_value = message
        client.get_message_attachments.return_value = attachments or []
        return client

    def test_ingest_persists_raw_message_with_blind_index(self):
        client = self._client_returning(_fake_message())
        raw, created = reception.ingest_message(client, 'office@mail.example.com', 'GRAPH-AAA-1')

        self.assertTrue(created)
        self.assertEqual(raw.internet_message_id, '<msg1@advocacy.example>')
        self.assertEqual(raw.conversation_id, 'CONV-1')
        self.assertEqual(raw.mailbox, 'office@mail.example.com')
        self.assertEqual(raw.source, 'sweep')
        # Sender stored encrypted; blind index derived from the normalized address.
        self.assertEqual(raw.sender, 'Jane@advocacy.example')
        self.assertEqual(raw.sender_key, email_blind_index('jane@advocacy.example'))
        # Plain-text body path (not HTML).
        self.assertEqual(raw.body_text, 'Can we meet next Thursday at 2pm?')
        self.assertEqual(raw.body_html, '')
        self.assertEqual(raw.headers.get('Authentication-Results'), 'spf=pass dkim=pass')
        self.assertFalse(raw.has_calendar_part)

    def test_ingest_is_idempotent(self):
        client = self._client_returning(_fake_message())
        raw1, created1 = reception.ingest_message(client, 'mb@x.example', 'GRAPH-AAA-1')
        raw2, created2 = reception.ingest_message(client, 'mb@x.example', 'GRAPH-AAA-1')
        self.assertTrue(created1)
        self.assertFalse(created2)
        self.assertEqual(raw1.id, raw2.id)
        self.assertEqual(RawMessage.objects.count(), 1)

    def test_calendar_part_detected_from_ics_attachment(self):
        msg = _fake_message(hasAttachments=True)
        ics = base64.b64encode(b'BEGIN:VCALENDAR\nEND:VCALENDAR').decode()
        attachments = [{
            'id': 'ATT-1', 'name': 'invite.ics', 'contentType': 'text/calendar',
            'size': 30, 'isInline': False, 'contentBytes': ics,
        }]
        client = self._client_returning(msg, attachments)
        raw, _ = reception.ingest_message(client, 'mb@x.example', 'GRAPH-AAA-1')

        self.assertTrue(raw.has_calendar_part)
        blob = AttachmentBlob.objects.get(raw_message=raw)
        self.assertEqual(blob.name, 'invite.ics')
        self.assertEqual(bytes(blob.payload), b'BEGIN:VCALENDAR\nEND:VCALENDAR')
        self.assertEqual(raw.attachments[0]['content_type'], 'text/calendar')

    @override_settings(ATTACHMENT_STORE_MAX_BYTES=10)
    def test_oversized_attachment_stored_as_metadata_only(self):
        msg = _fake_message(hasAttachments=True)
        big = base64.b64encode(b'x' * 100).decode()
        attachments = [{
            'id': 'ATT-2', 'name': 'big.pdf', 'contentType': 'application/pdf',
            'size': 100, 'isInline': False, 'contentBytes': big,
        }]
        client = self._client_returning(msg, attachments)
        raw, _ = reception.ingest_message(client, 'mb@x.example', 'GRAPH-AAA-1')

        # Metadata recorded, but payload NOT stored (over the cap).
        self.assertEqual(len(raw.attachments), 1)
        self.assertEqual(AttachmentBlob.objects.filter(raw_message=raw).count(), 0)

    def test_raw_message_is_immutable(self):
        client = self._client_returning(_fake_message())
        raw, _ = reception.ingest_message(client, 'mb@x.example', 'GRAPH-AAA-1')
        raw.subject = 'tampered'
        with self.assertRaises(Exception):
            raw.save()


@override_settings(SCHEDULING_MAILBOXES=['office@mail.example.com'])
class SweepTests(TestCase):
    @patch('apps.email_processing.tasks.reception.run_pipeline')
    @patch('apps.email_processing.tasks.reception.MicrosoftGraphClient')
    def test_sweep_ingests_new_message_and_enqueues_pipeline(self, mock_client_cls, mock_pipeline):
        client = mock_client_cls.return_value
        client.delta_messages.return_value = {
            'messages': [{'id': 'GRAPH-AAA-1'}],
            'delta_link': 'https://graph.microsoft.com/v1.0/delta?$deltatoken=TOK',
        }
        client.get_message_full.return_value = _fake_message()
        client.get_message_attachments.return_value = []

        result = reception_tasks.sweep_mailbox('office@mail.example.com')

        self.assertEqual(result['ingested'], 1)
        self.assertTrue(RawMessage.objects.filter(graph_message_id='GRAPH-AAA-1').exists())
        mock_pipeline.delay.assert_called_once()
        # Delta token persisted for the next incremental sweep.
        state = SubscriptionState.objects.get(mailbox='office@mail.example.com')
        self.assertEqual(state.delta_token, 'https://graph.microsoft.com/v1.0/delta?$deltatoken=TOK')
        self.assertIsNotNone(state.last_sweep_at)

    @override_settings(GRAPH_WEBHOOK_ENABLED=True)
    @patch('apps.email_processing.tasks.reception.security_logger')
    @patch('apps.email_processing.tasks.reception.run_pipeline')
    @patch('apps.email_processing.tasks.reception.MicrosoftGraphClient')
    def test_sweep_logs_reconciliation_gap_when_webhook_enabled(
        self, mock_client_cls, mock_pipeline, mock_seclog
    ):
        # A message present in Graph but absent from RawMessage while webhooks are
        # on == the webhook silently dropped it: must be ingested AND logged.
        client = mock_client_cls.return_value
        client.delta_messages.return_value = {
            'messages': [{'id': 'GRAPH-AAA-1'}], 'delta_link': None,
        }
        client.get_message_full.return_value = _fake_message()
        client.get_message_attachments.return_value = []

        result = reception_tasks.sweep_mailbox('office@mail.example.com')

        self.assertEqual(result['gaps'], 1)
        self.assertTrue(mock_seclog.warning.called)

    @patch('apps.email_processing.tasks.reception.run_pipeline')
    @patch('apps.email_processing.tasks.reception.MicrosoftGraphClient')
    def test_sweep_falls_back_to_window_listing_on_delta_failure(self, mock_client_cls, mock_pipeline):
        from apps.email_processing.graph_client import GraphAPIError
        client = mock_client_cls.return_value
        client.delta_messages.side_effect = GraphAPIError('410 Gone')
        client.list_recent_messages.return_value = [{'id': 'GRAPH-AAA-1'}]
        client.get_message_full.return_value = _fake_message()
        client.get_message_attachments.return_value = []

        result = reception_tasks.sweep_mailbox('office@mail.example.com')

        self.assertTrue(result['fallback'])
        self.assertEqual(result['ingested'], 1)
        client.list_recent_messages.assert_called_once()
        # Delta token cleared so the next sweep re-establishes a fresh delta.
        state = SubscriptionState.objects.get(mailbox='office@mail.example.com')
        self.assertEqual(state.delta_token, '')


@override_settings(GRAPH_WEBHOOK_ENABLED=True, GRAPH_WEBHOOK_CLIENT_STATE='s3cr3t')
class WebhookTests(TestCase):
    def _url(self):
        return reverse('api:graph-webhook')

    def test_validation_handshake_echoes_token(self):
        resp = self.client.post(self._url() + '?validationToken=abc123')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content.decode(), 'abc123')
        self.assertEqual(resp['Content-Type'], 'text/plain')

    @patch('apps.email_processing.webhook_views.fetch_message')
    def test_valid_notification_enqueues_fetch(self, mock_fetch):
        SubscriptionState.objects.create(
            mailbox='office@mail.example.com', subscription_id='SUB-1', status='active'
        )
        payload = {'value': [{
            'subscriptionId': 'SUB-1', 'clientState': 's3cr3t',
            'resourceData': {'id': 'GRAPH-AAA-1'},
        }]}
        resp = self.client.post(self._url(), data=payload, content_type='application/json')
        self.assertEqual(resp.status_code, 202)
        mock_fetch.delay.assert_called_once_with('office@mail.example.com', 'GRAPH-AAA-1')

    @patch('apps.email_processing.webhook_views.fetch_message')
    def test_clientstate_mismatch_is_rejected(self, mock_fetch):
        payload = {'value': [{
            'subscriptionId': 'SUB-1', 'clientState': 'WRONG',
            'resourceData': {'id': 'GRAPH-AAA-1'},
        }]}
        resp = self.client.post(self._url(), data=payload, content_type='application/json')
        self.assertEqual(resp.status_code, 403)
        mock_fetch.delay.assert_not_called()

    @override_settings(GRAPH_WEBHOOK_ENABLED=False)
    def test_webhook_disabled_returns_404(self):
        resp = self.client.post(self._url() + '?validationToken=abc123')
        self.assertEqual(resp.status_code, 404)
