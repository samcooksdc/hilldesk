# Deploying HillDesk

This guide describes a generic production deployment on AWS. It doesn't
describe any House network. **House offices must get approval from the
House's IT security approvers before deploying anything that reads House
mail.** Start that conversation first; they decide where and how it runs.

Read [security-model.md](security-model.md), especially *Known gaps*,
before you deploy.

**Run one deployment per office.** HillDesk doesn't isolate data between
offices inside a single instance; roles control visibility within an office.

## Shape

| Piece | Suggested service | Notes |
| --- | --- | --- |
| Web | ECS Fargate task, `Dockerfile` default command (gunicorn on :8000) | Behind a load balancer that terminates TLS and sets `X-Forwarded-Proto`. Health check path: `/healthz/` (works over HTTP with the task IP as Host). |
| Worker | Same image, command `celery -A config worker -l info` | Runs ingestion, extraction and calendar sync |
| Scheduler | Same image, command `celery -A config beat -l info` | **Exactly one** instance |
| Database | RDS PostgreSQL, encrypted, TLS | `DB_SSL_ROOT_CERT` points at the RDS CA bundle |
| Broker and cache | ElastiCache Redis with TLS (`rediss://`) | |
| Model provider | Amazon Bedrock in the same account | Enable the model in `BEDROCK_EXTRACTION_MODEL` first |
| Secrets | Secrets Manager, injected as environment variables | See `.env.example` |
| Images | Private ECR repository | Build from a tagged release |

With no public internet egress you need VPC endpoints for Bedrock Runtime,
Secrets Manager, ECR (api + dkr), S3 (gateway, for ECR layers) and CloudWatch
Logs. Microsoft Graph and Entra ID sign-in also need a network path from the
tasks.

## Steps

1. **Build and push** the image: `docker build -t hilldesk:<version> .`
   Then push it to ECR.
2. **Create secrets.** Generate `SECRET_KEY`, `FIELD_ENCRYPTION_KEY` and
   `CONTACT_BLIND_INDEX_KEY` with
   `python -c "import secrets; print(secrets.token_urlsafe(50))"`.
   **Back up `FIELD_ENCRYPTION_KEY`.** Losing it makes the encrypted contact
   data unrecoverable.
3. **Register the apps** in Entra ID, one for sign-in (OIDC) and one for
   Graph. See [graph-setup.md](graph-setup.md).
4. **Configure** every *required* variable in `.env.example` on all three
   task definitions. Production refuses to start if a key is missing or is a
   development default, or if `LLM_PROVIDER` isn't `bedrock`.
5. **Migrate** with a one-off task: `python manage.py migrate`.
6. **Start** web, worker and one beat.
7. **Check:** `python manage.py check --deploy` should report no errors.
8. **Set up the office:** see [office-setup.md](office-setup.md).

## Operations

- **Logs:** JSON lines on stdout (CloudWatch picks them up on Fargate). Set
  `LOG_DIR` to write rotating files instead on hosts without a collector.
- **Static files** are served by WhiteNoise from the image; no S3 bucket is
  needed.
- **Backups:** rely on RDS automated backups and snapshots, plus your
  retention policy (the app doesn't delete old data yet).
- **Upgrades:** pull the new release, build, run `migrate`, then roll the
  tasks.
- **Attachment uploads** fail closed until you connect a malware scanner
  (`apps/event_management/services/attachment_scan_service.py`).
- **Outbound calls from browsers:** fonts are self-hosted. The dashboard
  embeds the House Clerk's YouTube live stream; remove that card if your
  network blocks YouTube.
