# SPDX-License-Identifier: Apache-2.0
"""DRF viewsets for contacts / organizations.

Powers the read-only directory's data needs and the event-editing modal's
search / link / unlink / create flow. Search on encrypted name falls back to
in-Python substring matching; exact email lookup uses the blind index (indexed,
no decryption needed).

Office scoping: Contact/Organization have no office FK (single-office demo), so
the queryset is not office-filtered. If multi-office support is added, scope
here via the linked events' offices.
"""

from django.db.models import Exists, OuterRef, Q
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.event_management.models import Event

from .crypto import email_blind_index
from .models import (
    Contact,
    EventContact,
    EventOrganization,
    Organization,
)
from .serializers import ContactSerializer, OrganizationSerializer


def _reviewed_only(qs, link_model, fk):
    """Drop records whose ONLY event links are to events still awaiting review.

    A contact/org a reviewer accepted on an AI draft is linked to that draft
    before the draft itself is approved. Until some reviewed event uses it,
    it shouldn't surface in global search. Records with no event links
    (created by hand in the directory) stay visible.
    """
    links = link_model.objects.filter(**{fk: OuterRef('pk')})
    reviewed = links.filter(event__requires_human_review=False).exclude(
        event__review_decision='dismissed'
    )
    return qs.filter(Q(~Exists(links)) | Q(Exists(reviewed)))


def _wants_reviewed_only(request):
    return request.query_params.get('exclude_in_review') == 'true'


def _matches(needle, *values):
    needle = needle.lower()
    return any(needle in (v or '').lower() for v in values)


