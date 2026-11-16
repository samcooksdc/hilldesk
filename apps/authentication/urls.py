# SPDX-License-Identifier: Apache-2.0
"""
Authentication URL configuration for HillDesk.

In production (USE_SSO=True), OIDC URLs are included for Azure AD integration.
In development (USE_SSO=False), only local Django auth URLs are used.
"""
from django.urls import path, include
from django.conf import settings
from . import views

app_name = 'authentication'

urlpatterns = [
    # Authentication
    path('login/', views.LoginView.as_view(), name='login'),
    path('logout/', views.LogoutView.as_view(), name='logout'),

    # Multi-Factor Authentication
    path('mfa/verify/', views.MFAVerificationView.as_view(), name='mfa_verify'),
    path('mfa/setup/', views.MFASetupView.as_view(), name='mfa_setup'),
    path('mfa/disable/', views.MFADisableView.as_view(), name='mfa_disable'),

    # User Management
    path('profile/', views.ProfileView.as_view(), name='profile'),
    path('preferences/', views.UserPreferencesView.as_view(), name='preferences'),
    path('password/change/', views.PasswordChangeView.as_view(), name='password_change'),

    # Office Setup and Role Management (Admin only)
    path('office/setup/', views.OfficeSetupWizardView.as_view(), name='office_setup'),
    path('roles/', views.RoleManagementView.as_view(), name='role_management'),
    path('roles/create/', views.RoleCreateView.as_view(), name='role_create'),
    path('roles/<uuid:role_id>/edit/', views.RoleEditView.as_view(), name='role_edit'),
    path('roles/<uuid:role_id>/delete/', views.RoleDeleteView.as_view(), name='role_delete'),
    path('roles/staff-profiles/', views.StaffProfileLinkView.as_view(), name='staff_profile_link'),
]

# Add OIDC URLs when SSO is enabled (production)
# These URLs are provided by mozilla-django-oidc for Azure AD integration
if getattr(settings, 'USE_SSO', False):
    try:
        urlpatterns += [
            path('oidc/', include('mozilla_django_oidc.urls')),
        ]
    except ImportError:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(
            "USE_SSO is True but mozilla-django-oidc is not installed. "
            "OIDC URLs will not be available."
        )