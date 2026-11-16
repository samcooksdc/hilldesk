# SPDX-License-Identifier: Apache-2.0
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _
from .models import Office, Role

User = get_user_model()


class RoleAdmin(admin.ModelAdmin):
    """Admin for office-defined Roles."""
    list_display = ('name', 'office', 'slug', 'is_admin', 'is_system', 'user_count')
    list_filter = ('office', 'is_admin', 'is_system')
    search_fields = ('name', 'slug', 'office__name')
    readonly_fields = ('id', 'created', 'modified')
    ordering = ('office', 'order', 'name')

    def user_count(self, obj):
        return obj.users.count()
    user_count.short_description = 'Users'


class OfficeAdmin(admin.ModelAdmin):
    """Admin for the Office model."""
    list_display = ('name', 'created', 'modified', 'user_count')
    search_fields = ('name',)
    readonly_fields = ('id', 'created', 'modified')
    ordering = ('name',)

    fieldsets = (
        (None, {'fields': ('id', 'name')}),
        (_('Event Status Choices'), {
            'fields': ('event_status_choices',),
            'description': 'JSON array of status options with colors. Each item: {"value": "...", "label": "...", "color": "#...", "bg_color": "#...", "is_active": true, "order": 1}'
        }),
        (_('Event Type Choices'), {
            'fields': ('event_type_choices',),
            'description': 'JSON array of type options. Each item: {"value": "...", "label": "...", "is_active": true, "order": 1}'
        }),
        (_('Event Format Choices'), {
            'fields': ('event_format_choices',),
            'description': 'JSON array of format options. Each item: {"value": "...", "label": "...", "is_active": true, "order": 1}'
        }),
        (_('Audit'), {'fields': ('created', 'modified')}),
    )

    def user_count(self, obj):
        return obj.users.count()
    user_count.short_description = 'Users'


class CustomUserAdmin(UserAdmin):
    """Custom admin for the User model with additional fields."""
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        (_('Personal info'), {'fields': ('first_name', 'last_name', 'email')}),
        (_('Office'), {'fields': ('office', 'office_role')}),
        (_('Preferences'), {'fields': ('theme', 'accent_color', 'default_view')}),
        (_('Security'), {'fields': ('mfa_enabled', 'failed_login_attempts', 'account_locked_until')}),
        (_('Permissions'), {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'),
        }),
        (_('Important dates'), {'fields': ('last_login', 'date_joined', 'created', 'modified')}),
    )
    readonly_fields = ('created', 'modified')
    list_display = ('username', 'email', 'first_name', 'last_name', 'office', 'is_staff', 'mfa_enabled')
    list_filter = ('is_staff', 'is_superuser', 'is_active', 'mfa_enabled', 'theme', 'accent_color', 'office')
    search_fields = ('username', 'first_name', 'last_name', 'email')
    ordering = ('username',)
    raw_id_fields = ('office', 'office_role')


admin.site.register(User, CustomUserAdmin)
admin.site.register(Office, OfficeAdmin)
admin.site.register(Role, RoleAdmin)
