# SPDX-License-Identifier: Apache-2.0
"""Contact / Organization matching + linking services.

Used by the email-extraction pipeline and the demo-population scripts to turn
extracted point-of-contact / organization data into normalized rows.

Matching policy (intentionally minimal — see the feature spec):
  * Contacts match on EXACT email (normalized) only. No fuzzy name matching,
    confidence scoring, or disambiguation. If no email matches, a new Contact
    is created.
  * Organizations have no email in extraction output, so they match on EXACT
    normalized name. Still exact — not fuzzy.
"""

import difflib
import logging
import re
from dataclasses import dataclass

from .constants import EventContactRole
from .crypto import (
    email_blind_index,
    name_blind_index,
    normalize_name,
    phone_blind_index,
)
from .models import (
    Contact,
    ContactEmailAddress,
    ContactPhoneNumber,
    EventContact,
    EventOrganization,
    Organization,
)

logger = logging.getLogger('apps.email_processing')


def _text(value):
    """Coerce an extracted field to a stripped string.

    Some providers (anthropic_dev) wrap values as ``{'value': ..., 'context': ...}``
    for UI highlighting; unwrap those. Everything else is stringified.
    """
    if value is None:
        return ''
    if isinstance(value, dict):
        value = value.get('value', '')
    return str(value).strip()


def get_or_create_contact(*, email='', name='', phone='', user=None):
    """Find a Contact by exact email, or create one. Returns (contact, created).

    Returns ``(None, False)`` when there is nothing to anchor a contact on
    (no email and no name).
    """
    email = _text(email)
    name = _text(name)
    phone = _text(phone)

    if email:
        key = email_blind_index(email)
        existing = (ContactEmailAddress.objects
                    .select_related('contact')
                    .filter(email_key=key)
                    .first())
        if existing:
            return existing.contact, False

        contact = Contact.objects.create(name=name, created_by=user, modified_by=user)
        ContactEmailAddress.objects.create(
            contact=contact, email=email, is_primary=True,
            created_by=user, modified_by=user,
        )
        if phone:
            ContactPhoneNumber.objects.create(
                contact=contact, phone=phone, is_primary=True,
                created_by=user, modified_by=user,
            )
        return contact, True

    if name:
        # No email to match on — cannot dedupe, create an unmatched contact.
        contact = Contact.objects.create(name=name, created_by=user, modified_by=user)
        if phone:
            ContactPhoneNumber.objects.create(
                contact=contact, phone=phone, is_primary=True,
                created_by=user, modified_by=user,
            )
        return contact, True

    return None, False


def get_or_create_organization(*, name='', user=None):
    """Find an Organization by exact normalized name, or create one.

    Returns (organization, created), or (None, False) for a blank name.
    """
    name = _text(name)
    if not name:
        return None, False

    key = name_blind_index(name)
    existing = Organization.objects.filter(name_key=key).first()
    if existing:
        return existing, False

    org = Organization.objects.create(name=name, created_by=user, modified_by=user)
    return org, True


def attach_contact_org_to_event(event, *, name='', email='', phone='', group='', user=None):
    """Resolve + link a point-of-contact and organization onto an event.

    Idempotent: re-running for the same event/contact/org does not duplicate
    rows. Also cross-links the contact↔organization and attaches both to the
    event's source emails. Returns (contact, organization).
    """
    contact, _ = get_or_create_contact(email=email, name=name, phone=phone, user=user)
    org, _ = get_or_create_organization(name=group, user=user)

    if contact:
        EventContact.objects.get_or_create(
            event=event, contact=contact,
            defaults={'role': 'point_of_contact', 'is_primary': True, 'linked_by': user},
        )
    if org:
        EventOrganization.objects.get_or_create(
            event=event, organization=org,
            defaults={'is_primary': True, 'linked_by': user},
        )
    if contact and org:
        contact.organizations.add(org)

    # Attach both to whatever emails already point at this event.
    source_emails = list(event.source_emails.all())
    if source_emails:
        if contact:
            contact.related_messages.add(*source_emails)
        if org:
            org.related_messages.add(*source_emails)

    return contact, org


# Legacy Event field names that are now normalized properties. Code paths that
# used to setattr() these onto an Event must route through apply_field_to_event.
NORMALIZED_EVENT_FIELDS = {
    'group', 'point_of_contact_name', 'point_of_contact_email', 'point_of_contact_phone',
}


