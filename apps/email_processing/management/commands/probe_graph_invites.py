# SPDX-License-Identifier: Apache-2.0
"""Spike (spec §4.2): verify how Outlook meeting invites arrive for a mailbox.

Answers, against the real tenant, the question the ICS channel depends on:
do invites show up as ``message`` resources with ``meetingMessageType`` set
(and with a retrievable calendar payload), or is a separate ``/events``
subscription resource required?

Run with Graph credentials configured:
    python manage.py probe_graph_invites --mailbox scheduling@mail.example.com

Read-only; makes no subscriptions and writes nothing.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.email_processing.graph_client import MicrosoftGraphClient, GraphAPIError


class Command(BaseCommand):
    help = 'Probe how meeting invites arrive via Graph for a mailbox (read-only spike)'

    def add_arguments(self, parser):
        parser.add_argument('--mailbox', required=True,
                            help='Mailbox to probe (must be Graph-accessible)')
        parser.add_argument('--top', type=int, default=50,
                            help='How many recent messages to inspect (default 50)')

    def handle(self, *args, **options):
        mailbox = options['mailbox']
        top = options['top']
        try:
            client = MicrosoftGraphClient()
        except GraphAPIError as exc:
            raise CommandError(f'Graph credentials not configured: {exc}')

        endpoint = f"users/{mailbox}/messages"
        params = {
            '$top': min(top, 200),
            '$orderby': 'receivedDateTime desc',
            '$select': 'id,subject,receivedDateTime,meetingMessageType,hasAttachments',
        }
        try:
            response = client._make_request('GET', endpoint, params=params)
        except GraphAPIError as exc:
            raise CommandError(f'Message listing failed: {exc}')

        messages = response.get('value', [])
        invites = [m for m in messages
                   if m.get('meetingMessageType') not in (None, 'none')]

        self.stdout.write(f"Inspected {len(messages)} recent messages in {mailbox}")
        self.stdout.write(f"Meeting messages found: {len(invites)}\n")

        for msg in invites:
            self.stdout.write(
                f"  [{msg.get('meetingMessageType')}] "
                f"{msg.get('receivedDateTime')}  "
                f"{(msg.get('subject') or '')[:60]}  "
                f"attachments={msg.get('hasAttachments')}"
            )
            # Check whether the invite exposes its event payload on the message
            # resource itself (the decisive question for the ICS channel).
            try:
                detail = client._make_request(
                    'GET', f"users/{mailbox}/messages/{msg['id']}",
                    params={'$select': 'id,meetingMessageType',
                            '$expand': 'attachments($select=name,contentType,size)'},
                )
                atts = detail.get('attachments', [])
                calendar_atts = [
                    a for a in atts
                    if 'calendar' in (a.get('contentType') or '').lower()
                    or (a.get('name') or '').lower().endswith('.ics')
                ]
                self.stdout.write(
                    f"      attachments: {[(a.get('name'), a.get('contentType')) for a in atts]}"
                )
                self.stdout.write(
                    f"      calendar payload on message resource: "
                    f"{'YES' if calendar_atts else 'NO'}"
                )
            except GraphAPIError as exc:
                self.stdout.write(self.style.WARNING(f"      detail fetch failed: {exc}"))

        self.stdout.write('')
        if not invites:
            self.stdout.write(self.style.WARNING(
                'No meeting messages in the inspected window. Send a test invite '
                'to the mailbox and re-run.'
            ))
        else:
            self.stdout.write(
                'Decision input: if calendar payload was NO for invites above, the '
                'ICS channel needs an /events subscription resource (spec §4.2) — '
                'record the answer in docs/EMAIL_INGESTION_BUILD_PLAN.md.'
            )
