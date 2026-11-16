# SPDX-License-Identifier: Apache-2.0
"""Anchor dictionary: phrases that anchor a request in time WITHOUT a strict
date token.

Congressional scheduling mail routinely says "after recess" or "when you're
back in district" instead of "August 4th". Stage 4 must treat these as real
scheduling signals — a dateless request with a legislative anchor passes
forward, it is not "no date found".

Data-driven so staff-reported misses can be added without touching stage logic.
"""

import re
from typing import List

_WEEKDAYS = r'(monday|tuesday|wednesday|thursday|friday|saturday|sunday)'

# Each entry: (label, compiled regex). Labels land in FilterLog.signals so the
# forensics view can show exactly which anchor fired.
ANCHOR_PATTERNS = [
    # Relative dates
    ('relative_day', re.compile(r'\b(today|tomorrow|tonight)\b', re.I)),
    ('next_weekday', re.compile(rf'\b(next|this)\s+{_WEEKDAYS}\b', re.I)),
    ('next_period', re.compile(r'\b(next|this|later\s+this)\s+(week|month|quarter|year)\b', re.I)),
    ('coming_period', re.compile(r'\bin\s+the\s+(coming|next\s+few)\s+(days|weeks|months)\b', re.I)),
    ('weekday_morning', re.compile(rf'\b{_WEEKDAYS}\s+(morning|afternoon|evening)\b', re.I)),
    # Bare ordinals ("the 14th", "on the 3rd")
    ('bare_ordinal', re.compile(r'\b(?:on\s+)?the\s+\d{1,2}(st|nd|rd|th)\b', re.I)),
    # Legislative-calendar anchors
    ('legislative', re.compile(
        r'\b('
        r'after\s+(the\s+)?recess|before\s+(the\s+)?recess|during\s+(the\s+)?recess|'
        r'august\s+recess|'
        r'after\s+the\s+markup|before\s+the\s+markup|'
        r'back\s+in\s+session|in\s+session|out\s+of\s+session|'
        r'district\s+work\s+period|'
        r'when\s+the\s+house\s+is\s+(in|out\s+of)\s+session|'
        r'lame[\s-]duck|'
        r'before\s+the\s+break|after\s+the\s+break|'
        r'end\s+of\s+the\s+(fiscal\s+)?year|'
        r'appropriations\s+season|'
        r'while\s+(you|the\s+congress(woman|man)|the\s+member)\s+(are|is)\s+in\s+(town|the\s+district|dc|washington)'
        r')\b', re.I)),
]


def find_anchors(text: str) -> List[str]:
    """Return the labels of every anchor family that fires in ``text``."""
    if not text:
        return []
    return [label for label, pattern in ANCHOR_PATTERNS if pattern.search(text)]
