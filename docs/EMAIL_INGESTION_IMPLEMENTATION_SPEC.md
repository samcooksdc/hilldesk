# Email Ingestion System — Implementation Spec

> Companion to the design specification (reception → funnel → single extraction call → post-processing → review handoff).
> This document maps that design onto the existing HillDesk codebase: what is built, what is replaced, what is net-new.
> Decisions locked with product owner (July 2026): **replace** the old classify→extract pipeline; **new `ExtractionCandidate` model** feeding the **existing inbox UI**; **full Event recurrence model**; **sweep-first reception** with webhook behind an env flag.

---

## 1. Integration Strategy (the one-paragraph version)

Ingestion lives in `apps/email_processing` (new modules; old services retired). Every received message is persisted as an immutable `RawMessage` before anything touches it. A deterministic funnel (header signals → sender reputation → dedup → content heuristics → rate gate) decides extract / divert / escalate, logging every decision to `FilterLog`. Messages that pass get **one** Bedrock call via a new `extract_candidates()` provider method returning a strict-schema array of typed candidates. Post-processing (cap, recurrence completeness, enumerated fold, event matching, intent routing) turns candidates into review surfaces the **current inbox already renders**: `NEW_EVENT`-family candidates materialize as draft `Event`s with `requires_human_review=True` and `extracted_fields` populated (multi-event fan-out = multiple Events — the inbox handles this today with zero listing changes); `RESCHEDULE`/`CANCELLATION` candidates materialize as `EventChangeSuggestion`s against the matched event, surfaced in the inbox via a third feed. Recurrence is a real `EventSeries` model whose occurrences are materialized as ordinary `Event` rows, so calendar/schedule views work unmodified.

---

## 2. What Is Removed / Replaced

| Existing | Fate | Replaced by |
|---|---|---|
| `apps/email_processing/classification_service.py` | **Delete** | Funnel stages 1–4 (deterministic) + intent field in the single extraction call |
| `apps/email_processing/extraction_service.py` | **Delete** | Single structured call + `schema.py` validation + post-processing |
| `apps/email_processing/llm_service.py` | **Delete** | `pipeline.py` orchestration |
| `apps/email_processing/llm_client.py` (legacy wrapper) | **Delete** | Providers called directly through `get_llm_provider()` |
| `BaseLLMProvider.classify_email()` / `.extract_information()` | **Remove from interface** | `extract_candidates(bundle) -> CandidateSet` (all providers reimplement) |
| `email_processor.py` `_is_potential_scheduling_request()` heuristics | **Absorb** | Funnel Stage 4 (`funnel/stage4_content.py`), extended with the anchor dictionary |
| `email_processor.py` Celery tasks (`process_email_for_scheduling`, `process_new_emails_for_user`, `process_unread_emails_for_user`, `periodic_email_processing`) | **Delete** | `tasks/reception.py` (sweep, fetch, webhook fan-in) + `tasks/pipeline.py` (funnel/extract) |
| Beat entry `process-emails-hourly` (per-user loop) | **Replace** | `ingestion-sweep` every `INGEST_SWEEP_MINUTES` over `SCHEDULING_MAILBOXES` only |
| `views.py` verification views (`email_verification_list`, `verify_email`, …) | **Retire** after triage/divert UIs land; inbox is the review surface | Triage list + divert-store browse (§10) |
| `EmailProcessing` model | **Keep** (UI contract: `EventEmailLink`, `attached_emails_data`, `EmailThread` all hang off it) | Gains `raw_message` FK; created by the pipeline only for messages that reach extraction/escalation |

`graph_client.py`, the provider factory, `EmailThread`, `EventEmailLink`/`EventThreadLink`, and the entire inbox/review API surface (`FieldReviewService`, `review-contact`, `accept-all`, `dismiss`) survive.

---

## 3. Data Models

### 3.1 New — `apps/email_processing/models.py` (ingestion-owned)

