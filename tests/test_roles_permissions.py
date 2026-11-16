# SPDX-License-Identifier: Apache-2.0
"""
Tests for the customizable office roles & permissions system.

Covers: default-role seeding, Role.has_permission, the Permissions catalog and
checks, event view-scoping, and the admin role-management UI (create/edit/delete
roles + assigning roles to users).
"""
import json
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.authentication.models import Office, OfficeStaff, Role, User
from apps.authentication.permissions import Permissions
from apps.event_management.models import Event
from tests.factories import create_event


class RoleModelTests(TestCase):
    def setUp(self):
        self.office = Office.objects.create(name='Test Office')
        self.roles = self.office.create_default_roles()

    def test_default_roles_seeded(self):
        slugs = set(self.office.roles.values_list('slug', flat=True))
        self.assertEqual(slugs, {'admin', 'scheduler', 'staff'})

    def test_admin_role_is_locked_and_grants_all(self):
        admin = self.roles['admin']
        self.assertTrue(admin.is_admin)
        self.assertFalse(admin.is_editable)
        self.assertFalse(admin.is_deletable)
        self.assertEqual(admin.get_permissions(), Permissions.all_permissions())
        self.assertTrue(admin.has_permission(Permissions.ASSIGN_ROLES))

    def test_staff_role_permissions(self):
        staff = self.roles['staff']
        self.assertIn(Permissions.VIEW_ASSIGNED_EVENTS, staff.permissions)
        self.assertNotIn(Permissions.VIEW_ALL_EVENTS, staff.permissions)
        self.assertFalse(staff.has_permission(Permissions.EDIT_ALL_EVENTS))

    def test_create_default_roles_is_idempotent(self):
        self.office.create_default_roles()
        self.assertEqual(self.office.roles.count(), 3)


class PermissionCheckTests(TestCase):
    def setUp(self):
        self.office = Office.objects.create(name='Perm Office')
        self.roles = self.office.create_default_roles()
        self.admin = self._user('admin_u', 'admin')
        self.staff = self._user('staff_u', 'staff')

    def _user(self, username, slug):
        u = User.objects.create_user(username=username, email=f'{username}@e.example', password='pw')
        u.office = self.office
        u.assign_role(self.roles[slug])
        u.save()
        return u

    def test_assign_role_syncs_slug(self):
        self.assertEqual(self.staff.role, 'staff')
        self.assertEqual(self.staff.office_role, self.roles['staff'])

    def test_admin_has_all_permissions(self):
        for perm in Permissions.all_permissions():
            self.assertTrue(Permissions.has_permission(self.admin, perm))

    def test_staff_lacks_admin_permissions(self):
        self.assertFalse(Permissions.has_permission(self.staff, Permissions.ASSIGN_ROLES))
        self.assertFalse(Permissions.has_permission(self.staff, Permissions.VIEW_ALL_EVENTS))
        self.assertTrue(Permissions.has_permission(self.staff, Permissions.VIEW_ASSIGNED_EVENTS))

    def test_is_office_admin(self):
        self.assertTrue(self.admin.is_office_admin)
        self.assertFalse(self.staff.is_office_admin)


class EventScopeTests(TestCase):
    def setUp(self):
        self.office = Office.objects.create(name='Scope Office')
        self.roles = self.office.create_default_roles()
        self.admin = User.objects.create_user(username='a', email='a@e.example', password='pw')
        self.admin.office = self.office
        self.admin.assign_role(self.roles['admin'])
        self.admin.save()

        self.staff = User.objects.create_user(
            username='jdoe', email='jdoe@e.example', password='pw', first_name='Jane', last_name='Doe'
        )
        self.staff.office = self.office
        self.staff.assign_role(self.roles['staff'])
        self.staff.save()

        tomorrow = timezone.now().date() + timedelta(days=1)
        # Event assigned to the staff member (by name)
        self.assigned = create_event(
            type='meeting', start_date=tomorrow, group='Assigned',
            status='received', staff=[{'name': 'Jane Doe', 'email': 'jdoe@e.example'}],
            created_by=self.admin, modified_by=self.admin,
        )
        # Event the staff member is NOT on
        self.other = create_event(
            type='meeting', start_date=tomorrow, group='Other',
            status='received', staff=[{'name': 'Someone Else'}],
            created_by=self.admin, modified_by=self.admin,
        )

    def test_admin_sees_all(self):
        qs = Permissions.scope_events_queryset(self.admin, Event.objects.all())
        self.assertEqual(qs.count(), 2)

    def test_staff_sees_only_assigned(self):
        qs = Permissions.scope_events_queryset(self.staff, Event.objects.all())
        ids = set(qs.values_list('id', flat=True))
        self.assertEqual(ids, {self.assigned.id})

    def test_no_view_permission_sees_nothing(self):
        # Custom role with no view permissions
        none_role = Role.objects.create(office=self.office, name='None', slug='none', permissions=[])
        self.staff.assign_role(none_role)
        self.staff.save()
        qs = Permissions.scope_events_queryset(self.staff, Event.objects.all())
        self.assertEqual(qs.count(), 0)


