# SPDX-License-Identifier: Apache-2.0
"""Candidate → existing-event matching (spec §8.4).

Cheap and deterministic, in strict precedence order:

1. ICS UID exact match — wins outright (the calendar system is telling us
   which event this is).
2. Thread match — an existing EventThreadLink on this conversation is a strong
   prior; confirmed by date proximity or title similarity.
3. Date ±1 day + fuzzy title similarity.

Fuzzy scoring uses ``difflib`` over a date-bounded window rather than pg_trgm:
the ±1-day prefilter reduces the comparison set to a handful of rows, so a
DB-agnostic in-Python ratio is sufficient and identical across
SQLite/Postgres. (Bedrock KB semantic retrieval stays feature-flagged off
until the KB exists — spec §8.4.)

Only unambiguous matches are returned; multiple mid-band scores are
*inconclusive* and reported as no-match with the scores recorded, because a
wrong match is worse than an escalation.
"""

import logging
from datetime import date, timedelta
from difflib import SequenceMatcher
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger('apps.email_processing')

# Similarity thresholds for the fuzzy stage.
_MATCH_THRESHOLD = 0.6      # clear winner
_MIDBAND_THRESHOLD = 0.45   # a second score above this makes the result ambiguous


def _norm(text: str) -> str:
    return ' '.join((text or '').split()).lower()


def _similarity(a: str, b: str) -> float:
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _parse_date(value) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


def match_existing_event(candidate, record) -> Tuple[Optional[Any], Dict[str, Any]]:
    """Find the existing Event a candidate refers to.

    Returns ``(event_or_none, basis)`` — basis always records how the decision
    was made (including inconclusive outcomes) for FilterLog forensics and the
    candidate's ``match_basis``.
    """
    from apps.event_management.models import Event, EventThreadLink

    from .models import ExtractionCandidate

    payload = candidate.payload or {}
    event_fields = payload.get('event') or {}
    provenance = candidate.provenance or {}

    # --- 1. ICS UID exact match wins outright ---
    uid = provenance.get('uid')
    if uid:
        prior = (ExtractionCandidate.objects
                 .filter(provenance__uid=uid, created_event__isnull=False)
                 .exclude(pk=candidate.pk)
                 .order_by('-created_at')
                 .first())
        if prior is not None:
            return prior.created_event, {'method': 'ics_uid', 'uid': uid}

    title = event_fields.get('title') or ''
    hint = (payload.get('reschedule_target_hint')
            or payload.get('cancellation_target_hint') or '')
    target_date = _parse_date(event_fields.get('start_date'))

    # Events materialized from THIS message are siblings, not match targets —
    # without this, candidate 2 of a multi-event email would "match" the draft
    # just created for candidate 1 via the thread link.
    def _not_own(qs):
        if record is not None:
            return qs.exclude(email_links__email=record)
        return qs

    # --- 2. Thread match: strong prior, confirmed cheaply ---
    if record is not None and record.thread_id:
        linked = (EventThreadLink.objects
                  .filter(thread_id=record.thread_id)
                  .exclude(event__email_links__email=record)
                  .select_related('event')
                  .order_by('-linked_at'))
        thread_events = [l.event for l in linked]
        if len(thread_events) == 1:
            return thread_events[0], {'method': 'thread', 'confirmed_by': 'only_link'}
        for event in thread_events:
            if target_date and event.start_date and \
                    abs((event.start_date - target_date).days) <= 3:
                return event, {'method': 'thread', 'confirmed_by': 'date'}
            score = max(_similarity(title, event.title), _similarity(hint, event.title))
            if score >= _MATCH_THRESHOLD:
                return event, {'method': 'thread', 'confirmed_by': 'title',
                               'score': round(score, 3)}

    # --- 3. Date window + fuzzy title ---
    window = Event.objects.none()
    if target_date:
        window = _not_own(Event.objects.filter(
            start_date__gte=target_date - timedelta(days=1),
            start_date__lte=target_date + timedelta(days=1),
        ))
    elif hint or title:
        # No date to anchor on (e.g. "cancel our meeting") — search upcoming.
        today = date.today()
        window = _not_own(Event.objects.filter(
            start_date__gte=today,
            start_date__lte=today + timedelta(days=90),
        ))

    scored = []
    for event in window.exclude(status='cancelled')[:200]:
        score = max(_similarity(title, event.title), _similarity(hint, event.title))
        if score >= _MIDBAND_THRESHOLD:
            scored.append((score, event))
    scored.sort(key=lambda pair: pair[0], reverse=True)

    if scored and scored[0][0] >= _MATCH_THRESHOLD:
        runner_up = scored[1][0] if len(scored) > 1 else 0.0
        if runner_up < _MIDBAND_THRESHOLD or scored[0][0] - runner_up > 0.15:
            return scored[0][1], {'method': 'date_title',
                                  'score': round(scored[0][0], 3)}
        return None, {'method': 'inconclusive',
                      'scores': [round(s, 3) for s, _ in scored[:3]]}

    return None, {'method': 'none',
                  'best_score': round(scored[0][0], 3) if scored else 0.0}
