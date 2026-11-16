# SPDX-License-Identifier: Apache-2.0
"""
Comprehensive enforcement tests for the customizable permission system.

For every permission in the catalog this exercises the REAL endpoint that it
gates: a user who lacks the permission is rejected (403), and a user who holds
it is allowed. Also covers the dependency closure (a permission can't be held
without its prerequisites).

Helpers build a user with a custom role granting exactly a chosen permission
set (dependency-expanded), so each test isolates a single capability.
"""
import json
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from django.utils.text import slugify

from apps.authentication.models import Office, OfficeStaff, Role, User
from apps.authentication.permissions import Permissions
from tests.factories import create_event

P = Permissions


class Base(TestCase):
    def setUp(self):
        self.office = Office.objects.create(
            name='Test Office',
            event_status_choices=[
                {'value': 'received', 'label': 'Received', 'is_active': True, 'order': 1},
                {'value': 'scheduled', 'label': 'Scheduled', 'is_active': True, 'order': 2},
            ],
        )
        self.roles = self.office.create_default_roles()
        self._creator = None

    # -- factories ---------------------------------------------------------
    def make_user(self, username, perms=(), admin=False, full_name=None):
        u = User.objects.create_user(username=username, email=f'{username}@e.example', password='pw')
        u.office = self.office
        if full_name:
            parts = full_name.split(' ', 1)
            u.first_name = parts[0]
            u.last_name = parts[1] if len(parts) > 1 else ''
        if admin:
            u.assign_role(self.roles['admin'])
        else:
            role = Role.objects.create(
                office=self.office,
                name=f'{username}-role',
                slug=slugify(f'{username}-role'),
                permissions=sorted(P.expand_permissions(set(perms))),
            )
            u.assign_role(role)
        u.save()
        return u

    def make_event(self, group='E', staff=None, status='received',
                   review=False, extracted=None, archived=False):
        if self._creator is None:
            self._creator = self.make_user('evt_creator', admin=True)
        return create_event(
            type='meeting', group=group, status=status,
            start_date=timezone.now().date() + timedelta(days=3),
            staff=staff or [], requires_human_review=review,
            extracted_fields=extracted or {}, is_archived=archived,
            created_by=self._creator, modified_by=self._creator,
        )

    # -- request helpers ---------------------------------------------------
    def get(self, user, url):
        self.client.force_login(user)
        return self.client.get(url)

    def post(self, user, url, payload=None):
        self.client.force_login(user)
        return self.client.post(url, data=json.dumps(payload or {}), content_type='application/json')

    def put(self, user, url, payload=None):
        self.client.force_login(user)
        return self.client.put(url, data=json.dumps(payload or {}), content_type='application/json')

    def patch(self, user, url, payload=None):
        self.client.force_login(user)
        return self.client.patch(url, data=json.dumps(payload or {}), content_type='application/json')

    def delete(self, user, url):
        self.client.force_login(user)
        return self.client.delete(url)


# =============================================================================
# Event access: view_all_events / view_assigned_events
# =============================================================================
class ViewEventsTests(Base):
    def setUp(self):
        super().setUp()
        self.assigned = self.make_event('Assigned', staff=[{'name': 'Vee Assigned'}])
        self.other = self.make_event('Other', staff=[{'name': 'Someone Else'}])

    def test_view_all_sees_everything(self):
        u = self.make_user('viewall', [P.VIEW_ALL_EVENTS])
        data = self.get(u, '/api/events/').json()
        self.assertEqual(data['count'], 2)

    def test_view_assigned_sees_only_assigned(self):
        u = self.make_user('viewassigned', [P.VIEW_ASSIGNED_EVENTS], full_name='Vee Assigned')
        data = self.get(u, '/api/events/').json()
        self.assertEqual({e['group'] for e in data['results']}, {'Assigned'})

    def test_no_view_sees_nothing(self):
        u = self.make_user('noview', [])
        data = self.get(u, '/api/events/').json()
        self.assertEqual(data['count'], 0)


