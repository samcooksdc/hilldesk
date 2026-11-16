# SPDX-License-Identifier: Apache-2.0
"""
Permission utilities for HillDesk role-based access control.

Roles are now **office-defined**. Each office has a set of ``Role`` objects
(``apps.authentication.models.Role``); every role carries an explicit list of
permission keys. The ``admin`` role is a locked, built-in role that implicitly
grants every permission and cannot be edited or deleted. All other roles
(``Scheduler``, ``Staff``, and any custom role like ``Intern``) are fully
customizable per office.

This module is the single source of truth for the **permission catalog** (the
set of capabilities a role can grant) and for the helper logic that checks them.

Usage:
    from apps.authentication.permissions import Permissions

    # Check a specific permission
    if Permissions.has_permission(user, Permissions.ASSIGN_ROLES):
        ...

    # Scope an event queryset to what the user is allowed to see
    qs = Permissions.scope_events_queryset(user, Event.objects.all())

    # Check if an edit must go through review (suggestion) mode
    if Permissions.staff_edit_requires_review(user, event):
        ...
"""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.authentication.models import User
    from apps.event_management.models import Event

logger = logging.getLogger('apps.authentication')


class Permissions:
    """
    Centralized permission constants, catalog, and checking utilities.

    The permission *catalog* (``PERMISSION_GROUPS``) defines every capability a
    role can be granted. ``ADMIN_ONLY_PERMISSIONS`` are never shown as toggles —
    only the locked Admin role holds them. Everything else is selectable when an
    admin builds a custom role.
    """

    # ------------------------------------------------------------------
    # Permission constants
    # ------------------------------------------------------------------
    # Event access
    VIEW_ALL_EVENTS = 'view_all_events'
    VIEW_ASSIGNED_EVENTS = 'view_assigned_events'
    EDIT_ALL_EVENTS = 'edit_all_events'
    EDIT_ASSIGNED_EVENTS = 'edit_assigned_events'

    # Event workflow
    CREATE_EVENTS = 'create_events'
    CHANGE_EVENT_STATUS = 'change_event_status'
    ARCHIVE_DELETE_EVENTS = 'archive_delete_events'
    APPROVE_STAFF_CHANGES = 'approve_staff_changes'
    CONFIGURE_APPROVAL_ROUTING = 'configure_approval_routing'

    # Inbox / email review
    VIEW_INBOX = 'view_inbox'
    PROCESS_INBOX = 'process_inbox'

    # Exports & templates
    EXPORT_EVENTS = 'export_events'
    MANAGE_EMAIL_TEMPLATES = 'manage_email_templates'
    MANAGE_EXPORT_TEMPLATES = 'manage_export_templates'

    # Office settings & staff
    MANAGE_OFFICE_SETTINGS = 'manage_office_settings'
    MANAGE_STAFF = 'manage_staff'

    # Admin-only (locked, not selectable as a toggle)
    ASSIGN_ROLES = 'assign_roles'
    COMPLETE_OFFICE_SETUP = 'complete_office_setup'

    # Backward-compatible aliases (old constant names → new keys)
    EDIT_ANY_EVENT = EDIT_ALL_EVENTS

    # ------------------------------------------------------------------
    # Permission catalog (grouped for the role-builder UI)
    # ------------------------------------------------------------------
    # Each group: {'key', 'label', 'permissions': [(key, label, help), ...]}
    PERMISSION_GROUPS = [
        {
            'key': 'event_access',
            'label': 'Event access',
            'permissions': [
                (VIEW_ALL_EVENTS, 'View all events', 'See every event in the office.'),
                (VIEW_ASSIGNED_EVENTS, 'View assigned events',
                 'See only events the user is assigned to or on the approval routing for.'),
                (EDIT_ALL_EVENTS, 'Edit all events', 'Edit any event directly.'),
                (EDIT_ASSIGNED_EVENTS, 'Edit assigned events',
                 'Edit assigned events directly; edits to other events go to review.'),
            ],
        },
        {
            'key': 'event_workflow',
            'label': 'Event workflow',
            'permissions': [
                (CREATE_EVENTS, 'Create events', 'Create new events.'),
                (CHANGE_EVENT_STATUS, 'Change event status', 'Move events between statuses.'),
                (ARCHIVE_DELETE_EVENTS, 'Archive / delete events', 'Archive or delete events.'),
                (APPROVE_STAFF_CHANGES, 'Approve change suggestions',
                 'Approve or reject change suggestions from staff.'),
                (CONFIGURE_APPROVAL_ROUTING, 'Configure approval routing',
                 'Set up the approval chain for events.'),
            ],
        },
        {
            'key': 'inbox',
            'label': 'Inbox / email review',
            'permissions': [
                (VIEW_INBOX, 'View inbox', 'Access the email inbox / human-review queue.'),
                (PROCESS_INBOX, 'Process inbox',
                 'Approve or reject AI-extracted events from the inbox.'),
            ],
        },
        {
            'key': 'exports',
            'label': 'Exports & templates',
            'permissions': [
                (EXPORT_EVENTS, 'Export events', 'Export events and calendars.'),
                (MANAGE_EMAIL_TEMPLATES, 'Manage email templates', 'Create and edit email templates.'),
                (MANAGE_EXPORT_TEMPLATES, 'Manage export templates',
                 'Create and edit export templates.'),
            ],
        },
        {
            'key': 'office',
            'label': 'Office settings & staff',
            'permissions': [
                (MANAGE_OFFICE_SETTINGS, 'Manage office settings',
                 'Edit statuses, types, formats, tags, and other office settings.'),
                (MANAGE_STAFF, 'Manage staff', 'Add, edit, and remove office staff records.'),
            ],
        },
    ]

    # Permissions only the locked Admin role holds; never offered as toggles.
    ADMIN_ONLY_PERMISSIONS = {
        ASSIGN_ROLES,
        COMPLETE_OFFICE_SETUP,
    }

    # ------------------------------------------------------------------
    # Permission dependencies
    # ------------------------------------------------------------------
    # Each key REQUIRES the listed permissions to be meaningful. Enforced both
    # in the role-builder UI (checking a permission auto-checks its requirements;
    # unchecking a requirement auto-unchecks everything that depends on it) and
    # server-side via expand_permissions() so a stored role can never hold a
    # capability without its prerequisites.
    #
    # Rationale:
    #   - You can't edit what you can't see  -> edit_* requires the matching view_*
    #   - "all" implies "assigned"           -> *_all requires *_assigned
    #   - Acting on events implies seeing them-> workflow perms require view_assigned
    #   - Processing the inbox implies viewing it -> process_inbox requires view_inbox
    PERMISSION_REQUIRES = {
        VIEW_ALL_EVENTS: [VIEW_ASSIGNED_EVENTS],
        EDIT_ASSIGNED_EVENTS: [VIEW_ASSIGNED_EVENTS],
        EDIT_ALL_EVENTS: [EDIT_ASSIGNED_EVENTS, VIEW_ALL_EVENTS],
        CREATE_EVENTS: [VIEW_ASSIGNED_EVENTS],
        CHANGE_EVENT_STATUS: [VIEW_ASSIGNED_EVENTS],
        ARCHIVE_DELETE_EVENTS: [VIEW_ASSIGNED_EVENTS],
        APPROVE_STAFF_CHANGES: [VIEW_ASSIGNED_EVENTS],
        CONFIGURE_APPROVAL_ROUTING: [VIEW_ASSIGNED_EVENTS],
        PROCESS_INBOX: [VIEW_INBOX],
    }

    @classmethod
    def expand_permissions(cls, permission_keys) -> set:
        """
        Return the dependency closure of a permission set: every selected
        permission plus all of its (transitive) requirements. Guarantees a role
        can't hold a capability without its prerequisites.
        """
        result = set(permission_keys)
        changed = True
        while changed:
            changed = False
            for key in list(result):
                for required in cls.PERMISSION_REQUIRES.get(key, ()):
                    if required not in result:
                        result.add(required)
                        changed = True
        return result

    @classmethod
    def toggleable_permissions(cls) -> list:
        """Flat list of permission keys that can be assigned to a custom role."""
        keys = []
        for group in cls.PERMISSION_GROUPS:
            keys.extend(perm[0] for perm in group['permissions'])
        return keys

    @classmethod
    def all_permissions(cls) -> set:
        """Every permission key, including admin-only ones."""
        return set(cls.toggleable_permissions()) | cls.ADMIN_ONLY_PERMISSIONS

    @classmethod
    def permission_label(cls, key: str) -> str:
        """Human-readable label for a permission key."""
        for group in cls.PERMISSION_GROUPS:
            for perm_key, label, _help in group['permissions']:
                if perm_key == key:
                    return label
        return key

    # ------------------------------------------------------------------
    # Legacy role → permission mapping
    # ------------------------------------------------------------------
    # Used ONLY to (a) seed the default per-office roles in the data migration
    # and (b) fall back when a user has no office_role assigned yet.
    LEGACY_ROLE_PERMISSIONS = {
        # 'admin' is filled in after the class body with the full catalog.
        'admin': None,
        'scheduler': {
            VIEW_ALL_EVENTS,
            VIEW_ASSIGNED_EVENTS,
            EDIT_ALL_EVENTS,
            EDIT_ASSIGNED_EVENTS,
            CREATE_EVENTS,
            CHANGE_EVENT_STATUS,
            ARCHIVE_DELETE_EVENTS,
            APPROVE_STAFF_CHANGES,
            CONFIGURE_APPROVAL_ROUTING,
            VIEW_INBOX,
            PROCESS_INBOX,
            EXPORT_EVENTS,
            MANAGE_EMAIL_TEMPLATES,
            MANAGE_EXPORT_TEMPLATES,
        },
        'staff': {
            VIEW_ASSIGNED_EVENTS,
            EDIT_ASSIGNED_EVENTS,
            VIEW_INBOX,
        },
    }

    # ------------------------------------------------------------------
    # Core checks
    # ------------------------------------------------------------------
    @classmethod
    def has_permission(cls, user: 'User', permission: str) -> bool:
        """
        Check if a user has a specific permission.

        Reads the user's ``office_role`` (the source of truth). Falls back to the
        legacy role-name mapping if the user has no office_role assigned yet.
        """
        if not user or not user.is_authenticated:
            return False

        office_role = getattr(user, 'office_role', None)
        if office_role is not None:
            return office_role.has_permission(permission)

        # Fallback: legacy role slug mapping (pre-migration safety)
        role = getattr(user, 'role', 'staff')
        if role == 'admin':
            return permission in cls.all_permissions()
        return permission in cls.LEGACY_ROLE_PERMISSIONS.get(role, set())

    @classmethod
    def can_view_events(cls, user: 'User') -> bool:
        """True if the user can view events at all (all or assigned)."""
        return (
            cls.has_permission(user, cls.VIEW_ALL_EVENTS)
            or cls.has_permission(user, cls.VIEW_ASSIGNED_EVENTS)
        )

    @classmethod
    def scope_events_queryset(cls, user: 'User', queryset):
        """
        Restrict an Event queryset to what ``user`` is allowed to see.

        - ``view_all_events``      → unchanged queryset
        - ``view_assigned_events`` → events the user is assigned to OR is an
                                      approver on (reuses _user_editable_event_filter)
        - neither                  → empty queryset
        """
        if cls.has_permission(user, cls.VIEW_ALL_EVENTS):
            return queryset
        if cls.has_permission(user, cls.VIEW_ASSIGNED_EVENTS):
            from apps.api.views import _user_editable_event_filter
            return queryset.filter(_user_editable_event_filter(user))
        return queryset.none()

    @classmethod
    def can_edit_event(cls, user: 'User', event: 'Event') -> bool:
        """
        Check if user can edit an event directly (without suggestion mode).

        Users with ``edit_all_events`` can always edit. Otherwise the user can
        edit if they have ``edit_assigned_events`` and are assigned to (or an
        approver on) the event.
        """
        if not user or not user.is_authenticated:
            return False

        if cls.has_permission(user, cls.EDIT_ALL_EVENTS):
            return True

        if not cls.has_permission(user, cls.EDIT_ASSIGNED_EVENTS):
            return False

        if user.is_assigned_to_event(event):
            return True

        from apps.event_management.models import EventApproval
        if EventApproval.objects.filter(event=event, approver=user).exists():
            return True

        return False

    @classmethod
    def staff_edit_requires_review(cls, user: 'User', event: 'Event') -> bool:
        """
        Check if a user's edit must be routed through scheduler review.

        Returns True when the user lacks ``edit_all_events`` and is not assigned
        to (or an approver on) the event — i.e. they can only suggest changes.
        """
        if not user or not user.is_authenticated:
            return True

        # Users who can edit any event never need review
        if cls.has_permission(user, cls.EDIT_ALL_EVENTS):
            return False

        # Assigned (or approver) users editing their own events don't need review
        if cls.can_edit_event(user, event):
            return False

        return True

    @classmethod
    def can_change_status(cls, user: 'User') -> bool:
        """Check if user can change event status."""
        return cls.has_permission(user, cls.CHANGE_EVENT_STATUS)

    @classmethod
    def can_approve_suggestions(cls, user: 'User') -> bool:
        """Check if user can approve/reject staff change suggestions."""
        return cls.has_permission(user, cls.APPROVE_STAFF_CHANGES)

    @classmethod
    def can_configure_approvals(cls, user: 'User') -> bool:
        """Check if user can configure approval routing for events."""
        return cls.has_permission(user, cls.CONFIGURE_APPROVAL_ROUTING)

    @classmethod
    def can_manage_roles(cls, user: 'User') -> bool:
        """Check if user can create roles and assign them (Admin only)."""
        return cls.has_permission(user, cls.ASSIGN_ROLES)

    @classmethod
    def can_complete_setup(cls, user: 'User') -> bool:
        """Check if user can complete the office setup wizard (Admin only)."""
        return cls.has_permission(user, cls.COMPLETE_OFFICE_SETUP)

    @classmethod
    def get_user_permissions(cls, user: 'User') -> set:
        """Get the full set of permission keys a user holds."""
        if not user or not user.is_authenticated:
            return set()

        office_role = getattr(user, 'office_role', None)
        if office_role is not None:
            return office_role.get_permissions()

        role = getattr(user, 'role', 'staff')
        if role == 'admin':
            return cls.all_permissions()
        return set(cls.LEGACY_ROLE_PERMISSIONS.get(role, set()))

    @classmethod
    def get_permissions_dict(cls, user: 'User') -> dict:
        """
        Get a dictionary of permission flags for template/API context.
        """
        if not user or not user.is_authenticated:
            return {
                'permission_keys': set(),
                'can_assign_roles': False,
                'can_change_status': False,
                'can_approve_suggestions': False,
                'can_configure_approvals': False,
                'can_view_all_events': False,
                'can_view_assigned_events': False,
                'can_edit_any_event': False,
                'can_edit_assigned_events': False,
                'can_create_events': False,
                'can_archive_delete_events': False,
                'can_view_inbox': False,
                'can_process_inbox': False,
                'can_export_events': False,
                'can_manage_office': False,
                'can_manage_staff': False,
                'can_manage_templates': False,
                'can_manage_export_templates': False,
                'role': None,
                'role_display': None,
            }

        keys = cls.get_user_permissions(user)

        def has(perm):
            return perm in keys

        return {
            'permission_keys': keys,
            'can_assign_roles': has(cls.ASSIGN_ROLES),
            'can_change_status': has(cls.CHANGE_EVENT_STATUS),
            'can_approve_suggestions': has(cls.APPROVE_STAFF_CHANGES),
            'can_configure_approvals': has(cls.CONFIGURE_APPROVAL_ROUTING),
            'can_view_all_events': has(cls.VIEW_ALL_EVENTS),
            'can_view_assigned_events': has(cls.VIEW_ASSIGNED_EVENTS),
            'can_edit_any_event': has(cls.EDIT_ALL_EVENTS),
            'can_edit_assigned_events': has(cls.EDIT_ASSIGNED_EVENTS),
            'can_create_events': has(cls.CREATE_EVENTS),
            'can_archive_delete_events': has(cls.ARCHIVE_DELETE_EVENTS),
            'can_view_inbox': has(cls.VIEW_INBOX),
            'can_process_inbox': has(cls.PROCESS_INBOX),
            'can_export_events': has(cls.EXPORT_EVENTS),
            'can_manage_office': has(cls.MANAGE_OFFICE_SETTINGS),
            'can_manage_staff': has(cls.MANAGE_STAFF),
            'can_manage_templates': has(cls.MANAGE_EMAIL_TEMPLATES),
            'can_manage_export_templates': has(cls.MANAGE_EXPORT_TEMPLATES),
            'role': user.role,
            'role_display': user.get_role_display_name(),
        }


