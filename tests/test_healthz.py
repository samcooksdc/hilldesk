# SPDX-License-Identifier: Apache-2.0
"""/healthz/ works for load-balancer probes: plain HTTP, IP Host header, no auth."""
import json
from unittest.mock import patch

from django.conf import settings
from django.test import TestCase, override_settings


class HealthCheckTests(TestCase):
    def test_ok_without_login(self) -> None:
        response = self.client.get('/healthz/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content), {'status': 'ok'})

    @override_settings(ALLOWED_HOSTS=['hilldesk.example.com'], SECURE_SSL_REDIRECT=True, DEBUG=False)
    def test_probe_by_ip_over_http_is_not_rejected(self) -> None:
        response = self.client.get('/healthz/', HTTP_HOST='10.0.12.34:8000')
        self.assertEqual(response.status_code, 200)
        # ...while normal pages from that Host are still refused.
        self.assertEqual(self.client.get('/auth/login/', HTTP_HOST='10.0.12.34:8000').status_code, 400)

    def test_reports_unavailable_when_database_fails(self) -> None:
        with patch('apps.authentication.health.connection.cursor', side_effect=Exception('db down')):
            response = self.client.get('/healthz/')
        self.assertEqual(response.status_code, 503)

    def test_only_get_and_head(self) -> None:
        self.assertEqual(self.client.post('/healthz/').status_code, 405)

    def test_is_first_middleware(self) -> None:
        self.assertEqual(settings.MIDDLEWARE[0], 'apps.authentication.health.HealthCheckMiddleware')