**`RawMessage`** — the audit floor. Written at reception, before any processing. Immutable (no update paths; enforced in `save()`).
- `graph_message_id` (unique, indexed), `internet_message_id` (indexed — stable across mailboxes, used by dedup), `conversation_id` (indexed)
- `mailbox` (which subscribed mailbox), `received_at`, `fetched_at`, `source` (`webhook | sweep | manual`)
- `sender`, `sender_name` (encrypted; blind index on sender for reputation/rate-gate lookups, reusing the `CONTACT_BLIND_INDEX_KEY` pattern)
- `subject`, `headers` (JSON — full header map incl. auth results, List-*, Auto-Submitted), `body_text`, `body_html` (encrypted)
- `attachments` (JSON metadata: name, content_type, size, is_inline) + `AttachmentBlob` child rows (payload `BinaryField`, ≤ `ATTACHMENT_STORE_MAX_BYTES` default 10 MB; larger = metadata only, re-fetched from Graph on demand)
- `has_calendar_part` (bool, set at reception from MIME inspection)

**`FilterLog`** — one row per message per pipeline run.
- `raw_message` FK, `stage` (`0_scope | 1_headers | 2_reputation | 3_dedup | 4_content | rate_gate | extraction | postprocess`), `signals` (JSON: the actual header hits, token counts, score components), `score`, `outcome` (`pass | divert | escalate | extract`), `created_at`
- This is the classifier-training dataset and the false-negative forensics tool. Never pruned.

**`SenderReputation`**
- `sender_email` (blind-indexed) or `domain` (row is one or the other), `list` (`allow | block | unknown`), `approve_count`, `reject_count`, `last_seen`, `added_by`, `notes`
- Written by: reviewer actions (accept → approve_count++, junk-mark → offer blocklist), staff allowlist management, and auto-allowlist of internal domain + existing Contacts' emails (seed migration).

**`SubscriptionState`**
- `subscription_id`, `resource` (mailbox/folder path), `expires_at`, `last_renewed_at`, `last_renewal_error`, `last_reconciled_at`, `status` (`active | lapsed | disabled`)
- One row per Graph subscription; also carries per-mailbox sweep bookkeeping (`delta_token`, `last_sweep_at`) so sweep state lives here even when webhooks are off.

**`ExtractionCandidate`** — the unit handed downstream (Principle 5).
- `raw_message` FK, `email_processing` FK (the pipeline-visible message record), `thread` FK (nullable)
- `intent` (`NEW_EVENT | RECURRING_EVENT | RESCHEDULE | CANCELLATION | UNCERTAIN`) — `NON_EVENT` never creates a candidate; it's a divert outcome
- `payload` (JSON — validated against the extraction schema §7: event fields, contacts[], organizations[], each value with source span + verbatim string)
- `provenance` (JSON — source channel `body | ics | attachment:<name> | forward-quoted`, span offsets, verbatim date/time strings, proposed timezone + resolution basis)
- `confidence` (overall), `recurrence_rule` (RFC-5545 RRULE string, nullable), `recurrence_needs_end` (bool)
- `matched_event` FK (nullable — set by post-processing match), `match_basis` (JSON: how it matched)
- `status` (`pending_review | materialized | escalated | rejected | superseded`), `created_event` FK (nullable), `change_suggestion` FK (nullable)
- One email → N candidate rows. The candidate is never shown raw to reviewers; it materializes into the review surfaces below.

### 3.2 Changed — `apps/email_processing`
- `EmailProcessing`: add `raw_message` OneToOne FK (nullable for legacy rows); add status choice `escalated`. Existing rows untouched; new pipeline always creates the `RawMessage` first, then `EmailProcessing` only for extract/escalate outcomes. Diverted mail exists **only** as `RawMessage` + `FilterLog` (the low-priority store is a query, not a table).

### 3.3 New — `apps/event_management` (recurrence, per locked decision)

**`EventSeries`**
- `rrule` (RFC-5545 string — parsed/validated with `dateutil.rrule`), `dtstart_date`, `dtstart_time`, `timezone`, `until_date` / `count` (**one required** — enforcement of "no open-ended series": a series cannot activate without a bound; the review UI forces the reviewer to set it, per design §7)
- `title_template`, `source_candidate` FK, `created_by`, `is_active`
- `materialized_through` (date — occurrence-generation horizon)

**`Event` additions**
- `series` FK (nullable), `series_occurrence_date` (the RRULE instance this row represents), `is_series_exception` (bool — detached/edited single occurrence)

