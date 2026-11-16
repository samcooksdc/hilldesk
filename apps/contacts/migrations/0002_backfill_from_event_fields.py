"""Backfill normalized Contact / Organization rows from denormalized Event data.

Moves each Event's ``point_of_contact_name/email/phone`` into a Contact (+ email
/ phone child rows + EventContact link) and its ``group`` into an Organization
(+ EventOrganization link), deduping by blind index so a repeated point of
contact or organization collapses to a single row.

The denormalized Event columns are left in place for now; a later migration
removes them once all readers/writers use the normalized models.

NOTE: historical models do not run the custom ``save()`` overrides, so the
blind-index keys are computed and set explicitly here.
"""

from django.db import migrations

from apps.contacts.crypto import email_blind_index, name_blind_index


def backfill(apps, schema_editor):
    Event = apps.get_model('event_management', 'Event')
    Contact = apps.get_model('contacts', 'Contact')
    ContactEmailAddress = apps.get_model('contacts', 'ContactEmailAddress')
    ContactPhoneNumber = apps.get_model('contacts', 'ContactPhoneNumber')
    Organization = apps.get_model('contacts', 'Organization')
    EventContact = apps.get_model('contacts', 'EventContact')
    EventOrganization = apps.get_model('contacts', 'EventOrganization')

    contacts_by_email_key = {}   # email_key -> Contact
    orgs_by_name_key = {}        # name_key  -> Organization

    for event in Event.objects.all().iterator():
        poc_name = (event.point_of_contact_name or '').strip()
        poc_email = (event.point_of_contact_email or '').strip()
        poc_phone = (event.point_of_contact_phone or '').strip()
        group = (event.group or '').strip()

        # ---- Contact -------------------------------------------------------
        contact = None
        if poc_email:
            key = email_blind_index(poc_email)
            contact = contacts_by_email_key.get(key)
            if contact is None:
                contact = Contact.objects.create(
                    name=poc_name,
                    created_by=event.created_by,
                    modified_by=event.modified_by,
                )
                ContactEmailAddress.objects.create(
                    contact=contact, email=poc_email, email_key=key, is_primary=True,
                    created_by=event.created_by, modified_by=event.modified_by,
                )
                if poc_phone:
                    ContactPhoneNumber.objects.create(
                        contact=contact, phone=poc_phone, is_primary=True,
                        created_by=event.created_by, modified_by=event.modified_by,
                    )
                contacts_by_email_key[key] = contact
        elif poc_name:
            # No email to dedupe on — one Contact per such event.
            contact = Contact.objects.create(
                name=poc_name,
                created_by=event.created_by,
                modified_by=event.modified_by,
            )
            if poc_phone:
                ContactPhoneNumber.objects.create(
                    contact=contact, phone=poc_phone, is_primary=True,
                    created_by=event.created_by, modified_by=event.modified_by,
                )

        # ---- Organization --------------------------------------------------
        org = None
        if group:
            nkey = name_blind_index(group)
            org = orgs_by_name_key.get(nkey)
            if org is None:
                org = Organization.objects.create(
                    name=group, name_key=nkey,
                    created_by=event.created_by, modified_by=event.modified_by,
                )
                orgs_by_name_key[nkey] = org

        # ---- Links ---------------------------------------------------------
        if contact:
            EventContact.objects.get_or_create(
                event=event, contact=contact,
                defaults={'role': 'point_of_contact', 'is_primary': True,
                          'linked_by': event.created_by},
            )
        if org:
            EventOrganization.objects.get_or_create(
                event=event, organization=org,
                defaults={'is_primary': True, 'linked_by': event.created_by},
            )
        if contact and org:
            contact.organizations.add(org)
            # Attach both to the event's source emails for the directory's
            # "related emails" view.
            email_ids = list(event.source_emails.values_list('pk', flat=True))
            if email_ids:
                contact.related_messages.add(*email_ids)
                org.related_messages.add(*email_ids)


def noop_reverse(apps, schema_editor):
    """Irreversible backfill: leave normalized rows in place on reverse."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('contacts', '0001_initial'),
        ('event_management', '0024_housefloorproceedings_houseflooraction'),
        ('email_processing', '0005_emailthread_emailprocessing_thread'),
    ]

    operations = [
        migrations.RunPython(backfill, noop_reverse),
    ]
