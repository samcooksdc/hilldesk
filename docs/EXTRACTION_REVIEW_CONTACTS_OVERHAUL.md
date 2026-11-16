# Extraction Review Overhaul — Multi-Contact / Multi-Org Resolution

**Status:** Spec (approved design decisions, not yet implemented)
**Branch:** `normalize-contacts-organizations`
**Author:** Samuel + Claude
**Date:** 2026-06-26

## 1. Goal

Replace today's single-point-of-contact / single-group extraction review with a
system that extracts **all** contacts and organizations from an email and lets a
reviewer resolve each one against the normalized `Contact` / `Organization`
models in the Event Editing Modal (EEM), with full CRUD, jump-to-next, and
source highlighting.

For every extracted party the reviewer can:
1. **Create** a new contact/org and populate it.
2. **Link** an existing one with no changes.
3. **Link + update** an existing one — add a position, add emails/phones.
   Emails/phones **always append**, never replace. Replacing is a separate,
   explicitly confirmed action.

## 2. Approved design decisions

| # | Decision | Choice |
|---|----------|--------|
| 1 | Match signals | **email** OR **name + phone** OR **name + organization** |
| 2 | Name comparison | **Fuzzy** (token/similarity), always gated behind an exact phone/org prefilter |
| 3 | Review unit | **Hybrid** — card-level accept/reject + navigation; field-level confirm for each add/replace |
| 4 | Scope | **Promote everyone** to rich contacts (POC + attendees) with role tag |
| 5 | Replace result | **Demote, keep on record** (old value loses `is_primary`, is not deleted) |
| 6 | Contact→Org capture | **Per-contact `organization` field** emitted by the LLM |
| 7 | Roles | `point_of_contact`, `attendee`, `host_speaker`. **Staff/internal excluded** (separate system) |
| 8 | Reject/undo | Mirror current field reject — discard the party; undo restores to pending |
| 9 | In-email dedupe | Merge duplicate extracted parties **before** showing the reviewer |
| 10 | Confidence gating | Nothing auto-accepted; everything stays **pending** until confirmed |

### Why encryption constrains matching

`Contact.name` / `Organization.name` are `EncryptedCharField` (Fernet,
non-deterministic) — not queryable or indexable on plaintext. The only
DB-queryable handles are **blind indexes** (`email_key`, `name_key`): keyed
HMAC-SHA256 of the normalized value, supporting **exact equality only**.

Therefore fuzzy name matching must **never scan the whole table** (that would
mean decrypting every contact). It is always run *inside* a small candidate set
produced by an exact blind-index lookup:

- **name + org** → exact `name_key` lookup on org → fuzzy-compare names among
  that org's members (handful of rows).
- **name + phone** → requires a **new `phone_key` blind index** (mirrors
  `email_key`) → exact phone lookup → fuzzy-compare names in that set.

## 3. Data model changes (`apps/contacts/`)

### 3.1 `ContactPhoneNumber.phone_key` (+ org equivalent)
Add a blind index so the **name + phone** signal is cheap:

```python
# models.py — ContactPhoneNumber / OrganizationPhoneNumber
phone_key = models.CharField(max_length=64, db_index=True, editable=False,
    help_text="HMAC-SHA256 blind index of the normalized phone (exact match)")

def save(self, *args, **kwargs):
    self.phone_key = phone_blind_index(self.phone)
    super().save(*args, **kwargs)
```

```python
# crypto.py
def normalize_phone(raw: str) -> str:
    """Keep digits only (and a leading +) so '(202) 555-0100' == '+12025550100'-ish."""
    digits = ''.join(ch for ch in (raw or '') if ch.isdigit())
    return digits[-10:] if len(digits) >= 10 else digits  # last 10 = US local key

def phone_blind_index(raw: str) -> str:
    return _hmac(normalize_phone(raw))
```

- **Migration:** add field + data migration to backfill `phone_key` on existing
  rows. No uniqueness constraint (two people can share an office line).
- **Open nuance:** phone normalization is lossy (extensions, intl). Last-10-digit
  key is a pragmatic default for US House offices; revisit if intl contacts matter.

### 3.2 Role vocabulary
`EventContact.role` already exists (`max_length=100`). Define constants:

```python
class EventContactRole:
    POINT_OF_CONTACT = 'point_of_contact'
    ATTENDEE = 'attendee'
    HOST_SPEAKER = 'host_speaker'
    CHOICES = [...]
```