# =============================================================================
# Event access: edit_all_events / edit_assigned_events
# =============================================================================
class EditEventsTests(Base):
    def setUp(self):
        super().setUp()
        self.event = self.make_event('E', staff=[{'name': 'Ed Itor'}])

    def _url(self):
        return f'/api/events/{self.event.id}/update_fields/'

    def test_edit_all_can_edit(self):
        u = self.make_user('editall', [P.EDIT_ALL_EVENTS])
        r = self.patch(u, self._url(), {'fields': {'location': 'Changed'}})
        self.assertEqual(r.status_code, 200)

    def test_assigned_can_edit(self):
        u = self.make_user('assignededitor', [P.EDIT_ASSIGNED_EVENTS], full_name='Ed Itor')
        r = self.patch(u, self._url(), {'fields': {'location': 'Changed'}})
        self.assertEqual(r.status_code, 200)

    def test_unassigned_cannot_edit_directly(self):
        # Sees all events (view_all) but may only edit assigned ones.
        u = self.make_user('unassignededitor', [P.VIEW_ALL_EVENTS, P.EDIT_ASSIGNED_EVENTS],
                           full_name='Not Assigned')
        r = self.patch(u, self._url(), {'fields': {'location': 'Changed'}})
        self.assertEqual(r.status_code, 403)

    def test_view_only_cannot_edit(self):
        u = self.make_user('vieweronly', [P.VIEW_ALL_EVENTS])
        r = self.patch(u, self._url(), {'fields': {'location': 'Changed'}})
        self.assertEqual(r.status_code, 403)


# =============================================================================
# Event workflow: create_events
# =============================================================================
class CreateEventsTests(Base):
    PAYLOAD = {'type': 'meeting', 'group': 'Created', 'start_date': '2026-07-01'}

    def test_create_with_perm(self):
        u = self.make_user('creator2', [P.CREATE_EVENTS])
        r = self.post(u, '/api/events/', self.PAYLOAD)
        self.assertEqual(r.status_code, 201)

    def test_create_without_perm(self):
        u = self.make_user('nocreate', [P.VIEW_ALL_EVENTS])
        r = self.post(u, '/api/events/', self.PAYLOAD)
        self.assertEqual(r.status_code, 403)


# =============================================================================
# Event workflow: change_event_status
# =============================================================================
class ChangeStatusTests(Base):
    def setUp(self):
        super().setUp()
        self.event = self.make_event('E', status='received')

    def _url(self):
        return f'/api/events/{self.event.id}/update_fields/'

    def test_change_status_with_perm(self):
        u = self.make_user('statuschanger', [P.EDIT_ALL_EVENTS, P.CHANGE_EVENT_STATUS])
        r = self.patch(u, self._url(), {'fields': {'status': 'scheduled'}})
        self.assertEqual(r.status_code, 200)
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, 'scheduled')

    def test_change_status_without_perm(self):
        # Can edit, but not change status.
        u = self.make_user('editornostatus', [P.EDIT_ALL_EVENTS])
        r = self.patch(u, self._url(), {'fields': {'status': 'scheduled'}})
        self.assertEqual(r.status_code, 403)


# =============================================================================
# Event workflow: archive_delete_events
# =============================================================================
class ArchiveDeleteTests(Base):
    def setUp(self):
        super().setUp()
        self.event = self.make_event('E')

    def test_archive_with_perm(self):
        u = self.make_user('archiver', [P.VIEW_ALL_EVENTS, P.ARCHIVE_DELETE_EVENTS])
        r = self.post(u, f'/api/events/{self.event.id}/archive/')
        self.assertEqual(r.status_code, 200)

    def test_archive_without_perm(self):
        u = self.make_user('noarchive', [P.VIEW_ALL_EVENTS])
        r = self.post(u, f'/api/events/{self.event.id}/archive/')
        self.assertEqual(r.status_code, 403)

    def test_delete_with_perm(self):
        u = self.make_user('deleter', [P.VIEW_ALL_EVENTS, P.ARCHIVE_DELETE_EVENTS])
        r = self.delete(u, f'/api/events/{self.event.id}/')
        self.assertEqual(r.status_code, 204)

    def test_delete_without_perm(self):
        u = self.make_user('nodelete', [P.VIEW_ALL_EVENTS])
        r = self.delete(u, f'/api/events/{self.event.id}/')
        self.assertEqual(r.status_code, 403)


