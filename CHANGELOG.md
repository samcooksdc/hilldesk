# Changelog

All notable changes are recorded here. The project follows
[Semantic Versioning](https://semver.org/).

## [0.1.0] - Unreleased

First public release under the Apache-2.0 license.

### Added
- Email ingestion from Outlook via Microsoft Graph, with a deterministic
  four-stage funnel (headers and authentication, sender reputation, dedup,
  content) and a per-sender rate gate
- One structured AI extraction per message (Amazon Bedrock in production; an
  offline mock provider for development)
- Human review: inbox drafts, triage, diverted mail, multi-stage approval
  routing, change and cancellation suggestions, and recurring series
- Calendar views, Outlook calendar sync, `.docx` briefings and exports, email
  reply templates, and the House floor schedule
- `bootstrap_demo` command and a Docker Compose demo with a fictional office
- `/healthz/` probe for load balancers and orchestrators (database check,
  no auth, no data) and a Docker `HEALTHCHECK`
- Production container (gunicorn, WhiteNoise), CI, CodeQL and Dependabot

### Security
- Production refuses to start without real `SECRET_KEY`,
  `FIELD_ENCRYPTION_KEY` and `CONTACT_BLIND_INDEX_KEY`, or with any AI
  provider other than Bedrock
- Email-derived data embedded in pages is escaped against `</script>`
  breakout, and calendar descriptions are HTML-escaped
- Microsoft Graph calls have timeouts
- Demo and seed tools refuse to run unless `DEBUG=True`
- The Settings "DEMO" tab and its reset endpoint exist only with `DEBUG=True`
  (the reset wipes every office, user and event)
- Event detail, create, edit and delete pages, the dashboard, the calendar
  sidebar and the editing interface now apply the same role scope and
  edit/create/delete permissions as the events API. Deleting from these
  pages is a soft delete.
- Removed unscoped or unauthenticated leftovers: a test editing route, a
  "simple schedule" test page, and three AJAX helpers (event detail,
  quick-update, quick-create) that needed no sign-in

### Fixed
- Outlook calendar sync, email reply templates, CSV export, event
  quick-create, single-event archive and unarchive, approval-routing removal,
  and event detail pages, all of which crashed on fields removed in an
  earlier refactor
- Calendar sync no longer makes a redundant second Graph call per save
- Encrypted fields no longer generate a new migration on every
  `makemigrations` run
- Search, filter stats, suggestions and CSV export now honor role-based
  event visibility (they previously returned every event) and no longer
  crash on removed fields
- Email templates without placeholders can be saved
- `update_fields` accepts only real, editable event fields
- Password reset tokens honor `PASSWORD_RESET_TIMEOUT` and are single-use
  (they stop working once the password changes or the user signs in)
- The global "/" quick search no longer shows AI drafts awaiting review,
  dismissed false positives, or contacts and organizations known only from
  such drafts
- Production logs go to stdout as JSON by default (`LOG_DIR` for files)
- Fonts are self-hosted; staff browsers no longer call Google Fonts
- Deleted (archived) events no longer appear in the dashboard agenda and
  weekly count
- The calendar computes "today" in office-local time, not UTC

### Removed
- Legacy archive and retention pages (unreachable from the UI, and built on
  removed fields). Archived ("deleted") events are managed in Settings ->
  Deleted events.
- Unrouted metadata pages and the unused `event_views.py` and `settings.html`
- Unreferenced templates, scripts and stylesheets (including a debug script
  and an unused email viewer with a regex "sanitizer"), legacy redirect stubs,
  a shadowed `config/settings.py`, and about 170 unused imports and variables
