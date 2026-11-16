# SPDX-License-Identifier: Apache-2.0
"""Normalize raw LLM contact/organization extraction into the review structure.

The LLM emits ``contacts[]`` and ``organizations[]`` (see the extraction prompt
in ``apps/email_processing/llm_providers/base.py``). This module turns that raw
output into the shape stored on ``Event.extracted_fields`` and consumed by the
review UI:

    {
      'schema_version': 2,
      'contacts': [ {ref, status, confidence, fields{...}, resolution{...}}, ... ],
      'organizations': [ {ref, status, confidence, fields{...}, resolution{...}}, ... ],
    }

Responsibilities:
  * clean each field and compute its source offsets in the email body (for the
    review highlighter),
  * dedupe parties that appear twice in one email (same email, or same name +
    phone), before the reviewer ever sees them,
  * pre-compute a resolution decision (new / link / link_update) against the
    existing directory via ``services.match_contact`` / ``match_organization``,
  * collapse cards that resolve to the same existing record.

It also provides ``iter_contacts`` / ``iter_organizations`` — a back-compat
reader that yields parties from either the new v2 shape or the legacy flat
``point_of_contact_* / group`` keys, so old events still render.
"""

from .constants import EXTRACTION_SCHEMA_VERSION, EventContactRole
from .crypto import normalize_email, normalize_name, normalize_phone
from . import services


# --- field helpers ---------------------------------------------------------

def _clean(value):
    return value.strip() if isinstance(value, str) else ''


def _offsets(value, body):
    """Case-insensitive exact span of ``value`` in ``body`` as [start, end], or None.

    Kept deliberately simple (no fuzzy/regex) and dependency-free: extracted
    values are near-verbatim, and a missing offset just means "no highlight",
    never a crash.
    """
    value = _clean(value)
    if not value or not body:
        return None
    idx = body.lower().find(value.lower())
    return [idx, idx + len(value)] if idx >= 0 else None


def _field(value, body):
    """A {'value', 'source'} cell, or None when the value is blank."""
    value = _clean(value)
    if not value:
        return None
    return {'value': value, 'source': _offsets(value, body)}


_ROLE_ALIASES = {
    'poc': EventContactRole.POINT_OF_CONTACT,
    'point of contact': EventContactRole.POINT_OF_CONTACT,
    'participant': EventContactRole.ATTENDEE,
    'attendee': EventContactRole.ATTENDEE,
    'host': EventContactRole.HOST_SPEAKER,
    'speaker': EventContactRole.HOST_SPEAKER,
    'host/speaker': EventContactRole.HOST_SPEAKER,
}


def _normalize_role(role):
    raw = _clean(role).lower()
    if raw in EventContactRole.VALUES:
        return raw
    collapsed = raw.replace('_', ' ').replace('/', ' ').strip()
    collapsed = ' '.join(collapsed.split())
    if collapsed in _ROLE_ALIASES:
        return _ROLE_ALIASES[collapsed]
    underscored = collapsed.replace(' ', '_')
    return underscored if underscored in EventContactRole.VALUES else EventContactRole.DEFAULT


# --- in-email dedupe -------------------------------------------------------

def _contact_key(raw):
    """Stable identity for in-email dedupe, or None when the party can't be deduped."""
    email = normalize_email(raw.get('email', ''))
    if email:
        return ('email', email)
    name = normalize_name(raw.get('name', ''))
    phone = normalize_phone(raw.get('phone', ''))
    if name and phone:
        return ('name_phone', name, phone)
    return None


def _merge_raw(into, other):
    """Fold ``other`` into ``into`` (first non-empty value per field wins)."""
    for key in ('name', 'email', 'phone', 'position', 'organization', 'role'):
        if not _clean(into.get(key)) and _clean(other.get(key)):
            into[key] = other[key]
    return into


def _dedupe(raw_list):
    merged = []
    by_key = {}
    for raw in raw_list or []:
        if not isinstance(raw, dict):
            continue
        key = _contact_key(raw)
        if key is not None and key in by_key:
            _merge_raw(by_key[key], raw)
            continue
        copy = dict(raw)
        merged.append(copy)
        if key is not None:
            by_key[key] = copy
    return merged


# --- resolution pre-computation -------------------------------------------

def _empty_resolution():
    return {
        'action': 'new',
        'matched_id': None,
        'matched_by': None,
        'match_confidence': 0.0,
        'pending_additions': [],
        'pending_replaces': [],
    }


def _resolve_contact(raw, *, resolve):
    res = _empty_resolution()
    if not resolve:
        return res
    matches = services.match_contact(
        email=raw.get('email', ''), name=raw.get('name', ''),
        phone=raw.get('phone', ''), organization=raw.get('organization', ''),
    )
    if not matches:
        return res
    top = matches[0]
    additions, replaces = services.diff_against_contact(
        top.contact, email=raw.get('email', ''),
        phone=raw.get('phone', ''), position=raw.get('position', ''),
    )
    res.update(top.as_dict())
    res['action'] = 'link_update' if (additions or replaces) else 'link'
    res['pending_additions'] = additions
    res['pending_replaces'] = [dict(rep, confirmed=False) for rep in replaces]
    return res


