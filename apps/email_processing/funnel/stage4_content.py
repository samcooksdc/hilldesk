# SPDX-License-Identifier: Apache-2.0
"""Funnel Stage 4 — content heuristics.

Applies only to unknown-sender prose mail with no calendar part and no
document attachments (the engine bypasses this stage for those channels, and
for allowlisted senders). Absorbs the retired EmailProcessor keyword scoring,
extended with the anchor dictionary.

Outcomes:
- PASS is the default on ANY scheduling vocabulary or anchor — even at zero
  strict date tokens ("after recess" is a real request).
- DIVERT only for near-zero signal, with newsletter shape as a strong second
  vote. The weekly re-scoring task is the safety net for these.
- ESCALATE when strict date-token density exceeds DIGEST_TOKEN_THRESHOLD —
  probable digest/enumeration; a human decides whether to extract.
"""

import re
from typing import Dict, List

from django.conf import settings

from .anchors import find_anchors
from .base import DIVERT, ESCALATE, PASS, StageDecision

# Absorbed from the retired EmailProcessor (email_processor.py), pruned of
# words that fired constantly in congressional mail without meaning a request.
SCHEDULING_KEYWORDS = [
    'meeting', 'schedule', 'appointment', 'event', 'conference',
    'briefing', 'session', 'hearing', 'roundtable',
    'presentation', 'speaking', 'appearance', 'keynote',
    'interview', 'call', 'zoom', 'webinar', 'visit', 'tour',
    'invite', 'invitation', 'rsvp', 'attend', 'availability',
]

# Vocabulary that signals a CHANGE to something already scheduled. Also sets
# the action-intent hint carried into extraction.
ACTION_KEYWORDS = ['cancel', 'cancelled', 'canceled', 'reschedule', 'rescheduled',
                   'move', 'moved', 'postpone', 'postponed', 'push back']

QUESTION_INDICATORS = [
    'would you', 'could you', 'can you', 'are you available',
    'would the', 'could the', 'can the', 'interested in',
    'like to', 'want to', 'hoping to', 'planning to',
]

# Strict date/time tokens (from the retired _has_scheduling_patterns, tightened).
_DATE_PATTERNS = [
    re.compile(r'\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b'),
    re.compile(r'\b(january|february|march|april|may|june|july|august|september|'
               r'october|november|december)\s+\d{1,2}\b', re.I),
    re.compile(r'\b(jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\.?\s+\d{1,2}\b', re.I),
    re.compile(r'\b\d{4}-\d{2}-\d{2}\b'),
]
_TIME_PATTERNS = [
    re.compile(r'\b\d{1,2}:\d{2}\s*(am|pm)?\b', re.I),
    re.compile(r'\b\d{1,2}\s*(am|pm)\b', re.I),
    re.compile(r'\bfrom\s+\d{1,2}(:\d{2})?\s*(am|pm)?\s*(to|-|–)\s*\d{1,2}(:\d{2})?\s*(am|pm)?\b', re.I),
]

_SCHEDULING_PHRASES = [
    re.compile(p, re.I) for p in (
        r'would you be available', r'are you free', r'can we schedule',
        r"let'?s meet", r'meeting request', r'calendar invite',
        r'book a time', r'set up a (meeting|call)', r'schedule a call',
        r'save the date', r'requesting a meeting',
    )
]

_URL_RE = re.compile(r'https?://', re.I)


def _count_matches(patterns: List[re.Pattern], text: str) -> int:
    return sum(len(p.findall(text)) for p in patterns)


def _newsletter_shape(text: str, link_count: int) -> bool:
    """Long body with heavy link density and no conversational address."""
    length = len(text)
    if length < 400:
        return False
    links_per_kb = link_count / (length / 1000)
    return link_count >= 5 and links_per_kb >= 2.0


def evaluate(ctx) -> StageDecision:
    text = f"{ctx.subject_normalized} {ctx.new_content}".lower()
    signals: Dict = {}

    date_tokens = _count_matches(_DATE_PATTERNS, text)
    time_tokens = _count_matches(_TIME_PATTERNS, text)
    signals['date_tokens'] = date_tokens
    signals['time_tokens'] = time_tokens

    # Digest/enumeration guard: dozens of strict dates in one message is a
    # newsletter of events, not a request — a human decides.
    digest_threshold = getattr(settings, 'DIGEST_TOKEN_THRESHOLD', 12)
    if date_tokens > digest_threshold:
        signals['digest_suspect'] = True
        return StageDecision(ESCALATE, signals, score=float(date_tokens))

    keyword_hits = [k for k in SCHEDULING_KEYWORDS if k in text]
    action_hits = [k for k in ACTION_KEYWORDS if k in text]
    question_hits = [q for q in QUESTION_INDICATORS if q in text]
    phrase_hits = [p.pattern for p in _SCHEDULING_PHRASES if p.search(text)]
    anchor_hits = find_anchors(text)

    signals['scheduling_keywords'] = keyword_hits
    signals['action_keywords'] = action_hits
    signals['question_indicators'] = question_hits
    signals['scheduling_phrases'] = phrase_hits
    signals['anchors'] = anchor_hits

    if action_hits:
        ctx.action_intent = True

    link_count = len(_URL_RE.findall(ctx.new_content))
    newsletter = _newsletter_shape(ctx.new_content, link_count)
    signals['link_count'] = link_count
    signals['newsletter_shape'] = newsletter
    signals['length'] = len(ctx.new_content)

    score = (
        len(keyword_hits)
        + 2.0 * len(action_hits)
        + 2.0 * len(phrase_hits)
        + 1.5 * len(anchor_hits)
        + 0.7 * len(question_hits)
        + 0.5 * min(time_tokens, 4)
        + 0.5 * min(date_tokens, 4)
    )

    # Any scheduling vocabulary, phrase, anchor, or action word → pass forward,
    # even with zero strict dates.
    if keyword_hits or phrase_hits or anchor_hits or action_hits:
        return StageDecision(PASS, signals, score=score)

    # Date/time tokens without vocabulary still read as scheduling-shaped
    # ("Thursday 2pm work?") — pass forward.
    if date_tokens or time_tokens:
        return StageDecision(PASS, signals, score=score)

    # Zero signal. Newsletter shape confirms bulk; either way there is nothing
    # here for extraction — divert (re-scoring + browse are the safety nets).
    signals['divert_reason'] = 'newsletter_shape' if newsletter else 'no_signal'
    return StageDecision(DIVERT, signals, score=score)