**Materialization model:** occurrences are real `Event` rows generated through a rolling horizon (`SERIES_HORIZON_DAYS`, default 400), extended by a monthly beat task. Consequences, all intentional: calendar/schedule/conflict views need **zero changes**; single-occurrence edits are ordinary event edits (flag `is_series_exception`); cancel-one is an ordinary status change; series-level edit regenerates future non-exception occurrences. Series UI affordances (edit-series vs edit-occurrence prompt, series badge) are the only view-layer work.

---

## 4. Reception Layer

New module: `apps/email_processing/reception.py` + `tasks/reception.py`.

### 4.1 Sweep (primary, always-on — the §2.3 reconciliation guard promoted to the front door)
- Beat task `ingestion_sweep` every `INGEST_SWEEP_MINUTES` (default 5) per mailbox in `SCHEDULING_MAILBOXES` (replaces the all-active-users loop; §2.1 scope narrowing).
- Uses Graph **delta queries** (`/mailFolders/{inbox}/messages/delta`), token persisted on `SubscriptionState`. Falls back to `receivedDateTime`-window listing if the delta token is invalidated.
- For each returned message id not present in `RawMessage.graph_message_id`: fetch full message + attachments (existing `MicrosoftGraphClient`, extended with `get_message_attachments()`, `create_subscription()`, `renew_subscription()`, `delta_messages()`), persist `RawMessage`, enqueue `run_pipeline(raw_message_id)`.
- If webhooks are enabled and the sweep finds a message the webhook missed, that **is** the silent-drop detection: log a reconciliation gap metric and warn. Sweep-only mode is simply "every message arrives via reconciliation."

### 4.2 Webhook (optional accelerator, `GRAPH_WEBHOOK_ENABLED`)
- `POST /api/webhooks/graph/` (`apps/api/urls.py` → `apps/email_processing/webhook_views.py`): handles the `validationToken` handshake (echo, 200, `text/plain`), validates `clientState` against `GRAPH_WEBHOOK_CLIENT_STATE`, returns 202 immediately, enqueues `fetch_message(resource_id)` per notification. CSRF-exempt, unauthenticated by necessity — clientState + payload-shape validation is the gate; no data is trusted from the notification beyond the resource id (the fetch re-reads from Graph).
- Subscription lifecycle beat task (`manage_subscriptions`, every 15 min): create missing subscriptions for `SCHEDULING_MAILBOXES`, renew any expiring within 24 h (Graph mail subscription max ≈ 7 days), on renewal failure mark `lapsed`, log at CRITICAL to `security_audit`, and surface a P1 banner flag (the sweep keeps mail flowing meanwhile — this is why sweep-first makes the lapse survivable).
- **Spike task (pre-build):** verify how Outlook meeting invites arrive for the subscribed mailbox — as `message` resources with `meetingMessageType=meetingRequest`, and whether `/events` subscriptions are additionally needed. Result decides whether §6.2's calendar path needs a second subscription resource. Do not assume.

---

## 5. The Funnel

New package: `apps/email_processing/funnel/` — one module per stage, each a pure function `(RawMessage, Context) -> StageDecision(outcome, signals, score)`; orchestrated by `run_pipeline` (Celery task in `tasks/pipeline.py`). Every stage writes `FilterLog`. Order and short-circuit semantics:

**Stage 1 — headers** (`stage1_headers.py`): `List-Unsubscribe` / `List-Id` / `Precedence: bulk|list` / `Auto-Submitted: auto-generated` → divert. Sender-pattern regexes (`no-reply@`, `donotreply@`, `notifications@`, `mailer-daemon`) → divert. SPF/DKIM/DMARC failure (parsed from `Authentication-Results` header) → **escalate** (security review, never divert silently, never send to the model).

**Stage 2 — reputation** (`stage2_reputation.py`): blind-index lookup on sender, then domain. `block` → divert. `allow` → **skip Stages 3-content-scoring and 4 entirely**; allowlist overrides content heuristics (a known stakeholder is never dropped by a threshold). `unknown` → proceed, and carry an `unknown_sender` flag that biases Stage 4 toward pass-forward.

**Stage 3 — dedup** (`stage3_dedup.py`): **message identity only** — (a) `internet_message_id` already in `RawMessage` with a completed pipeline run → divert as duplicate delivery; (b) normalized hash of (new-content body §6.4 + sender + subject-stripped-of-Re/Fwd) seen in last `DEDUP_WINDOW_DAYS` → divert. Explicitly **not** thread-similarity: a new message in an existing conversation is never a duplicate, no matter how much history it quotes. The quoted-history stripping (shared util `thread_text.py`) happens *before* hashing, so a short "move it to 3pm" reply hashes on "move it to 3pm", not on the quoted thread. **This interaction gets a dedicated test module** (`tests/test_dedup_vs_reschedule.py`) per the design's "most dangerous interaction" warning.

