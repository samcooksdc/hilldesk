# SPDX-License-Identifier: Apache-2.0
"""Staff browsers must not fetch fonts from third parties, and production logs
must default to stdout (containers have no persistent log files)."""
import os
import re
import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

ROOT = Path(settings.BASE_DIR)
THIRD_PARTY_FONTS = re.compile(r'fonts\.(googleapis|gstatic)\.com')


class SelfHostedFontTests(SimpleTestCase):
    def test_no_template_or_asset_loads_google_fonts(self) -> None:
        offenders = []
        for folder in ('templates', 'static/css', 'static/js', 'config', 'apps'):
            for path in (ROOT / folder).rglob('*'):
                if path.suffix in {'.html', '.css', '.js', '.py'} and path.is_file():
                    if THIRD_PARTY_FONTS.search(path.read_text(encoding='utf-8', errors='ignore')):
                        offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [])

    def test_every_font_file_referenced_by_fonts_css_exists(self) -> None:
        css = (ROOT / 'static' / 'css' / 'fonts.css').read_text(encoding='utf-8')
        files = re.findall(r'url\(\.\./fonts/([^)]+)\)', css)
        self.assertTrue(files)
        for name in files:
            self.assertTrue((ROOT / 'static' / 'fonts' / name).is_file(), name)
        self.assertTrue((ROOT / 'static' / 'fonts' / 'LICENSES.md').is_file())


class ProductionLoggingTests(SimpleTestCase):
    def _handlers(self, extra_env: dict) -> str:
        env = {k: v for k, v in os.environ.items() if k != 'LOG_DIR'}
        env.update({'DJANGO_SETTINGS_MODULE': 'config.settings.production',
                    'SECRET_KEY': 'test-only-0123456789abcdefghijklmnopqrstuvwxyzABCDEF',
                    'FIELD_ENCRYPTION_KEY': 'test-only-field-key', **extra_env})
        code = ("from django.conf import settings; h = settings.LOGGING['handlers'];"
                "print(h['file']['class'], h['security_file']['class'])")
        return subprocess.run([sys.executable, '-c', code], cwd=ROOT, env=env,
                              capture_output=True, text=True, check=True).stdout

    def test_stdout_by_default(self) -> None:
        self.assertEqual(self._handlers({}).split(), ['logging.StreamHandler'] * 2)

    def test_files_when_log_dir_set(self) -> None:
        out = self._handlers({'LOG_DIR': str(ROOT)})
        self.assertEqual(out.split(), ['logging.handlers.RotatingFileHandler'] * 2)
