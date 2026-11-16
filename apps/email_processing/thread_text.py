# SPDX-License-Identifier: Apache-2.0
"""Thread text shaping: quoted-history stripping and normalization.

Shared by funnel Stage 3 (dedup hashes on a message's *new content*, not the
quoted thread it carries) and, later, by the extraction bundle builder (the
model is pointed at new content with the thread as delimited context).

The stakes: a short "move it to 3pm" reply quoting a long thread must hash on
"move it to 3pm" — otherwise every reply in a busy thread looks like a
duplicate of the thread itself and reschedules get silently dropped. This is
the interaction the design doc calls the most dangerous in the funnel.
"""

import html as html_lib
import re
from typing import Optional

# Markers that begin quoted history. Matched per-line, case-insensitive; the
# earliest hit truncates. Ordered roughly by frequency in Outlook/Gmail mail.
_QUOTE_MARKER_PATTERNS = [
    # Gmail / Apple Mail: "On Mon, Jul 6, 2026 at 2:14 PM Jane Doe <j@x> wrote:"
    re.compile(r'^On .{0,200}wrote:\s*$', re.IGNORECASE),
    # Outlook desktop separator
    re.compile(r'^\s*-{3,}\s*Original Message\s*-{3,}\s*$', re.IGNORECASE),
    # Forward separator (Gmail)
    re.compile(r'^\s*-{5,}\s*Forwarded message\s*-{5,}\s*$', re.IGNORECASE),
    # Underscore rule Outlook inserts above its quoted-header block
    re.compile(r'^_{10,}\s*$'),
    # Quoted variant of the Gmail marker
    re.compile(r'^>{1,}\s?On .{0,200}wrote:\s*$', re.IGNORECASE),
]
# NOTE: bare "From:" lines are intentionally NOT in this list — they only count
# as a marker when they head an Outlook header block (see strip_quoted_history).

# A "From:" line only counts as a quote marker when it looks like the start of
# an Outlook header block (a Sent:/Date:/To: line within the next few lines);
# otherwise prose like "From: my perspective..." would truncate real content.
_OUTLOOK_FOLLOWUP = re.compile(r'^\s*(Sent|Date|To|Subject|Cc):\s', re.IGNORECASE)
_FROM_LINE = re.compile(r'^\s*From:\s.+$', re.IGNORECASE)

# Subject prefixes to strip for normalization ("Re: Re: FW: mtg" -> "mtg").
_SUBJECT_PREFIX = re.compile(r'^\s*(re|fw|fwd|aw|sv|vs)\s*(\[\d+\])?\s*:\s*', re.IGNORECASE)

_TAG_RE = re.compile(r'<[^>]+>')
_STYLE_SCRIPT_RE = re.compile(
    r'<(style|script|head)[^>]*>.*?</\1>', re.IGNORECASE | re.DOTALL
)
_BR_RE = re.compile(r'<\s*(br|/p|/div|/tr|/li|/h[1-6])\s*/?\s*>', re.IGNORECASE)


def html_to_text(html: str) -> str:
    """Cheap, dependency-free HTML → text for scoring/hashing purposes.

    Not a renderer: drops style/script, turns block-level closes and <br> into
    newlines, strips remaining tags, unescapes entities, collapses blank runs.
    """
    if not html:
        return ''
    text = _STYLE_SCRIPT_RE.sub(' ', html)
    text = _BR_RE.sub('\n', text)
    text = _TAG_RE.sub(' ', text)
    text = html_lib.unescape(text)
    # Collapse horizontal whitespace but keep line structure for marker matching.
    lines = [re.sub(r'[ \t\xa0]+', ' ', ln).strip() for ln in text.splitlines()]
    out, blank = [], 0
    for ln in lines:
        blank = blank + 1 if not ln else 0
        if blank <= 1:
            out.append(ln)
    return '\n'.join(out).strip()


def message_text(raw_message) -> str:
    """The message body as plain text, whichever form was stored."""
    if raw_message.body_text:
        return raw_message.body_text
    return html_to_text(raw_message.body_html or '')


def strip_quoted_history(text: str) -> str:
    """Return the message's NEW content: everything before the first quoted-
    history marker, with any residual '>'-quoted lines dropped.

    Conservative by design: when no marker is found the text is returned whole
    (minus quoted lines). A false negative here (history kept) costs an extra
    hash collision candidate; a false positive (real content stripped) loses a
    message — so 'From:' lines only truncate when they head an Outlook block.
    """
    if not text:
        return ''
    lines = text.splitlines()
    cut: Optional[int] = None
    for i, line in enumerate(lines):
        matched = any(pat.match(line) for pat in _QUOTE_MARKER_PATTERNS)
        if not matched and _FROM_LINE.match(line):
            # Outlook header block: require a Sent:/To:/... line close behind.
            lookahead = lines[i + 1:i + 4]
            matched = any(_OUTLOOK_FOLLOWUP.match(l) for l in lookahead)
        if matched:
            cut = i
            break
    kept = lines[:cut] if cut is not None else lines
    new_content = [ln for ln in kept if not ln.lstrip().startswith('>')]
    return '\n'.join(new_content).strip()


def new_content(raw_message) -> str:
    """Convenience: quoted-history-stripped text of a RawMessage."""
    return strip_quoted_history(message_text(raw_message))


def normalize_subject(subject: str) -> str:
    """Strip reply/forward prefixes (repeatedly) and normalize whitespace/case."""
    s = subject or ''
    while True:
        stripped = _SUBJECT_PREFIX.sub('', s, count=1)
        if stripped == s:
            break
        s = stripped
    return ' '.join(s.split()).lower()
