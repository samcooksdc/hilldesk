# SPDX-License-Identifier: Apache-2.0
"""DRF serializers for the contacts API.

Support the event-editing modal and the directory: nested emails/phones, a
write path that accepts plain lists, and a duplicate-email guard that surfaces
the existing contact (so the UI can link instead of erroring).
"""

from rest_framework import serializers

from .crypto import email_blind_index
from .models import (
    Contact,
    ContactEmailAddress,
    ContactPhoneNumber,
    Organization,
    OrganizationEmailAddress,
    OrganizationPhoneNumber,
)


class ContactEmailSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContactEmailAddress
        fields = ['id', 'email', 'is_primary']
        read_only_fields = ['id']


class ContactPhoneSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContactPhoneNumber
        fields = ['id', 'phone', 'is_primary']
        read_only_fields = ['id']


class OrganizationEmailSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrganizationEmailAddress
        fields = ['id', 'email', 'is_primary']
        read_only_fields = ['id']


class OrganizationPhoneSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrganizationPhoneNumber
        fields = ['id', 'phone', 'is_primary']
        read_only_fields = ['id']


class _AuditedNestedMixin:
    """Shared create/update handling for nested email/phone child rows."""

    email_model = None
    phone_model = None
    fk_name = None  # 'contact' or 'organization'

    def _user(self):
        request = self.context.get('request')
        return getattr(request, 'user', None) if request else None

    def _sync_children(self, parent, model, items, value_field, user):
        """Replace the parent's child rows with `items` (list of dicts)."""
        if items is None:
            return
        model.objects.filter(**{self.fk_name: parent}).delete()
        for item in items:
            model.objects.create(
                **{self.fk_name: parent},
                **{value_field: item[value_field]},
                # No automatic primary — only mark primary when explicitly chosen.
                is_primary=bool(item.get('is_primary', False)),
                created_by=user, modified_by=user,
            )


class ContactSerializer(_AuditedNestedMixin, serializers.ModelSerializer):
    emails = ContactEmailSerializer(source='email_addresses', many=True, required=False)
    phones = ContactPhoneSerializer(source='phone_numbers', many=True, required=False)
    organizations = serializers.SerializerMethodField(read_only=True)
    organization_ids = serializers.PrimaryKeyRelatedField(
        source='organizations', queryset=Organization.objects.all(),
        many=True, required=False, write_only=True,
    )
    primary_email = serializers.ReadOnlyField()
    primary_phone = serializers.ReadOnlyField()
    event_count = serializers.SerializerMethodField()

    email_model = ContactEmailAddress
    primary_organization_id = serializers.PrimaryKeyRelatedField(
        source='primary_organization', queryset=Organization.objects.all(),
        allow_null=True, required=False,
    )
    phone_model = ContactPhoneNumber
    fk_name = 'contact'

    class Meta:
        model = Contact
        fields = [
            'id', 'name', 'position', 'notes', 'emails', 'phones',
            'organizations', 'organization_ids', 'primary_organization_id',
            'primary_email', 'primary_phone', 'event_count',
            'created', 'modified',
        ]
        read_only_fields = ['id', 'created', 'modified']

    def get_organizations(self, obj):
        return [{'id': str(o.id), 'name': o.name} for o in obj.organizations.all()]

    def get_event_count(self, obj):
        return obj.event_links.count()

    def _check_duplicate_emails(self, emails, exclude_contact=None):
        for item in emails or []:
            key = email_blind_index(item['email'])
            qs = ContactEmailAddress.objects.filter(email_key=key)
            if exclude_contact is not None:
                qs = qs.exclude(contact=exclude_contact)
            existing = qs.select_related('contact').first()
            if existing:
                raise serializers.ValidationError({
                    'emails': f"Email '{item['email']}' already belongs to another contact.",
                    'existing_contact_id': str(existing.contact_id),
                })

    def create(self, validated_data):
        emails = validated_data.pop('email_addresses', [])
        phones = validated_data.pop('phone_numbers', [])
        orgs = validated_data.pop('organizations', [])
        self._check_duplicate_emails(emails)
        user = self._user()
        validated_data['created_by'] = user
        validated_data['modified_by'] = user
        contact = Contact.objects.create(**validated_data)
        if orgs:
            contact.organizations.set(orgs)
        self._sync_children(contact, ContactEmailAddress, emails, 'email', user)
        self._sync_children(contact, ContactPhoneNumber, phones, 'phone', user)
        return contact

    def update(self, instance, validated_data):
        emails = validated_data.pop('email_addresses', None)
        phones = validated_data.pop('phone_numbers', None)
        orgs = validated_data.pop('organizations', None)
        self._check_duplicate_emails(emails, exclude_contact=instance)
        user = self._user()
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.modified_by = user
        instance.save()
        if orgs is not None:
            instance.organizations.set(orgs)
        self._sync_children(instance, ContactEmailAddress, emails, 'email', user)
        self._sync_children(instance, ContactPhoneNumber, phones, 'phone', user)
        return instance


class OrganizationSerializer(_AuditedNestedMixin, serializers.ModelSerializer):
    # Allow a blank name so the modal can create an empty org card to fill in.
    name = serializers.CharField(required=False, allow_blank=True, max_length=255)
    emails = OrganizationEmailSerializer(source='email_addresses', many=True, required=False)
    phones = OrganizationPhoneSerializer(source='phone_numbers', many=True, required=False)
    primary_email = serializers.ReadOnlyField()
    primary_phone = serializers.ReadOnlyField()
    contact_count = serializers.SerializerMethodField()
    members = serializers.SerializerMethodField()
    primary_contact_id = serializers.PrimaryKeyRelatedField(
        source='primary_contact', queryset=Contact.objects.all(),
        allow_null=True, required=False,
    )
    event_count = serializers.SerializerMethodField()

    email_model = OrganizationEmailAddress
    phone_model = OrganizationPhoneNumber
    fk_name = 'organization'

    class Meta:
        model = Organization
        fields = [
            'id', 'name', 'location', 'notes', 'emails', 'phones',
            'primary_email', 'primary_phone', 'contact_count', 'members',
            'primary_contact_id', 'event_count', 'created', 'modified',
        ]
        read_only_fields = ['id', 'created', 'modified']

    def get_contact_count(self, obj):
        return obj.contacts.count()

    def get_members(self, obj):
        return [
            {'id': str(c.id), 'name': c.name, 'email': c.primary_email}
            for c in obj.contacts.all()
        ]

    def get_event_count(self, obj):
        return obj.event_links.count()

    def create(self, validated_data):
        emails = validated_data.pop('email_addresses', [])
        phones = validated_data.pop('phone_numbers', [])
        user = self._user()
        validated_data['created_by'] = user
        validated_data['modified_by'] = user
        org = Organization.objects.create(**validated_data)
        self._sync_children(org, OrganizationEmailAddress, emails, 'email', user)
        self._sync_children(org, OrganizationPhoneNumber, phones, 'phone', user)
        return org

    def update(self, instance, validated_data):
        emails = validated_data.pop('email_addresses', None)
        phones = validated_data.pop('phone_numbers', None)
        user = self._user()
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.modified_by = user
        instance.save()
        self._sync_children(instance, OrganizationEmailAddress, emails, 'email', user)
        self._sync_children(instance, OrganizationPhoneNumber, phones, 'phone', user)
        return instance
