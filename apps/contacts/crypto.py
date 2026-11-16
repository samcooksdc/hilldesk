# SPDX-License-Identifier: Apache-2.0
"""Blind-index helpers for the contacts app.

Contact / Organization PII (name, email, phone, notes) is stored with the
project's Fernet-based encrypted fields. Fernet is non-deterministic, so an
encrypted column cannot be queried with ``filter(email=...)`` or used as a
unique key. To support EXACT-match lookup on encrypted email (and exact-name
lookup on organizations) we store a separate, non-encrypted blind index next to
the encrypted value: a keyed HMAC-SHA256 of the normalized plaintext.

The HMAC is keyed (not a bare hash) so the index is not trivially reversible
via a dictionary attack on a leaked column. The key is derived from
``CONTACT_BLIND_INDEX_KEY`` (falling back to ``FIELD_ENCRYPTION_KEY``).
"""

import hashlib
import hmac

from django.conf import settings


def _blind_index_key() -> bytes:
    key = getattr(settings, 'CONTACT_BLIND_INDEX_KEY', None) \
        or getattr(settings, 'FIELD_ENCRYPTION_KEY', None)
    if not key:
        raise ValueError(
            "Neither CONTACT_BLIND_INDEX_KEY nor FIELD_ENCRYPTION_KEY is configured"
        )
    if isinstance(key, str):
        key = key.encode()
    return key


def normalize_email(raw: str) -> str:
    """Lowercase + strip surrounding whitespace. Email is the natural match key."""
    return (raw or '').strip().lower()


def normalize_name(raw: str) -> str:
    """Collapse internal whitespace + lowercase for exact-name org matching."""
    return ' '.join((raw or '').split()).lower()


def normalize_phone(raw: str) -> str:
    """Reduce a phone number to a stable match key: digits only.

    Strips formatting ('(540) 555-0173' -> '5405550173') so differently-formatted
    copies of the same number share a blind index. For >=10 digits we keep the
    last 10 (the US local number), dropping a leading country/trunk code so
    '+1 540 555 0173' and '(540) 555-0173' collapse to the same key. Shorter
    inputs (extensions, partial numbers) are kept whole. Intentionally lossy:
    extensions and international subscriber numbers may collide — acceptable for
    the name+phone match signal, which is always confirmed by a reviewer.
    """
    digits = ''.join(ch for ch in (raw or '') if ch.isdigit())
    return digits[-10:] if len(digits) >= 10 else digits


def phone_blind_index(raw: str) -> str:
    """Deterministic match key for a phone number (empty for blank input)."""
    return _hmac(normalize_phone(raw))


def _hmac(value: str) -> str:
    if not value:
        return ''
    return hmac.new(
        _blind_index_key(), value.encode('utf-8'), hashlib.sha256
    ).hexdigest()


def email_blind_index(raw: str) -> str:
    """Deterministic match key for an email address (empty for blank input)."""
    return _hmac(normalize_email(raw))


def name_blind_index(raw: str) -> str:
    """Deterministic match key for an organization name (empty for blank input)."""
    return _hmac(normalize_name(raw))
