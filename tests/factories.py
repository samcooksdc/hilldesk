# SPDX-License-Identifier: Apache-2.0
"""Test factories.

``Event.group`` and ``Event.point_of_contact_*`` are read-only properties
backed by the normalized contacts models. Older tests still pass them (and the
removed ``time`` / ``details`` columns) as keyword arguments. ``create_event``
accepts those legacy kwargs and routes them through the real contacts service,
so tests exercise the same path production code uses.
"""
from typing import Any

from apps.contacts.services import attach_contact_org_to_event
from apps.event_management.models import Event

_LEGACY_CONTACT_KWARGS = {
    'group': 'group',
    'point_of_contact_name': 'name',
    'point_of_contact_email': 'email',
    'point_of_contact_phone': 'phone',
}


def _split_legacy(kwargs: dict) -> dict:
    """Map/remove legacy Event kwargs in place; return the contact/org part."""
    contact = {
        target: kwargs.pop(legacy)
        for legacy, target in _LEGACY_CONTACT_KWARGS.items()
        if legacy in kwargs
    }
    if 'details' in kwargs:
        details = kwargs.pop('details')
        kwargs.setdefault('description', details)
    kwargs.pop('time', None)  # free-text time column was replaced by start_time/end_time
    if 'schedule_notes' in kwargs:
        kwargs.setdefault('notes', kwargs.pop('schedule_notes'))
    # Columns removed from Event with no replacement.
    for removed in ('staff_recommendation', 'hms_review_status', 'campaign_notes', 'hms_notes'):
        kwargs.pop(removed, None)
    return contact


def build_event(**kwargs: Any) -> Event:
    """Unsaved ``Event(...)`` that tolerates the legacy field names."""
    _split_legacy(kwargs)
    return Event(**kwargs)


def create_event(**kwargs: Any) -> Event:
    """``Event.objects.create`` that also understands the legacy field names."""
    contact = _split_legacy(kwargs)
    event = Event.objects.create(**kwargs)
    if any(contact.values()):
        attach_contact_org_to_event(event, user=kwargs.get('created_by'), **contact)
    return event


def make_office_member(user: Any, role: str = 'admin', office_name: str = 'Test Office') -> Any:
    """Put ``user`` in an office with one of its default roles.

    Event visibility is scoped to the user's office and role, so a bare user
    (no office) correctly sees nothing through the API.
    """
    from apps.authentication.models import Office

    office, _ = Office.objects.get_or_create(name=office_name)
    roles = office.create_default_roles()
    user.office = office
    user.assign_role(roles[role])
    user.save()  # assign_role() only sets the attribute
    return user