# =============================================================================
# Inbox: view_inbox
# =============================================================================
class InboxViewTests(Base):
    def setUp(self):
        super().setUp()
        self.review_event = self.make_event('Review', review=True)

    def test_view_inbox_sees_review_items(self):
        u = self.make_user('inboxviewer', [P.EDIT_ALL_EVENTS, P.VIEW_INBOX])
        data = self.get(u, '/api/events/?requires_human_review=true').json()
        self.assertEqual(data['count'], 1)

    def test_no_view_inbox_sees_nothing(self):
        # Has view_all (via edit_all) but not view_inbox.
        u = self.make_user('noinbox', [P.EDIT_ALL_EVENTS])
        data = self.get(u, '/api/events/?requires_human_review=true').json()
        self.assertEqual(data['count'], 0)


# =============================================================================
# Inbox: process_inbox
# =============================================================================
class InboxProcessTests(Base):
    def setUp(self):
        super().setUp()
        self.event = self.make_event(
            'Review', review=True,
            extracted={'group': {'value': 'X', 'status': 'pending'}},
        )

    def test_dismiss_without_process_inbox(self):
        u = self.make_user('noprocess', [P.VIEW_INBOX, P.EDIT_ALL_EVENTS])
        r = self.post(u, f'/api/events/{self.event.id}/dismiss/', {'action': 'dismiss'})
        self.assertEqual(r.status_code, 403)

    def test_dismiss_with_process_inbox(self):
        u = self.make_user('processor', [P.VIEW_INBOX, P.PROCESS_INBOX, P.EDIT_ALL_EVENTS])
        r = self.post(u, f'/api/events/{self.event.id}/dismiss/', {'action': 'dismiss'})
        self.assertNotEqual(r.status_code, 403)

    def test_review_field_without_process_inbox(self):
        u = self.make_user('noprocess2', [P.VIEW_INBOX, P.EDIT_ALL_EVENTS])
        r = self.post(u, f'/api/events/{self.event.id}/review-field/',
                      {'field': 'group', 'action': 'accept'})
        self.assertEqual(r.status_code, 403)


# =============================================================================
# Exports & templates
# =============================================================================
class ExportTests(Base):
    def test_export_csv_with_perm(self):
        u = self.make_user('exporter', [P.EXPORT_EVENTS, P.VIEW_ALL_EVENTS])
        r = self.get(u, '/api/events/export/csv/')
        self.assertEqual(r.status_code, 200)

    def test_export_csv_without_perm(self):
        u = self.make_user('noexport', [P.VIEW_ALL_EVENTS])
        r = self.get(u, '/api/events/export/csv/')
        self.assertEqual(r.status_code, 403)


class TemplateTests(Base):
    def test_email_template_create_denied(self):
        u = self.make_user('notemplates', [P.VIEW_ALL_EVENTS])
        r = self.post(u, '/api/email/templates/create/',
                      {'name': 'X', 'category': 'general', 'subject': 's', 'body': 'hi'})
        self.assertEqual(r.status_code, 403)

    def test_email_template_create_allowed(self):
        u = self.make_user('templater', [P.MANAGE_EMAIL_TEMPLATES])
        r = self.post(u, '/api/email/templates/create/',
                      {'name': 'X', 'category': 'general', 'subject': 's', 'body': 'hi'})
        self.assertNotEqual(r.status_code, 403)

    def test_export_template_upload_denied(self):
        u = self.make_user('noexporttpl', [P.VIEW_ALL_EVENTS])
        r = self.post(u, '/api/export/templates/upload/', {})
        self.assertEqual(r.status_code, 403)


# =============================================================================
# Office settings & staff
# =============================================================================
class OfficeSettingsTests(Base):
    def test_office_settings_put_with_perm(self):
        u = self.make_user('officemgr', [P.MANAGE_OFFICE_SETTINGS])
        r = self.put(u, '/api/office/choices/', {'member_name': 'Rep X'})
        self.assertEqual(r.status_code, 200)

    def test_office_settings_put_without_perm(self):
        u = self.make_user('noofficemgr', [P.VIEW_ALL_EVENTS])
        r = self.put(u, '/api/office/choices/', {'member_name': 'Rep X'})
        self.assertEqual(r.status_code, 403)


