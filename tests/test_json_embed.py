# SPDX-License-Identifier: Apache-2.0
"""Regression tests: email-derived data must not break out of <script> blocks."""
import json

from django.test import SimpleTestCase

from apps.event_management.utils.json_embed import script_safe_json

PAYLOAD = {'title': '</script><script>alert(1)</script>', 'note': 'a & b <!--', 'ls': ' '}


class ScriptSafeJsonTests(SimpleTestCase):
    def test_no_raw_angle_brackets_or_ampersands(self) -> None:
        out = script_safe_json(PAYLOAD)
        for ch in ('<', '>', '&', ' '):
            self.assertNotIn(ch, out)

    def test_round_trips_to_original_value(self) -> None:
        self.assertEqual(json.loads(script_safe_json(PAYLOAD)), PAYLOAD)

    def test_template_embed_cannot_close_script(self) -> None:
        html = f'<script type="application/json">{script_safe_json(PAYLOAD)}</script>'
        self.assertEqual(html.lower().count('</script'), 1)
