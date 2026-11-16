# SPDX-License-Identifier: Apache-2.0
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.conf import settings
import uuid
from .fields import EncryptedCharField, DataClassificationField


class Office(models.Model):
    """
    Office/organization that users belong to.
    Stores customizable event status, type, and format choices.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200, help_text="Office name (e.g., 'Rep. Smith Office')")

    # Office setup tracking
    is_setup_complete = models.BooleanField(
        default=False,
        help_text="Whether office setup wizard has been completed"
    )
    setup_completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the office setup was completed"
    )
    setup_completed_by = models.ForeignKey(
        'User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='offices_setup',
        help_text="User who completed the office setup"
    )

    # Member/Office Information
    member_name = models.CharField(
        max_length=200,
        blank=True,
        default='',
        help_text="Name of the Member of Congress"
    )
    district = models.CharField(
        max_length=100,
        blank=True,
        default='',
        help_text="Congressional district (e.g., 'MI-11')"
    )
    dc_office_address = models.TextField(
        blank=True,
        default='',
        help_text="Washington D.C. office address"
    )
    district_office_address = models.TextField(
        blank=True,
        default='',
        help_text="District office address"
    )

    # Customizable event choices (JSONField)
    # Status choices include colors: [{"value": "...", "label": "...", "color": "#...", "bg_color": "#...", "is_active": true, "order": 1}]
    event_status_choices = models.JSONField(
        default=list,
        help_text="Custom event status options with colors"
    )

    # Type choices (no colors): [{"value": "...", "label": "...", "is_active": true, "order": 1}]
    event_type_choices = models.JSONField(
        default=list,
        help_text="Custom event type options"
    )

    # Format choices (no colors): [{"value": "...", "label": "...", "is_active": true, "order": 1}]
    event_format_choices = models.JSONField(
        default=list,
        help_text="Custom event format options"
    )

    # Default tags for events: [{"value": "...", "label": "...", "color": "#...", "is_active": true}]
    default_tags = models.JSONField(
        default=list,
        help_text="Default tags available for events"
    )

    # Audit fields
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'authentication_office'
        verbose_name = 'Office'
        verbose_name_plural = 'Offices'
        ordering = ['name']

    def __str__(self):
        return self.name

    def get_active_statuses(self):
        """Return only active status choices, sorted by order."""
        statuses = [s for s in self.event_status_choices if s.get('is_active', True)]
        return sorted(statuses, key=lambda x: x.get('order', 999))

    def get_active_types(self):
        """Return only active type choices, sorted by order."""
        types = [t for t in self.event_type_choices if t.get('is_active', True)]
        return sorted(types, key=lambda x: x.get('order', 999))

    def get_active_formats(self):
        """Return only active format choices, sorted by order."""
        formats = [f for f in self.event_format_choices if f.get('is_active', True)]
        return sorted(formats, key=lambda x: x.get('order', 999))

    def get_status_by_value(self, value):
        """Get a status choice by its value."""
        for status in self.event_status_choices:
            if status.get('value') == value:
                return status
        return None

    def get_type_by_value(self, value):
        """Get a type choice by its value."""
        for t in self.event_type_choices:
            if t.get('value') == value:
                return t
        return None

    def get_format_by_value(self, value):
        """Get a format choice by its value."""
        for f in self.event_format_choices:
            if f.get('value') == value:
                return f
        return None

    @classmethod
    def create_with_defaults(cls, name):
        """Create a new office with default choices and default roles."""
        office = cls.objects.create(
            name=name,
            event_status_choices=getattr(settings, 'DEFAULT_EVENT_STATUS_CHOICES', []),
            event_type_choices=getattr(settings, 'DEFAULT_EVENT_TYPE_CHOICES', []),
            event_format_choices=getattr(settings, 'DEFAULT_EVENT_FORMAT_CHOICES', []),
            default_tags=getattr(settings, 'DEFAULT_EVENT_TAGS', []),
        )
        office.create_default_roles()
        return office

    def create_default_roles(self):
        """
        Idempotently create this office's default roles (Admin/Scheduler/Staff).
        Returns a dict mapping slug -> Role. Safe to call repeatedly.
        """
        from .permissions import DEFAULT_ROLE_SPECS
        roles = {}
        for spec in DEFAULT_ROLE_SPECS:
            role, _created = Role.objects.get_or_create(
                office=self,
                slug=spec['slug'],
                defaults={
                    'name': spec['name'],
                    'color': spec['color'],
                    'is_admin': spec['is_admin'],
                    'is_system': spec['is_system'],
                    'order': spec['order'],
                    'description': spec['description'],
                    'permissions': spec['permissions'] or [],
                },
            )
            roles[spec['slug']] = role
        return roles

    def get_admin_role(self):
        """Return the locked admin role for this office (or None)."""
        return self.roles.filter(is_admin=True).first()


class OfficeStaff(models.Model):
    """
    Staff members associated with an office.
    Tracks staff name, position, and legislative areas of responsibility.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    office = models.ForeignKey(
        Office,
        on_delete=models.CASCADE,
        related_name='staff_members',
        help_text="Office this staff member belongs to"
    )
    name = models.CharField(
        max_length=200,
        help_text="Staff member's full name"
    )
    position = models.CharField(
        max_length=200,
        blank=True,
        default='',
        help_text="Staff member's position/title (e.g., 'Legislative Director')"
    )
    email = models.EmailField(
        blank=True,
        default='',
        help_text="Staff member's email address"
    )
    phone = models.CharField(
        max_length=50,
        blank=True,
        default='',
        help_text="Staff member's phone number"
    )
    # Legislative areas as a JSON list: ["Healthcare", "Education", "Defense"]
    legislative_areas = models.JSONField(
        default=list,
        help_text="Legislative areas of responsibility"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Whether this staff member is currently active"
    )
    is_member_of_congress = models.BooleanField(
        default=False,
        help_text="Whether this staff member is the Member of Congress for this office "
                  "(at most one per office)"
    )
    order = models.IntegerField(
        default=0,
        help_text="Display order for staff listing"
    )

    # Audit fields
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'authentication_officestaff'
        verbose_name = 'Office Staff'
        verbose_name_plural = 'Office Staff'
        ordering = ['order', 'name']

    def __str__(self):
        if self.position:
            return f"{self.name} - {self.position}"
        return self.name