def _resolve_org(raw, *, resolve):
    res = _empty_resolution()
    if not resolve:
        return res
    matches = services.match_organization(name=raw.get('name', ''))
    if not matches:
        return res
    top = matches[0]
    additions, replaces = services.diff_against_organization(
        top.organization, email=raw.get('email', ''),
        phone=raw.get('phone', ''), location=raw.get('location', ''),
    )
    res.update(top.as_dict())
    res['action'] = 'link_update' if (additions or replaces) else 'link'
    res['pending_additions'] = additions
    res['pending_replaces'] = [dict(rep, confirmed=False) for rep in replaces]
    return res


def _collapse_by_match(cards):
    """Drop later cards that resolve to the same existing record as an earlier one."""
    seen = set()
    out = []
    for card in cards:
        mid = card['resolution'].get('matched_id')
        if mid and mid in seen:
            continue
        if mid:
            seen.add(mid)
        out.append(card)
    return out


# --- public API ------------------------------------------------------------

def build_review_parties(raw_contacts, raw_organizations, body='', *, resolve=True):
    """Build the stored ``contacts[]`` / ``organizations[]`` review structure.

    ``resolve=False`` skips the DB match lookup (useful for pure unit tests of
    dedupe/offsets). Returns a dict ready to merge into ``Event.extracted_fields``.
    """
    contacts = []
    for i, raw in enumerate(_dedupe(raw_contacts)):
        fields = {}
        for key in ('name', 'email', 'phone', 'position', 'organization'):
            cell = _field(raw.get(key), body)
            if cell:
                fields[key] = cell
        fields['role'] = {'value': _normalize_role(raw.get('role'))}
        contacts.append({
            'ref': f'c{i}',
            'status': 'pending',
            'confidence': raw.get('confidence'),
            'fields': fields,
            'resolution': _resolve_contact(raw, resolve=resolve),
        })
    contacts = _collapse_by_match(contacts)

    organizations = []
    for i, raw in enumerate(raw_organizations or []):
        if not isinstance(raw, dict):
            continue
        fields = {}
        for key in ('name', 'location', 'email', 'phone'):
            cell = _field(raw.get(key), body)
            if cell:
                fields[key] = cell
        if 'name' not in fields:
            continue
        organizations.append({
            'ref': f'o{i}',
            'status': 'pending',
            'confidence': raw.get('confidence'),
            'fields': fields,
            'resolution': _resolve_org(raw, resolve=resolve),
        })
    organizations = _collapse_by_match(organizations)

    return {
        'schema_version': EXTRACTION_SCHEMA_VERSION,
        'contacts': contacts,
        'organizations': organizations,
    }


def is_v2(extracted_fields):
    """True when extracted_fields uses the new multi-contact shape."""
    ef = extracted_fields or {}
    return ef.get('schema_version') == EXTRACTION_SCHEMA_VERSION or isinstance(ef.get('contacts'), list)


def _cell_value(fields, key):
    cell = (fields or {}).get(key)
    if isinstance(cell, dict):
        return _clean(cell.get('value'))
    return _clean(cell)


def _legacy_value(extracted_fields, key):
    cell = (extracted_fields or {}).get(key)
    if isinstance(cell, dict):
        return _clean(cell.get('value'))
    return _clean(cell)


def iter_contacts(extracted_fields):
    """Yield contact-party dicts from either the v2 or the legacy flat shape.

    Each yielded dict: {name, email, phone, position, organization, role,
    ref, status, resolution}. Legacy events surface their single point of
    contact with role 'point_of_contact'.
    """
    ef = extracted_fields or {}
    if isinstance(ef.get('contacts'), list):
        for card in ef['contacts']:
            fields = card.get('fields', {})
            yield {
                'ref': card.get('ref'),
                'status': card.get('status'),
                'resolution': card.get('resolution'),
                'name': _cell_value(fields, 'name'),
                'email': _cell_value(fields, 'email'),
                'phone': _cell_value(fields, 'phone'),
                'position': _cell_value(fields, 'position'),
                'organization': _cell_value(fields, 'organization'),
                'role': _cell_value(fields, 'role') or EventContactRole.DEFAULT,
            }
        return
    # Legacy flat shape.
    name = _legacy_value(ef, 'point_of_contact_name')
    email = _legacy_value(ef, 'point_of_contact_email')
    phone = _legacy_value(ef, 'point_of_contact_phone')
    if name or email or phone:
        yield {
            'ref': 'legacy', 'status': None, 'resolution': None,
            'name': name, 'email': email, 'phone': phone,
            'position': '', 'organization': _legacy_value(ef, 'group'),
            'role': EventContactRole.POINT_OF_CONTACT,
        }


def iter_organizations(extracted_fields):
    """Yield org-party dicts from either the v2 or the legacy flat ('group') shape."""
    ef = extracted_fields or {}
    if isinstance(ef.get('organizations'), list):
        for card in ef['organizations']:
            fields = card.get('fields', {})
            yield {
                'ref': card.get('ref'),
                'status': card.get('status'),
                'resolution': card.get('resolution'),
                'name': _cell_value(fields, 'name'),
                'location': _cell_value(fields, 'location'),
                'email': _cell_value(fields, 'email'),
                'phone': _cell_value(fields, 'phone'),
            }
        return
    group = _legacy_value(ef, 'group')
    if group:
        yield {
            'ref': 'legacy', 'status': None, 'resolution': None,
            'name': group, 'location': '', 'email': '', 'phone': '',
        }