class RoleManagementViewTests(TestCase):
    def setUp(self):
        self.office = Office.objects.create(name='UI Office')
        self.roles = self.office.create_default_roles()
        self.admin = User.objects.create_user(username='admin_ui', email='admin@e.example', password='pw')
        self.admin.office = self.office
        self.admin.assign_role(self.roles['admin'])
        self.admin.save()
        self.member = User.objects.create_user(username='member', email='m@e.example', password='pw')
        self.member.office = self.office
        self.member.assign_role(self.roles['staff'])
        self.member.save()
        self.client.force_login(self.admin)

    def test_admin_can_load_page(self):
        resp = self.client.get(reverse('authentication:role_management'))
        self.assertEqual(resp.status_code, 200)

    def test_non_admin_forbidden(self):
        self.client.force_login(self.member)
        resp = self.client.get(reverse('authentication:role_management'))
        self.assertEqual(resp.status_code, 403)

    def test_create_role(self):
        resp = self.client.post(reverse('authentication:role_create'), {
            'name': 'Intern', 'description': 'Limited', 'color': '#9333ea',
            'permissions': [Permissions.VIEW_ASSIGNED_EVENTS],
        })
        self.assertEqual(resp.status_code, 302)
        role = Role.objects.get(office=self.office, name='Intern')
        self.assertEqual(role.permissions, [Permissions.VIEW_ASSIGNED_EVENTS])
        self.assertEqual(role.slug, 'intern')

    def test_create_role_rejects_admin_only_permission(self):
        self.client.post(reverse('authentication:role_create'), {
            'name': 'Sneaky', 'color': '#000000',
            'permissions': [Permissions.VIEW_ASSIGNED_EVENTS, Permissions.ASSIGN_ROLES],
        })
        role = Role.objects.get(office=self.office, name='Sneaky')
        self.assertNotIn(Permissions.ASSIGN_ROLES, role.permissions)

    def test_edit_role(self):
        scheduler = self.roles['scheduler']
        resp = self.client.post(
            reverse('authentication:role_edit', args=[scheduler.id]),
            {'name': 'Coordinator', 'color': '#2563eb',
             'permissions': [Permissions.VIEW_ALL_EVENTS, Permissions.CHANGE_EVENT_STATUS]},
        )
        self.assertEqual(resp.status_code, 302)
        scheduler.refresh_from_db()
        self.assertEqual(scheduler.name, 'Coordinator')
        # Permissions are stored as their dependency closure: view_all and
        # change_status both pull in view_assigned.
        self.assertEqual(set(scheduler.permissions), {
            Permissions.VIEW_ALL_EVENTS, Permissions.CHANGE_EVENT_STATUS,
            Permissions.VIEW_ASSIGNED_EVENTS,
        })
        # Slug stays stable
        self.assertEqual(scheduler.slug, 'scheduler')

    def test_cannot_edit_admin_role(self):
        admin_role = self.roles['admin']
        self.client.post(
            reverse('authentication:role_edit', args=[admin_role.id]),
            {'name': 'Hacked', 'color': '#000000', 'permissions': []},
        )
        admin_role.refresh_from_db()
        self.assertEqual(admin_role.name, 'Admin')

    def test_assign_role_to_member(self):
        scheduler = self.roles['scheduler']
        resp = self.client.post(reverse('authentication:role_management'), {
            'user_id': str(self.member.id), 'role': str(scheduler.id),
        })
        self.assertEqual(resp.status_code, 302)
        self.member.refresh_from_db()
        self.assertEqual(self.member.office_role, scheduler)
        self.assertEqual(self.member.role, 'scheduler')

    def test_cannot_remove_last_admin(self):
        staff = self.roles['staff']
        self.client.post(reverse('authentication:role_management'), {
            'user_id': str(self.admin.id), 'role': str(staff.id),
        })
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_office_admin)

    def test_delete_unused_role(self):
        intern = Role.objects.create(office=self.office, name='Intern', slug='intern', permissions=[])
        resp = self.client.post(reverse('authentication:role_delete', args=[intern.id]))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Role.objects.filter(id=intern.id).exists())

    def test_cannot_delete_role_with_users(self):
        staff = self.roles['staff']  # member is assigned to staff
        self.client.post(reverse('authentication:role_delete', args=[staff.id]))
        self.assertTrue(Role.objects.filter(id=staff.id).exists())

    def test_cannot_delete_admin_role(self):
        admin_role = self.roles['admin']
        self.client.post(reverse('authentication:role_delete', args=[admin_role.id]))
        self.assertTrue(Role.objects.filter(id=admin_role.id).exists())