class ContactViewSet(viewsets.ModelViewSet):
    serializer_class = ContactSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = Contact.objects.select_related('primary_organization').prefetch_related(
            'email_addresses', 'phone_numbers', 'organizations', 'event_links',
        )
        # Exact email lookup via blind index (fast, indexed).
        email = self.request.query_params.get('email')
        if email:
            qs = qs.filter(email_addresses__email_key=email_blind_index(email)).distinct()
        # Contacts linked to a given event.
        event_id = self.request.query_params.get('event')
        if event_id:
            qs = qs.filter(event_links__event_id=event_id).distinct()
        if _wants_reviewed_only(self.request):
            qs = _reviewed_only(qs, EventContact, 'contact')
        return qs.order_by('id')

    def list(self, request, *args, **kwargs):
        # Substring search happens in Python (name/email are encrypted). Return a
        # SLIM payload (id/name/primary_email) so the modal's type-ahead doesn't
        # pay to fully serialize every match (emails, phones, orgs, counts).
        search = request.query_params.get('search')
        if search:
            matches = [
                c for c in self.get_queryset()
                if _matches(search, c.name, c.primary_email,
                            *[o.name for o in c.organizations.all()])
            ]
            page = self.paginate_queryset(matches)
            records = page if page is not None else matches
            slim = [
                {
                    'id': str(c.id), 'name': c.name, 'primary_email': c.primary_email,
                    'primary_organization': (c.primary_organization.name
                                             if c.primary_organization_id else ''),
                }
                for c in records
            ]
            return (self.get_paginated_response(slim) if page is not None
                    else Response(slim))
        return super().list(request, *args, **kwargs)

    @action(detail=True, methods=['post'])
    def link_event(self, request, pk=None):
        """Link this contact to an event. Body: {event_id, role?, is_primary?}."""
        contact = self.get_object()
        event = get_object_or_404(Event, pk=request.data.get('event_id'))
        link, created = EventContact.objects.get_or_create(
            event=event, contact=contact,
            defaults={
                'role': request.data.get('role', ''),
                'is_primary': bool(request.data.get('is_primary', False)),
                'linked_by': request.user,
            },
        )
        # Attach the contact to the event's source emails for the directory.
        source_emails = list(event.source_emails.all())
        if source_emails:
            contact.related_messages.add(*source_emails)
        # An event with at least one contact always has a primary one.
        if not EventContact.objects.filter(event=event, is_primary=True).exists():
            EventContact.objects.filter(event=event, contact=contact).update(is_primary=True)
        return Response(
            {'linked': True, 'created': created, 'event_id': str(event.id)},
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=['post'])
    def unlink_event(self, request, pk=None):
        """Unlink this contact from an event. Body: {event_id}."""
        contact = self.get_object()
        event_id = request.data.get('event_id')
        deleted, _ = EventContact.objects.filter(
            contact=contact, event_id=event_id,
        ).delete()
        # If that removed the primary, promote another so a primary remains.
        remaining = EventContact.objects.filter(event_id=event_id)
        if remaining.exists() and not remaining.filter(is_primary=True).exists():
            first = remaining.first()
            first.is_primary = True
            first.save(update_fields=['is_primary'])
        return Response({'unlinked': bool(deleted)}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def set_primary(self, request, pk=None):
        """Mark this contact as the event's primary (exclusive).

        Body: {event_id, is_primary?}. Setting is_primary clears the flag on the
        event's other contacts; passing is_primary=false clears it entirely.
        """
        contact = self.get_object()
        event_id = request.data.get('event_id')
        make_primary = bool(request.data.get('is_primary', True))
        links = EventContact.objects.filter(event_id=event_id)
        links.exclude(contact=contact).update(is_primary=False)
        links.filter(contact=contact).update(is_primary=make_primary)
        return Response({'is_primary': make_primary}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def set_primary_org(self, request, pk=None):
        """Set this contact's primary organization. Body: {organization_id|null}."""
        contact = self.get_object()
        contact.primary_organization_id = request.data.get('organization_id') or None
        contact.save(update_fields=['primary_organization', 'modified'])
        return Response({
            'primary_organization_id': (str(contact.primary_organization_id)
                                        if contact.primary_organization_id else None),
        }, status=status.HTTP_200_OK)


class OrganizationViewSet(viewsets.ModelViewSet):
    serializer_class = OrganizationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = Organization.objects.prefetch_related(
            'email_addresses', 'phone_numbers', 'contacts', 'event_links',
        )
        event_id = self.request.query_params.get('event')
        if event_id:
            qs = qs.filter(event_links__event_id=event_id).distinct()
        if _wants_reviewed_only(self.request):
            qs = _reviewed_only(qs, EventOrganization, 'organization')
        return qs.order_by('name_key')

    def list(self, request, *args, **kwargs):
        search = request.query_params.get('search')
        if search:
            matches = [
                o for o in self.get_queryset()
                if _matches(search, o.name, o.location, o.primary_email)
            ]
            page = self.paginate_queryset(matches)
            records = page if page is not None else matches
            slim = [
                {'id': str(o.id), 'name': o.name, 'primary_email': o.primary_email}
                for o in records
            ]
            return (self.get_paginated_response(slim) if page is not None
                    else Response(slim))
        return super().list(request, *args, **kwargs)

    @action(detail=True, methods=['post'])
    def link_event(self, request, pk=None):
        """Link this organization to an event. Body: {event_id, is_primary?}."""
        org = self.get_object()
        event = get_object_or_404(Event, pk=request.data.get('event_id'))
        link, created = EventOrganization.objects.get_or_create(
            event=event, organization=org,
            defaults={
                'is_primary': bool(request.data.get('is_primary', False)),
                'linked_by': request.user,
            },
        )
        source_emails = list(event.source_emails.all())
        if source_emails:
            org.related_messages.add(*source_emails)
        # An event with at least one organization always has a primary one.
        if not EventOrganization.objects.filter(event=event, is_primary=True).exists():
            EventOrganization.objects.filter(event=event, organization=org).update(is_primary=True)
        return Response(
            {'linked': True, 'created': created, 'event_id': str(event.id)},
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=['post'])
    def unlink_event(self, request, pk=None):
        """Unlink this organization from an event. Body: {event_id}."""
        org = self.get_object()
        event_id = request.data.get('event_id')
        deleted, _ = EventOrganization.objects.filter(
            organization=org, event_id=event_id,
        ).delete()
        remaining = EventOrganization.objects.filter(event_id=event_id)
        if remaining.exists() and not remaining.filter(is_primary=True).exists():
            first = remaining.first()
            first.is_primary = True
            first.save(update_fields=['is_primary'])
        return Response({'unlinked': bool(deleted)}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def set_primary(self, request, pk=None):
        """Mark this organization as the event's primary (exclusive).

        The primary organization is the one shown in the event header. Body:
        {event_id, is_primary?}.
        """
        org = self.get_object()
        event_id = request.data.get('event_id')
        make_primary = bool(request.data.get('is_primary', True))
        links = EventOrganization.objects.filter(event_id=event_id)
        links.exclude(organization=org).update(is_primary=False)
        links.filter(organization=org).update(is_primary=make_primary)
        return Response({'is_primary': make_primary}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def add_member(self, request, pk=None):
        """Add a contact to this organization. Body: {contact_id}."""
        org = self.get_object()
        contact = get_object_or_404(Contact, pk=request.data.get('contact_id'))
        contact.organizations.add(org)
        return Response({'ok': True}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def remove_member(self, request, pk=None):
        """Remove a contact from this organization. Body: {contact_id}."""
        org = self.get_object()
        contact = get_object_or_404(Contact, pk=request.data.get('contact_id'))
        contact.organizations.remove(org)
        if org.primary_contact_id == contact.id:
            org.primary_contact = None
            org.save(update_fields=['primary_contact', 'modified'])
        return Response({'ok': True}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def set_primary_contact(self, request, pk=None):
        """Set this org's primary point of contact. Body: {contact_id|null}."""
        org = self.get_object()
        org.primary_contact_id = request.data.get('contact_id') or None
        org.save(update_fields=['primary_contact', 'modified'])
        return Response({
            'primary_contact_id': (str(org.primary_contact_id)
                                   if org.primary_contact_id else None),
        }, status=status.HTTP_200_OK)
