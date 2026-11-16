# SPDX-License-Identifier: Apache-2.0
"""The named dangerous interaction (design spec §5 / implementation spec §12.2):

Dedup must catch redelivered/resent messages WITHOUT ever eating a short
reschedule reply that quotes a long thread. If quoted-history stripping and
content hashing interact wrongly, "move it to 3pm" hashes on the quoted thread
and every reply in a busy conversation looks like a duplicate — reschedules
get silently dropped, which is the worst failure this system can have.
"""
from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.email_processing.models import EmailProcessing, FilterLog
from apps.email_processing.tasks.pipeline import run_pipeline

from .test_email_funnel import make_raw


LONG_ORIGINAL_BODY = (
    "Dear Scheduler,\n\n"
    "On behalf of the Franklin Manufacturing Alliance I would like to request a "
    "meeting with the Congresswoman on Thursday, July 16 at 2:00 PM to discuss "
    "the pending workforce development legislation. We expect five attendees "
    "including our executive director. Please let me know if that time works.\n\n"
    "Best regards,\nJane Doe\nFranklin Manufacturing Alliance\n(517) 555-0140"
)


class DedupVsRescheduleTests(TestCase):
    def _process(self, raw):
        return run_pipeline(str(raw.id))

    def test_short_reschedule_reply_quoting_long_thread_passes(self):
        # Original request goes through.
        original = make_raw(
            sender='jane@mma.example', subject='Meeting request — MMA',
            body=LONG_ORIGINAL_BODY,
        )
        self.assertEqual(self._process(original)['status'], 'extract')

        # Short reply in the same conversation quoting the ENTIRE thread.
        quoted = '\n'.join(f'> {line}' for line in LONG_ORIGINAL_BODY.splitlines())
        reply = make_raw(
            sender='jane@mma.example', subject='RE: Meeting request — MMA',
            conversation_id=original.conversation_id,
            body=(
                "Apologies — can we move it to 3pm instead?\n\n"
                "On Thu, Jul 9, 2026 at 10:02 AM Office Scheduler "
                "<sched@mail.example.com> wrote:\n" + quoted
            ),
        )
        result = self._process(reply)

        # The reply must NOT be diverted as a duplicate…
        self.assertEqual(result['status'], 'extract',
                         "Reschedule reply was eaten by the funnel")
        dedup_log = FilterLog.objects.get(raw_message=reply, stage='3_dedup')
        self.assertEqual(dedup_log.outcome, 'pass')
        # …and its hash must be of the new content, i.e. different from the
        # original message's hash even though it quotes it in full.
        original_hash = FilterLog.objects.get(
            raw_message=original, stage='3_dedup').dedup_hash
        self.assertNotEqual(dedup_log.dedup_hash, original_hash)

    def test_identical_redelivery_by_message_id_diverts(self):
        # Same internet_message_id landing twice (second mailbox copy / race).
        original = make_raw(sender='jane@mma.example', body=LONG_ORIGINAL_BODY)
        self.assertEqual(self._process(original)['status'], 'extract')

        redelivered = make_raw(
            sender='jane@mma.example', body=LONG_ORIGINAL_BODY,
            internet_message_id=original.internet_message_id,
            mailbox='scheduling@mail.example.com',
        )
        result = self._process(redelivered)
        self.assertEqual(result['status'], 'divert')
        log = FilterLog.objects.get(raw_message=redelivered, stage='3_dedup')
        self.assertEqual(log.signals['duplicate_of'], 'internet_message_id')

    def test_content_identical_resend_diverts(self):
        # Fresh Message-ID, same sender/subject/body (sender clicked Send twice).
        first = make_raw(sender='jane@mma.example', subject='Meeting request',
                         body=LONG_ORIGINAL_BODY)
        self.assertEqual(self._process(first)['status'], 'extract')

        resend = make_raw(sender='jane@mma.example', subject='Meeting request',
                          body=LONG_ORIGINAL_BODY)
        result = self._process(resend)
        self.assertEqual(result['status'], 'divert')
        log = FilterLog.objects.get(raw_message=resend, stage='3_dedup')
        self.assertEqual(log.signals['duplicate_of'], 'content_hash')
        # No pipeline record was created for the duplicate.
        self.assertFalse(EmailProcessing.objects.filter(raw_message=resend).exists())

    def test_same_short_text_in_different_thread_is_not_a_duplicate(self):
        # "Sounds good, Tuesday works" in two unrelated conversations must not
        # collide: the hash includes the normalized subject.
        a = make_raw(sender='jane@mma.example', subject='RE: Factory tour',
                     body='Sounds good, Tuesday works. Can we schedule it?')
        self.assertEqual(self._process(a)['status'], 'extract')

        b = make_raw(sender='jane@mma.example', subject='RE: Board meeting',
                     body='Sounds good, Tuesday works. Can we schedule it?')
        self.assertEqual(self._process(b)['status'], 'extract')

    @override_settings(DEDUP_WINDOW_DAYS=14)
    def test_resend_outside_window_is_not_a_duplicate(self):
        first = make_raw(sender='jane@mma.example', subject='Meeting request',
                         body=LONG_ORIGINAL_BODY)
        self.assertEqual(self._process(first)['status'], 'extract')
        # Age the first run's ledger past the window.
        FilterLog.objects.filter(raw_message=first).update(
            created_at=timezone.now() - timedelta(days=20))

        resend = make_raw(sender='jane@mma.example', subject='Meeting request',
                          body=LONG_ORIGINAL_BODY)
        self.assertEqual(self._process(resend)['status'], 'extract')

    def test_forward_with_fresh_message_id_reenters(self):
        # A staffer forwarding a diverted/processed message is a signal it
        # matters; the forwarded copy has a fresh Message-ID and (Phase 2,
        # before forward-channel parsing) a body wrapped in forward markers, so
        # its stripped content is the forwarder's note — it must re-enter.
        original = make_raw(sender='jane@mma.example', body=LONG_ORIGINAL_BODY)
        self.assertEqual(self._process(original)['status'], 'extract')

        forward = make_raw(
            sender='staffer@mail.example.com', subject='FW: Meeting request — MMA',
            body=(
                "Flagging this one — can we make it happen?\n\n"
                "---------- Forwarded message ----------\n"
                + LONG_ORIGINAL_BODY
            ),
        )
        result = self._process(forward)
        self.assertEqual(result['status'], 'extract')
        log = FilterLog.objects.get(raw_message=forward, stage='3_dedup')
        self.assertEqual(log.outcome, 'pass')