class Role(models.Model):
    """
    An office-defined role with a customizable set of permissions.

    Every office has one locked ``admin`` role (``is_admin=True``) that grants
    every permission and cannot be edited or deleted. ``Scheduler`` and ``Staff``
    are seeded as editable defaults (``is_system=True``). Admins may also create
    fully custom roles (e.g. "Intern", "Press").

    The permission *catalog* lives in ``apps.authentication.permissions``;
    ``permissions`` here stores the subset of permission keys this role grants.
    """
    DEFAULT_COLOR = '#64748b'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    office = models.ForeignKey(
        'Office',
        on_delete=models.CASCADE,
        related_name='roles',
        help_text="Office this role belongs to"
    )
    name = models.CharField(max_length=100, help_text="Role name (e.g., 'Scheduler', 'Intern')")
    slug = models.SlugField(
        max_length=120,
        help_text="Stable identifier for this role, unique within the office"
    )
    description = models.TextField(blank=True, default='', help_text="What this role is for")
    permissions = models.JSONField(
        default=list,
        blank=True,
        help_text="List of permission keys this role grants (see permissions.py catalog)"
    )
    is_admin = models.BooleanField(
        default=False,
        help_text="Locked built-in admin role: grants all permissions, cannot be edited or deleted"
    )
    is_system = models.BooleanField(
        default=False,
        help_text="Seeded default role (admin/scheduler/staff). Editable unless is_admin."
    )
    color = models.CharField(
        max_length=20,
        default=DEFAULT_COLOR,
        help_text="Badge color for this role"
    )
    order = models.IntegerField(default=0, help_text="Display order")

    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'authentication_role'
        verbose_name = 'Role'
        verbose_name_plural = 'Roles'
        ordering = ['order', 'name']
        unique_together = [('office', 'slug')]

    def __str__(self):
        return f"{self.name} ({self.office.name})"

    def get_permissions(self):
        """Return the set of permission keys this role grants."""
        from .permissions import Permissions
        if self.is_admin:
            return Permissions.all_permissions()
        return set(self.permissions or [])

    def has_permission(self, permission):
        """Check whether this role grants a given permission key."""
        if self.is_admin:
            return True
        return permission in (self.permissions or [])

    @property
    def is_deletable(self):
        """Admin and other locked roles cannot be deleted."""
        return not self.is_admin

    @property
    def is_editable(self):
        """Admin role permissions are locked; everything else is editable."""
        return not self.is_admin