**Stage 4 — content heuristics** (`stage4_content.py`): applies only to unknown-sender prose mail with no calendar part and no document attachments (those channels bypass, §6). Scoring components: strict date/time token density; **anchor dictionary** (`funnel/anchors.py`, data-driven list: relative dates, "next Thursday", bare ordinals, and legislative anchors — "after recess", "after the markup", "back in session", "district work period"); scheduling keywords (existing list from `email_processor.py`, plus `cancel/reschedule/move/postpone` which also set an action-intent hint on the context); length/link-density newsletter shape. Combined score → `pass` (default on any scheduling vocab or anchor, even at zero strict dates), `divert` (near-zero everything + newsletter shape), or `escalate` (date-token count over `DIGEST_TOKEN_THRESHOLD` → probable digest/enumeration, human decides — the enumerated-recurrence fold in post-processing handles the case where extraction *does* run).

**Rate gate** (`rate_gate.py`, evaluated before Stage 4): count of `RawMessage` rows for this sender (blind index) in `RATE_GATE_WINDOW_MINUTES` over `RATE_GATE_SENDER_LIMIT`, or mailbox-wide volume over `RATE_GATE_MAILBOX_LIMIT` → escalate this and subsequent messages from that sender in the window (one triage item, not N).

**Stage 5 — local classifier: not built now.** The `FilterLog.signals` JSON is deliberately shaped as its future feature vector. Revisit once reviewer-labeled volume exists.

**Divert re-scoring** (`tasks/rescoring.py`, weekly beat): re-run Stage 4 (current anchors + current reputation) over diverted `RawMessage`s from the last `RESCORE_WINDOW_DAYS`; anything now scoring pass-forward is promoted into the pipeline tagged low-confidence. Divert-store safety must not depend on a human scanning it.

---

## 6. Channels (evaluated before/around the funnel)

`apps/email_processing/channels/`:

