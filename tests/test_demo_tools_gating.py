# SPDX-License-Identifier: Apache-2.0
"""Demo tools wipe every office, user and event: they must not exist in production."""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import NoReverseMatch, reverse

from tests.factories import make_office_member

User = get_user_model()


class DemoToolsGatingTests(TestCase):
    def setUp(self) -> None:
        self.admin = make_office_member(
            User.objects.create_user(username='officeadmin', email='a@example.com', password='pw-for-tests')
        )
        self.client.force_login(self.admin)

    @override_settings(DEBUG=False)
    def test_reset_endpoint_is_404_without_debug(self) -> None:
        self.assertEqual(self.client.post('/api/demo/reset/').status_code, 404)

    @override_settings(DEBUG=False)
    def test_settings_hides_demo_tab_without_debug(self) -> None:
        response = self.client.get(reverse('event_management:settings'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'reset-demo-btn')
        self.assertNotContains(response, 'data-tab="demo"')

    @override_settings(DEBUG=True)
    def test_settings_shows_demo_tab_in_development(self) -> None:
        response = self.client.get(reverse('event_management:settings'))
        self.assertContains(response, 'reset-demo-btn')

    def test_unscoped_test_editing_route_is_gone(self) -> None:
        with self.assertRaises(NoReverseMatch):
            reverse('event_management:test_event_editing', kwargs={'event_id': '00000000-0000-0000-0000-000000000000'})