# The admin legacy mapping is the full catalog; set it after the class body so
# it can reference Permissions.all_permissions().
Permissions.LEGACY_ROLE_PERMISSIONS['admin'] = Permissions.all_permissions()


# Specs for the default per-office roles seeded on office creation and in the
# data migration. `permissions` is None for the admin role (it implicitly grants
# everything via is_admin). Used by Office.create_default_roles() and the seed
# data migration (which inlines the same data to stay self-contained).
DEFAULT_ROLE_SPECS = [
    {
        'slug': 'admin',
        'name': 'Admin',
        'color': '#dc2626',
        'is_admin': True,
        'is_system': True,
        'order': 0,
        'description': 'Full access. Manages roles, office settings, and all events.',
        'permissions': None,  # locked: all permissions
    },
    {
        'slug': 'scheduler',
        'name': 'Scheduler',
        'color': '#2563eb',
        'is_admin': False,
        'is_system': True,
        'order': 1,
        'description': 'Manages events, status, approvals, inbox, and templates.',
        'permissions': sorted(Permissions.LEGACY_ROLE_PERMISSIONS['scheduler']),
    },
    {
        'slug': 'staff',
        'name': 'Staff',
        'color': '#22c55e',
        'is_admin': False,
        'is_system': True,
        'order': 2,
        'description': 'Views and edits assigned events. Other edits go to review.',
        'permissions': sorted(Permissions.LEGACY_ROLE_PERMISSIONS['staff']),
    },
]


# Convenience functions for DRF permission classes
def is_admin(user: 'User') -> bool:
    """Check if user is an office admin (holds a locked admin role)."""
    office_role = getattr(user, 'office_role', None)
    if office_role is not None:
        return office_role.is_admin
    return getattr(user, 'role', None) == 'admin'


def is_admin_or_scheduler(user: 'User') -> bool:
    """
    Deprecated shape kept for compatibility: true if the user can edit any
    event (the capability the old admin/scheduler check guarded).
    """
    return Permissions.has_permission(user, Permissions.EDIT_ALL_EVENTS)
