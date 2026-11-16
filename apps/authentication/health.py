# SPDX-License-Identifier: Apache-2.0
"""Liveness/readiness probe for load balancers and container orchestrators.

``GET /healthz/`` answers before host validation and the HTTPS redirect,
because AWS load balancers probe over plain HTTP with the task's IP address
as the Host header, which ALLOWED_HOSTS and SECURE_SSL_REDIRECT would
otherwise reject. It checks the database with ``SELECT 1`` and returns
nothing but a status word: no auth, no data, no version information.

Keep this middleware first in MIDDLEWARE.
"""
import logging
from typing import Callable

from django.db import connection
from django.http import HttpRequest, HttpResponse, JsonResponse

logger = logging.getLogger(__name__)

HEALTH_PATH = '/healthz/'


class HealthCheckMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if request.path != HEALTH_PATH:
            return self.get_response(request)
        if request.method not in ('GET', 'HEAD'):
            return HttpResponse(status=405)
        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1')
                cursor.fetchone()
        except Exception:  # noqa: BLE001 - any DB failure means "not ready"
            logger.exception('Health check: database unavailable')
            return JsonResponse({'status': 'unavailable'}, status=503)
        return JsonResponse({'status': 'ok'})
