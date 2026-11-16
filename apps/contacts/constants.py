# SPDX-License-Identifier: Apache-2.0
"""Shared constants for the contacts app and the extraction-review pipeline.

Kept separate from models.py so non-model code (services, extraction parsers,
serializers) can import them without pulling in the ORM.
"""


class EventContactRole:
    """Allowed values for ``EventContact.role``.

    The role describes how a person relates to a *specific* event, not who they
    are. Staff / internal office members are intentionally excluded — they are
    handled by a separate staffing system, not the involved-parties review.
    """

    POINT_OF_CONTACT = 'point_of_contact'   # scheduler / organizer reaching out
    ATTENDEE = 'attendee'                    # expected at the event, not coordinating
    HOST_SPEAKER = 'host_speaker'            # hosting, presenting, or being honored

    CHOICES = [
        (POINT_OF_CONTACT, 'Point of contact'),
        (ATTENDEE, 'Attendee / participant'),
        (HOST_SPEAKER, 'Host / speaker'),
    ]

    VALUES = frozenset(value for value, _label in CHOICES)
    DEFAULT = ATTENDEE


# Version stamped onto ``Event.extracted_fields`` so serializers and the review
# UI can tell the new multi-contact/multi-org shape (contacts[] / organizations[]
# with per-party resolution blocks) apart from the legacy flat field map.
#   v1 (implicit / absent) — legacy: flat point_of_contact_* + group keys
#   v2 — contacts[] + organizations[] resolution objects
EXTRACTION_SCHEMA_VERSION = 2