def apply_field_to_event(event, field, value, user=None):
    """Apply a single legacy field name + value by creating/linking normalized rows.

    Bridges old "setattr(event, field, value)" call sites (review accept/undo,
    suggestion apply) to the normalized model. Returns (contact, organization)
    or (None, None) if `field` is not a normalized field.
    """
    kwargs = {'name': '', 'email': '', 'phone': '', 'group': ''}
    if field == 'group':
        kwargs['group'] = value or ''
    elif field == 'point_of_contact_name':
        kwargs['name'] = value or ''
    elif field == 'point_of_contact_email':
        kwargs['email'] = value or ''
    elif field == 'point_of_contact_phone':
        kwargs['phone'] = value or ''
    else:
        return None, None
    return attach_contact_org_to_event(event, user=user, **kwargs)


def link_extraction_to_event(event, extracted_data, user=None):
    """Link normalized contact/org rows from an email's extracted_data.

    Reads the ``point_of_contact`` and ``group`` keys produced by the LLM
    extraction pipeline. Provider-agnostic: handles both the plain-string and
    ``{'value': ...}`` shapes. Returns (contact, organization).
    """
    extracted_data = extracted_data or {}
    poc = extracted_data.get('point_of_contact') or {}

    return attach_contact_org_to_event(
        event,
        name=poc.get('name', ''),
        email=poc.get('email', ''),
        phone=poc.get('phone', ''),
        group=extracted_data.get('group', ''),
        user=user,
    )


# ===========================================================================
# Multi-contact / multi-org resolution (extraction-review overhaul)
#
# The functions above handle the legacy single-POC / single-group path. The
# functions below resolve an arbitrary number of extracted parties/orgs against
# the directory, supporting the three reviewer actions: create new, link
# unchanged, or link-and-update.
# ===========================================================================

# Honorifics / suffixes dropped before comparing names so "Dr. Alan Foster"
# matches "Alan Foster" and "Smith Jr." matches "Smith".
_NAME_NOISE = frozenset({
    'dr', 'mr', 'mrs', 'ms', 'mx', 'prof', 'professor', 'rev', 'hon', 'sir',
    'madam', 'madame', 'officer', 'sen', 'senator', 'rep', 'representative',
    'ret', 'jr', 'sr', 'ii', 'iii', 'iv',
})

# Minimum token-set similarity (0..1) to treat two names as the same person.
# Names are never a standalone signal — a match here is always corroborated by an
# exact phone or organization hit and confirmed by the reviewer — so this can be
# fairly permissive without risking silent false merges.
NAME_MATCH_THRESHOLD = 0.82


def _name_tokens(name):
    """Normalized, punctuation-free, honorific-free token set for a person name."""
    cleaned = re.sub(r'[^\w\s]', ' ', normalize_name(name))
    return {tok for tok in cleaned.split() if tok and tok not in _NAME_NOISE}


def name_similarity(a, b):
    """Order-insensitive 0..1 similarity between two person names.

    Token-set ratio built on stdlib difflib (no third-party dependency, so it
    works in every environment regardless of rapidfuzz availability). Identical
    token sets short-circuit to 1.0; otherwise the sorted token strings are
    compared so "John Smith" ~ "Smith, John".
    """
    ta, tb = _name_tokens(a), _name_tokens(b)
    if not ta or not tb:
        return 0.0
    if ta == tb:
        return 1.0
    return difflib.SequenceMatcher(None, ' '.join(sorted(ta)), ' '.join(sorted(tb))).ratio()


@dataclass
class ContactMatch:
    """A candidate existing Contact for an extracted party."""
    contact: Contact
    matched_by: str        # 'email' | 'name_phone' | 'name_org'
    confidence: float      # 1.0 for email/exact, else the name similarity

    def as_dict(self):
        return {
            'matched_id': str(self.contact.id),
            'matched_by': self.matched_by,
            'match_confidence': round(self.confidence, 3),
        }


@dataclass
class OrganizationMatch:
    organization: Organization
    matched_by: str        # 'name'
    confidence: float

    def as_dict(self):
        return {
            'matched_id': str(self.organization.id),
            'matched_by': self.matched_by,
            'match_confidence': round(self.confidence, 3),
        }


