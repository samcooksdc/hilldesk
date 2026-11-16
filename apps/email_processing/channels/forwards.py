# SPDX-License-Identifier: Apache-2.0
"""Forward channel: detect forwarded mail and recover the ORIGINAL sender.

Reputation (funnel Stage 2) must evaluate the original external sender, not
the forwarding staffer — an internal allowlisted forwarder must not launder an
unknown external request past scrutiny. Conversely, a staffer forwarding
something *is* a signal it matters, so forwarded content is intentionally
allowed back into the pipeline (dedup treats the forward as new: fresh
Message-ID, and its stripped content is the quoted original).
"""

import re
from dataclasses import dataclass

_FWD_SUBJECT = re.compile(r'^\s*(fwd?|fw)\s*:', re.IGNORECASE)
_FWD_SEPARATORS = [
    re.compile(r'^\s*-{5,}\s*Forwarded message\s*-{5,}\s*$', re.IGNORECASE | re.MULTILINE),
    re.compile(r'^\s*Begin forwarded message:\s*$', re.IGNORECASE | re.MULTILINE),
    re.compile(r'^_{10,}\s*$', re.MULTILINE),
]
# "From: Jane Doe <jane@x.org>" or "From: jane@x.org" inside the quoted block.
_FROM_LINE = re.compile(
    r'^\s*>?\s*From:\s*(?:"?([^"<\n]*)"?\s*)?<?([\w.+-]+@[\w-]+\.[\w.-]+)>?\s*$',
    re.IGNORECASE | re.MULTILINE,
)


@dataclass
class ForwardInfo:
    is_forward: bool = False
    original_sender: str = ''       # empty when undetectable
    original_name: str = ''
    quoted_block: str = ''          # the forwarded original (from the separator on)


def detect(subject: str, body_text: str) -> ForwardInfo:
    """Detect a forward and extract the original sender from the quoted block.

    Detection requires a forward marker (Fwd: subject or a body separator);
    sender recovery then looks for the first From: line inside the quoted
    block. Either can fail independently — is_forward may be True with an
    empty original_sender, in which case Stage 2 falls back to the forwarder
    (safe: a forwarder is never MORE trusted than the original)."""
    info = ForwardInfo()
    body = body_text or ''

    separator_match = None
    for sep in _FWD_SEPARATORS:
        m = sep.search(body)
        if m and (separator_match is None or m.start() < separator_match.start()):
            separator_match = m

    subject_says_forward = bool(_FWD_SUBJECT.match(subject or ''))
    if not subject_says_forward and separator_match is None:
        return info

    info.is_forward = True
    info.quoted_block = body[separator_match.start():] if separator_match else body

    from_match = _FROM_LINE.search(info.quoted_block)
    if from_match:
        info.original_name = (from_match.group(1) or '').strip()
        info.original_sender = from_match.group(2).strip()
    return info
