# SPDX-License-Identifier: Apache-2.0
"""Funnel Stage 1 — header signals.

Deterministic transport-level checks, evaluated before any content is read:

- Bulk-mail headers (List-Unsubscribe, List-Id, Precedence: bulk/list,
  Auto-Submitted: auto-*) → divert. Machines announcing themselves as machines.
- No-reply sender patterns → divert.
- SPF/DKIM/DMARC failure (parsed from Authentication-Results) → ESCALATE.
  A spoofed sender is a security question, never a silent divert and never
  something to hand a language model.
"""

import re
from typing import Dict

from .base import DIVERT, ESCALATE, PASS, StageDecision

# Local parts that mark automated senders.
_AUTOMATED_LOCAL_PART = re.compile(
    r'^(no-?reply|do-?not-?reply|donotreply|notifications?|mailer-daemon|'
    r'postmaster|bounce[s]?|auto(mated)?-?(reply|response)?)([+.-].*)?$',
    re.IGNORECASE,
)

# spf=fail / dkim=fail / dmarc=fail (permerror counts as suspicious too).
# Word-boundary anchored so 'softfail' does NOT match — soft failures are
# common on legitimate forwarded mail.
_AUTH_FAILURE = re.compile(r'\b(spf|dkim|dmarc)\s*=\s*(fail|permerror)\b', re.IGNORECASE)


def evaluate(ctx) -> StageDecision:
    headers = {k.lower(): (v or '') for k, v in (ctx.raw.headers or {}).items()}
    signals: Dict = {}

    # --- Authentication results: escalate on hard failure (checked first —
    #     a spoofed newsletter is still a spoof). ---
    auth_results = headers.get('authentication-results', '')
    failures = sorted({f"{m.group(1).lower()}={m.group(2).lower()}"
                       for m in _AUTH_FAILURE.finditer(auth_results)})
    if failures:
        signals['auth_failures'] = failures
        return StageDecision(ESCALATE, signals)

    # --- Bulk / automated mail headers → divert ---
    bulk_hits = [h for h in ('list-unsubscribe', 'list-id') if h in headers]
    precedence = headers.get('precedence', '').strip().lower()
    if precedence in ('bulk', 'list', 'junk'):
        bulk_hits.append(f'precedence:{precedence}')
    auto_submitted = headers.get('auto-submitted', '').strip().lower()
    if auto_submitted and auto_submitted != 'no':
        bulk_hits.append(f'auto-submitted:{auto_submitted}')
    if bulk_hits:
        signals['bulk_headers'] = bulk_hits
        return StageDecision(DIVERT, signals)

    # --- Automated sender local-part patterns → divert ---
    local_part = ctx.sender_email.split('@')[0] if '@' in ctx.sender_email else ctx.sender_email
    if local_part and _AUTOMATED_LOCAL_PART.match(local_part):
        signals['automated_sender'] = local_part.lower()
        return StageDecision(DIVERT, signals)

    return StageDecision(PASS, signals)
