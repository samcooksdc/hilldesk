# SPDX-License-Identifier: Apache-2.0
"""Shared types for the deterministic ingestion funnel.

Each stage is a pure function ``evaluate(ctx) -> StageDecision``; the engine
(`engine.py`) orders them, applies short-circuit semantics, and writes a
FilterLog row per stage. Stages never touch the database destructively and
never call a model — determinism is the point.
"""

from dataclasses import dataclass, field
from typing import Any, Dict

# Stage/funnel outcomes. PASS moves to the next stage; the others are terminal
# for the run (EXTRACT is the funnel's final "send to extraction" outcome).
PASS = 'pass'
DIVERT = 'divert'
ESCALATE = 'escalate'
EXTRACT = 'extract'


@dataclass
class StageDecision:
    """One stage's verdict plus the evidence behind it."""
    outcome: str                      # PASS | DIVERT | ESCALATE
    signals: Dict[str, Any] = field(default_factory=dict)
    score: float = 0.0


@dataclass
class FunnelContext:
    """Per-message working state threaded through the stages.

    Built once by the engine so each stage stays cheap: body decoding and
    quoted-history stripping happen exactly once per run.
    """
    raw: Any                          # RawMessage (typed loosely to avoid import cycle)
    body_text: str = ''               # full body as plain text
    new_content: str = ''             # quoted-history-stripped body
    subject_normalized: str = ''      # Re:/Fwd:-stripped, lowercased
    sender_email: str = ''
    sender_domain: str = ''
    # Set by stage 2; consumed by stages 3/4 and the engine's routing.
    allowlisted: bool = False
    unknown_sender: bool = True
    # Set by stage 4 when cancel/reschedule vocabulary is present; carried into
    # extraction as an intent hint.
    action_intent: bool = False
    # Channel presence flags.
    has_calendar_part: bool = False
    has_document_attachments: bool = False
    # Forward channel: when a forward's original sender is recoverable,
    # reputation evaluates THAT address, not the forwarding staffer's.
    is_forward: bool = False
    original_sender: str = ''

    @property
    def reputation_sender(self) -> str:
        """The address reputation judges: the forwarded original when known."""
        return self.original_sender or self.sender_email
