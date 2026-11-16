# SPDX-License-Identifier: Apache-2.0
"""Tests for the API services — v2 multi-contact review with DEFERRED commit.

Invariants:
  * Accepting a card records the decision but writes nothing to the contacts
    tables; rows are created only when the ENTIRE event passes review.
  * Each extracted field of a card is its own review unit (role excluded — it is
    staff-assigned, not extracted). A card resolves only once its card-level
    accept AND every one of its extracted fields has been reviewed.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.api.services import FieldReviewService
from apps.contacts.extraction import build_review_parties
from apps.contacts.models import (
    Contact,
    ContactEmailAddress,
    EventContact,
    EventOrganization,
    Organization,
)
from tests.factories import create_event

User = get_user_model()


class V2FieldReviewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('rev', 'rev@example.org', 'pw')
        self.service = FieldReviewService()

        self.jane = Contact.objects.create(name='Jane Doe', position='Staff Asst')
        ContactEmailAddress.objects.create(contact=self.jane, email='jane@acme.example', is_primary=True)
        self.acme = Organization.objects.create(name='Acme')

        parties = build_review_parties(
            [{'name': 'Jane Doe', 'email': 'jane@acme.example', 'phone': '2025550100',
              'position': 'Director', 'organization': 'Acme', 'role': 'point_of_contact'}],
            [{'name': 'Acme', 'location': 'Washington, DC'}],
            'Jane Doe jane@acme.example Acme',
            resolve=True,
        )
        extracted = dict(parties)
        extracted['title'] = {'value': 'Meeting with Acme', 'status': 'pending', 'confidence': 0.9}
        self.event = create_event(
            type='meeting', status='received', requires_human_review=True,
            extracted_fields=extracted, created_by=self.user, modified_by=self.user,
        )
        self.cref = self.event.extracted_fields['contacts'][0]['ref']
        self.oref = self.event.extracted_fields['organizations'][0]['ref']

    def _contact_card(self):
        return self.event.extracted_fields['contacts'][0]

    def _review_all_fields(self, kind, ref):
        card = self.service._find_card(self.event, kind, ref)
        for k in self.service._card_field_keys(card):
            method = self.service.review_contact if kind == 'contacts' else self.service.review_organization
            method(self.event, ref, 'review_field', self.user, payload={'ref': ref, 'field': k})

    def _link_count(self):
        return EventContact.objects.filter(event=self.event).count()

    def test_role_is_not_a_field_unit(self):
        keys = self.service._card_field_keys(self._contact_card())
        self.assertNotIn('role', keys)
        self.assertIn('email', keys)

    def test_counts_include_card_and_each_field(self):
        status = self.service.get_review_status(self.event)
        # title(1) + contact card(1 + name/email/phone/position/organization=5)
        #          + org card(1 + name/location=2) = 10
        self.assertEqual(status['total_fields'], 10)
        self.assertEqual(status['pending_count'], 10)

    def test_accept_card_defers_and_fields_still_pending(self):
        r = self.service.review_contact(self.event, self.cref, 'accept', self.user)
        self.assertFalse(r['review_complete'])
        # The card unit is reviewed but its 5 fields are not.
        total, reviewed = self.service._card_unit_counts(self._contact_card())
        self.assertEqual((total, reviewed), (6, 1))
        self.assertEqual(self._link_count(), 0)

    def test_full_review_commits_only_when_all_fields_reviewed(self):
        self.service.accept_field(self.event, 'title', self.user)
        self.service.review_contact(
            self.event, self.cref, 'accept', self.user,
            payload={
                'additions': [{'kind': 'phone', 'value': '2025550100'}],
                'replaces': [{'kind': 'position', 'new': 'Director', 'confirmed': True}],
                'role': 'point_of_contact', 'is_primary': True,
            },
        )
        self.service.review_organization(
            self.event, self.oref, 'accept', self.user,
            payload={'additions': [{'kind': 'location', 'value': 'Washington, DC'}]},
        )
        # Cards accepted but their fields are unreviewed -> NOT complete, no commit.
        self.assertFalse(self.service.is_review_complete(self.event))
        self.assertEqual(self._link_count(), 0)

        # Review every field of both cards -> now complete -> commit.
        self._review_all_fields('contacts', self.cref)
        self._review_all_fields('organizations', self.oref)
        self.event.refresh_from_db()
        self.assertFalse(self.event.requires_human_review)
        link = EventContact.objects.get(event=self.event, contact=self.jane)
        self.assertEqual(link.role, 'point_of_contact')
        self.jane.refresh_from_db()
        self.assertEqual(self.jane.position, 'Director')
        self.assertEqual(Contact.objects.count(), 1)
        self.acme.refresh_from_db()
        self.assertEqual(self.acme.location, 'Washington, DC')

    def test_rejected_card_needs_no_field_review(self):
        self.service.accept_field(self.event, 'title', self.user)
        self.service.review_contact(self.event, self.cref, 'reject', self.user)
        # Rejected card is fully closed (no field review needed).
        total, reviewed = self.service._card_unit_counts(self._contact_card())
        self.assertEqual(total, reviewed)
        self.service.review_organization(self.event, self.oref, 'accept', self.user,
                                         payload={'additions': []})
        self._review_all_fields('organizations', self.oref)
        self.event.refresh_from_db()
        self.assertFalse(self.event.requires_human_review)
        self.assertEqual(self._link_count(), 0)  # rejected contact never linked
        self.assertEqual(EventOrganization.objects.filter(event=self.event).count(), 1)

    def test_abandoned_review_writes_nothing(self):
        self.service.review_contact(self.event, self.cref, 'accept', self.user)
        self._review_all_fields('contacts', self.cref)
        # Org card + title still pending -> incomplete -> nothing committed.
        self.assertTrue(self.event.requires_human_review)
        self.assertEqual(self._link_count(), 0)

    def test_undo_card_re_pends_its_fields(self):
        self.service.review_contact(self.event, self.cref, 'accept', self.user)
        self._review_all_fields('contacts', self.cref)
        self.service.review_contact(self.event, self.cref, 'undo', self.user)
        card = self._contact_card()
        self.assertEqual(card['status'], 'pending')
        self.assertEqual(card.get('reviewed_fields'), [])

    def test_accept_all_commits_on_completion(self):
        r = self.service.accept_all_fields(self.event, self.user)
        self.assertTrue(r['review_complete'])
        self.assertEqual(self._link_count(), 1)
        self.assertEqual(EventOrganization.objects.filter(event=self.event).count(), 1)
