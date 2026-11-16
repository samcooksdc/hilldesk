# SPDX-License-Identifier: Apache-2.0
"""Normalized Contact / Organization models for HillDesk.

Contacts and organizations were previously denormalized onto each Event
(``point_of_contact_*`` and ``group``). That cannot represent an event with
several people or organizations, nor a single contact appearing across many
events. These models normalize that data:

  * ``Contact`` / ``Organization`` hold identity + scheduling-relevant data.
  * ``ContactEmailAddress`` / ``ContactPhoneNumber`` (and the Organization
    equivalents) are child tables so a record can carry several emails/phones.
  * ``EventContact`` / ``EventOrganization`` are explicit M2M through tables
    linking events to contacts/organizations (mirroring ``EventEmailLink``).

PII fields are encrypted at rest (AES-256 via the project's Fernet-backed
encrypted fields). Because encrypted columns are not queryable, each email
carries a non-encrypted ``email_key`` blind index (and each organization a
``name_key``) used for exact-match lookup. See ``apps/contacts/crypto.py``.
"""

import uuid

from django.conf import settings
from django.db import models

from apps.authentication.fields import (
    EncryptedCharField,
    EncryptedEmailField,
    EncryptedTextField,
    SecureModelMixin,
)

from .constants import EventContactRole
from .crypto import email_blind_index, name_blind_index, phone_blind_index

User = settings.AUTH_USER_MODEL


class Organization(SecureModelMixin):
    """An organization that requests time or otherwise relates to events.

    Only ``name`` is required; every other field is nullable/blank per spec.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    name = EncryptedCharField(max_length=255, help_text="Organization name (required)")
    # Non-encrypted blind index of the normalized name, for exact-match lookup
    # during extraction (extraction supplies only an org name, never an email).
    name_key = models.CharField(
        max_length=64, db_index=True, editable=False, blank=True, default='',
        help_text="HMAC-SHA256 blind index of the normalized name (exact match)",
    )
    location = EncryptedCharField(
        max_length=512, blank=True, null=True, help_text="Primary location",
    )
    notes = EncryptedTextField(blank=True, default='', help_text="Freeform notes")

    # Related emails (the message records this org is referenced in).
    related_messages = models.ManyToManyField(
        'email_processing.EmailProcessing',
        related_name='organizations',
        blank=True,
    )
    # The organization's primary point of contact (one of its linked contacts).
    primary_contact = models.ForeignKey(
        'Contact', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', help_text="Primary point of contact for this organization",
    )

    class Meta:
        db_table = 'contacts_organization'
        ordering = ['name_key']
        verbose_name = 'Organization'
        verbose_name_plural = 'Organizations'

    def __str__(self):
        return self.name or str(self.id)

    def save(self, *args, **kwargs):
        self.name_key = name_blind_index(self.name)
        super().save(*args, **kwargs)

    @property
    def primary_email(self):
        # Iterate the (often prefetched) related set to avoid an extra query.
        addrs = list(self.email_addresses.all())
        if not addrs:
            return ''
        return (next((a for a in addrs if a.is_primary), addrs[0])).email

    @property
    def primary_phone(self):
        nums = list(self.phone_numbers.all())
        if not nums:
            return ''
        return (next((n for n in nums if n.is_primary), nums[0])).phone


class Contact(SecureModelMixin):
    """A person who relates to one or more events (point of contact, etc.)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    name = EncryptedCharField(
        max_length=255, blank=True, default='', help_text="Contact full name",
    )
    position = EncryptedCharField(
        max_length=255, blank=True, default='', help_text="Job title / position",
    )
    notes = EncryptedTextField(blank=True, default='', help_text="Freeform notes")

    # Related organizations (a contact can belong to several).
    organizations = models.ManyToManyField(
        Organization, related_name='contacts', blank=True,
    )
    # This contact's primary organization (one of `organizations`).
    primary_organization = models.ForeignKey(
        Organization, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', help_text="This contact's primary organization",
    )
    # Related emails (the message records this contact is referenced in).
    related_messages = models.ManyToManyField(
        'email_processing.EmailProcessing',
        related_name='contacts',
        blank=True,
    )

    class Meta:
        db_table = 'contacts_contact'
        ordering = ['id']
        verbose_name = 'Contact'
        verbose_name_plural = 'Contacts'

    def __str__(self):
        return self.name or self.primary_email or str(self.id)

    @property
    def primary_email(self):
        addrs = list(self.email_addresses.all())
        if not addrs:
            return ''
        return (next((a for a in addrs if a.is_primary), addrs[0])).email

    @property
    def primary_phone(self):
        nums = list(self.phone_numbers.all())
        if not nums:
            return ''
        return (next((n for n in nums if n.is_primary), nums[0])).phone