def match_contact(*, email='', name='', phone='', organization='',
                  threshold=NAME_MATCH_THRESHOLD):
    """Return ranked existing-Contact matches for an extracted party.

    Signals (per the approved policy), strongest first:
      1. exact email (blind index)            -> confidence 1.0
      2. name + exact phone (blind index)     -> confidence = name similarity
      3. name + exact organization name       -> confidence = name similarity

    Fuzzy name comparison only ever runs inside the small candidate set produced
    by an exact phone/org blind-index lookup — never across the whole (encrypted)
    table. Returns a list[ContactMatch] sorted by confidence desc, deduped by
    contact, possibly empty.
    """
    email = _text(email)
    name = _text(name)
    phone = _text(phone)
    organization = _text(organization)

    matches = []
    seen = set()

    def _add(contact, by, conf):
        if contact.id in seen:
            return
        seen.add(contact.id)
        matches.append(ContactMatch(contact, by, conf))

    # 1. Exact email.
    if email:
        row = (ContactEmailAddress.objects
               .select_related('contact')
               .filter(email_key=email_blind_index(email))
               .first())
        if row:
            _add(row.contact, 'email', 1.0)

    # 2. Name + exact phone.
    if name and phone:
        pkey = phone_blind_index(phone)
        if pkey:
            for pn in (ContactPhoneNumber.objects
                       .select_related('contact')
                       .filter(phone_key=pkey)):
                sim = name_similarity(name, pn.contact.name)
                if sim >= threshold:
                    _add(pn.contact, 'name_phone', sim)

    # 3. Name + exact organization name.
    if name and organization:
        org = Organization.objects.filter(name_key=name_blind_index(organization)).first()
        if org:
            for contact in org.contacts.all():
                sim = name_similarity(name, contact.name)
                if sim >= threshold:
                    _add(contact, 'name_org', sim)

    matches.sort(key=lambda m: m.confidence, reverse=True)
    return matches


def match_organization(*, name=''):
    """Return existing-Organization matches by exact normalized name (or [])."""
    name = _text(name)
    if not name:
        return []
    org = Organization.objects.filter(name_key=name_blind_index(name)).first()
    return [OrganizationMatch(org, 'name', 1.0)] if org else []


def diff_against_contact(contact, *, email='', phone='', position=''):
    """Describe how an extracted party's info differs from an existing contact.

    Returns (additions, replaces):
      * additions — emails/phones not already present (always appended), plus a
        position when the contact has none. Each: {'kind', 'value'}.
      * replaces — single-valued conflicts that need explicit confirmation,
        currently a differing position. Each: {'kind', 'old', 'new'}.
    Email/phone are never replaces: extra contact points always accumulate; the
    reviewer promotes one to primary through a separate confirmed action.
    """
    additions = []
    replaces = []
    email = _text(email)
    phone = _text(phone)
    position = _text(position)

    if email and not contact.email_addresses.filter(email_key=email_blind_index(email)).exists():
        additions.append({'kind': 'email', 'value': email})

    if phone:
        pkey = phone_blind_index(phone)
        if pkey and not contact.phone_numbers.filter(phone_key=pkey).exists():
            additions.append({'kind': 'phone', 'value': phone})

    if position:
        current = _text(contact.position)
        if not current:
            additions.append({'kind': 'position', 'value': position})
        elif current.lower() != position.lower():
            replaces.append({'kind': 'position', 'old': contact.position, 'new': position})

    return additions, replaces


def diff_against_organization(org, *, email='', phone='', location=''):
    """Like diff_against_contact, for organizations (location is the single field)."""
    additions = []
    replaces = []
    email = _text(email)
    phone = _text(phone)
    location = _text(location)

    if email and not org.email_addresses.filter(email_key=email_blind_index(email)).exists():
        additions.append({'kind': 'email', 'value': email})

    if phone:
        pkey = phone_blind_index(phone)
        if pkey and not org.phone_numbers.filter(phone_key=pkey).exists():
            additions.append({'kind': 'phone', 'value': phone})

    if location:
        current = _text(org.location)
        if not current:
            additions.append({'kind': 'location', 'value': location})
        elif current.lower() != location.lower():
            replaces.append({'kind': 'location', 'old': org.location, 'new': location})

    return additions, replaces


