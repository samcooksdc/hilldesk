# SPDX-License-Identifier: Apache-2.0
"""Diverted mail lives in the inbox as a second view (Inbox / Diverted toggle,
same control as Contacts' People / Organizations). Feed is JSON; the old
standalone URL redirects to the tab; all of it requires inbox access."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.authentication.models import Role
from apps.authentication.permissions import Permissions
from apps.email_processing.tasks.pipeline import run_pipeline
from tests.factories import make_office_member
from tests.test_email_funnel import make_raw

User = get_user_model()


class DivertedViewTests(TestCase):
    def setUp(self) -> None:
        self.user = make_office_member(
            User.objects.create_user(username='sched2', email='s2@example.com', password='pw-for-tests')
        )
        self.client.force_login(self.user)
        self.raw = make_raw(subject='Weekly newsletter blast',
                            headers={'List-Unsubscribe': '<mailto:u@x.example>'},
                            body='This week in the county...')
        run_pipeline(str(self.raw.id))
        self.api = reverse('email_processing:diverted_items_api')

    def test_feed_has_plain_reason_and_body(self) -> None:
        data = self.client.get(self.api).json()
        self.assertEqual(data['count'], 1)
        item = data['results'][0]
        self.assertEqual(item['id'], str(self.raw.id))
        self.assertEqual(item['reason_label'], 'Bulk or list mail')
        self.assertIn('This week in the county', item['body_text'])

    def test_feed_search(self) -> None:
        self.assertEqual(self.client.get(self.api, {'search': 'newsletter'}).json()['count'], 1)
        self.assertEqual(self.client.get(self.api, {'search': 'gala'}).json()['count'], 0)

    def test_inbox_header_has_view_toggle(self) -> None:
        response = self.client.get(reverse('event_management:inbox'))
        self.assertContains(response, 'class="contacts-tabs"')
        self.assertContains(response, 'data-view="diverted"')

    def test_old_url_redirects_to_tab(self) -> None:
        response = self.client.get(reverse('email_processing:divert_store'))
        self.assertRedirects(response, reverse('event_management:inbox') + '?view=diverted',
                             fetch_redirect_response=False)

    def test_promote_json_drops_item(self) -> None:
        promote = reverse('email_processing:promote_diverted', args=[self.raw.id])
        with patch('apps.email_processing.tasks.pipeline.run_pipeline.delay') as mock_delay:
            response = self.client.post(promote, HTTP_ACCEPT='application/json')
        self.assertEqual(response.json(), {'success': True, 'action': 'promote'})
        mock_delay.assert_called_once_with(str(self.raw.id), force_extract=True)

    def test_requires_inbox_permission(self) -> None:
        outsider = User.objects.create_user(username='noinbox2', email='n2@example.com', password='pw-for-tests')
        outsider.office = self.user.office
        outsider.assign_role(Role.objects.create(
            office=outsider.office, name='Viewer2', slug='viewer2',
            permissions=sorted(Permissions.expand_permissions({Permissions.VIEW_ALL_EVENTS})),
        ))
        outsider.save()
        self.client.force_login(outsider)
        self.assertEqual(self.client.get(self.api).status_code, 403)
        promote = reverse('email_processing:promote_diverted', args=[self.raw.id])
        self.assertEqual(self.client.post(promote).status_code, 403)