class ContactEmailAddress(SecureModelMixin):
    """One email address for a Contact. Email is the natural match key."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    contact = models.ForeignKey(
        Contact, on_delete=models.CASCADE, related_name='email_addresses',
    )
    email = EncryptedEmailField(help_text="Email address (encrypted at rest)")
    email_key = models.CharField(
        max_length=64, db_index=True, editable=False,
        help_text="HMAC-SHA256 blind index of the normalized email (exact match)",
    )
    is_primary = models.BooleanField(default=False)

    class Meta:
        db_table = 'contacts_contact_email'
        constraints = [
            # Email is the natural key: one contact email row per address.
            models.UniqueConstraint(
                fields=['email_key'], name='uniq_contact_email_key',
            ),
            models.UniqueConstraint(
                fields=['contact'], condition=models.Q(is_primary=True),
                name='uniq_primary_email_per_contact',
            ),
        ]

    def __str__(self):
        return self.email

    def save(self, *args, **kwargs):
        self.email_key = email_blind_index(self.email)
        super().save(*args, **kwargs)


class ContactPhoneNumber(SecureModelMixin):
    """One phone number for a Contact."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    contact = models.ForeignKey(
        Contact, on_delete=models.CASCADE, related_name='phone_numbers',
    )
    phone = EncryptedCharField(max_length=50, help_text="Phone number (encrypted at rest)")
    phone_key = models.CharField(
        max_length=64, db_index=True, editable=False, default='',
        help_text="HMAC-SHA256 blind index of the normalized phone (exact match)",
    )
    is_primary = models.BooleanField(default=False)

    class Meta:
        db_table = 'contacts_contact_phone'
        constraints = [
            models.UniqueConstraint(
                fields=['contact'], condition=models.Q(is_primary=True),
                name='uniq_primary_phone_per_contact',
            ),
        ]

    def __str__(self):
        return self.phone

    def save(self, *args, **kwargs):
        # Not unique: two people can share an office line. Indexed only so the
        # name+phone match signal narrows candidates cheaply (see services).
        self.phone_key = phone_blind_index(self.phone)
        super().save(*args, **kwargs)


class OrganizationEmailAddress(SecureModelMixin):
    """One email address for an Organization."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='email_addresses',
    )
    email = EncryptedEmailField(help_text="Email address (encrypted at rest)")
    email_key = models.CharField(
        max_length=64, db_index=True, editable=False,
        help_text="HMAC-SHA256 blind index of the normalized email (exact match)",
    )
    is_primary = models.BooleanField(default=False)

    class Meta:
        db_table = 'contacts_organization_email'
        constraints = [
            models.UniqueConstraint(
                fields=['email_key'], name='uniq_org_email_key',
            ),
            models.UniqueConstraint(
                fields=['organization'], condition=models.Q(is_primary=True),
                name='uniq_primary_email_per_org',
            ),
        ]

    def __str__(self):
        return self.email

    def save(self, *args, **kwargs):
        self.email_key = email_blind_index(self.email)
        super().save(*args, **kwargs)


class OrganizationPhoneNumber(SecureModelMixin):
    """One phone number for an Organization."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='phone_numbers',
    )
    phone = EncryptedCharField(max_length=50, help_text="Phone number (encrypted at rest)")
    phone_key = models.CharField(
        max_length=64, db_index=True, editable=False, default='',
        help_text="HMAC-SHA256 blind index of the normalized phone (exact match)",
    )
    is_primary = models.BooleanField(default=False)

    class Meta:
        db_table = 'contacts_organization_phone'
        constraints = [
            models.UniqueConstraint(
                fields=['organization'], condition=models.Q(is_primary=True),
                name='uniq_primary_phone_per_org',
            ),
        ]

    def __str__(self):
        return self.phone

    def save(self, *args, **kwargs):
        self.phone_key = phone_blind_index(self.phone)
        super().save(*args, **kwargs)


class EventContact(models.Model):
    """Association between an Event and a Contact (replaces point_of_contact_*).

    Explicit through table mirroring ``EventEmailLink`` so the relationship is
    many-to-many and individually auditable.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event = models.ForeignKey(
        'event_management.Event', on_delete=models.CASCADE,
        related_name='contact_links',
    )
    contact = models.ForeignKey(
        Contact, on_delete=models.CASCADE, related_name='event_links',
    )
    role = models.CharField(
        max_length=100, blank=True, default='',
        choices=EventContactRole.CHOICES,
        help_text="Role on this event, e.g. 'point_of_contact'",
    )
    is_primary = models.BooleanField(
        default=False, help_text="Primary contact for THIS event",
    )
    linked_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='event_contact_links',
    )
    linked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'event_contacts'
        verbose_name = 'Event Contact'
        verbose_name_plural = 'Event Contacts'
        constraints = [
            models.UniqueConstraint(
                fields=['event', 'contact'], name='uniq_event_contact',
            ),
        ]
        indexes = [
            models.Index(fields=['event']),
            models.Index(fields=['contact']),
        ]

    def __str__(self):
        return f"{self.event_id} ←→ {self.contact_id}"


class EventOrganization(models.Model):
    """Association between an Event and an Organization (replaces group)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event = models.ForeignKey(
        'event_management.Event', on_delete=models.CASCADE,
        related_name='organization_links',
    )
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='event_links',
    )
    is_primary = models.BooleanField(
        default=False, help_text="Primary requesting organization for THIS event",
    )
    linked_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='event_organization_links',
    )
    linked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'event_organizations'
        verbose_name = 'Event Organization'
        verbose_name_plural = 'Event Organizations'
        constraints = [
            models.UniqueConstraint(
                fields=['event', 'organization'], name='uniq_event_organization',
            ),
        ]
        indexes = [
            models.Index(fields=['event']),
            models.Index(fields=['organization']),
        ]

    def __str__(self):
        return f"{self.event_id} ←→ {self.organization_id}"
