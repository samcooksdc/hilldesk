# Email Ingestion System — Build Plan (Phases 2–6)

> Companion to `EMAIL_INGESTION_IMPLEMENTATION_SPEC.md`. Maps the spec's build
> sequence (§12) onto concrete files, migrations, and decisions after a full
> codebase contract audit (July 2026). Phase numbering matches the spec.

---

## Status

| Phase | State | Branch |
|---|---|---|
| 1 — Reception spine | ✅ **Complete** (12/12 tests green) | `new-email-ingestion-system` |
| 2 — Funnel | ✅ **Complete** (35/35 tests green; migrations 0007–0008) | `new-email-ingestion-system` |
| 3 — Channels | ✅ **Complete** (17/17 tests green; spike command built, awaiting tenant run) | `new-email-ingestion-system` |
| 4 — Single extraction call | ✅ **Complete** (82/82 ingestion tests green; migration 0009) | `new-email-ingestion-system` |
| 5 — Post-processing + materialization | ✅ **Complete** (105/105 ingestion tests green; migrations `email_processing.0010`, `event_management.0028`) | `new-email-ingestion-system` |
| 6 — Hardening loop | ✅ **Complete** (112/112 ingestion tests green) | `new-email-ingestion-system` |

**Phase 1 delivered:** `RawMessage` (immutable, encrypted sender/body, blind-index
`sender_key`), `AttachmentBlob` (≤ `ATTACHMENT_STORE_MAX_BYTES` inline),
`SubscriptionState` (webhook + sweep bookkeeping in one row); migration `0006`;
Graph client delta/attachment/subscription methods; `reception.ingest_message`
(idempotent, calendar detection); `tasks/reception.py` (`ingestion_sweep` →
`sweep_mailbox` with delta + window fallback + reconciliation-gap logging,
`fetch_message`, `manage_subscriptions`); `tasks/pipeline.py` `run_pipeline`
stub; webhook at `/api/webhooks/graph/` (handshake echo, clientState gate);
beat entries `ingestion-sweep` + `manage-subscriptions` replacing
`process-emails-hourly`; old per-user polling tasks deleted; `EmailProcessing`
gained nullable `raw_message` OneToOne + `escalated` status; §11 settings block;
`tests/test_email_reception.py`.

**Phase 2 delivered:** `FilterLog` (with indexed `dedup_hash`) +
`SenderReputation` (encrypted `sender_email` + blind `sender_key` XOR plaintext
`domain`; migration 0007) and the allowlist seed (migration 0008: internal
domains + `ContactEmailAddress.email_key` copied — note the blind index lives
on the child model, not `Contact`) with re-runnable `seed_sender_reputation`
command; `funnel/` package (stages 1–4, `anchors.py`, `rate_gate.py`,
`engine.py` orchestration with channel/allowlist bypasses); `thread_text.py`
(quoted-history stripping, html→text, subject normalization); real
`run_pipeline` (divert = ledger-only, escalate = `EmailProcessing` `escalated`
with rate-gate burst folding, extract = `EmailProcessing` `pending`);
`email_processor.py` deleted (keywords absorbed into stage 4); divert-store
browse at `/email/diverted/` with promote action (app URLs re-enabled at root,
trimmed to pipeline surfaces only — legacy verification views stay dark);
`tests/test_email_funnel.py` + `tests/test_dedup_vs_reschedule.py`.
Gotcha for later phases: `EmailProcessing.full_clean()` rejects EMPTY dicts for
`complete_email_data`/`extracted_data` — always populate both.

**Phase 3 delivered:** `channels/` package — `ics.py` (`icalendar` parsing →
§7-shaped candidate dicts, confidence 1.0; REQUEST/CANCEL/RRULE/RECURRENCE-ID
mapping; `substantial_body_prose` for the also-extract-body case),
`documents.py` (`harvest()` → `HarvestResult{texts, images, failures}` via
pypdf/python-docx; scan-only PDFs + images collected as b64 for Phase-4 vision
blocks; unstored/corrupt → failures), `forwards.py` (`detect()` →
`ForwardInfo`; Outlook + Gmail markers, original-sender recovery); funnel
integration: `FunnelContext.reputation_sender` — stage 2 judges the forwarded
ORIGINAL sender (laundering test in `tests/test_email_channels.py`); deps
added to requirements.txt (icalendar/pypdf/python-docx/jsonschema);
`probe_graph_invites` management command (the §4.2 spike — **still needs a
run against the real tenant**; result decides whether an `/events`
subscription resource is required). Candidate dicts stay in-memory until the
ExtractionCandidate model lands in Phase 4.

