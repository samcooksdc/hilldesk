# SPDX-License-Identifier: Apache-2.0
"""Serialize data for embedding inside an HTML ``<script>`` element.

Templates embed JSON with ``{{ value|safe }}`` inside ``<script>`` blocks.
Much of that data (event titles, extracted fields, snippets) originates in
inbound email, which is attacker-controlled. Plain ``json.dumps`` leaves
``</script>`` intact, letting a sender close the script element and inject
markup. Escaping ``<``, ``>`` and ``&`` as ``\\u`` sequences (the same thing
Django's ``json_script`` filter does) keeps the output valid JSON and valid
JavaScript while making breakout impossible.
"""
import json
from typing import Any

_ESCAPES = {
    ord('<'): '\\u003C',
    ord('>'): '\\u003E',
    ord('&'): '\\u0026',
    0x2028: '\\u2028',
    0x2029: '\\u2029',
}


def script_safe_json(value: Any, **kwargs: Any) -> str:
    """``json.dumps`` that is safe to place inside ``<script>`` with ``|safe``."""
    return json.dumps(value, **kwargs).translate(_ESCAPES)
