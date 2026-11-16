# SPDX-License-Identifier: Apache-2.0
"""Server-rendered event pages enforce the same role rules as the events API
(they previously let any signed-in user read, edit or delete any event)."""
from django.test import Client
from django.urls import NoReverseMatch, reverse

from tests.test_permissions_comprehensive import Base, P


class EventPagePermissionTests(Base):
    def setUp(self) -> None:
        super().setUp()
        self.event = self.make_event('Locked', staff=[{'name': 'Some One Else'}])

    def _client(self, user) -> Client:
        client = Client()
        client.force_login(user)
        return client

    # --- anonymous ---------------------------------------------------------
    def test_anonymous_is_sent_to_login(self) -> None:
        anon = Client()
        for url in (f'/events/{self.event.id}/', f'/events/{self.event.id}/edit/', '/events/create/'):
            self.assertEqual(anon.get(url).status_code, 302, url)

    def test_unused_unscoped_ajax_helpers_are_gone(self) -> None:
        for name in ('event_api_detail', 'event_quick_update', 'event_quick_create'):
            with self.assertRaises(NoReverseMatch):
                reverse(f'event_management:{name}', kwargs={'event_id': self.event.id})

    # --- visibility ----------------------------------------------------------
    def test_user_without_view_scope_gets_404(self) -> None:
        nobody = self._client(self.make_user('noview', []))
        self.assertEqual(nobody.get(f'/events/{self.event.id}/').status_code, 404)

    def test_viewer_can_read(self) -> None:
        viewer = self._client(self.make_user('viewer', [P.VIEW_ALL_EVENTS]))
        self.assertEqual(viewer.get(f'/events/{self.event.id}/').status_code, 200)

    # --- editing -------------------------------------------------------------
    def test_viewer_cannot_edit(self) -> None:
        viewer = self._client(self.make_user('viewonly', [P.VIEW_ALL_EVENTS]))
        self.assertEqual(viewer.get(f'/events/{self.event.id}/edit/').status_code, 403)
        r = viewer.post(f'/events/{self.event.id}/edit/', {'location': 'Hacked'})
        self.assertEqual(r.status_code, 403)
        self.event.refresh_from_db()
        self.assertNotEqual(self.event.location, 'Hacked')

    def test_editor_can_open_edit_page(self) -> None:
        editor = self._client(self.make_user('editor', [P.EDIT_ALL_EVENTS]))
        self.assertEqual(editor.get(f'/events/{self.event.id}/edit/').status_code, 200)

    # --- create / delete -----------------------------------------------------
    def test_create_page_requires_create_permission(self) -> None:
        viewer = self._client(self.make_user('nocreate', [P.VIEW_ALL_EVENTS]))
        self.assertEqual(viewer.get('/events/create/').status_code, 403)
        creator = self._client(self.make_user('creator', [P.CREATE_EVENTS]))
        self.assertEqual(creator.get('/events/create/').status_code, 200)

    def test_delete_requires_permission_and_soft_deletes(self) -> None:
        viewer = self._client(self.make_user('nodelete', [P.VIEW_ALL_EVENTS]))
        self.assertEqual(viewer.post(f'/events/{self.event.id}/delete/').status_code, 403)

        deleter = self._client(self.make_user('deleter', [P.VIEW_ALL_EVENTS, P.ARCHIVE_DELETE_EVENTS]))
        self.assertEqual(deleter.post(f'/events/{self.event.id}/delete/').status_code, 302)
        self.event.refresh_from_db()
        self.assertTrue(self.event.is_archived)  # moved to Deleted events, not destroyed


class ScopedListingTests(Base):
    """Dashboard, calendar sidebar and editing page follow the same role scope."""

    def setUp(self) -> None:
        super().setUp()
        from django.utils import timezone
        self.today = timezone.localdate()  # the dashboard works in local time
        self.mine = self.make_event('Mine', staff=[{'name': 'Ann Assigned'}], status='scheduled')
        self.other = self.make_event('Other', staff=[{'name': 'Someone Else'}], status='scheduled')
        self.deleted = self.make_event('Deleted', staff=[{'name': 'Ann Assigned'}], status='scheduled')
        for e in (self.mine, self.other, self.deleted):
            e.title, e.start_date, e.requires_human_review = f'{e.group} meeting', self.today, False
            e.save()
        self.deleted.archive(user=self.make_user('archiver', admin=True))
        self.assigned_only = self.make_user('ann', [P.VIEW_ASSIGNED_EVENTS], full_name='Ann Assigned')

    def _client(self, user) -> Client:
        client = Client()
        client.force_login(user)
        return client

    def test_dashboard_agenda_respects_scope_and_hides_deleted(self) -> None:
        ctx = self._client(self.assigned_only).get(reverse('event_management:dashboard')).context
        agenda = {e.id for e in ctx['office_agenda']}
        self.assertIn(self.mine.id, agenda)
        self.assertNotIn(self.other.id, agenda)
        self.assertNotIn(self.deleted.id, agenda)
        self.assertEqual(ctx['week_event_count'], 1)

    def test_admin_dashboard_still_sees_office_but_not_deleted(self) -> None:
        admin = self.make_user('boss', admin=True)
        agenda = {e.id for e in self._client(admin).get(reverse('event_management:dashboard')).context['office_agenda']}
        self.assertTrue({self.mine.id, self.other.id} <= agenda)
        self.assertNotIn(self.deleted.id, agenda)

    def test_calendar_upcoming_respects_scope(self) -> None:
        body = self._client(self.assigned_only).get(reverse('event_management:calendar_upcoming_events_api')).content.decode()
        self.assertIn(str(self.mine.id), body)
        self.assertNotIn(str(self.other.id), body)

    def test_editing_interface_respects_scope(self) -> None:
        client = self._client(self.assigned_only)
        url = lambda e: reverse('event_management:event_editing_interface', kwargs={'event_id': e.id})  # noqa: E731
        self.assertEqual(client.get(url(self.other)).status_code, 404)
        self.assertEqual(client.get(url(self.mine)).status_code, 200)