**Phase 4 delivered:** `llm_providers/schema.py` (§7 `CANDIDATE_SET_SCHEMA` +
`MessageBundle`/`RawModelOutput` + `validate_candidate_set` + shared forced-tool
material); `base.py` slimmed to `extract_candidates` + draft surface (draft
machinery untouched — `draft_generation_service` unaffected); `bedrock.py` one
`invoke_model` with `tools` + `tool_choice` (legacy boto3
`bedrock-2023-05-31` path per the production requirements; images/scan-PDFs as base64 blocks; NOTE:
newer Claude on Bedrock needs thinking disabled with forced tool_choice);
`anthropic_dev.py` same contract via SDK; `mock.py` rewritten — deterministic
candidates keyed off markers (`EVENT:` fan-out, cancel/reschedule/recur words,
`for N weeks`/`until` bounds); `ExtractionCandidate` model (migration 0009) +
admin; pipeline extraction step (ICS deterministic-first, model skipped unless
`substantial_body_prose`; harvest failures → escalate; schema-validate → ONE
repair retry via `bundle.repair_error` → escalate `malformed_model_output`;
candidates persisted, `EmailProcessing` → `processed`); **deleted**
`classification_service/extraction_service/llm_service/llm_client` + their 4
test files + 4 test management commands; `SmartExtractService` reimplemented on
`extract_candidates` over the event's primary `EventEmailLink` (dead
`populate_extracted_fields` removed); settings `BEDROCK_CLASSIFICATION_MODEL` +
`LLM_CLASSIFICATION_THRESHOLD` removed; demo scripts verified clean (no LLM
imports — untouched). `tests/test_email_extraction.py` incl. schema fuzz +
faked-boto3 Bedrock tests.

