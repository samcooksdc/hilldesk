# SPDX-License-Identifier: Apache-2.0
"""
Tests for the event attachment feature (upload, download, replace, delete).

Covers the security-critical paths: size/extension validation, edit-permission
gating on writes, view gating + scan gating on downloads, version history on
replace, and file cleanup on delete.
"""

import shutil
import tempfile
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.event_management.models import (
    EventAttachment, EventAttachmentVersion,
)
from tests.factories import create_event

User = get_user_model()

_TEMP_MEDIA = tempfile.mkdtemp(prefix='hilldesk-attach-test-')


@override_settings(MEDIA_ROOT=_TEMP_MEDIA, FILE_UPLOAD_VIRUS_SCAN=False)
class EventAttachmentTests(APITestCase):
    """Test cases for event attachment endpoints."""

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(_TEMP_MEDIA, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin', email='admin@example.com', password='pw'
        )
        self.admin.role = 'admin'
        self.admin.save()

        self.staff = User.objects.create_user(
            username='staff', email='staff@example.com', password='pw'
        )
        self.staff.role = 'staff'
        self.staff.save()

        # A user whose role grants no permissions at all (not in ROLE_PERMISSIONS).
        self.outsider = User.objects.create_user(
            username='outsider', email='outsider@example.com', password='pw'
        )
        self.outsider.role = 'none'
        self.outsider.save()

        self.event = create_event(
            type='meeting',
            start_date=timezone.now().date() + timedelta(days=1),
            group='Test Group',
            status='received',
            created_by=self.admin,
            modified_by=self.admin,
        )

        self.list_url = reverse('api:event-attachments', kwargs={'event_id': self.event.id})

    def _upload(self, name='memo.docx', content=b'hello world'):
        upload = SimpleUploadedFile(
            name, content,
            content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        )
        return self.client.post(self.list_url, {'file': upload}, format='multipart')

    # --- Upload ---

    def test_upload_happy_path(self):
        self.client.force_authenticate(user=self.admin)
        resp = self._upload()
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertEqual(EventAttachment.objects.filter(event=self.event).count(), 1)
        att = EventAttachment.objects.get(event=self.event)
        self.assertEqual(att.original_filename, 'memo.docx')
        self.assertEqual(att.versions.count(), 1)
        version = att.current_version
        self.assertEqual(version.version_number, 1)
        # Scanning disabled in tests → skipped → downloadable.
        self.assertEqual(version.scan_status, 'skipped')

    def test_file_field_max_length_fits_scoped_path(self):
        # The upload path is event_attachments/<office uuid>/<event uuid>/<uuid>.ext
        # (~133 chars). The FileField must allow it — the default of 100 raised
        # SuspiciousFileOperation in real (office-scoped) use.
        field = EventAttachmentVersion._meta.get_field('file')
        self.assertGreaterEqual(field.max_length, 200)

    def test_upload_does_not_crash_audit_logging(self):
        # Upload/scan emit security_audit INFO logs. assertLogs forces that
        # logger to INFO, which builds the LogRecord — catching reserved-key
        # collisions (e.g. a 'filename' extra) that crash only when logging is
        # actually enabled (as in production/dev, but not default test config).
        self.client.force_authenticate(user=self.admin)
        with self.assertLogs('security_audit', level='INFO'):
            resp = self._upload()
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)

    def test_upload_rejects_oversize(self):
        self.client.force_authenticate(user=self.admin)
        with override_settings(EVENT_ATTACHMENT_MAX_SIZE=10):
            resp = self._upload(content=b'x' * 50)
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(EventAttachment.objects.count(), 0)

    def test_upload_rejects_bad_extension(self):
        self.client.force_authenticate(user=self.admin)
        resp = self._upload(name='evil.exe', content=b'MZ')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(EventAttachment.objects.count(), 0)

    def test_upload_rejects_infected_file(self):
        self.client.force_authenticate(user=self.admin)
        with patch(
            'apps.event_management.services.attachment_scan_service.scan_file',
            return_value='infected',
        ):
            resp = self._upload()
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(EventAttachment.objects.count(), 0)

    def test_upload_requires_edit_permission(self):
        # Unassigned staff cannot edit this event → cannot upload.
        self.client.force_authenticate(user=self.staff)
        resp = self._upload()
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(EventAttachment.objects.count(), 0)

    def test_upload_requires_authentication(self):
        resp = self._upload()
        self.assertIn(resp.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    # --- Replace / version history ---

    def test_replace_creates_new_version(self):
        self.client.force_authenticate(user=self.admin)
        self._upload(name='v1.docx', content=b'first')
        att = EventAttachment.objects.get(event=self.event)

        replace_url = reverse('api:event-attachment-replace', kwargs={
            'event_id': self.event.id, 'attachment_id': att.id,
        })
        upload = SimpleUploadedFile('v2.docx', b'second', content_type='text/plain')
        resp = self.client.post(replace_url, {'file': upload}, format='multipart')

        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        att.refresh_from_db()
        self.assertEqual(att.versions.count(), 2)
        self.assertEqual(att.current_version.version_number, 2)
        self.assertEqual(att.original_filename, 'v2.docx')

    # --- Download ---

    def test_download_streams_file(self):
        self.client.force_authenticate(user=self.admin)
        self._upload(content=b'payload-bytes')
        version = EventAttachmentVersion.objects.get()
        url = reverse('api:event-attachment-download', kwargs={
            'event_id': self.event.id,
            'attachment_id': version.attachment_id,
            'version_id': version.id,
        })
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(b''.join(resp.streaming_content), b'payload-bytes')

    def test_download_allowed_for_viewer_without_edit(self):
        # Staff can VIEW_EVENTS even when they cannot edit → download works.
        self.client.force_authenticate(user=self.admin)
        self._upload()
        version = EventAttachmentVersion.objects.get()
        url = reverse('api:event-attachment-download', kwargs={
            'event_id': self.event.id,
            'attachment_id': version.attachment_id,
            'version_id': version.id,
        })
        self.client.force_authenticate(user=self.staff)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_download_denied_without_view_permission(self):
        self.client.force_authenticate(user=self.admin)
        self._upload()
        version = EventAttachmentVersion.objects.get()
        url = reverse('api:event-attachment-download', kwargs={
            'event_id': self.event.id,
            'attachment_id': version.attachment_id,
            'version_id': version.id,
        })
        self.client.force_authenticate(user=self.outsider)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_download_blocked_until_scanned(self):
        # A version still pending scan must not be served.
        att = EventAttachment.objects.create(
            event=self.event, original_filename='pending.docx',
            source='upload', created_by=self.admin,
        )
        version = EventAttachmentVersion(
            attachment=att, version_number=1, scan_status='pending',
            uploaded_by=self.admin, file_size=3,
        )
        version.file.save('pending.docx', SimpleUploadedFile('pending.docx', b'abc'), save=False)
        version.save()

        url = reverse('api:event-attachment-download', kwargs={
            'event_id': self.event.id, 'attachment_id': att.id, 'version_id': version.id,
        })
        self.client.force_authenticate(user=self.admin)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    # --- Delete ---

    def test_delete_removes_attachment_and_file(self):
        self.client.force_authenticate(user=self.admin)
        self._upload()
        version = EventAttachmentVersion.objects.get()
        storage = version.file.storage
        stored_name = version.file.name
        self.assertTrue(storage.exists(stored_name))

        att = version.attachment
        delete_url = reverse('api:event-attachment-delete', kwargs={
            'event_id': self.event.id, 'attachment_id': att.id,
        })
        resp = self.client.delete(delete_url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(EventAttachment.objects.count(), 0)
        self.assertEqual(EventAttachmentVersion.objects.count(), 0)
        # post_delete signal removes the underlying blob.
        self.assertFalse(storage.exists(stored_name))

    def test_delete_requires_edit_permission(self):
        self.client.force_authenticate(user=self.admin)
        self._upload()
        att = EventAttachment.objects.get()
        delete_url = reverse('api:event-attachment-delete', kwargs={
            'event_id': self.event.id, 'attachment_id': att.id,
        })
        self.client.force_authenticate(user=self.staff)
        resp = self.client.delete(delete_url)
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(EventAttachment.objects.count(), 1)