No schema change — just a constants module + validation. `is_primary` continues
to mark the single primary contact per event (the POC).

## 4. Extraction changes (`apps/email_processing/`)

### 4.1 New extraction schema
`_build_extraction_prompt` (`llm_providers/base.py:221`) replaces
`point_of_contact` (object) + `participants` (string[]) with:

```json
{
  "contacts": [
    {
      "name": "Jane Doe",
      "email": "jane@acme.org",
      "phone": "202-555-0100",
      "position": "Legislative Director",
      "organization": "Acme Advocacy",
      "role": "point_of_contact",
      "source": { "name": [120, 128], "email": [140, 154] }
    }
  ],
  "organizations": [
    { "name": "Acme Advocacy", "location": "Washington, DC",
      "source": { "name": [200, 213] } }
  ]
}
```

- `role` ∈ {`point_of_contact`, `attendee`, `host_speaker`}; default `attendee`.
- `organization` is the org **name** the contact belongs to (free text; resolved
  later). Enables the name+org match signal and the contact↔org cross-link.
- `source` carries per-field `[start, end]` char offsets into the email body for
  highlighting. Keep `group` / `point_of_contact_*` **out** of the new schema.
- Update `missing_fields` / `uncertain_fields` semantics to be per-contact-index.

### 4.2 Parser / persistence
- New normalizer turns the raw LLM list into the **stored review structure**
  (§5), running **in-email dedupe** (decision #9): merge two extracted entries
  that share an email (exact) or normalized name+phone.
- Mock + `anthropic_dev` providers updated to emit the new shape so offline dev
  works (CLAUDE.md: dev uses `mock`/`anthropic_dev`).
- Keep a back-compat reader: old events with the flat
  `point_of_contact_*`/`group` extracted_fields still render (read-only) so we
  don't have to re-extract historical emails.

## 5. Stored review structure (`Event.extracted_fields`)

Today: flat `{field_name: {value, status, confidence, start_index, ...}}`.
New: scalar event fields keep that shape; **contacts/orgs move to lists** of
resolution objects:

```json
{
  "title":      { "value": "...", "status": "pending", ... },
  "start_date": { ... },

  "contacts": [
    {
      "ref": "c0",                       // stable id for this extracted party
      "status": "pending",               // pending | accepted | rejected
      "confidence": 0.82,
      "fields": {
        "name":     { "value": "Jane Doe", "source": [120,128] },
        "email":    { "value": "jane@acme.org", "source": [140,154] },
        "phone":    { "value": "202-555-0100", "source": null },
        "position": { "value": "Legislative Director", "source": null },
        "role":     { "value": "point_of_contact" }
      },
      "resolution": {
        "action": "link_update",         // new | link | link_update
        "matched_id": "<contact-uuid>",  // null when action == new
        "matched_by": "email",           // email | name_phone | name_org | null
        "match_confidence": 0.95,
        "pending_additions": [           // appended on accept, no confirm needed
          { "kind": "phone", "value": "202-555-0100" }
        ],
        "pending_replaces": [            // require explicit per-item confirm
          { "kind": "position", "old": "Staff Asst", "new": "Legislative Director", "confirmed": false }
        ]
      }
    }
  ],
  "organizations": [ /* same shape, role-less */ ]
}
```

- **Migration:** a data migration is *not* strictly required (old events keep old
  shape; new extractions write new shape). Add a `schema_version` marker so the
  serializer/JS can branch.

## 6. Resolution service (`apps/contacts/services.py`)

New functions (additive; keep `attach_contact_org_to_event` for the
legacy/back-compat path):

```python
def match_contact(*, email='', name='', phone='', organization='') -> list[Match]:
    """Return ranked candidate matches using the approved signals.
    1. exact email_key  -> Match(by='email', confidence=high)
    2. exact phone_key  -> fuzzy name among those contacts -> by='name_phone'
    3. exact org name_key -> fuzzy name among org members -> by='name_org'
    Dedupe candidates; sort by signal strength then name similarity.
    """

def diff_against_contact(contact, *, email, phone, position) -> (additions, replaces):
    """additions = emails/phones not already on the contact (always append).
       replaces  = position change, or a new value the reviewer may promote to primary."""

def resolve_contact(event, party, *, user):
    """Apply a confirmed resolution object: create OR link OR link+update,
       append additions, apply confirmed replaces (demote old -> keep, set new primary),
       create EventContact(role, is_primary), cross-link org, attach source_emails.
       Idempotent + fully audit-logged."""
```

- **Fuzzy name compare** lives in a small util (`rapidfuzz` token_set_ratio or a
  vendored Levenshtein if we avoid the dep) operating only on decrypted names of
  the narrowed candidate set.
- **Replace = demote** (decision #5): the old `ContactEmailAddress` /
  `ContactPhoneNumber` row stays; `is_primary` moves to the new value. Position
  (single field) replace overwrites but writes the old value to the audit log.
- Organizations resolved with the same pattern (email-less → exact name_key,
  then fuzzy among same key is moot; match is exact-name only for orgs).

## 7. API (`apps/api/`)

Extend the field-review endpoints rather than replace them:

- `POST /api/events/{id}/review-contact/` — body
  `{ ref, action, matched_id?, role?, additions[], replaces[], field_edits{} }`.
  Validates, calls `resolve_contact`, returns updated review status + the
  resolved nested contact (for the card to re-render).
- `POST /api/events/{id}/review-org/` — same for organizations.
- Keep `review-field/`, `accept-all/`, `dismiss-review/` for scalar fields.
- `get_review_status` extended: review is complete when all scalar fields **and**
  all contact/org cards are accepted/rejected, **and** no unconfirmed
  `pending_replaces` remain.
- Reuse existing `ContactSerializer` / `OrganizationSerializer` for resolved
  output; reuse `/api/contacts/?search=` typeahead for manual link.
- **Audit:** one `EventReviewAuditLog` row per accept/reject/add/replace
  (CLAUDE.md: audit logging on all sensitive operations).

## 8. EEM UI (`event-editing-modal-v2.js`, `event-contacts-panel.js`)

### 8.1 Card model (hybrid review — decision #3)
Each extracted contact/org renders as a **card** in the Involved Parties tab:

```
┌─ Jane Doe · Legislative Director ──────────── [Link + updates ▾] ─┐
│  matched Jane Doe (acme.org) — by email · 95%                      │
│  Email   jane@acme.org                                            │
│  Phone   202-555-0100   ＋ new → will be added        [confirm]   │
│  Position Staff Asst → Legislative Director  (replace) [Replace]   │
│  Org     Acme Advocacy                                           │
│  Role    ( ) POC  (•) Attendee  ( ) Host/Speaker                  │
│                                        [Reject]   [Accept party]   │
└───────────────────────────────────────────────────────────────────┘
```

- **Action selector** (`New / Link / Link+updates`) pre-set from
  `resolution.action`; reviewer can override → switches to a search box to pick
  a different existing contact (manual link).
- **Additions** (`＋ new`) are applied on **Accept party** with no extra click.
- **Replaces** show the `old → new` affordance and stay blocking until the
  reviewer clicks **Replace** (or dismisses to keep old). This is the "replace UI
  element" from the request — inline, per-value, confirmed, with strikethrough.
- All fields are editable inputs (open CRUD): editing name/email/phone/position
  writes back into `field_edits` and can change the live match.

### 8.2 Navigation + highlighting
- **Jump-to-next** field order becomes: scalar fields (as today) → contact cards
  in extraction order → org cards. Within a card, Tab advances through unconfirmed
  replaces, then to the next card. Card is "done" when accepted/rejected with no
  open replaces.
- **Click-in / highlight:** focusing a card field highlights the email source span
  via the per-field `source` offsets (§4.1) — same mechanism as today's
  `start_index`/`end_index`, just nested under `contacts[i].fields[f].source`.
- Reject greys the card; **undo** restores to pending (decision #8).
- Progress bar counts cards as review units alongside scalar fields.

## 9. Phasing

1. **Schema/migration** — `phone_key` + normalize_phone/phone_blind_index +
   backfill migration; role constants; `schema_version` marker. *(No UI yet.)*
2. **Extraction** — new prompt schema, parser/normalizer with in-email dedupe,
   mock + anthropic_dev providers, back-compat reader.
3. **Resolution service** — `match_contact`, `diff_against_contact`,
   `resolve_contact`, fuzzy-name util, org variant; unit tests on match signals.
4. **API** — `review-contact/` + `review-org/`, extended `get_review_status`,
   audit logging.
5. **EEM UI** — card rendering, action selector, add/replace confirm affordances,
   jump-to-next + highlighting, progress bar, reject/undo.
6. **Demo data + tests** — rework `scripts/populate_office_demo_info.py` to the
   new multi-contact/multi-org shape (§11); re-run populate after edits (per
   project convention); pytest coverage for services + API.

   **No migration of existing events** (decision): historical/production events
   keep their legacy flat `extracted_fields` and render read-only via the
   back-compat reader (§4.2). The new shape is exercised entirely through the
   demo population scripts, which wipe and rebuild on every run.

### Tests required (CLAUDE.md)
- Match signal matrix: email / name+phone / name+org / no-match → new.
- Append vs replace (demote-keeps-old-row).
- In-email dedupe.
- Review completion gating (open replace blocks completion).
- Back-compat render of legacy flat extracted_fields.

## 10. Risks / open nuances
- **Phone key normalization** is lossy (extensions/intl); last-10-digit default.
- **Fuzzy threshold** tuning — too low spams "possible match" cards; start
  conservative, log near-misses.
- **Re-extraction / migration:** explicitly **out of scope**. Existing events
  keep the legacy flat shape and render read-only. The new shape lives only in
  freshly-populated demo data (§11). No one-off backfill job.
- **Two extracted parties resolving to the same existing contact across the
  signal types** (not just exact email) — extend dedupe to post-match (collapse
  cards whose `matched_id` is equal) before render.

## 11. Demo data population changes (`scripts/populate_office_demo_info.py`)

`clear_event_data` already wipes `Event`, `EmailProcessing`, and **all
`Contact`/`Organization` rows** each run, so the demo rebuilds a clean directory
every time — no migration concerns. Per project convention, re-run
`create_demo_office.py` (if touched) then `populate_office_demo_info.py`
immediately after edits.

### 11.1 Spec shape: one POC/group → lists of parties + orgs
Today each spec carries a single contact + group:
```python
poc_name=..., poc_email=..., poc_phone=..., group=...
'fields': [('point_of_contact_name', ...), ('group', ...), ...]
```
Replace with explicit party/org lists:
```python
'parties': [
    dict(name='Margaret Halloran', email='mhalloran@shenandoahsistercities.org',
         phone='(540) 555-0173', position='President',
         organization='Cedar Valley Sister Cities Association',
         role='point_of_contact'),
    dict(name='Hans Vogel', position='Visiting Delegate',
         organization='Fairview Sister City — Germany', role='host_speaker'),
],
'orgs': [ dict(name='Cedar Valley Sister Cities Association', location='Fairview, FR') ],
```
Most demo emails already name extra people in prose ("two teacher members from
the district", "Sheriff Thomas Beale and two association representatives",
"President Ellen Marsh and our workforce dean") and carry a **position** in the
signature ("Policy Coordinator", "Executive Director", "Board Chair"). Promote
those to `attendee` / `host_speaker` parties with `position` set, so the
multi-contact UI renders real data instead of a single POC.

### 11.2 New extracted_fields builders
Keep `build_extracted_fields` for scalar fields; add:
- `build_contact_cards(parties, body)` → the `contacts[]` resolution list (§5):
  per-field `source` offsets via the existing `find_text_position`, `status:
  pending`, and a `resolution` block.
- `build_org_cards(orgs, body)` → the `organizations[]` list.
- Stamp `schema_version: 2` so the serializer/JS branch on shape.

### 11.3 Seed all three resolution paths + replace
Add deliberate recurrences (realization order is deterministic) so the review UI
demonstrates each action end to end:
- **Create (new):** first appearance of a contact/org (most specs).
- **Link, no change:** a later spec whose POC is an exact-email match to an
  already-created contact with identical info (reuse e.g. `VFW Post 5051` /
  `mhalloran@…` across two specs).
- **Link + update:** a later spec where a known contact reappears with a **new
  phone/email** (append → "＋ new" chip) and/or a **changed position** (replace →
  `old → new [Replace]` affordance). Include one spec reaching a known contact
  from a **new email address** so the name+org / name+phone match signal (not
  exact email) is exercised.

### 11.4 Realization changes (`realize_events`, ~line 1518)
Replace the single `attach_contact_org_to_event(...)` call with a loop over
`spec['parties']` / `spec['orgs']` that calls the new resolution services with
`role` + `position`, marking the POC `is_primary=True`. For **review-bucket**
events also write the `contacts[]`/`organizations[]` cards into
`event.extracted_fields`; **calendar/undated** events keep `extracted_fields={}`
(post-review) but still create the normalized rows and links as today. The card's
`resolution` for review events is computed against the rows already created at
that point in the deterministic realize order.

### 11.5 Out of scope for the script
- No migration of non-demo events.
- `create_demo_office.py` untouched unless a shared role/position fixture is
  needed.
