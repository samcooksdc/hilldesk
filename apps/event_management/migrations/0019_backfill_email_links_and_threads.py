# Backfill the new link/thread tables from the legacy email associations.
#
# Source of truth going forward is EventEmailLink / EventThreadLink + the
# EmailProcessing.thread FK. This migration seeds them from:
#   * EmailProcessing.event (reverse FK)          -> EventEmailLink(origin='ai_auto')
#   * Event.attached_email_ids (legacy JSON list) -> EventEmailLink(origin='ai_auto')
#   * complete_email_data['thread_id'] (Outlook conversationId) -> EmailThread
#
# Deliberately does NOT create EventThreadLink rows: thread attachment is a
# forward-going, opt-in action, and auto-attaching historical conversations
# would retroactively pull in any future replies on those threads.

from django.db import migrations


def backfill(apps, schema_editor):
    EmailProcessing = apps.get_model('email_processing', 'EmailProcessing')
    EmailThread = apps.get_model('email_processing', 'EmailThread')
    Event = apps.get_model('event_management', 'Event')
    EventEmailLink = apps.get_model('event_management', 'EventEmailLink')

    # 1) Threads: group every email by its Outlook conversationId.
    touched_threads = set()
    for email in EmailProcessing.objects.all().iterator():
        data = email.complete_email_data or {}
        conversation_id = data.get('thread_id') or ''
        if not conversation_id:
            continue
        thread, _ = EmailThread.objects.get_or_create(
            conversation_id=conversation_id,
            defaults={'subject': email.subject or ''},
        )
        if email.thread_id != thread.id:
            email.thread = thread
            email.save(update_fields=['thread'])
        touched_threads.add(thread.id)

    # Refresh denormalized thread metadata.
    from django.db.models import Count, Max, Min
    for thread in EmailThread.objects.filter(id__in=touched_threads):
        agg = thread.emails.aggregate(
            n=Count('id'), last=Max('received'), first=Min('received')
        )
        participants = {}
        for sender, sender_name in thread.emails.values_list('sender', 'sender_name'):
            if sender and sender not in participants:
                participants[sender] = sender_name or ''
        thread.message_count = agg['n'] or 0
        thread.last_message_at = agg['last']
        thread.first_message_at = agg['first']
        thread.participants = [
            {'email': e, 'name': n} for e, n in participants.items()
        ]
        thread.save(update_fields=[
            'message_count', 'last_message_at', 'first_message_at', 'participants',
        ])

    # 2) Direct email links from the reverse FK (the email -> its event).
    for email in EmailProcessing.objects.exclude(event__isnull=True).iterator():
        meta = (email.complete_email_data or {}).get('processing_metadata', {})
        EventEmailLink.objects.get_or_create(
            event_id=email.event_id,
            email_id=email.id,
            defaults={
                'mode': 'include',
                'origin': 'ai_auto',
                'is_primary': bool(meta.get('is_primary_email', False)),
            },
        )

    # 3) Direct email links from the legacy Event.attached_email_ids JSON list.
    valid_email_ids = set(
        str(pk) for pk in EmailProcessing.objects.values_list('id', flat=True)
    )
    for event in Event.objects.all().iterator():
        for raw_id in (event.attached_email_ids or []):
            email_id = str(raw_id)
            if email_id not in valid_email_ids:
                continue
            EventEmailLink.objects.get_or_create(
                event_id=event.id,
                email_id=email_id,
                defaults={'mode': 'include', 'origin': 'ai_auto'},
            )


def unbackfill(apps, schema_editor):
    # Reverse: clear the seeded links and thread assignments. Safe because the
    # legacy columns (event FK, attached_email_ids) are left intact.
    EmailProcessing = apps.get_model('email_processing', 'EmailProcessing')
    EmailThread = apps.get_model('email_processing', 'EmailThread')
    EventEmailLink = apps.get_model('event_management', 'EventEmailLink')

    EventEmailLink.objects.filter(origin='ai_auto').delete()
    EmailProcessing.objects.update(thread=None)
    EmailThread.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('event_management', '0018_eventemaillink_eventthreadlink'),
    ]

    operations = [
        migrations.RunPython(backfill, unbackfill),
    ]