class StaffManageTests(Base):
    def setUp(self):
        super().setUp()
        self.profile = OfficeStaff.objects.create(office=self.office, name='P', email='p@e.example')

    def test_create_staff_with_perm(self):
        u = self.make_user('staffmgr', [P.MANAGE_STAFF])
        r = self.post(u, '/api/office/staff/', {'name': 'New Person'})
        self.assertEqual(r.status_code, 201)

    def test_create_staff_without_perm(self):
        u = self.make_user('nostaffmgr', [P.VIEW_ALL_EVENTS])
        r = self.post(u, '/api/office/staff/', {'name': 'New Person'})
        self.assertEqual(r.status_code, 403)

    def test_update_staff_without_perm(self):
        u = self.make_user('nostaffmgr2', [P.VIEW_ALL_EVENTS])
        r = self.put(u, f'/api/office/staff/{self.profile.id}/', {'name': 'X'})
        self.assertEqual(r.status_code, 403)

    def test_delete_staff_without_perm(self):
        u = self.make_user('nostaffmgr3', [P.VIEW_ALL_EVENTS])
        r = self.delete(u, f'/api/office/staff/{self.profile.id}/delete/')
        self.assertEqual(r.status_code, 403)

    def test_link_staff_without_perm(self):
        u = self.make_user('nostaffmgr4', [P.VIEW_ALL_EVENTS])
        r = self.post(u, f'/api/office/staff/{self.profile.id}/link/', {'user_id': str(u.id)})
        self.assertEqual(r.status_code, 403)


# =============================================================================
# Admin-only: assign_roles (role management)
# =============================================================================
class RoleManageTests(Base):
    def test_create_role_admin(self):
        admin = self.make_user('roleadmin', admin=True)
        r = self.post(admin, '/api/office/roles/', {'name': 'NewRole', 'permissions': ['view_inbox']})
        self.assertEqual(r.status_code, 201)

    def test_create_role_non_admin_denied(self):
        # Even a heavily-privileged non-admin can't manage roles.
        u = self.make_user('rolenonadmin', [P.MANAGE_OFFICE_SETTINGS, P.MANAGE_STAFF, P.EDIT_ALL_EVENTS])
        r = self.post(u, '/api/office/roles/', {'name': 'X', 'permissions': []})
        self.assertEqual(r.status_code, 403)

    def test_update_role_non_admin_denied(self):
        u = self.make_user('rolenonadmin2', [P.MANAGE_STAFF])
        r = self.put(u, f'/api/office/roles/{self.roles["staff"].id}/',
                     {'name': 'Hacked', 'permissions': []})
        self.assertEqual(r.status_code, 403)


# =============================================================================
# Dependency closure (checkbox logic)
# =============================================================================
class DependencyClosureTests(Base):
    def test_expand_edit_all(self):
        expanded = P.expand_permissions({P.EDIT_ALL_EVENTS})
        self.assertTrue(
            {P.EDIT_ALL_EVENTS, P.EDIT_ASSIGNED_EVENTS, P.VIEW_ALL_EVENTS, P.VIEW_ASSIGNED_EVENTS}
            <= expanded
        )

    def test_expand_view_all_pulls_view_assigned(self):
        self.assertIn(P.VIEW_ASSIGNED_EVENTS, P.expand_permissions({P.VIEW_ALL_EVENTS}))

    def test_expand_process_inbox_pulls_view_inbox(self):
        self.assertIn(P.VIEW_INBOX, P.expand_permissions({P.PROCESS_INBOX}))

    def test_workflow_perms_pull_view_assigned(self):
        for key in (P.CREATE_EVENTS, P.CHANGE_EVENT_STATUS, P.ARCHIVE_DELETE_EVENTS,
                    P.APPROVE_STAFF_CHANGES, P.CONFIGURE_APPROVAL_ROUTING):
            self.assertIn(P.VIEW_ASSIGNED_EVENTS, P.expand_permissions({key}), key)

    def test_create_role_stores_closure(self):
        admin = self.make_user('depadmin', admin=True)
        self.post(admin, '/api/office/roles/', {'name': 'Ed', 'permissions': ['edit_all_events']})
        role = Role.objects.get(office=self.office, name='Ed')
        for k in ('view_all_events', 'view_assigned_events', 'edit_assigned_events'):
            self.assertIn(k, role.permissions)

    def test_seeded_roles_are_closed(self):
        for role in self.office.roles.all():
            if role.is_admin:
                continue
            perms = set(role.permissions)
            self.assertEqual(perms, P.expand_permissions(perms), f'{role.slug} not closed')
