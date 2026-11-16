# SPDX-License-Identifier: Apache-2.0
"""
Malware-scan seam for event attachments.

This module is the single integration point for virus/malware scanning of
uploaded files. It deliberately ships WITHOUT a real scanner backend:

  * In development and testing, scanning is a no-op and files are marked
    ``skipped`` so the feature works end-to-end offline.
  * In production, scanning is gated on the ``FILE_UPLOAD_VIRUS_SCAN`` setting.
    The actual scanner (e.g. a ClamAV sidecar or an AWS-side scan) is an
    infrastructure dependency that must be selected and signed off as part of
    the security review — until ``_run_backend_scan`` is wired to a real
    engine it conservatively raises, so production cannot silently accept
    unscanned files while believing they were checked.

Callers should treat the returned status as authoritative and only serve files
whose version ``is_downloadable`` (clean or skipped).
"""

import logging

from django.conf import settings

logger = logging.getLogger('security_audit')

# Status constants mirror EventAttachmentVersion.SCAN_STATUS_CHOICES.
STATUS_CLEAN = 'clean'
STATUS_INFECTED = 'infected'
STATUS_SKIPPED = 'skipped'


class AttachmentScanError(Exception):
    """Raised when scanning is required but no backend is configured/available."""


def scan_file(django_file) -> str:
    """Scan an uploaded file and return its resulting scan status.

    Args:
        django_file: An uploaded file-like object (e.g. ``request.FILES['file']``).

    Returns:
        One of ``STATUS_CLEAN``, ``STATUS_INFECTED``, or ``STATUS_SKIPPED``.

    Raises:
        AttachmentScanError: If scanning is enabled (``FILE_UPLOAD_VIRUS_SCAN``)
            but no scanner backend has been wired up yet.
    """
    if not getattr(settings, 'FILE_UPLOAD_VIRUS_SCAN', False):
        # Offline/dev/test path: no scanner, mark as skipped so downloads work.
        logger.info(
            'Attachment scan skipped (FILE_UPLOAD_VIRUS_SCAN disabled)',
            extra={'file_name': getattr(django_file, 'name', '')},
        )
        return STATUS_SKIPPED

    return _run_backend_scan(django_file)


def _run_backend_scan(django_file) -> str:
    """Hook for the real scanner backend. Not yet implemented.

    Wire this to the approved engine (ClamAV sidecar, AWS-side scan, etc.) once
    selected during security review. It must return STATUS_CLEAN / STATUS_INFECTED.
    """
    raise AttachmentScanError(
        'FILE_UPLOAD_VIRUS_SCAN is enabled but no malware scanner backend is '
        'configured. Wire attachment_scan_service._run_backend_scan to the '
        'approved scanner before enabling scanning in this environment.'
    )
