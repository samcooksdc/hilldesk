# SPDX-License-Identifier: Apache-2.0
"""
This will make sure the app is always imported when
Django starts so that shared_task will use this app.
"""

import sys

# ---------------------------------------------------------------------------
# Windows + Python 3.14 dev workaround.
#
# Python 3.14 added platform._wmi_query(), which Celery calls (via
# platform.win32_ver()) at import time. On some Windows setups that WMI query
# hangs indefinitely, which freezes `from celery import Celery` below and thus
# every `manage.py` command. Fall back to the non-WMI detection path so the
# import returns immediately. This only affects Windows dev machines —
# production runs on Linux (Fargate), where win32_ver()/_wmi_query are never
# called — so it has no effect on deployed behavior.
# ---------------------------------------------------------------------------
if sys.platform == 'win32':
    import platform as _platform
    if hasattr(_platform, '_wmi_query'):
        def _wmi_query_disabled(*args, **kwargs):
            raise OSError('platform._wmi_query disabled (Py3.14 Windows hang workaround)')
        _platform._wmi_query = _wmi_query_disabled

from .celery import app as celery_app

__all__ = ('celery_app',)