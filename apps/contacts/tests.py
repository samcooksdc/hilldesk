# SPDX-License-Identifier: Apache-2.0
"""Tests for the contacts feature: crypto, models, services, directory, API."""

import json

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse


from .crypto import email_blind_index, name_blind_index, normalize_email
from .models import (
    Contact,
    ContactEmailAddress,
    ContactPhoneNumber,
    EventContact,
    EventOrganization,
    Organization,
)
from .services import (
    attach_contact_org_to_event,
    get_or_create_contact,
    get_or_create_organization,
    link_extraction_to_event,
)
from tests.factories import create_event

User = get_user_model()


class CryptoTests(TestCase):
    def test_email_blind_index_is_deterministic(self):
        self.assertEqual(
            email_blind_index('a@b.example'), email_blind_index('a@b.example'),
        )

    def test_email_blind_index_normalizes_case_and_whitespace(self):
        self.assertEqual(
            email_blind_index('  Foo.Bar@EXAMPLE.org '),
            email_blind_index('foo.bar@example.org'),
        )

    def test_email_blind_index_distinguishes_addresses(self):
        self.assertNotEqual(email_blind_index('a@b.example'), email_blind_index('a@c.example'))

    def test_blank_email_yields_empty_index(self):
        self.assertEqual(email_blind_index(''), '')
        self.assertEqual(email_blind_index(None), '')

    def test_name_blind_index_normalizes(self):
        self.assertEqual(name_blind_index('Acme  LLC'), name_blind_index('acme llc'))

    def test_normalize_email(self):
        self.assertEqual(normalize_email('  X@y.example '), 'x@y.example')


class ModelTests(TestCase):
    def test_encryption_round_trip(self):
        c = Contact.objects.create(name='Jane Doe', notes='VIP')
        reloaded = Contact.objects.get(pk=c.pk)
        self.assertEqual(reloaded.name, 'Jane Doe')
        self.assertEqual(reloaded.notes, 'VIP')

    def test_email_key_auto_set_on_save(self):
        c = Contact.objects.create(name='Jane')
        addr = ContactEmailAddress.objects.create(contact=c, email='Jane@Example.org', is_primary=True)
        self.assertEqual(addr.email_key, email_blind_index('jane@example.org'))

    def test_duplicate_email_key_rejected(self):
        c1 = Contact.objects.create(name='A')
        c2 = Contact.objects.create(name='B')
        ContactEmailAddress.objects.create(contact=c1, email='dup@example.org')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ContactEmailAddress.objects.create(contact=c2, email='dup@example.org')

    def test_primary_email_and_phone_properties(self):
        c = Contact.objects.create(name='Jane')
        ContactEmailAddress.objects.create(contact=c, email='second@example.org', is_primary=False)
        ContactEmailAddress.objects.create(contact=c, email='primary@example.org', is_primary=True)
        ContactPhoneNumber.objects.create(contact=c, phone='111', is_primary=True)
        self.assertEqual(c.primary_email, 'primary@example.org')
        self.assertEqual(c.primary_phone, '111')

    def test_organization_name_key_auto_set(self):
        org = Organization.objects.create(name='Acme LLC')
        self.assertEqual(org.name_key, name_blind_index('Acme LLC'))


class ServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('svc', 'svc@example.org', 'pw')

    def test_get_or_create_contact_creates_then_matches(self):
        c1, created1 = get_or_create_contact(email='match@example.org', name='M', phone='1', user=self.user)
        self.assertTrue(created1)
        # Same email, different case/whitespace -> must match, not create.
        c2, created2 = get_or_create_contact(email='  MATCH@example.org ', name='M2', user=self.user)
        self.assertFalse(created2)
        self.assertEqual(c1.pk, c2.pk)
        self.assertEqual(Contact.objects.count(), 1)

    def test_get_or_create_contact_no_email_no_name(self):
        c, created = get_or_create_contact(email='', name='', user=self.user)
        self.assertIsNone(c)
        self.assertFalse(created)

    def test_get_or_create_organization_exact_name(self):
        o1, c1 = get_or_create_organization(name='Acme LLC', user=self.user)
        o2, c2 = get_or_create_organization(name='acme   llc', user=self.user)
        self.assertTrue(c1)
        self.assertFalse(c2)
        self.assertEqual(o1.pk, o2.pk)

    def test_attach_contact_org_to_event_links_and_dedupes(self):
        e1 = create_event(type='meeting', status='received', created_by=self.user, modified_by=self.user)
        e2 = create_event(type='meeting', status='received', created_by=self.user, modified_by=self.user)
        c1, o1 = attach_contact_org_to_event(e1, name='P', email='p@example.org', phone='1', group='Org X', user=self.user)
        c2, o2 = attach_contact_org_to_event(e2, name='P', email='p@example.org', group='Org X', user=self.user)
        self.assertEqual(c1.pk, c2.pk)
        self.assertEqual(o1.pk, o2.pk)
        self.assertEqual(Contact.objects.count(), 1)
        self.assertEqual(Organization.objects.count(), 1)
        self.assertEqual(EventContact.objects.count(), 2)
        self.assertEqual(EventOrganization.objects.count(), 2)
        self.assertEqual(c1.event_links.count(), 2)
        self.assertIn(o1, c1.organizations.all())

    def test_link_extraction_handles_plain_and_value_shapes(self):
        e = create_event(type='meeting', status='received', created_by=self.user, modified_by=self.user)
        extracted = {
            'point_of_contact': {
                'name': {'value': 'Wrapped Name'},
                'email': {'value': 'wrapped@example.org'},
                'phone': '(202) 555-0000',
            },
            'group': 'Wrapped Org',
        }
        contact, org = link_extraction_to_event(e, extracted, self.user)
        self.assertEqual(contact.name, 'Wrapped Name')
        self.assertEqual(contact.primary_email, 'wrapped@example.org')
        self.assertEqual(org.name, 'Wrapped Org')
        self.assertEqual(EventContact.objects.filter(event=e).count(), 1)


class DirectoryViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('dir', 'dir@example.org', 'pw')
        self.client = Client()
        self.client.force_login(self.user)
        self.contact = Contact.objects.create(name='Zelda Smith')
        ContactEmailAddress.objects.create(contact=self.contact, email='zelda@example.org', is_primary=True)
        self.org = Organization.objects.create(name='Hyrule Council')
        self.contact.organizations.add(self.org)

    def test_contact_list_renders(self):
        r = self.client.get(reverse('contacts:list'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Zelda Smith')

    def test_contact_list_renders_all(self):
        # Search and sort are client-side now; the server renders every row.
        Contact.objects.create(name='Other Person')
        r = self.client.get(reverse('contacts:list'))
        self.assertContains(r, 'Zelda Smith')
        self.assertContains(r, 'Other Person')

    def test_contact_panel_renders(self):
        r = self.client.get(reverse('contacts:panel', args=[self.contact.id]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'zelda@example.org')
        self.assertContains(r, 'Hyrule Council')

    def test_org_list_and_panel(self):
        self.assertEqual(self.client.get(reverse('contacts:org_list')).status_code, 200)
        r = self.client.get(reverse('contacts:org_panel', args=[self.org.id]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Hyrule Council')

    def test_login_required(self):
        self.client.logout()
        r = self.client.get(reverse('contacts:list'))
        self.assertEqual(r.status_code, 302)


class ApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('api', 'api@example.org', 'pw')
        self.client = Client()
        self.client.force_login(self.user)
        self.contact = Contact.objects.create(name='Existing')
        ContactEmailAddress.objects.create(contact=self.contact, email='existing@example.org', is_primary=True)

    def test_list(self):
        r = self.client.get('/api/contacts/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['count'], 1)

    def test_exact_email_lookup(self):
        r = self.client.get('/api/contacts/', {'email': 'EXISTING@example.org'})
        self.assertEqual(r.json()['count'], 1)

    def test_create(self):
        payload = {'name': 'New', 'emails': [{'email': 'new@example.org', 'is_primary': True}]}
        r = self.client.post('/api/contacts/', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()['primary_email'], 'new@example.org')

    def test_create_duplicate_email_rejected(self):
        payload = {'name': 'Dup', 'emails': [{'email': 'existing@example.org'}]}
        r = self.client.post('/api/contacts/', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('existing_contact_id', r.json())

    def test_link_and_unlink_event(self):
        event = create_event(type='meeting', status='received', created_by=self.user, modified_by=self.user)
        r = self.client.post(
            f'/api/contacts/{self.contact.id}/link_event/',
            data=json.dumps({'event_id': str(event.id), 'role': 'point_of_contact'}),
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(EventContact.objects.filter(contact=self.contact, event=event).exists())
        r = self.client.post(
            f'/api/contacts/{self.contact.id}/unlink_event/',
            data=json.dumps({'event_id': str(event.id)}),
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 200)
        self.assertFalse(EventContact.objects.filter(contact=self.contact, event=event).exists())

    def test_requires_authentication(self):
        self.client.logout()
        r = self.client.get('/api/contacts/')
        self.assertIn(r.status_code, (401, 403))


class ResolutionServiceTests(TestCase):
    """Multi-contact matching + resolution (extraction-review overhaul, Phase 3)."""

    def setUp(self):
        self.user = User.objects.create_user('res', 'res@example.org', 'pw')

    def _event(self):
        return create_event(
            type='meeting', status='received',
            created_by=self.user, modified_by=self.user,
        )

    def _contact(self, *, name='', email='', phone='', position='', org=None):
        c = Contact.objects.create(name=name, position=position,
                                   created_by=self.user, modified_by=self.user)
        if email:
            ContactEmailAddress.objects.create(contact=c, email=email, is_primary=True)
        if phone:
            ContactPhoneNumber.objects.create(contact=c, phone=phone, is_primary=True)
        if org:
            c.organizations.add(org)
        return c

    # --- name_similarity --------------------------------------------------
    def test_name_similarity_order_and_honorifics(self):
        from .services import name_similarity
        self.assertEqual(name_similarity('John Smith', 'Smith, John'), 1.0)
        self.assertEqual(name_similarity('Dr. Alan Foster', 'Alan Foster'), 1.0)
        self.assertEqual(name_similarity('Jane Doe', ''), 0.0)
        self.assertLess(name_similarity('Jane Doe', 'Robert Klein'), 0.5)

    # --- match signal matrix ---------------------------------------------
    def test_match_by_email(self):
        from .services import match_contact
        c = self._contact(name='Jane Doe', email='jane@acme.example')
        matches = match_contact(email='JANE@acme.example', name='Totally Different')
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].contact.pk, c.pk)
        self.assertEqual(matches[0].matched_by, 'email')
        self.assertEqual(matches[0].confidence, 1.0)

    def test_match_by_name_and_phone(self):
        from .services import match_contact
        c = self._contact(name='Jane Doe', phone='(202) 555-0100')
        # New email (no email match) but same name + same phone, different format.
        matches = match_contact(email='new@x.example', name='Jane Doe', phone='+1 202 555 0100')
        self.assertEqual([m.contact.pk for m in matches], [c.pk])
        self.assertEqual(matches[0].matched_by, 'name_phone')

    def test_match_by_name_and_org(self):
        from .services import match_contact
        org = Organization.objects.create(name='Acme Advocacy')
        c = self._contact(name='Jane Q Doe', org=org)
        matches = match_contact(name='Jane Q Doe', organization='acme advocacy')
        self.assertEqual([m.contact.pk for m in matches], [c.pk])
        self.assertEqual(matches[0].matched_by, 'name_org')

    def test_no_match_when_only_name(self):
        from .services import match_contact
        self._contact(name='Jane Doe', phone='2025550100')
        # Name alone (no corroborating phone/org/email) must not match.
        self.assertEqual(match_contact(name='Jane Doe'), [])

    def test_phone_match_requires_name_agreement(self):
        from .services import match_contact
        self._contact(name='Jane Doe', phone='2025550100')
        # Same phone but a clearly different name -> no false merge.
        self.assertEqual(match_contact(name='Robert Klein', phone='2025550100'), [])

    # --- diff + resolve ---------------------------------------------------
    def test_diff_additions_and_position_replace(self):
        from .services import diff_against_contact
        c = self._contact(name='Jane', email='jane@acme.example', phone='2025550100',
                          position='Staff Asst')
        additions, replaces = diff_against_contact(
            c, email='jane2@acme.example', phone='2025550100', position='Legislative Aide',
        )
        # New email appends; identical phone is not re-added; position differs -> replace.
        self.assertEqual(additions, [{'kind': 'email', 'value': 'jane2@acme.example'}])
        self.assertEqual(replaces, [{'kind': 'position', 'old': 'Staff Asst',
                                     'new': 'Legislative Aide'}])

    def test_resolve_new_creates_contact_and_link(self):
        from .services import resolve_contact
        ev = self._event()
        c = resolve_contact(ev, {
            'name': 'Margaret Halloran', 'email': 'mh@scc.example',
            'phone': '5405550173', 'position': 'President',
            'organization': 'Sister Cities', 'role': 'point_of_contact',
        }, {'action': 'new'}, user=self.user)
        self.assertEqual(c.primary_email, 'mh@scc.example')
        self.assertEqual(c.position, 'President')
        link = EventContact.objects.get(event=ev, contact=c)
        self.assertEqual(link.role, 'point_of_contact')
        self.assertTrue(link.is_primary)
        self.assertEqual([o.name for o in c.organizations.all()], ['Sister Cities'])

    def test_resolve_link_update_appends_and_demotes(self):
        from .services import resolve_contact
        ev = self._event()
        c = self._contact(name='Jane Doe', email='jane@acme.example', phone='2025550100',
                          position='Staff Asst')
        resolve_contact(ev, {
            'name': 'Jane Doe', 'role': 'attendee',
        }, {
            'action': 'link_update', 'matched_id': str(c.pk),
            # An addition accumulates as a non-primary contact point.
            'additions': [{'kind': 'email', 'value': 'jane.alt@acme.example'}],
            # A confirmed replace promotes a new primary (demoting the old) and
            # overwrites the single-valued position.
            'replaces': [
                {'kind': 'email', 'new': 'jane.new@acme.example', 'confirmed': True},
                {'kind': 'position', 'new': 'Legislative Aide', 'confirmed': True},
            ],
        }, user=self.user)
        c.refresh_from_db()
        emails = {e.email: e.is_primary for e in c.email_addresses.all()}
        # Old primary kept but demoted (decision #5: demote, never delete); the
        # appended email stays non-primary; the replaced email is the new primary.
        self.assertEqual(emails, {
            'jane@acme.example': False,
            'jane.alt@acme.example': False,
            'jane.new@acme.example': True,
        })
        self.assertEqual(c.position, 'Legislative Aide')
        self.assertEqual(Contact.objects.count(), 1)

    def test_resolve_link_leaves_existing_untouched(self):
        from .services import resolve_contact
        ev = self._event()
        c = self._contact(name='Jane Doe', email='jane@acme.example', position='Staff Asst')
        resolve_contact(ev, {'name': 'Jane Doe', 'position': 'Should Not Apply'},
                        {'action': 'link', 'matched_id': str(c.pk)}, user=self.user)
        c.refresh_from_db()
        self.assertEqual(c.position, 'Staff Asst')  # plain link makes no edits
        self.assertTrue(EventContact.objects.filter(event=ev, contact=c).exists())


class ExtractionNormalizerTests(TestCase):
    """build_review_parties + back-compat reader (Phase 2)."""

    def setUp(self):
        self.user = User.objects.create_user('ext', 'ext@example.org', 'pw')

    def test_dedupe_by_email_and_offsets(self):
        from .extraction import build_review_parties
        body = "Contact Jane Doe at jane@acme.example or her assistant."
        raw = [
            {'name': 'Jane Doe', 'email': 'jane@acme.example', 'role': 'point_of_contact'},
            {'name': 'J. Doe', 'email': 'JANE@acme.example', 'phone': '2025550100'},
        ]
        out = build_review_parties(raw, [], body, resolve=False)
        self.assertEqual(out['schema_version'], 2)
        # Two raw entries, same email -> one card; phone folded in from the second.
        self.assertEqual(len(out['contacts']), 1)
        fields = out['contacts'][0]['fields']
        self.assertEqual(fields['phone']['value'], '2025550100')
        # Name offsets point into the body.
        s, e = fields['name']['source']
        self.assertEqual(body[s:e], 'Jane Doe')

    def test_dedupe_by_name_and_phone(self):
        from .extraction import build_review_parties
        raw = [
            {'name': 'Jane Doe', 'phone': '(202) 555-0100', 'role': 'attendee'},
            {'name': 'jane doe', 'phone': '+1 202 555 0100', 'position': 'Director'},
        ]
        out = build_review_parties(raw, [], '', resolve=False)
        self.assertEqual(len(out['contacts']), 1)
        self.assertEqual(out['contacts'][0]['fields']['position']['value'], 'Director')

    def test_role_normalization_and_default(self):
        from .extraction import build_review_parties
        raw = [
            {'name': 'A', 'email': 'a@x.example', 'role': 'POC'},
            {'name': 'B', 'email': 'b@x.example', 'role': 'speaker'},
            {'name': 'C', 'email': 'c@x.example'},  # no role -> default attendee
        ]
        out = build_review_parties(raw, [], '', resolve=False)
        roles = [c['fields']['role']['value'] for c in out['contacts']]
        self.assertEqual(roles, ['point_of_contact', 'host_speaker', 'attendee'])

    def test_resolution_new_vs_link_update(self):
        from .extraction import build_review_parties
        existing = Contact.objects.create(name='Jane Doe', position='Staff Asst')
        ContactEmailAddress.objects.create(contact=existing, email='jane@acme.example', is_primary=True)
        raw = [
            {'name': 'Jane Doe', 'email': 'jane@acme.example', 'position': 'Legislative Aide'},
            {'name': 'New Person', 'email': 'new@acme.example'},
        ]
        out = build_review_parties(raw, [], '', resolve=True)
        by_name = {c['fields']['name']['value']: c['resolution'] for c in out['contacts']}
        # Existing email match + differing position -> link_update with a replace.
        self.assertEqual(by_name['Jane Doe']['action'], 'link_update')
        self.assertEqual(by_name['Jane Doe']['matched_by'], 'email')
        self.assertEqual(by_name['Jane Doe']['pending_replaces'][0]['kind'], 'position')
        self.assertFalse(by_name['Jane Doe']['pending_replaces'][0]['confirmed'])
        # Unknown person -> new.
        self.assertEqual(by_name['New Person']['action'], 'new')

    def test_collapse_cards_resolving_to_same_contact(self):
        from .extraction import build_review_parties
        existing = Contact.objects.create(name='Jane Doe')
        ContactEmailAddress.objects.create(contact=existing, email='jane@acme.example', is_primary=True)
        ContactEmailAddress.objects.create(contact=existing, email='jane.alt@acme.example')
        # Two raw parties (different emails, not deduped pre-match) that both
        # resolve to the same existing contact -> collapse to one card.
        raw = [
            {'name': 'Jane Doe', 'email': 'jane@acme.example'},
            {'name': 'Jane Doe', 'email': 'jane.alt@acme.example'},
        ]
        out = build_review_parties(raw, [], '', resolve=True)
        self.assertEqual(len(out['contacts']), 1)

    def test_iter_contacts_v2_shape(self):
        from .extraction import build_review_parties, iter_contacts
        raw = [{'name': 'Jane', 'email': 'jane@acme.example', 'role': 'point_of_contact'}]
        ef = build_review_parties(raw, [], '', resolve=False)
        parties = list(iter_contacts(ef))
        self.assertEqual(len(parties), 1)
        self.assertEqual(parties[0]['email'], 'jane@acme.example')
        self.assertEqual(parties[0]['role'], 'point_of_contact')

    def test_iter_contacts_legacy_flat_shape(self):
        from .extraction import iter_contacts, iter_organizations
        legacy = {
            'point_of_contact_name': {'value': 'Old POC'},
            'point_of_contact_email': {'value': 'old@x.example'},
            'group': {'value': 'Old Org'},
        }
        parties = list(iter_contacts(legacy))
        self.assertEqual(parties[0]['name'], 'Old POC')
        self.assertEqual(parties[0]['role'], 'point_of_contact')
        orgs = list(iter_organizations(legacy))
        self.assertEqual(orgs[0]['name'], 'Old Org')
