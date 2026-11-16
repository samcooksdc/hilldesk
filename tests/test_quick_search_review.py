# SPDX-License-Identifier: Apache-2.0
"""The global "/" quick search must not surface anything still awaiting review.

The quick search (static/js/keyboard-nav.js) queries:
  /api/events/?search=...&requires_human_review=false
  /api/contacts/?search=...&exclude_in_review=true
  /api/organizations/?search=...&exclude_in_review=true
"""
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.contacts.services import attach_contact_org_to_event, get_or_create_contact
from tests.factories import create_event, make_office_member

User = get_user_model()


def _names(response):
    data = response.json()
    rows = data['results'] if isinstance(data, dict) and 'results' in data else data
    return {row.get('name') or row.get('title') for row in rows}


class QuickSearchReviewFilterTests(APITestCase):
    def setUp(self) -> None:
        self.user = make_office_member(
            User.objects.create_user(username='searcher', email='s@example.com', password='pw-for-tests')
        )
        self.client.force_authenticate(self.user)
        today = timezone.now().date()

        def event(title, **extra):
            return create_event(title=title, type='meeting', start_date=today,
                                created_by=self.user, modified_by=self.user, **extra)

        self.draft = event('Zeta draft meeting', requires_human_review=True)
        self.reviewed = event('Zeta approved meeting', requires_human_review=False)
        self.dismissed = event('Zeta dismissed meeting', requires_human_review=False,
                               review_decision='dismissed')

        attach_contact_org_to_event(self.draft, name='Zeta Draftonly', group='Zeta Draft Org')
        attach_contact_org_to_event(self.dismissed, name='Zeta Dismissedonly', group='Zeta Dismissed Org')
        attach_contact_org_to_event(self.reviewed, name='Zeta Reviewed', group='Zeta Reviewed Org')
        # Linked to both a draft and a reviewed event: already known, so visible.
        attach_contact_org_to_event(self.draft, name='Zeta Both', group='Zeta Both Org')
        attach_contact_org_to_event(self.reviewed, name='Zeta Both', group='Zeta Both Org')
        # Created by hand in the directory, never linked to an event: visible.
        get_or_create_contact(name='Zeta Directory', user=self.user)

    def test_events_exclude_drafts_and_dismissed(self) -> None:
        titles = _names(self.client.get('/api/events/', {
            'search': 'Zeta', 'page_size': 8, 'requires_human_review': 'false'}))
        self.assertEqual(titles, {'Zeta approved meeting'})

    def test_contacts_exclude_review_only(self) -> None:
        names = _names(self.client.get('/api/contacts/', {
            'search': 'Zeta', 'page_size': 8, 'exclude_in_review': 'true'}))
        self.assertEqual(names, {'Zeta Reviewed', 'Zeta Both', 'Zeta Directory'})

    def test_organizations_exclude_review_only(self) -> None:
        names = _names(self.client.get('/api/organizations/', {
            'search': 'Zeta', 'page_size': 8, 'exclude_in_review': 'true'}))
        self.assertEqual(names, {'Zeta Reviewed Org', 'Zeta Both Org'})

    def test_filters_are_opt_in(self) -> None:
        """Other screens (inbox, contact pickers) still see everything."""
        names = _names(self.client.get('/api/contacts/', {'search': 'Zeta', 'page_size': 8}))
        self.assertIn('Zeta Draftonly', names)

    def test_quick_search_script_uses_the_filters(self) -> None:
        from pathlib import Path
        from django.conf import settings
        js = (Path(settings.BASE_DIR) / 'static' / 'js' / 'keyboard-nav.js').read_text(encoding='utf-8')
        self.assertIn("requires_human_review=false", js)
        self.assertEqual(js.count("exclude_in_review=true"), 2)