**Phase 5 delivered:** `EventSeries` (+ `Event.series`/`series_occurrence_date`/
`is_series_exception`; end-bound enforced in `clean()`; idempotent
`materialize_occurrences`, `regenerate_future` preserving exceptions,
`activate()` adopting a dateless draft as occurrence 1) +
`extend_series_horizon` monthly beat; `EventChangeSuggestion` gained nullable
`suggested_by`, `origin`, `source_candidate`; `matching.py` (ICS-UID > thread >
date±1 + difflib-over-window — **decision: pg_trgm skipped**, the date window
makes in-Python difflib sufficient and DB-agnostic; also excludes events
sourced from the same message so multi-event siblings don't self-match);
`postprocess.py` (cap collapse, enumerated fold w/ cadence detection, timezone
resolution, intent routing, `hilldesk_pipeline` system user because
`Event.created_by` is non-null); pipeline runs it after extraction;
`extracted_fields` built mechanically via `apps.contacts.extraction.
build_review_parties` + additive `meta` block (`NON_FIELD_KEYS` gained
`'meta'`); reputation feedback (review completion → approve++, `dismiss` +
`junk:true` → reject++ + `offer_block_sender`); API:
`GET /api/change-suggestions/` (grouped feed), `POST /api/series/<id>/activate/`,
`POST /api/reputation/block/`, `series_info` on EventSerializer; UI: third feed
merged in `inbox-redesign.js` (`_inboxType: 'change_request'`, violet accent,
diff rows, Apply/Reject wired to existing `/api/suggestions/<id>/review/`),
ingestion meta chips on review rows, recurrence confirm block in the detail
panel (`_describeRrule`, `_confirmSeries`); triage list at `/email/triage/`
(extract anyway / divert / open source) replacing the DELETED verification
views + templates; `tests/test_email_postprocess.py` (23 tests).

**Phase 6 delivered:** `tasks/rescoring.py` weekly beat (`rescore-diverted`) —
re-runs reputation + stage-4 scoring over content/reputation-diverted mail from
`RESCORE_WINDOW_DAYS`; promotions go through `run_pipeline(force_extract=True)`;
header-diverted machine mail and dedup diverts never re-enter; a
`rescore_checked` FilterLog marker prevents endless rescans. Reconciliation
metrics on the triage header: P1 banner on lapsed subscriptions, webhook-gap
count (sweep-sourced messages while webhooks are on), per-mailbox last-sweep
ages, sweep-only mode label. `tests/test_email_rescoring.py` (7 tests).

**Remaining open items (spec §14):** run `probe_graph_invites` against the real
tenant (decides if an `/events` subscription resource is needed); confirm
webhook endpoint reachability on the House network before flipping
`GRAPH_WEBHOOK_ENABLED`; set `SCHEDULING_MAILBOXES` + `INTERNAL_EMAIL_DOMAINS`
in prod env and re-run `seed_sender_reputation`; Bedrock KB semantic dedup and
the local classifier remain data-gated (Phase 7); revisit attachment volume /
S3 if real volume demands it.

Pre-existing failures (verified identical on a clean tree):
`tests/test_email_classification.py` (4F+1E — lives in
`classification_service.py`, deleted in Phase 4) and
`tests.test_dismiss_review` + `apps.event_management` (2F+35E — stale
`Event.objects.create` setUps predating this branch).

---

## Phase 2 — Funnel

**New models** (`apps/email_processing/models.py`, one migration):

- `FilterLog` — `raw_message` FK, `stage`
  (`0_scope | 1_headers | 2_reputation | 3_dedup | 4_content | rate_gate | extraction | postprocess`),
  `signals` JSON (actual header hits, token counts, score components — shaped as
  the future classifier feature vector), `score`, `outcome`
  (`pass | divert | escalate | extract`), `created_at`, plus an indexed
  **`dedup_hash`** column. *Decision:* the spec doesn't say where dedup hashes
  live; querying JSON within a time window is impractical, so stage 3 writes the
  hash onto its own FilterLog row and lookup is
  `filter(dedup_hash=h, created_at__gte=window)`. Never pruned.
- `SenderReputation` — `sender_key` (blind index, same HMAC/key-space as
  `apps.contacts.crypto`) **or** `domain` (row is one or the other), `list`
  (`allow | block | unknown`), `approve_count`, `reject_count`, `last_seen`,
  `added_by`, `notes`. **Seed data migration:** allowlist rows for (a) domains
  of `SCHEDULING_MAILBOXES` + a new `INTERNAL_EMAIL_DOMAINS` setting (internal
  domain is not derivable from any existing setting), (b) existing
  `Contact.email_key` values copied directly — no decryption needed, same blind
  index key space.

**New package** `apps/email_processing/funnel/` — one module per stage, each a
pure function `(RawMessage, Context) -> StageDecision(outcome, signals, score)`:

- `stage1_headers.py` — List-Unsubscribe/List-Id/Precedence/Auto-Submitted →
  divert; no-reply sender regexes → divert; SPF/DKIM/DMARC failure (parsed from
  `Authentication-Results`, already captured in `RawMessage.headers`) →
  **escalate** (never divert silently, never send to model).
- `stage2_reputation.py` — blind-index sender lookup, then domain. `block` →
  divert; `allow` → skip stages 3-scoring/4 entirely; `unknown` → proceed with
  pass-forward bias flag.
- `stage3_dedup.py` — message identity only: (a) `internet_message_id` already
  completed → divert duplicate; (b) normalized hash of (stripped new-content +
  sender + subject-minus-Re/Fwd) within `DEDUP_WINDOW_DAYS` → divert.
  Explicitly NOT thread-similarity.
- `stage4_content.py` — unknown-sender prose only. Absorbs the
  `EmailProcessor` keyword lists (then **delete `email_processor.py`**);
  scoring: strict date/time token density, anchor dictionary, scheduling
  keywords (cancel/reschedule/move/postpone also set action-intent hint),
  newsletter shape. Pass on any scheduling vocab/anchor even at zero strict
  dates; escalate over `DIGEST_TOKEN_THRESHOLD`.
- `anchors.py` — data-driven anchor list incl. legislative anchors ("after
  recess", "after the markup", "back in session", "district work period").
- `rate_gate.py` — evaluated before stage 4; counts `RawMessage.sender_key`
  rows in `RATE_GATE_WINDOW_MINUTES` (index exists from Phase 1) and
  mailbox-wide volume; burst → one escalated triage item, not N.
- **`thread_text.py` lands here, not Phase 3.** *Decision:* spec files it under
  §6.4 channels, but stage-3 dedup hashes on stripped new-content and the
  mandated `test_dedup_vs_reschedule` module lands in Phase 2 — it can't wait.
  Phase 3 extends it.

**Wiring:** `tasks/pipeline.py` `run_pipeline` becomes real: stages in order
with short-circuit; every stage writes FilterLog. Outcomes: `divert` →
RawMessage + FilterLog only (divert store is a query, not a table); `escalate`
→ `EmailProcessing(status='escalated', raw_message=...)`; `extract` →
`EmailProcessing(status='pending')` and stop (extraction arrives Phase 4).

**UI:** divert-store browse page under `email_processing`
(sender/subject/date/stage filters, "promote to extraction" action that
re-enqueues with a force flag).

**Tests:** per-stage header/body fixtures (newsletter, no-reply, DMARC-fail →
escalate, dateless-with-legislative-anchor → pass, digest → escalate);
allowlist-overrides-content; rate-gate window; **`tests/test_dedup_vs_reschedule.py`**
— short "move it to 3pm" reply quoting a long thread must pass; identical
redelivered message must divert.

---

## Phase 3 — Channels

**Spike first** (spec §4.2): management command probing how meeting invites
arrive for the subscribed mailbox (`meetingMessageType=meetingRequest` on
message resources vs needing an `/events` subscription). Requires real Graph
access — build the probe, run it against the office tenant, result may adjust
`ics.py`.

**New package** `apps/email_processing/channels/`:

- `ics.py` — `icalendar` parsing of text/calendar parts, `.ics` attachments
  (AttachmentBlob payloads), Graph invites → deterministic candidates,
  confidence 1.0, no model call. METHOD:REQUEST → NEW_EVENT (or
  RECURRING_EVENT when VEVENT has RRULE → `recurrence_rule`); METHOD:CANCEL →
  CANCELLATION; RECURRENCE-ID → RESCHEDULE of one occurrence; VEVENT UID into
  provenance for Phase 5 matching. Skips stage 4 + Bedrock unless body prose >
  `ICS_BODY_PROSE_THRESHOLD` (then body extraction runs additionally).
- `documents.py` — PDF/DOCX/image attachments force pass-forward past stage 4.
  `pypdf` / `python-docx` text harvest; images + scan-only PDFs flagged for
  vision content blocks in the Phase-4 bundle; unparseable/oversized →
  escalate with reason.
- `forwards.py` — forward markers (`Fwd:`, `---------- Forwarded message`,
  Outlook `From:/Sent:/To:/Subject:` blocks); extract quoted original + original
  sender; **stage 2 evaluates the original sender**, not the forwarder;
  provenance channel `forward-quoted`; forwarded content intentionally allowed
  to re-enter dedup.
- `thread_text.py` — full reply-marker / `On … wrote:` / Outlook-block
  stripping repertoire (dedup already consumes it from Phase 2).

**Deps** (`requirements.txt`): `icalendar`, `pypdf`, `python-docx` — pure
Python, no egress.

**Tests:** real `.ics` fixtures (REQUEST / CANCEL / RRULE / RECURRENCE-ID),
Outlook forward block fixture, PDF invitation fixture.

---

## Phase 4 — Single extraction call

**Provider swap** (`apps/email_processing/llm_providers/`):

- `schema.py` — the §7 JSON Schema, single source of truth, validated with
  `jsonschema` on every response; `MessageBundle` dataclass (subject,
  new-content, thread context, harvested attachment text, image blocks, sender
  display info, received date, office timezone).
- `base.py` — remove `classify_email` / `extract_information` + their prompt
  builders; add abstract `extract_candidates(bundle) -> RawModelOutput`.
  **`generate_email_draft` machinery stays** — `draft_generation_service.py`
  calls providers directly via `get_llm_provider()` and survives untouched
  (`email_response_service.py` has no LLM imports at all).
- `bedrock.py` — one `invoke_model` call on `BEDROCK_EXTRACTION_MODEL` with a
  **forced tool-use** definition (schema as the tool's input_schema); image
  content blocks for vision/OCR inside the same call; one repair retry on
  malformed output; still malformed → escalate, never act on free text.
- `mock.py` — rewritten: deterministic candidate sets keyed off content markers
  (multi-event, recurrence, cancellation paths exercisable offline).
- `anthropic_dev.py` — same schema via the Anthropic SDK.

**New model:** `ExtractionCandidate` (all §3.1 fields; `matched_event` /
`created_event` / `change_suggestion` FKs nullable — filled in Phase 5).
Admin-registered so the pipeline is reviewable before Phase 5.

**Deletions and blast radius** (audited caller map):

- Delete `classification_service.py`, `extraction_service.py`,
  `llm_service.py`, `llm_client.py`.
- Delete their test suites (`tests/test_email_classification.py`,
  `test_information_extraction.py`, `test_llm_integration.py`, most of
  `test_llm_providers.py`) and the 4 `test_*` management commands
  (`test_email_classification`, `test_information_extraction`,
  `test_llm_integration`, `test_email_pipeline`). Replaced by new
  provider/schema/pipeline tests incl. **schema fuzz** (malformed /
  injection-shaped outputs must escalate, never reach an Event).
- ⚠️ **SmartExtract:** `SmartExtractAPIView` (`apps/api/views.py:2199`) →
  `SmartExtractService` (`apps/api/services.py:32`) imports
  `extraction_service`. Its `generate_suggestions()` calls a method that does
  not exist — the GET path is already dead. *Decision:* reimplement
  `SmartExtractService` as a thin adapter over `extract_candidates()` so the
  wired endpoints keep working. (Alternative: retire SmartExtract entirely —
  product call.)
- Remove settings `BEDROCK_CLASSIFICATION_MODEL`, `LLM_CLASSIFICATION_THRESHOLD`.
- Demo scripts (`populate_office_demo_info.py`, `create_demo_office.py`) write
  model rows directly, no LLM calls — only light touch-ups where they fabricate
  `extracted_fields`; re-run after edits.
- `requirements.txt`: add `jsonschema`.

Pipeline ends at candidate rows in this phase (reviewable via admin).

---

## Phase 5 — Post-processing + materialization (largest phase)

**Recurrence** (`apps/event_management`, one migration):

- `EventSeries` — `rrule` (validated with `dateutil.rrule`), `dtstart_date`,
  `dtstart_time`, `timezone`, `until_date`/`count` (**one required** to
  activate — model-level enforcement of "no open-ended series"),
  `title_template`, `source_candidate` FK, `created_by`, `is_active`,
  `materialized_through`.
- `Event` gains `series` FK (nullable), `series_occurrence_date`,
  `is_series_exception`.
- Occurrences materialize as ordinary Event rows through
  `SERIES_HORIZON_DAYS` (default 400); monthly `extend_series_horizon` beat
  task. Calendar/schedule/conflict views need zero changes.

**Post-processing** (`apps/email_processing/postprocess.py` + `matching.py`,
deterministic, same pipeline task after schema validation):

1. Cap check (`CANDIDATE_CAP`) → collapse to one escalated triage item.
2. RRULE without UNTIL/COUNT → `recurrence_needs_end=True`.
3. Enumerated-recurrence fold (shared title + attendees + cadence → one
   RECURRING_EVENT with synthesized RRULE, originals in provenance).
4. Matching: ICS-UID exact match wins outright > thread match (existing
   `EventThreadLink` on `conversation_id`) strong prior > date ±1 day + fuzzy
   title (`pg_trgm` on Postgres via guarded extension migration; `difflib`
   fallback on SQLite) + same org/contact. Bedrock KB retrieval stays
   feature-flagged off (`BEDROCK_KB_ID`).
5. Intent routing (below). 6. Timezone resolution (proposed zone vs office
   default; basis stored; ambiguity flags the field; no zoneless time reaches
   an Event).

**Materialization:**

- `NEW_EVENT` / `UNCERTAIN` / unmatched `RECURRING_EVENT` groundwork → draft
  `Event` (`requires_human_review=True`), `extracted_fields` v2 built
  mechanically from candidate contacts/orgs (shape per
  `apps/contacts/extraction.py` builder: cards with `ref`, `status`,
  `confidence`, `fields.{name}.{value, source}`, `resolution`), plus new
  top-level **`meta`** block (intent, confidence, verbatim date strings,
  timezone basis, channel). ⚠️ **`FieldReviewService.NON_FIELD_KEYS`**
  (`apps/api/services.py:559`) **must gain `'meta'`** or the review service
  treats it as a reviewable scalar. Attach via `EventEmailLink` —
  `origin='ai_auto'` already exists (`event_management/models.py:1909`), no
  migration needed — and `EventThreadLink`. Multi-event → multiple Events; the
  inbox lists them today with no changes.
- Matched `NEW_EVENT` → still a draft Event with `meta.duplicate_of` so the
  card shows "possible duplicate of ⟨event⟩".
- `RECURRING_EVENT` → draft Event for first occurrence + pending inactive
  `EventSeries`; approval activates + materializes.
- `RESCHEDULE` / `CANCELLATION` with match → `EventChangeSuggestion` rows.
  ⚠️ Two audited constraints requiring a migration: (a) `suggested_by` is a
  **non-null** User FK (`models.py:987`) — needs `null=True` for system-origin
  suggestions; (b) the model is **one field per row**, so a reschedule
  (date + time) materializes as N rows sharing new fields
  `origin='email_ingestion'` + `source_candidate` FK, grouped per-candidate in
  the feed. Approve wires to existing `approve()` / bulk-approve machinery
  (`models.py:1042`); cancellation = one `status→cancelled` row, which fits.
  This resolves the spec's "decide during phase 5" item; fall back to a
  dedicated `CandidateChangeRequest` model only if this strains in practice.
  Without a match → escalate to triage ("cancellation of unknown event").

**UI (kept thin; conventions audited):**

- **Third inbox feed** — new DRF endpoint
  `GET /api/change-suggestions/?origin=email_ingestion&status=pending`
  (grouped by candidate), merged in `inbox-redesign.js` (feeds merge at
  ~lines 560–695; tag `_inboxType: 'change_request'` alongside
  `'human_review'` / `'needs_approval'`). Card: intent badge
  (Reschedule/Cancellation), matched event, field-level old→proposed diff with
  verbatim source string; approve/reject → existing suggestion endpoints. New
  `.change-request-card` CSS following the `.human-review-card` pattern
  (`inbox-redesign.css:238`) with its own accent (the gold border is reserved
  for needs-review by design).
- **`meta` rendering** in `event-review-cards.js` — intent/confidence badges,
  duplicate-of banner, channel icon, verbatim-date tooltip. Additive only.
- **Recurrence confirm block** in `event-editing-modal-v2.js` (no recurrence
  UI exists today): plain-language rule summary, editable, end bound required
  before Accept enables.
- **Triage list** — new lightweight page replacing the `verification/` URLs
  (`email_processing/urls.py:14-19`) and templates
  (`verification_list.html`, `verify_email.html`); shows escalated items
  (digest suspects, rate-gate bursts, auth failures, unmatched cancellations,
  malformed extractions) with *extract anyway / divert / open source* actions.
- **Reputation touchpoints** — accept → `approve_count++` silently;
  junk-dismiss → "block this sender?" offer; settings section for allow/block
  list management.

**Tests:** end-to-end on mock provider (one email → multi-candidate fan-out →
N inbox Events; recurring → one series candidate; cancellation → suggestion on
matched event); series horizon / exception detachment / regenerate-on-rule-change
/ end-bound enforcement; matching with SQLite-fallback markers.

---

## Phase 6 — Hardening loop

- `tasks/rescoring.py` weekly beat — re-run stage 4 (current anchors +
  reputation) over diverted RawMessages from `RESCORE_WINDOW_DAYS`; promote
  pass-forwards tagged low-confidence.
- Reconciliation metrics — surface Phase 1's gap warnings + subscription
  health on the triage page header; P1 banner on subscription lapse.
- Rate-gate / threshold tuning against real volume.

---

## Cross-cutting decisions (locked during planning)

| Decision | Rationale |
|---|---|
| `thread_text.py` lands in Phase 2, not 3 | Stage-3 dedup and the mandated `test_dedup_vs_reschedule` module depend on it |
| Dedup hashes on an indexed `FilterLog.dedup_hash` column | Time-windowed hash lookup can't live in JSON; keeps FilterLog the single funnel ledger |
| SmartExtract reimplemented as adapter over `extract_candidates()` | Endpoints are UI-wired; GET path already broken, so behavior only improves |
| `EventChangeSuggestion` gains `origin` + `source_candidate` + nullable `suggested_by`; multi-field change = N grouped rows | Reuses the entire existing approve/audit machinery, per spec preference |
| New `INTERNAL_EMAIL_DOMAINS` setting seeds the allowlist | Internal domain isn't derivable from any existing setting |
| `FieldReviewService.NON_FIELD_KEYS` gains `'meta'` | Otherwise the new meta block is treated as a reviewable scalar field |

## Sizing

Phase 2 ≈ Phase 1. Phase 3 smaller (spike gates ICS details). Phase 4 medium
with a wide deletion blast radius. Phase 5 largest (2 apps, 3 JS files,
~4 migrations). Phase 6 small.
