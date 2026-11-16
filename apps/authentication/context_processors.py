# SPDX-License-Identifier: Apache-2.0
"""
Authentication context processors for HillDesk.
Makes authentication-related data available in templates.
"""

from django.conf import settings
from .permissions import Permissions


def authentication_context(request):
    """
    Add authentication-related context variables to the template context.
    """
    context = {
        'app_name': 'HillDesk',
        'auth_settings': getattr(settings, 'AUTH_SETTINGS', {}),
    }

    # Add user preferences if user is authenticated
    if request.user.is_authenticated:
        context.update({
            'user_theme': request.user.theme,
            'user_accent_color': request.user.accent_color,
            'user_default_view': request.user.default_view,
            'mfa_enabled': request.user.mfa_enabled,
        })

        # Add office customization choices for CSS variable generation
        office = getattr(request.user, 'office', None)
        if office:
            context['office'] = office
            context['office_status_choices'] = office.event_status_choices
            context['office_type_choices'] = office.event_type_choices
            context['office_format_choices'] = office.event_format_choices
            context['office_setup_complete'] = office.is_setup_complete

    return context


def user_permissions(request):
    """
    Add user role and permission context variables to the template context.

    Provides:
    - user_role: Current user's role (admin/scheduler/staff)
    - user_role_display: Human-readable role name
    - can_change_status: Whether user can change event status
    - can_assign_roles: Whether user can assign roles (admin only)
    - can_approve_suggestions: Whether user can approve staff suggestions
    - can_configure_approvals: Whether user can configure approval routing
    - can_edit_any_event: Whether user can edit any event directly
    - can_manage_office: Whether user can manage office settings
    - is_office_admin: Boolean for admin role check
    - is_scheduler: Boolean for scheduler role check
    - is_staff_role: Boolean for staff role check
    """
    if request.user.is_authenticated:
        # Get permissions dictionary from Permissions class
        permissions_dict = Permissions.get_permissions_dict(request.user)

        # Settings tabs this user can actually reach, in display order, for the
        # global command palette (keyboard-nav.js). Mirrors the gating in
        # settings_redesign.html. The temporary DEMO tab is intentionally
        # excluded so it never shows up in navigation.
        settings_nav_tabs = []
        if permissions_dict['can_manage_office']:
            settings_nav_tabs.append({'label': 'Customization', 'tab': 'customization'})
        if (permissions_dict['can_manage_templates']
                or permissions_dict['can_manage_export_templates']):
            settings_nav_tabs.append({'label': 'Templates', 'tab': 'templates'})
        settings_nav_tabs += [
            {'label': 'Profile', 'tab': 'profile'},
            {'label': 'Notifications', 'tab': 'notifications'},
            {'label': 'Security', 'tab': 'security'},
            {'label': 'Deleted Events', 'tab': 'deleted-events'},
        ]

        return {
            'settings_nav_tabs': settings_nav_tabs,
            # Role information
            'user_role': permissions_dict['role'],
            'user_role_display': permissions_dict['role_display'],

            # Raw permission-key set so templates can check arbitrary perms,
            # e.g. {% if 'view_inbox' in user_permission_keys %}
            'user_permission_keys': permissions_dict['permission_keys'],

            # Permission flags
            'can_change_status': permissions_dict['can_change_status'],
            'can_assign_roles': permissions_dict['can_assign_roles'],
            'can_approve_suggestions': permissions_dict['can_approve_suggestions'],
            'can_configure_approvals': permissions_dict['can_configure_approvals'],
            'can_view_all_events': permissions_dict['can_view_all_events'],
            'can_view_assigned_events': permissions_dict['can_view_assigned_events'],
            'can_edit_any_event': permissions_dict['can_edit_any_event'],
            'can_edit_assigned_events': permissions_dict['can_edit_assigned_events'],
            'can_create_events': permissions_dict['can_create_events'],
            'can_archive_delete_events': permissions_dict['can_archive_delete_events'],
            'can_view_inbox': permissions_dict['can_view_inbox'],
            'can_process_inbox': permissions_dict['can_process_inbox'],
            'can_export_events': permissions_dict['can_export_events'],
            'can_manage_office': permissions_dict['can_manage_office'],
            'can_manage_staff': permissions_dict['can_manage_staff'],
            'can_manage_templates': permissions_dict['can_manage_templates'],
            'can_manage_export_templates': permissions_dict['can_manage_export_templates'],

            # Role boolean checks (for template convenience)
            'is_office_admin': getattr(request.user, 'is_office_admin', False),
        }

    return {
        'settings_nav_tabs': [],
        'user_role': None,
        'user_role_display': None,
        'user_permission_keys': set(),
        'can_change_status': False,
        'can_assign_roles': False,
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
        'is_office_admin': False,
    }