# CLAUDE.md

Guidance for AI coding assistants (and humans) working in this repository.

## Project Overview
HillDesk is an open-source scheduling and workflow application for U.S. House
offices. It ingests email from Outlook, uses AI to extract scheduling
information, and provides a human-in-the-loop review interface. See
`docs/architecture.md`.

## Tech Stack
- Django 5.2 / Python 3.10+
- Django REST Framework
- Celery + Redis
- PostgreSQL (production) / SQLite (development)
- Amazon Bedrock for LLM (production)
- Microsoft Graph API for Outlook integration
- Azure AD OIDC authentication (production)

## Deployment Constraints (House profile)
Production settings target restricted House-style AWS environments:
- **LLM**: Amazon Bedrock ONLY in production — `production.py` refuses any other
  provider. Never add a SaaS LLM path to production.
- **Network**: assume no public internet egress; reach AWS services via VPC endpoints
- **Auth**: Azure AD SSO in production; local Django auth in development
- **Compute**: containers (ECS Fargate), images from a private registry
- **Secrets**: injected from a secrets manager; never hardcoded. Production
  fails closed if `SECRET_KEY`, `FIELD_ENCRYPTION_KEY` or
  `CONTACT_BLIND_INDEX_KEY` is missing or a dev default.

## Development Environments

| Environment | LLM_PROVIDER | USE_SSO | Database |
|-------------|--------------|---------|----------|
| Production | `bedrock` | `True` | PostgreSQL |
| Dev (offline) | `mock` | `False` | SQLite |
| Dev (API test) | `anthropic_dev` | `False` | SQLite |

## Code Conventions
- Human-in-the-loop: AI is assistive only, never decision-making. Model output
  is data for a human to approve; it never sends mail or changes the calendar.
- Treat inbound email as untrusted input (prompt injection is expected).
- All PII fields use `EncryptedCharField`
- Audit logging on all sensitive operations
- Type hints on all new code
- Tests required for new features
- Demo/seed tools call `apps.authentication.devtools.require_dev_environment()`
  and only run with `DEBUG=True`
- Fixtures use fictional people and `example.com` addresses — never real
  constituent, staff or office data

## Project Structure
The Django project lives at the repository root (run `manage.py` from there).
Apps are grouped under the `apps/` package and referenced as `apps.<name>`
(e.g. `apps.event_management`); their app *labels* and URL namespaces remain the
short form (`event_management`).

```
hilldesk/
  manage.py
  config/            # settings (base/development/production/testing), urls, celery, wsgi/asgi
  apps/
    api/             # DRF serializers, services, viewsets
    authentication/  # custom User, OIDC backend, security middleware
    contacts/        # normalized contacts + organizations
    email_processing/# Graph ingestion, funnel, LLM providers, extraction
    event_management/# events, calendar, templates, exports
  templates/  static/  tests/
  docs/              # architecture, design docs, specs
  scripts/           # demo + simulation helpers (run from repo root, DEBUG only)
```

## Commands
- `python manage.py runserver` — start dev server (from repo root)
- `python manage.py test --settings=config.settings.testing` — run tests
- `celery -A config worker` — start Celery worker
- `python scripts/create_demo_office.py` then `python scripts/populate_office_demo_info.py`
  — seed the fictional demo office
- `python scripts/simulate_email_ingestion.py` — push fake mail through the real pipeline

## Documentation
- **Architecture**: `docs/architecture.md` — stack, layout, pipeline, security model, deployment shape
- **Design history**: `docs/` and `docs/kiro/specs/`
