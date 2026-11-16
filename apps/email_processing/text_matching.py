# SPDX-License-Identifier: Apache-2.0
"""
Text matching utilities for finding source text positions in email bodies.

This module provides fuzzy matching capabilities to handle cases where
the LLM's extracted text doesn't exactly match the source email.
"""

import logging
from typing import Tuple, Optional

logger = logging.getLogger(__name__)


def find_text_position(
    search_text: str,
    body_text: str,
    min_score: int = 70
) -> Tuple[Optional[int], Optional[int]]:
    """
    Find the position of search_text in body_text using multi-strategy matching.

    Strategies (in order):
    1. Exact match (case-insensitive)
    2. Fuzzy matching with sliding window

    Args:
        search_text: The text to find
        body_text: The text to search in
        min_score: Minimum fuzzy match score (0-100) to accept

    Returns:
        Tuple of (start_index, end_index) or (None, None) if not found
    """
    if not search_text or not body_text:
        return None, None

    search_clean = search_text.strip()
    if not search_clean:
        return None, None

    # Strategy 1: Exact match (case-insensitive)
    idx = body_text.lower().find(search_clean.lower())
    if idx >= 0:
        return idx, idx + len(search_clean)

    # Strategy 2: Fuzzy matching with sliding window
    try:
        from rapidfuzz import fuzz

        best_score = 0
        best_start = None
        best_end = None

        # Use window sizes around the search text length
        search_len = len(search_clean)
        window_sizes = [
            search_len,
            int(search_len * 0.8),
            int(search_len * 1.2),
            int(search_len * 1.5),
            int(search_len * 0.6),
        ]

        for window_size in window_sizes:
            if window_size < 5:
                continue

            # Slide window across body text
            # Use smaller step for more precision
            step = max(1, window_size // 6)
            for i in range(0, len(body_text) - window_size + 1, step):
                window = body_text[i:i + window_size]
                score = fuzz.ratio(search_clean.lower(), window.lower())

                if score > best_score:
                    best_score = score
                    best_start = i
                    best_end = i + window_size

        # Refine the match boundaries if we found a good match
        if best_score >= min_score and best_start is not None:
            refined_start, refined_end = refine_match_boundaries(
                body_text, best_start, best_end, search_clean
            )
            logger.debug(
                f"Fuzzy match found: '{search_clean[:30]}...' -> "
                f"'{body_text[refined_start:refined_end][:30]}...' (score={best_score})"
            )
            return refined_start, refined_end

    except ImportError:
        logger.warning("rapidfuzz not installed, falling back to exact match only")

    return None, None


def refine_match_boundaries(
    body_text: str,
    start: int,
    end: int,
    search_text: str
) -> Tuple[int, int]:
    """
    Refine match boundaries to better align with word/phrase boundaries.

    Args:
        body_text: The full text being searched
        start: Initial start index
        end: Initial end index
        search_text: The text we're looking for

    Returns:
        Tuple of (refined_start, refined_end)
    """
    # Define boundary characters
    boundary_chars = ' \n\t.,;:!?()[]{}"\''

    # Expand to word boundaries (but don't expand too far)
    max_expand = 10
    expanded = 0
    while start > 0 and body_text[start - 1] not in boundary_chars and expanded < max_expand:
        start -= 1
        expanded += 1

    expanded = 0
    while end < len(body_text) and body_text[end] not in boundary_chars and expanded < max_expand:
        end += 1
        expanded += 1

    # Trim whitespace and punctuation from edges
    while start < end and body_text[start] in ' \n\t':
        start += 1
    while end > start and body_text[end - 1] in ' \n\t':
        end -= 1

    return start, end


def find_best_match_for_field(
    field_value: str,
    body_text: str,
    field_type: str = 'default'
) -> Tuple[Optional[int], Optional[int], Optional[str]]:
    """
    Find the best match for a field value in the email body.

    Returns the position and the actual matched text snippet.

    Args:
        field_value: The extracted field value to find
        body_text: The email body text
        field_type: Type of field ('date', 'time', 'email', 'phone', 'default')

    Returns:
        Tuple of (start_index, end_index, matched_text) or (None, None, None)
    """
    if not field_value or not body_text:
        return None, None, None

    # Adjust min_score based on field type
    min_scores = {
        'date': 60,      # Dates can vary a lot (Jan 15 vs January 15th)
        'time': 65,      # Times can vary (2pm vs 2:00 PM)
        'email': 90,     # Emails should match closely
        'phone': 85,     # Phones should match closely
        'default': 70,
    }
    min_score = min_scores.get(field_type, 70)

    start, end = find_text_position(field_value, body_text, min_score)

    if start is not None and end is not None:
        matched_text = body_text[start:end]
        return start, end, matched_text

    return None, None, None
