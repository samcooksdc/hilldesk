# HillDesk Architecture

HillDesk turns a House office's scheduling inbox into reviewed calendar
events. Email is ingested from Outlook, filtered by a deterministic funnel,
read by an LLM in a single structured-extraction call, and materialized as
**draft** items that only a staff member can approve. The model has no tools
and no write path.

> **One deployment per office.** Events are not partitioned by office in the
> database; visibility is controlled by roles within a single deployment.
> Don't host several offices on one instance.
>
> Status: beta. Designed for restricted AWS environments (no public internet
> egress, Amazon Bedrock as the only model provider, Azure AD sign-in). It is
> not certified under FedRAMP, NIST 800-53 or any House program; each
> deployment needs its own security review.

## Stack

| Layer | Production | Development |
| --- | --- | --- |
| Web | Django 5.2, Django REST Framework (Python 3.10+) | same |
| Background work | Celery workers + beat, Redis broker/cache | Celery eager mode |
| Database | PostgreSQL (e.g. RDS, TLS required) | SQLite |
| Model provider | Amazon Bedrock (`LLM_PROVIDER=bedrock`, enforced) | `mock` (offline, deterministic) or `anthropic_dev` (API testing only) |
| Sign-in | Azure AD / Entra ID OIDC (`mozilla-django-oidc`) | Django username/password |
| Mail + calendar | Microsoft Graph (application permissions) | simulated (`scripts/simulate_email_ingestion.py`) |
| Secrets | Environment, injected from a secrets manager | `.env` |

## Code layout

```
config/            settings (base / development / testing / production), urls, celery
apps/
  authentication/  custom User, Office + OfficeStaff, OIDC backend, MFA,
                   EncryptedCharField, security middleware, dev-only guards
  email_processing/
    reception.py   Graph message -> immutable RawMessage (+ AttachmentBlob)
    channels/      .ics invites, forwarded mail, attached documents
    funnel/        deterministic stages 1-4 + rate gate, FilterLog per stage
    llm_providers/ provider factory: bedrock, mock, anthropic_dev
    postprocess.py validated candidates -> draft events / change suggestions
    tasks/         Celery: reception sweep, pipeline, rescoring
  contacts/        normalized contacts + organizations, blind-indexed PII
  event_management/events, series, approvals, calendar, exports (.docx), floor schedule
  api/             DRF serializers, services, viewsets
templates/ static/ tests/ scripts/ (demo + simulation tools, DEBUG only)
```

## Email pipeline

```
Outlook shared mailbox
   │  Graph sweep every INGEST_SWEEP_MINUTES (webhook optional)
   ▼
Reception ── RawMessage written first (audit floor, idempotent by Graph id)
   ▼
Funnel (no model call)
   1 headers / authentication (DMARC failures escalate)
   2 sender reputation (INTERNAL_EMAIL_DOMAINS seed the allowlist)
   3 dedup against existing threads/events
   4 content anchors (dates, invitations, .ics)
   + rate gate per sender / mailbox
   │  outcome: DIVERT · ESCALATE · EXTRACT
   ▼
Extraction ── ONE structured call to the configured provider; output is
              schema-validated into an ExtractionCandidate (data only)
   ▼
Post-processing (deterministic)
   new event        -> draft Event (requires_human_review)
   possible dup     -> draft Event flagged duplicate_of
   recurring        -> draft first occurrence + pending EventSeries
   reschedule/cancel-> EventChangeSuggestion rows on the matched event
   unmatched change -> triage
   ▼
Human review: Inbox · Triage · Diverted mail
```

Nothing reaches the calendar, and no email is sent, without a staff action.
Approval routing (`EventApproval`) can require several stages of sign-off.

## Security model (summary)

- **Untrusted input.** Inbound email is attacker-controlled text and is
  expected to contain prompt-injection attempts. The model can only return
  data into a candidate row; humans approve every outcome.
- **PII at rest.** Contact fields use `EncryptedCharField`
  (`FIELD_ENCRYPTION_KEY`); exact-match lookups use an HMAC blind index
  (`CONTACT_BLIND_INDEX_KEY`). Production refuses to start if either key, or
  `SECRET_KEY`, is unset or a public development default.
- **Audit.** Raw messages are immutable; every funnel stage writes a
  `FilterLog`; event field changes write `EventChangeHistory`.
- **Transport/session.** HSTS, secure + SameSite=Strict cookies, CSP,
  rate limiting, account lockout.
- **Model provider.** `production.py` hard-fails on any provider other than
  Bedrock, so email text stays inside the office's own AWS account.
- **Graph scope.** The app uses application permissions; restrict it to the
  shared scheduling mailbox (Exchange Online application access policy)
  rather than the whole tenant.

## Deployment shape

```
users ──► load balancer ──► web (Django, ECS Fargate)
                              │        ▲
                              ▼        │
                      worker + beat (Celery, same image)
                              │
       private subnets: PostgreSQL · Redis · VPC endpoints
       (Bedrock, Secrets Manager, ECR, logs)  ──► Microsoft Graph / Entra ID
```

Public House data feeds (docs.house.gov, clerk.house.gov) are optional and
need outbound access.

## Configuration

See `.env.example`. The environments are:

| Setting | Production | Dev (offline) | Dev (API test) |
| --- | --- | --- | --- |
| `DJANGO_SETTINGS_MODULE` | `config.settings.production` | `config.settings.development` | `config.settings.development` |
| `LLM_PROVIDER` | `bedrock` | `mock` | `anthropic_dev` |
| `USE_SSO` | `True` | `False` | `False` |
| `DEBUG` | `False` | `True` | `True` |
| Database | PostgreSQL | SQLite | SQLite |