def _add_or_promote_email(owner, value, *, make_primary, user):
    """Append an email to a Contact/Organization (or promote an existing one).

    Works for either owner type via the shared ``email_addresses`` reverse
    manager. Appends by default; ``make_primary`` (or being the owner's first
    email) demotes the current primary — old rows are kept, never deleted.
    """
    value = _text(value)
    if not value:
        return None
    rel = owner.email_addresses
    existing = rel.filter(email_key=email_blind_index(value)).first()
    if existing:
        if make_primary and not existing.is_primary:
            rel.filter(is_primary=True).exclude(pk=existing.pk).update(is_primary=False)
            existing.is_primary = True
            existing.save(update_fields=['is_primary'])
        return existing
    make_primary = make_primary or not rel.exists()
    if make_primary:
        rel.filter(is_primary=True).update(is_primary=False)
    return rel.create(email=value, is_primary=make_primary, created_by=user, modified_by=user)


def _add_or_promote_phone(owner, value, *, make_primary, user):
    """Append a phone to a Contact/Organization (or promote an existing one)."""
    value = _text(value)
    if not value:
        return None
    rel = owner.phone_numbers
    pkey = phone_blind_index(value)
    existing = rel.filter(phone_key=pkey).first() if pkey else None
    if existing:
        if make_primary and not existing.is_primary:
            rel.filter(is_primary=True).exclude(pk=existing.pk).update(is_primary=False)
            existing.is_primary = True
            existing.save(update_fields=['is_primary'])
        return existing
    make_primary = make_primary or not rel.exists()
    if make_primary:
        rel.filter(is_primary=True).update(is_primary=False)
    return rel.create(phone=value, is_primary=make_primary, created_by=user, modified_by=user)


def _link_contact_to_event(event, contact, *, role, is_primary, user):
    """Idempotently link a contact to an event with a role; enforce single primary."""
    link, created = EventContact.objects.get_or_create(
        event=event, contact=contact,
        defaults={'role': role, 'is_primary': is_primary, 'linked_by': user},
    )
    if not created:
        changed = []
        if role and link.role != role:
            link.role = role
            changed.append('role')
        if is_primary and not link.is_primary:
            link.is_primary = True
            changed.append('is_primary')
        if changed:
            link.save(update_fields=changed)
    if is_primary:
        (EventContact.objects.filter(event=event, is_primary=True)
         .exclude(pk=link.pk).update(is_primary=False))
    return link


def _apply_contact_changes(contact, resolution, *, email, phone, position, user):
    """Apply a link_update resolution's additions + confirmed replaces to a contact."""
    additions = resolution.get('additions')
    if additions is None:
        # No explicit decision supplied (e.g. demo/programmatic call): derive the
        # safe appends automatically. Replaces still require explicit confirmation.
        additions, _ = diff_against_contact(
            contact, email=email, phone=phone, position=position,
        )
    for add in additions:
        kind, value = add.get('kind'), add.get('value')
        if kind == 'email':
            _add_or_promote_email(contact, value, make_primary=False, user=user)
        elif kind == 'phone':
            _add_or_promote_phone(contact, value, make_primary=False, user=user)
        elif kind == 'position' and _text(value):
            contact.position = value
            contact.modified_by = user
            contact.save(update_fields=['position', 'modified_by'])

    for rep in (resolution.get('replaces') or []):
        if not rep.get('confirmed'):
            continue  # unconfirmed replaces are left for the reviewer
        kind, new_value = rep.get('kind'), _text(rep.get('new'))
        if not new_value:
            continue
        if kind == 'email':
            _add_or_promote_email(contact, new_value, make_primary=True, user=user)
        elif kind == 'phone':
            _add_or_promote_phone(contact, new_value, make_primary=True, user=user)
        elif kind == 'position':
            contact.position = new_value
            contact.modified_by = user
            contact.save(update_fields=['position', 'modified_by'])


