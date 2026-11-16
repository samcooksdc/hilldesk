# SPDX-License-Identifier: Apache-2.0
"""Re-runnable version of the sender-reputation seed (migration 0008).

Useful when SCHEDULING_MAILBOXES / INTERNAL_EMAIL_DOMAINS get configured after
the migration already ran (typical in prod bring-up), or after a contact
import.
"""

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.contacts.models import ContactEmailAddress
from apps.email_processing.models import SenderReputation


class Command(BaseCommand):
    help = 'Seed/refresh the sender-reputation allowlist from internal domains and existing contacts'

    def handle(self, *args, **options):
        # Internal domains
        domains = set(getattr(settings, 'INTERNAL_EMAIL_DOMAINS', []) or [])
        for mailbox in getattr(settings, 'SCHEDULING_MAILBOXES', []) or []:
            if '@' in mailbox:
                domains.add(mailbox.split('@')[1].strip().lower())
        created_domains = 0
        for domain in sorted(d for d in domains if d):
            _, created = SenderReputation.objects.get_or_create(
                domain=domain, sender_key='',
                defaults={'list': 'allow', 'notes': 'seed: internal domain'},
            )
            created_domains += int(created)

        # Existing contacts (blind index copied; no decryption)
        contact_keys = (
            ContactEmailAddress.objects.exclude(email_key='')
            .values_list('email_key', flat=True).distinct()
        )
        existing = set(
            SenderReputation.objects.exclude(sender_key='')
            .values_list('sender_key', flat=True)
        )
        new_rows = [
            SenderReputation(sender_key=key, domain='', list='allow',
                             notes='seed: existing contact')
            for key in contact_keys if key not in existing
        ]
        SenderReputation.objects.bulk_create(new_rows)

        self.stdout.write(self.style.SUCCESS(
            f"Seeded {created_domains} internal domain(s), {len(new_rows)} contact sender(s)"
        ))