class User(AbstractUser):
    """
    Custom User model for HillDesk.
    Extends Django's AbstractUser with additional fields for security and preferences.
    """
    # Role choices for permission system
    ROLE_CHOICES = [
        ('admin', 'Admin'),
        ('scheduler', 'Scheduler'),
        ('staff', 'Staff'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Role-based access control.
    # `office_role` is the source of truth for permissions. `role` is a
    # denormalized slug kept in sync with office_role.slug so legacy badge/query
    # code keeps working (and as a fallback before office_role is assigned).
    role = models.CharField(
        max_length=50,
        default='staff',
        help_text="Denormalized role slug (synced from office_role). Source of truth is office_role."
    )
    office_role = models.ForeignKey(
        'Role',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='users',
        help_text="Office-defined role granting this user's permissions"
    )

    # Link to staff profile (for staff assigned to events)
    staff_profile = models.OneToOneField(
        'OfficeStaff',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='user_account',
        help_text="Link to OfficeStaff profile for event assignment matching"
    )

    # User preferences
    theme = models.CharField(
        max_length=10,
        choices=[('light', 'Light'), ('dark', 'Dark')],
        default='light'
    )
    accent_color = models.CharField(
        max_length=10,
        choices=[('blue', 'Blue'), ('red', 'Red')],
        default='blue'
    )
    default_view = models.CharField(
        max_length=10,
        choices=[('list', 'List'), ('calendar', 'Calendar')],
        default='list'
    )
    
    # Notification preferences
    notify_email_processing = models.BooleanField(
        default=True,
        help_text="Receive notifications when new emails are processed"
    )
    notify_event_reminders = models.BooleanField(
        default=True,
        help_text="Receive reminders for upcoming events"
    )
    notify_status_changes = models.BooleanField(
        default=True,
        help_text="Receive notifications when event statuses change"
    )
    notify_system_updates = models.BooleanField(
        default=False,
        help_text="Receive notifications about system updates"
    )
    
    # Azure AD / SSO Integration
    azure_ad_id = models.CharField(
        max_length=255,
        unique=True,
        null=True,
        blank=True,
        help_text="Azure AD Object ID for SSO users (populated on first SSO login)"
    )

    # Office association
    office = models.ForeignKey(
        'Office',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='users',
        help_text="Office this user belongs to"
    )

    # Saved filter preset
    saved_filter_preset = models.JSONField(
        default=dict,
        blank=True,
        help_text="Saved filter preset for the schedule page"
    )

    # Security fields
    mfa_enabled = models.BooleanField(default=False)
    mfa_secret = EncryptedCharField(max_length=32, blank=True, help_text="MFA secret key (encrypted)")
    failed_login_attempts = models.IntegerField(default=0)
    account_locked_until = models.DateTimeField(null=True, blank=True)
    
    # Audit fields
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)
    data_classification = DataClassificationField()
    
    class Meta:
        db_table = 'auth_user'
        verbose_name = 'User'
        verbose_name_plural = 'Users'

    def __str__(self):
        return self.username

    def get_display_name(self):
        """
        Get the user's display name, preferring OfficeStaff.name (settings)
        over User.first_name/last_name (which may be stale).
        """
        if self.staff_profile_id:
            try:
                return self.staff_profile.name
            except OfficeStaff.DoesNotExist:
                pass
        return self.get_full_name() or self.username

    def get_display_initials(self):
        """Get initials from the display name (e.g. 'Parker Wilkinson' -> 'PW')."""
        name = self.get_display_name()
        parts = name.split()
        if len(parts) >= 2:
            return (parts[0][0] + parts[-1][0]).upper()
        return name[0].upper() if name else '?'

    # Role-based permission helper methods.
    # All of these delegate to the Permissions catalog via office_role so they
    # work for custom roles, not just the legacy admin/scheduler/staff slugs.
    @property
    def is_office_admin(self):
        """Check if user holds a locked admin role."""
        if self.office_role_id and self.office_role:
            return self.office_role.is_admin
        return self.role == 'admin'

    @property
    def can_manage_roles(self):
        """Check if user can assign/manage roles (admin only)."""
        from .permissions import Permissions
        return Permissions.can_manage_roles(self)

    @property
    def can_change_event_status(self):
        """Check if user can change event status."""
        from .permissions import Permissions
        return Permissions.can_change_status(self)

    @property
    def can_approve_suggestions(self):
        """Check if user can approve staff change suggestions."""
        from .permissions import Permissions
        return Permissions.can_approve_suggestions(self)

    @property
    def can_configure_approval_routing(self):
        """Check if user can configure approval routing."""
        from .permissions import Permissions
        return Permissions.can_configure_approvals(self)

    def assign_role(self, role):
        """Assign an office Role and keep the denormalized `role` slug in sync."""
        self.office_role = role
        self.role = role.slug if role else 'staff'

    def can_edit_event_directly(self, event):
        """
        Check if user can edit an event directly (without creating a suggestion).
        Delegates to the Permissions catalog.
        """
        from .permissions import Permissions
        return Permissions.can_edit_event(self, event)

    def is_assigned_to_event(self, event):
        """Check if user is assigned to an event's staff list."""
        if not event.staff:
            return False

        # Check by staff_profile link
        if self.staff_profile:
            staff_name = self.staff_profile.name.lower()
            staff_email = self.staff_profile.email.lower() if self.staff_profile.email else ''
            for staff_entry in event.staff:
                if isinstance(staff_entry, dict):
                    entry_name = staff_entry.get('name', '').lower()
                    entry_email = staff_entry.get('email', '').lower()
                    if staff_name == entry_name or (staff_email and staff_email == entry_email):
                        return True
                elif isinstance(staff_entry, str):
                    if staff_name == staff_entry.lower():
                        return True

        # Also check by user's name and email
        user_name = self.get_full_name().lower() or self.username.lower()
        user_email = self.email.lower() if self.email else ''

        for staff_entry in event.staff:
            if isinstance(staff_entry, dict):
                entry_name = staff_entry.get('name', '').lower()
                entry_email = staff_entry.get('email', '').lower()
                if user_name == entry_name or (user_email and user_email == entry_email):
                    return True
            elif isinstance(staff_entry, str):
                if user_name == staff_entry.lower():
                    return True

        return False

    def get_role_display_name(self):
        """Get human-readable role name (prefers the office role's name)."""
        if self.office_role_id and self.office_role:
            return self.office_role.name
        return dict(self.ROLE_CHOICES).get(self.role, self.role)


class UserFilterPreset(models.Model):
    """
    A named, user-level saved filter preset for the schedule/calendar views.

    Stored per-user (not per-office). The ``data`` blob holds the same shape
    the schedule/calendar front-ends use for a filter preset (status, type,
    format, staff, source, quick-filter toggles, sort, past-event range, etc.).
    A user may flag one preset as the default, which is auto-applied on load.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='filter_presets',
    )
    name = models.CharField(max_length=100, help_text="User-facing preset name")
    data = models.JSONField(
        default=dict,
        blank=True,
        help_text="Filter selections captured by this preset",
    )
    is_default = models.BooleanField(
        default=False,
        help_text="Auto-apply this preset when the schedule/calendar loads",
    )
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'auth_user_filter_preset'
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'name'],
                name='unique_user_filter_preset_name',
            ),
        ]

    def __str__(self):
        return f"{self.user} – {self.name}"


class UserRoutingPreset(models.Model):
    """
    A named, user-level saved approval-routing preset for the event editing
    routing builder.

    Stored per-user (not per-office). The ``data`` blob holds an approval
    routing config (``{"stages": [...]}``) in the same shape the routing builder
    produces, minus the creator stage (which is always prepended server-side
    when a route is applied to an event). A user may flag one preset as the
    default, which is pre-loaded when configuring routing on a new event.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='routing_presets',
    )
    name = models.CharField(max_length=100, help_text="User-facing preset name")
    data = models.JSONField(
        default=dict,
        blank=True,
        help_text="Approval routing config captured by this preset",
    )
    is_default = models.BooleanField(
        default=False,
        help_text="Pre-load this route when configuring a new event's routing",
    )
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'auth_user_routing_preset'
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'name'],
                name='unique_user_routing_preset_name',
            ),
        ]

    def __str__(self):
        return f"{self.user} – {self.name}"