def resolve_contact(event, party, resolution=None, *, user=None):
    """Create or link one extracted party onto an event, applying confirmed edits.

    ``party`` — {'name','email','phone','position','organization','role'}.
    ``resolution`` — {'action': 'new'|'link'|'link_update', 'matched_id', 'is_primary',
    'additions', 'replaces'}; defaults to creating a new contact. ``additions`` /
    ``replaces`` are only consulted for the ``link_update`` action. Returns the
    resolved Contact (or None when the party has nothing to anchor on).
    """
    party = party or {}
    resolution = resolution or {}

    name = _text(party.get('name'))
    email = _text(party.get('email'))
    phone = _text(party.get('phone'))
    position = _text(party.get('position'))
    organization = _text(party.get('organization'))

    role = party.get('role') or resolution.get('role') or EventContactRole.DEFAULT
    if role not in EventContactRole.VALUES:
        role = EventContactRole.DEFAULT
    is_primary = bool(resolution.get('is_primary')) or role == EventContactRole.POINT_OF_CONTACT

    action = resolution.get('action') or 'new'
    matched_id = resolution.get('matched_id')

    contact = None
    if action in ('link', 'link_update') and matched_id:
        contact = Contact.objects.filter(pk=matched_id).first()

    if contact is None:
        # Create path (explicit 'new', or a stale matched_id that no longer exists).
        if not (name or email or phone):
            return None
        contact = Contact.objects.create(
            name=name, position=position, created_by=user, modified_by=user,
        )
        if email:
            _add_or_promote_email(contact, email, make_primary=True, user=user)
        if phone:
            _add_or_promote_phone(contact, phone, make_primary=True, user=user)
    else:
        if action == 'link_update':
            _apply_contact_changes(
                contact, resolution, email=email, phone=phone, position=position, user=user,
            )
        # Backfill an empty name even on a plain 'link' (harmless, never overwrites).
        if name and not _text(contact.name):
            contact.name = name
            contact.modified_by = user
            contact.save(update_fields=['name', 'modified_by'])

    org = None
    if organization:
        org, _ = get_or_create_organization(name=organization, user=user)
        if org:
            contact.organizations.add(org)
            if contact.primary_organization_id is None:
                contact.primary_organization = org
                contact.save(update_fields=['primary_organization'])

    _link_contact_to_event(event, contact, role=role, is_primary=is_primary, user=user)

    source_emails = list(event.source_emails.all())
    if source_emails:
        contact.related_messages.add(*source_emails)
        if org:
            org.related_messages.add(*source_emails)

    return contact


def resolve_organization(event, org_party, resolution=None, *, user=None):
    """Create or link one extracted organization onto an event, applying edits.

    ``org_party`` — {'name','email','phone','location'}. ``resolution`` mirrors
    resolve_contact (action/matched_id/is_primary/additions/replaces). Returns
    the resolved Organization (or None for a blank name with no match).
    """
    org_party = org_party or {}
    resolution = resolution or {}

    name = _text(org_party.get('name'))
    email = _text(org_party.get('email'))
    phone = _text(org_party.get('phone'))
    location = _text(org_party.get('location'))
    is_primary = bool(resolution.get('is_primary'))

    action = resolution.get('action') or 'new'
    matched_id = resolution.get('matched_id')

    org = None
    if action in ('link', 'link_update') and matched_id:
        org = Organization.objects.filter(pk=matched_id).first()

    if org is None:
        if not name:
            return None
        org, _ = get_or_create_organization(name=name, user=user)
        if location:
            org.location = location
            org.modified_by = user
            org.save(update_fields=['location', 'modified_by'])
        if email:
            _add_or_promote_email(org, email, make_primary=True, user=user)
        if phone:
            _add_or_promote_phone(org, phone, make_primary=True, user=user)
    elif action == 'link_update':
        additions = resolution.get('additions')
        if additions is None:
            additions, _ = diff_against_organization(
                org, email=email, phone=phone, location=location,
            )
        for add in additions:
            kind, value = add.get('kind'), add.get('value')
            if kind == 'email':
                _add_or_promote_email(org, value, make_primary=False, user=user)
            elif kind == 'phone':
                _add_or_promote_phone(org, value, make_primary=False, user=user)
            elif kind == 'location' and _text(value):
                org.location = value
                org.modified_by = user
                org.save(update_fields=['location', 'modified_by'])
        for rep in (resolution.get('replaces') or []):
            if not rep.get('confirmed'):
                continue
            kind, new_value = rep.get('kind'), _text(rep.get('new'))
            if kind == 'email' and new_value:
                _add_or_promote_email(org, new_value, make_primary=True, user=user)
            elif kind == 'phone' and new_value:
                _add_or_promote_phone(org, new_value, make_primary=True, user=user)
            elif kind == 'location' and new_value:
                org.location = new_value
                org.modified_by = user
                org.save(update_fields=['location', 'modified_by'])

    link, created = EventOrganization.objects.get_or_create(
        event=event, organization=org,
        defaults={'is_primary': is_primary, 'linked_by': user},
    )
    if not created and is_primary and not link.is_primary:
        link.is_primary = True
        link.save(update_fields=['is_primary'])
    if is_primary:
        (EventOrganization.objects.filter(event=event, is_primary=True)
         .exclude(pk=link.pk).update(is_primary=False))

    source_emails = list(event.source_emails.all())
    if source_emails:
        org.related_messages.add(*source_emails)

    return org