class RoleAndStaffApiTests(TestCase):
    """The customization-tab API: roles in office_choices, role CRUD, and
    assigning a role to a linked user via the staff edit endpoint."""

    def setUp(self):
        self.office = Office.objects.create(name='API Office')
        self.roles = self.office.create_default_roles()
        self.admin = User.objects.create_user(username='api_admin', email='a@e.example', password='pw')
        self.admin.office = self.office
        self.admin.assign_role(self.roles['admin'])
        self.admin.save()

        # A staff member linked to a user account
        self.staff_user = User.objects.create_user(username='linked', email='l@e.example', password='pw')
        self.staff_user.office = self.office
        self.staff_user.assign_role(self.roles['staff'])
        self.profile = OfficeStaff.objects.create(office=self.office, name='Linked Person', email='l@e.example')
        self.staff_user.staff_profile = self.profile
        self.staff_user.save()

        self.client.force_login(self.admin)

    def test_office_choices_includes_roles_and_catalog(self):
        resp = self.client.get('/api/office/choices/')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual({r['slug'] for r in data['roles']}, {'admin', 'scheduler', 'staff'})
        self.assertTrue(len(data['permission_catalog']) >= 4)
        self.assertTrue(data['can_manage_roles'])
        # Linked staff exposes their role
        linked = [s for s in data['staff_members'] if s['linked_user']][0]
        self.assertEqual(linked['linked_user']['role_id'], str(self.roles['staff'].id))

    def test_create_role_api(self):
        resp = self.client.post('/api/office/roles/', data=json.dumps({
            'name': 'Intern', 'color': '#9333ea', 'description': 'x',
            'permissions': ['view_assigned_events'],
        }), content_type='application/json')
        self.assertEqual(resp.status_code, 201)
        role = Role.objects.get(office=self.office, name='Intern')
        self.assertEqual(role.permissions, ['view_assigned_events'])

    def test_create_role_api_requires_admin(self):
        self.client.force_login(self.staff_user)
        resp = self.client.post('/api/office/roles/', data=json.dumps({
            'name': 'X', 'permissions': [],
        }), content_type='application/json')
        self.assertEqual(resp.status_code, 403)

    def test_assign_role_via_staff_edit(self):
        resp = self.client.put(
            f'/api/office/staff/{self.profile.id}/',
            data=json.dumps({'name': 'Linked Person', 'role_id': str(self.roles['scheduler'].id)}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        self.staff_user.refresh_from_db()
        self.assertEqual(self.staff_user.office_role, self.roles['scheduler'])
        self.assertEqual(resp.json()['staff']['linked_user']['role_name'], 'Scheduler')

    def test_staff_edit_ignores_role_for_non_admin(self):
        # The staff user is not an admin, so role_id should be ignored — but they
        # also can't even reach update_staff_member now (manage_staff required),
        # so the role is unchanged regardless.
        self.client.force_login(self.staff_user)
        original = self.staff_user.office_role
        self.client.put(
            f'/api/office/staff/{self.profile.id}/',
            data=json.dumps({'name': 'Linked Person', 'role_id': str(self.roles['admin'].id)}),
            content_type='application/json',
        )
        self.staff_user.refresh_from_db()
        self.assertEqual(self.staff_user.office_role, original)


class PermissionDependencyTests(TestCase):
    """The dependency closure: a permission can't be held without prerequisites."""

    def setUp(self):
        self.office = Office.objects.create(name='Dep Office')
        self.roles = self.office.create_default_roles()
        self.admin = User.objects.create_user(username='dep_admin', email='d@e.example', password='pw')
        self.admin.office = self.office
        self.admin.assign_role(self.roles['admin'])
        self.admin.save()
        self.client.force_login(self.admin)

    def test_expand_edit_all_pulls_view_chain(self):
        p = Permissions
        expanded = p.expand_permissions({p.EDIT_ALL_EVENTS})
        self.assertTrue(
            {p.EDIT_ALL_EVENTS, p.EDIT_ASSIGNED_EVENTS, p.VIEW_ALL_EVENTS, p.VIEW_ASSIGNED_EVENTS}
            <= expanded
        )

    def test_expand_process_inbox_requires_view_inbox(self):
        self.assertIn(Permissions.VIEW_INBOX,
                      Permissions.expand_permissions({Permissions.PROCESS_INBOX}))

    def test_view_all_pulls_view_assigned(self):
        self.assertIn(Permissions.VIEW_ASSIGNED_EVENTS,
                      Permissions.expand_permissions({Permissions.VIEW_ALL_EVENTS}))

    def test_create_role_api_stores_dependency_closure(self):
        resp = self.client.post('/api/office/roles/', data=json.dumps({
            'name': 'Editor', 'permissions': ['edit_all_events'],
        }), content_type='application/json')
        self.assertEqual(resp.status_code, 201)
        role = Role.objects.get(office=self.office, name='Editor')
        for required in ('view_all_events', 'view_assigned_events', 'edit_assigned_events'):
            self.assertIn(required, role.permissions)

    def test_office_choices_exposes_dependencies(self):
        data = self.client.get('/api/office/choices/').json()
        self.assertIn('permission_dependencies', data)
        self.assertEqual(data['permission_dependencies']['view_all_events'], ['view_assigned_events'])

    def test_default_roles_are_dependency_closed(self):
        for role in self.office.roles.all():
            if role.is_admin:
                continue
            perms = set(role.permissions)
            self.assertEqual(perms, Permissions.expand_permissions(perms),
                             f'{role.slug} is not dependency-closed')


class EnforcementTests(TestCase):
    """New permissions actually gate their endpoints server-side."""

    def setUp(self):
        self.office = Office.objects.create(name='Enf Office')
        self.roles = self.office.create_default_roles()
        self.admin = User.objects.create_user(username='enf_admin', email='a@e.example', password='pw')
        self.admin.office = self.office
        self.admin.assign_role(self.roles['admin'])
        self.admin.save()
        # Staff role lacks manage_staff, manage_office_settings, export_events.
        self.staff = User.objects.create_user(username='enf_staff', email='s@e.example', password='pw')
        self.staff.office = self.office
        self.staff.assign_role(self.roles['staff'])
        self.staff.save()

    def test_staff_cannot_manage_office_settings(self):
        self.client.force_login(self.staff)
        resp = self.client.put('/api/office/choices/',
                               data=json.dumps({'member_name': 'Hacked'}),
                               content_type='application/json')
        self.assertEqual(resp.status_code, 403)

    def test_admin_can_manage_office_settings(self):
        self.client.force_login(self.admin)
        resp = self.client.put('/api/office/choices/',
                               data=json.dumps({'member_name': 'Rep. Real'}),
                               content_type='application/json')
        self.assertEqual(resp.status_code, 200)

    def test_staff_cannot_create_staff(self):
        self.client.force_login(self.staff)
        resp = self.client.post('/api/office/staff/',
                                data=json.dumps({'name': 'New Person'}),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 403)

    def test_staff_cannot_export_csv(self):
        self.client.force_login(self.staff)
        resp = self.client.get('/api/events/export/csv/')
        self.assertEqual(resp.status_code, 403)