**6.1 Calendar objects** (`ics.py`) — checked immediately after reception, **before** body heuristics. `text/calendar` MIME parts, `.ics` attachments, and Graph `meetingMessageType` invites parse deterministically with the `icalendar` library into candidates — **no model call, confidence 1.0**. `METHOD:REQUEST` → `NEW_EVENT` (or `RECURRING_EVENT` if VEVENT carries an RRULE — mapped straight onto the candidate's `recurrence_rule`); `METHOD:CANCEL` → `CANCELLATION`; `RECURRENCE-ID` → `RESCHEDULE` of one occurrence. VEVENT UID stored in provenance for §8 matching. A message with a parsed calendar part skips Stage 4 and the Bedrock call entirely unless the body contains substantial non-boilerplate prose (heuristic: > `ICS_BODY_PROSE_THRESHOLD` chars after stripping "see attached"-class boilerplate), in which case body extraction runs *additionally*.

**6.2 Document attachments** (`documents.py`) — presence of PDF/DOCX/image attachments forces pass-forward past Stage 4 regardless of body score. Pre-extraction text harvest: `pypdf` for PDFs, `python-docx` for Word (both pure-Python, no egress). Image attachments and scan-only PDFs are passed to the single Bedrock call as vision content blocks (Claude on Bedrock accepts images — this keeps OCR inside the one call, zero extra services). Unparseable/oversized attachments → escalate with reason.

**6.3 Forwards** (`forwards.py`) — detect forward markers (`Fwd:` subject, `---------- Forwarded message`, Outlook `From:/Sent:/To:/Subject:` blocks). Extract the quoted-original block and the original sender. Reputation (Stage 2) evaluates the **original** sender, not the forwarding staffer — an internal allowlisted forwarder must not launder an unknown external request past scrutiny. Provenance records channel `forward-quoted`. Forward ≠ reply for dedup: the forwarded copy has a fresh `internet_message_id` and its stripped content is the quoted original, which is intentionally allowed to re-enter (a staffer forwarding something *is* a signal it matters).

**6.4 Threads** (`thread_text.py` + `EmailThread`) — quoted-history stripping (reply markers, `On … wrote:` blocks) yields the message's *new content* used by dedup hashing and sent to extraction (full thread available to the model as clearly-delimited context, but instructed to extract from new content). Post-processing checks for existing candidates on the same `conversation_id`: a confirming message ("sounds good, Tuesday works") matches and **updates/confirms** the earlier candidate rather than spawning a new one; the model's `UNCERTAIN` output plus a thread match is resolved in post-processing, not by a second call.

---

## 7. The Extraction Call

**Provider interface** (`llm_providers/base.py`): `classify_email`/`extract_information` removed; new abstract method:

```python
def extract_candidates(self, bundle: MessageBundle) -> RawModelOutput: ...
```

`MessageBundle` = subject, new-content text, thread context, harvested attachment text, image blocks, sender display info, received date (for relative-date resolution), office timezone. One call per message, `BEDROCK_EXTRACTION_MODEL`, invoked with a forced tool-use/structured-output definition. The classification model setting and Haiku call disappear (funnel replaced them).

**Schema** (`llm_providers/schema.py`, single source of truth — JSON Schema validated with `jsonschema` on every response):

```
{ candidates: [ {
    intent: NEW_EVENT|RECURRING_EVENT|RESCHEDULE|CANCELLATION|UNCERTAIN,
    confidence: 0..1,
    event: { title, type, format, start_date, start_time, end_date, end_time,
             location, description, legislative_topics[], participants[] },
    verbatim: { date_text, time_text },          # exact source strings (§6.2 provenance)
    timezone: { proposed, basis },               # never a zoneless time downstream
    recurrence: { rrule|null, has_end: bool },
    contacts: [ {name, email, phone, position, organization, source_span} ],   # extracted_fields v2 shape
    organizations: [ {name, location, email, phone, source_span} ],
    reschedule_target_hint / cancellation_target_hint: free-text description of which event,
    source_span: [start, end]                    # anchor within provided text
} ], notes: string }
```

The `contacts`/`organizations` arrays intentionally mirror the **existing `extracted_fields` schema_version 2** contract (`ref`, `fields.{name,email,…}.{value, source}`) so materialization is a mechanical mapping and the current review-card JS works unchanged.

**Defensive parsing (§6.4 trust boundary):** schema-validate; one repair retry on malformed output; still malformed → `escalate`, never act on free text. Multi-event = array length (post-processing counts it). Recurrence = a populated rule, never expanded instances. The provider has no tools and no write path — it returns data into a candidate row that only a human can act on.

**Mock provider** rewritten to return deterministic candidate sets keyed off content markers (so demo scripts and tests exercise multi-event, recurrence, cancellation paths offline). `anthropic_dev` reimplements the same schema for API-key testing. Demo scripts (`scripts/populate_office_demo_info.py` etc.) updated to seed via the new pipeline shapes where they touch extractions.

---

## 8. Post-Processing & Materialization (`postprocess.py`)

Deterministic, no model, runs in the same pipeline task after schema validation:

1. **Cap check** — `len(candidates) > CANDIDATE_CAP` (default 10) → collapse to one escalated "many events — review source" triage item.
2. **Recurrence completeness** — RRULE without UNTIL/COUNT → `recurrence_needs_end=True`; the series cannot be activated until the reviewer sets a bound (§3.3 enforces at the model level too).
3. **Enumerated-recurrence fold** — N candidates sharing normalized title + attendee set + detectable cadence across dates → fold into one `RECURRING_EVENT` candidate with a synthesized RRULE, originals recorded in provenance.
4. **Match against existing events** (`matching.py`) — cheap SQL first: date within ±1 day (or target-hint date) + fuzzy title (Postgres `pg_trgm` similarity; `difflib` fallback on SQLite) + same organization/contact; ICS UID exact match wins outright; thread match (existing `EventThreadLink` on this `conversation_id`) is a strong prior. Only if cheap matching is *inconclusive* (multiple mid-band scores) → optional Bedrock KB semantic retrieval (`BEDROCK_KB_ID`, feature-flagged off until the KB exists). Result → `matched_event` + `match_basis`.
5. **Intent routing / materialization:**
   - `NEW_EVENT`, `UNCERTAIN`, unmatched `RECURRING_EVENT` groundwork → create a **draft `Event`** (`requires_human_review=True`, event scalars populated, `extracted_fields` v2 built from the candidate's contacts/orgs + a new top-level `meta` block: intent, confidence, verbatim date strings, timezone basis, channel — additive, schema_version stays 2-compatible). Attach source via `EventEmailLink` (`origin='ai_auto'`) and `EventThreadLink`. Multiple candidates → multiple Events; **the inbox lists them today with no changes** (it already queries `requires_human_review=true`).
   - `NEW_EVENT` that *matched* an existing event → duplicate-suspect: still a draft Event, but `extracted_fields.meta.duplicate_of` set so the review card can show "possible duplicate of ⟨event⟩" (a dropped real event is worse than a duplicate card; the human resolves).
   - `RECURRING_EVENT` → draft Event for the first occurrence + pending `EventSeries` (inactive until review confirms rule + end bound); approval activates the series and materializes occurrences.
   - `RESCHEDULE` / `CANCELLATION` with a match → create **`EventChangeSuggestion`** on the matched event (reusing its existing field-diff + `.approve()` apply machinery), new `origin='email_ingestion'` field, linked from the candidate. Without a match → escalate to triage ("cancellation of unknown event") rather than guessing.
6. **Timezone resolution** — candidate's proposed zone reconciled against office default / sender-location heuristics; result + basis stored; ambiguity flags the field for review. No zoneless time ever reaches an Event row.

---

## 9. Recurrence Semantics (summary of §3.3 behavior)

- Reviewer approves a `RECURRING_EVENT` card → confirms/edits RRULE, **must** set UNTIL or COUNT → `EventSeries` activates → occurrences materialize as `Event` rows through the horizon → monthly `extend_series_horizon` beat task rolls it forward.
- Occurrence edit prompts "this event / whole series" (new modal affordance). "This event" → `is_series_exception=True`, series regeneration skips it. "Whole series" → rule/template update + regenerate future non-exceptions.
- ICS `RECURRENCE-ID` reschedules and `CANCELLATION` of a single occurrence resolve to the specific occurrence `Event` row via `(series, series_occurrence_date)`.

---

## 10. UI / API Changes (kept deliberately thin)

The locked constraint: the **current inbox** (`InboxView`, `inbox-redesign.js`, `event-review-cards.js`, `FieldReviewService`) stays the review surface.

1. **No changes** for new-event candidates: they arrive as review Events through the existing `/api/events/?requires_human_review=true` feed and the existing accept/reject/dismiss/accept-all endpoints.
2. **Third inbox feed** — `GET /api/change-suggestions/?origin=email_ingestion&status=pending` merged in `inbox-redesign.js` alongside the two existing feeds, `_inboxType: 'change_request'`. Card shows intent badge (Reschedule/Cancellation), the matched event, and a field-level diff (old → proposed, with verbatim source string). Approve/reject wire to the existing `EventChangeSuggestion` approve/reject endpoints. This is the largest piece of new UI and it is one card type + one feed merge.
3. **Card metadata** — review cards read `extracted_fields.meta` (intent badge, confidence, "possible duplicate of…", channel icon, verbatim date tooltip on date fields). Additive rendering only.
4. **Recurrence confirm block** on review modal for `RECURRING_EVENT`: rule summary in plain language, editable, end-bound required before Accept enables.
5. **Triage list** — new lightweight page under `email_processing` (replaces `verification_list`): escalated items (digest suspects, rate-gate bursts, auth-failures, unmatched cancellations, malformed extractions) with actions *extract anyway / divert / open source*. Low-volume by design.
6. **Divert-store browse** — searchable list over diverted `RawMessage`s (sender/subject/date/stage filters) + *promote to extraction* action. Satisfies "the office can always find a message it received."
7. **Reputation touchpoint** — dismissing with a junk reason offers "block this sender"; accept increments reputation silently. Settings page section for managing allow/block lists.

---

## 11. Settings & Dependencies

`config/settings/base.py` additions (all env-overridable):

```
SCHEDULING_MAILBOXES=[...]            # replaces all-active-users polling; §2.1 scope
INGEST_SWEEP_MINUTES=5
GRAPH_WEBHOOK_ENABLED=False           # prod flips on once endpoint reachability is confirmed
GRAPH_WEBHOOK_CLIENT_STATE=<secret>   # Secrets Manager in prod
CANDIDATE_CAP=10
DEDUP_WINDOW_DAYS=14
RATE_GATE_SENDER_LIMIT / RATE_GATE_WINDOW_MINUTES / RATE_GATE_MAILBOX_LIMIT
DIGEST_TOKEN_THRESHOLD
ATTACHMENT_STORE_MAX_BYTES=10485760
SERIES_HORIZON_DAYS=400
RESCORE_WINDOW_DAYS=30
```

Removed: `BEDROCK_CLASSIFICATION_MODEL`, `LLM_CLASSIFICATION_THRESHOLD` (no classification call).

New deps (`requirements.txt`): `icalendar`, `pypdf`, `python-docx`, `jsonschema`, `python-dateutil` (verify — likely present). All pure-Python (no egress). Postgres: enable `pg_trgm` extension via migration (guarded to Postgres only).

---

## 12. Build Sequence (PR-sized phases, dependency-ordered)

Mirrors design §10; each phase lands migrations + tests and is independently shippable.

1. **Reception spine** — `RawMessage`/`AttachmentBlob`/`SubscriptionState`, graph client delta/attachment/subscription methods, sweep task on `SCHEDULING_MAILBOXES`, webhook endpoint + lifecycle task behind flag, gap-detection logging. Old hourly polling retired here. *(Silent-drop guard first — nothing else matters if delivery is lossy.)*
2. **Funnel** — Stages 1–4, `FilterLog`, `SenderReputation` + seed migration (internal domain + Contacts), rate gate, divert-store browse view. The critical `test_dedup_vs_reschedule` module lands here.
3. **Channels** — ics parser path (+ the Graph invite-delivery spike from §4.2), attachment harvest, forward detection, thread new-content stripping.
4. **Single extraction call** — provider interface swap, schema + validation, Bedrock/mock/anthropic_dev implementations, `ExtractionCandidate`, old services deleted, demo scripts updated. *(Pipeline ends at candidate rows in this phase — reviewable via admin.)*
5. **Post-processing + materialization** — cap/fold/completeness, matching, intent routing into draft Events / `EventChangeSuggestion`; `EventSeries` + Event FK migration + horizon task; inbox meta rendering, change-request card + third feed, recurrence confirm block, triage list; reputation feedback loop.
6. **Hardening loop** — divert re-scoring task, reconciliation metrics dashboard/alerts, rate-gate tuning against real volume.
7. **(Later, data-gated)** — local classifier from `FilterLog` labels; Bedrock KB semantic dedup behind the cheap-match gate.

---

## 13. Testing Plan

- **Per-stage unit tests** with header/body fixtures (newsletter, no-reply, DMARC-fail, dateless request with legislative anchors, digest).
- **`test_dedup_vs_reschedule.py`** — the named dangerous interaction: short reschedule reply quoting a long thread must pass dedup; identical redelivered message must not.
- **Channel fixtures** — real `.ics` files (REQUEST/CANCEL/RRULE/RECURRENCE-ID), Outlook forward blocks, PDF invitation.
- **End-to-end pipeline test** on mock provider: one email → multi-candidate fan-out → N inbox Events; recurring email → one series candidate; cancellation email → suggestion on matched event.
- **Schema fuzz** — malformed/injection-shaped model outputs must land in escalate, never in an Event.
- **Sweep gap test** — message present in (mocked) Graph but absent from `RawMessage` is ingested and logged as a gap.
- **Series tests** — horizon generation, exception detachment, regenerate-on-rule-change, end-bound enforcement.

## 14. Risks / Open Items

- **Invite delivery via Graph** (§4.2 spike) — resolves before phase 3; may add an `/events` subscription resource.
- **Webhook reachability on House network** — unresolved externally; sweep-first means it degrades latency, not correctness.
- **Attachment volume in Postgres** — 10 MB cap + on-demand refetch is the mitigation; revisit S3 if real volume demands it (security review implication).
- **`EventChangeSuggestion` fit** — it was built for in-app staff suggestions; if the email-origin diff semantics strain it (e.g., cancellation as a status-only change), fall back to a dedicated `CandidateChangeRequest` model with the same approve/apply pattern. Decide during phase 5, not before.
- **SQLite dev parity** — `pg_trgm` fuzzy matching falls back to `difflib`; acceptable divergence, flagged in test markers.
