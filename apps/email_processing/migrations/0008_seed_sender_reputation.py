"""Seed the sender-reputation allowlist (spec §3.1 / build plan Phase 2).

Two seed sources, both idempotent:
- Internal domains: domains of SCHEDULING_MAILBOXES plus INTERNAL_EMAIL_DOMAINS
  — office mail must never be threshold-dropped.
- Existing Contacts: every Contact with an email blind index gets a per-sender
  allow row. The blind index is copied directly (same HMAC key space), so no
  decryption happens here; the encrypted display copy is left blank and the
  note records the provenance.

If settings/mailboxes are unconfigured at migrate time this seeds nothing; the
``seed_sender_reputation`` management command re-runs the same logic later.
"""

from django.conf import settings
from django.db import migrations


def seed(apps, schema_editor):
    SenderReputation = apps.get_model('email_processing', 'SenderReputation')
    ContactEmailAddress = apps.get_model('contacts', 'ContactEmailAddress')

    # --- Internal domains ---
    domains = set(getattr(settings, 'INTERNAL_EMAIL_DOMAINS', []) or [])
    for mailbox in getattr(settings, 'SCHEDULING_MAILBOXES', []) or []:
        if '@' in mailbox:
            domains.add(mailbox.split('@')[1].strip().lower())
    for domain in sorted(d for d in domains if d):
        SenderReputation.objects.get_or_create(
            domain=domain, sender_key='',
            defaults={'list': 'allow', 'notes': 'seed: internal domain'},
        )

    # --- Existing contacts (blind index copied, no decryption) ---
    contact_keys = (
        ContactEmailAddress.objects.exclude(email_key='')
        .values_list('email_key', flat=True).distinct()
    )
    existing = set(
        SenderReputation.objects.exclude(sender_key='')
        .values_list('sender_key', flat=True)
    )
    SenderReputation.objects.bulk_create([
        SenderReputation(sender_key=key, domain='', list='allow',
                         notes='seed: existing contact')
        for key in contact_keys if key not in existing
    ])


def unseed(apps, schema_editor):
    SenderReputation = apps.get_model('email_processing', 'SenderReputation')
    SenderReputation.objects.filter(notes__startswith='seed: ').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('email_processing', '0007_alter_rawmessage_sender_alter_rawmessage_sender_name_and_more'),
        ('contacts', '0005_contactphonenumber_phone_key_and_more'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
