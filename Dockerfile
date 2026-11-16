# SPDX-License-Identifier: Apache-2.0
#
# One image for every process:
#   web     (default)  gunicorn config.wsgi
#   worker             celery -A config worker -l info
#   beat               celery -A config beat -l info
#   demo               see docker-compose.yml (development settings, mock AI)
#
# Production configuration comes entirely from the environment; the image
# contains no secrets. See docs/deployment.md.

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# libpq for psycopg2-binary at runtime; nothing else from apt.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Exact versions from the lock file (regenerate: see pyproject.toml).
COPY requirements.lock .
RUN pip install -r requirements.lock

COPY . .

# Collect static files at build time with throwaway build-only secrets
# (production settings refuse to load without values).
RUN SECRET_KEY=build-only-not-secret FIELD_ENCRYPTION_KEY=build-only-not-secret \
       DJANGO_SETTINGS_MODULE=config.settings.production \
       python manage.py collectstatic --noinput

# /data holds the demo's SQLite file (docker-compose mounts a volume there).
RUN useradd --create-home --uid 10001 hilldesk \
    && mkdir -p /data \
    && chown -R hilldesk:hilldesk /app /data
USER hilldesk

EXPOSE 8000
ENV DJANGO_SETTINGS_MODULE=config.settings.production
# Web container health (worker/beat task definitions should override or drop it).
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz/', timeout=4).status == 200 else 1)"
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--access-logfile", "-"]
