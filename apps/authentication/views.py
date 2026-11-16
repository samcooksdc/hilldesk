# SPDX-License-Identifier: Apache-2.0
import logging
import qrcode
import io
import base64
from django.shortcuts import redirect, get_object_or_404
from django.views.generic import TemplateView, FormView, View
from django.contrib.auth.views import LoginView as DjangoLoginView, LogoutView as DjangoLogoutView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth import login
from django.contrib import messages
from django.urls import reverse_lazy
from django.utils import timezone
from django.conf import settings
from django.contrib.auth import get_user_model
import pyotp
from .forms import (
    CustomAuthenticationForm,
    MFASetupForm,
    MFAVerificationForm,
    UserPreferencesForm,
    PasswordChangeForm,
    OfficeSetupForm,
    RoleAssignmentForm,
    RoleForm,
)
from .mixins import MFARequiredMixin, SecurityAuditMixin, OfficeAdminRequiredMixin
from .utils import generate_mfa_secret, verify_mfa_token
from .permissions import Permissions

User = get_user_model()
logger = logging.getLogger('apps.authentication')
security_logger = logging.getLogger('security_audit')


class LoginView(SecurityAuditMixin, DjangoLoginView):
    """
    Custom login view with security enhancements.
    Supports OAuth2/OpenID Connect and MFA.

    In production (USE_SSO=True), this view redirects to Azure AD OIDC.
    In development (USE_SSO=False), this view shows the local login form.
    """
    template_name = 'authentication/login.html'
    form_class = CustomAuthenticationForm
    redirect_authenticated_user = True

    def dispatch(self, request, *args, **kwargs):
        """
        Handle SSO redirect before showing local login form.

        If USE_SSO is True (production), redirect to OIDC authentication.
        Otherwise, show the local Django login form.
        """
        # Check if SSO is enabled
        use_sso = getattr(settings, 'USE_SSO', False)

        if use_sso and not request.user.is_authenticated:
            # In production, redirect to Azure AD OIDC
            logger.info("SSO enabled, redirecting to OIDC authentication")
            return redirect('oidc_authentication_init')

        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        """Handle successful authentication with security logging."""
        user = form.get_user()
        
        # Check if MFA is required
        if user.mfa_enabled:
            # Store user in session for MFA verification
            self.request.session['mfa_user_id'] = str(user.id)
            self.request.session['mfa_verified'] = False
            
            # Log MFA requirement
            security_logger.info(
                'MFA required for user login',
                extra={
                    'user_id': str(user.id),
                    'username': user.username,
                    'ip_address': self.get_client_ip(),
                    'timestamp': timezone.now().isoformat(),
                }
            )
            
            return redirect('authentication:mfa_verify')
        
        # Standard login without MFA
        response = super().form_valid(form)
        
        # Log successful login
        security_logger.info(
            'User login successful',
            extra={
                'user_id': str(user.id),
                'username': user.username,
                'ip_address': self.get_client_ip(),
                'mfa_enabled': user.mfa_enabled,
                'timestamp': timezone.now().isoformat(),
            }
        )
        
        return response
    
    def form_invalid(self, form):
        """Handle failed authentication with security logging."""
        username = form.cleaned_data.get('username', 'unknown')
        
        security_logger.warning(
            'Login attempt failed',
            extra={
                'username': username,
                'ip_address': self.get_client_ip(),
                'errors': form.errors.as_json(),
                'timestamp': timezone.now().isoformat(),
            }
        )
        
        return super().form_invalid(form)


class MFAVerificationView(SecurityAuditMixin, FormView):
    """Multi-Factor Authentication verification view."""
    template_name = 'authentication/mfa_verify.html'
    form_class = MFAVerificationForm
    success_url = reverse_lazy('event_management:dashboard')
    
    def dispatch(self, request, *args, **kwargs):
        """Ensure MFA verification is required."""
        if not request.session.get('mfa_user_id'):
            messages.error(request, 'MFA verification session expired.')
            return redirect('authentication:login')
        
        return super().dispatch(request, *args, **kwargs)
    
    def form_valid(self, form):
        """Handle successful MFA verification."""
        user_id = self.request.session.get('mfa_user_id')
        token = form.cleaned_data['token']
        
        try:
            user = User.objects.get(id=user_id)
            
            if verify_mfa_token(user, token):
                # Complete login process
                login(self.request, user)
                
                # Clear MFA session data
                self.request.session.pop('mfa_user_id', None)
                self.request.session['mfa_verified'] = True
                
                # Log successful MFA verification
                security_logger.info(
                    'MFA verification successful',
                    extra={
                        'user_id': str(user.id),
                        'username': user.username,
                        'ip_address': self.get_client_ip(),
                        'timestamp': timezone.now().isoformat(),
                    }
                )
                
                messages.success(self.request, 'Login successful!')
                return super().form_valid(form)
            else:
                # Invalid MFA token
                security_logger.warning(
                    'Invalid MFA token provided',
                    extra={
                        'user_id': str(user.id),
                        'username': user.username,
                        'ip_address': self.get_client_ip(),
                        'timestamp': timezone.now().isoformat(),
                    }
                )
                
                form.add_error('token', 'Invalid verification code.')
                return self.form_invalid(form)
                
        except User.DoesNotExist:
            messages.error(self.request, 'Verification session expired.')
            return redirect('authentication:login')
    
    def form_invalid(self, form):
        """Handle failed MFA verification."""
        user_id = self.request.session.get('mfa_user_id')
        
        security_logger.warning(
            'MFA verification failed',
            extra={
                'user_id': user_id,
                'ip_address': self.get_client_ip(),
                'errors': form.errors.as_json(),
                'timestamp': timezone.now().isoformat(),
            }
        )
        
        return super().form_invalid(form)


class LogoutView(SecurityAuditMixin, DjangoLogoutView):
    """Custom logout view with security logging."""
    template_name = 'authentication/logout.html'
    
    def dispatch(self, request, *args, **kwargs):
        """Log logout attempt."""
        if request.user.is_authenticated:
            security_logger.info(
                'User logout',
                extra={
                    'user_id': str(request.user.id),
                    'username': request.user.username,
                    'ip_address': self.get_client_ip(),
                    'timestamp': timezone.now().isoformat(),
                }
            )
        
        return super().dispatch(request, *args, **kwargs)


class ProfileView(MFARequiredMixin, LoginRequiredMixin, TemplateView):
    """User profile view with security features."""
    template_name = 'authentication/profile.html'
    
    def get_context_data(self, **kwargs):
        """Add user profile data to context."""
        context = super().get_context_data(**kwargs)
        context['user'] = self.request.user
        context['mfa_enabled'] = self.request.user.mfa_enabled
        context['preferences_form'] = UserPreferencesForm(instance=self.request.user)
        return context


class MFASetupView(LoginRequiredMixin, SecurityAuditMixin, FormView):
    """Multi-Factor Authentication setup view."""
    template_name = 'authentication/mfa_setup.html'
    form_class = MFASetupForm
    success_url = reverse_lazy('authentication:profile')
    
    def get_context_data(self, **kwargs):
        """Add MFA setup data to context."""
        context = super().get_context_data(**kwargs)
        
        if not self.request.user.mfa_enabled:
            # Generate QR code for MFA setup
            secret = generate_mfa_secret()
            self.request.session['mfa_setup_secret'] = secret
            
            # Create QR code
            totp_uri = pyotp.totp.TOTP(secret).provisioning_uri(
                name=self.request.user.email,
                issuer_name=getattr(settings, 'MFA_ISSUER_NAME', 'HillDesk')
            )
            
            qr = qrcode.QRCode(version=1, box_size=10, border=5)
            qr.add_data(totp_uri)
            qr.make(fit=True)
            
            img = qr.make_image(fill_color="black", back_color="white")
            buffer = io.BytesIO()
            img.save(buffer, format='PNG')
            qr_code_data = base64.b64encode(buffer.getvalue()).decode()
            
            context['qr_code'] = qr_code_data
            context['secret'] = secret
        
        context['mfa_enabled'] = self.request.user.mfa_enabled
        return context
    
    def form_valid(self, form):
        """Handle MFA setup completion."""
        secret = self.request.session.get('mfa_setup_secret')
        token = form.cleaned_data['token']
        
        if secret and verify_mfa_token_with_secret(secret, token):
            # Save MFA secret to user profile
            user = self.request.user
            user.mfa_secret = secret  # This would need to be added to the User model
            user.mfa_enabled = True
            user.save()
            
            # Clear setup session
            self.request.session.pop('mfa_setup_secret', None)
            
            # Log MFA setup
            security_logger.info(
                'MFA setup completed',
                extra={
                    'user_id': str(user.id),
                    'username': user.username,
                    'ip_address': self.get_client_ip(),
                    'timestamp': timezone.now().isoformat(),
                }
            )
            
            messages.success(self.request, 'Multi-Factor Authentication has been enabled!')
            return super().form_valid(form)
        else:
            form.add_error('token', 'Invalid verification code.')
            return self.form_invalid(form)


class MFADisableView(MFARequiredMixin, LoginRequiredMixin, SecurityAuditMixin, TemplateView):
    """Disable Multi-Factor Authentication view."""
    template_name = 'authentication/mfa_disable.html'
    
    def post(self, request, *args, **kwargs):
        """Handle MFA disable request."""
        if request.user.mfa_enabled:
            request.user.mfa_enabled = False
            request.user.save()
            
            # Log MFA disable
            security_logger.warning(
                'MFA disabled by user',
                extra={
                    'user_id': str(request.user.id),
                    'username': request.user.username,
                    'ip_address': self.get_client_ip(),
                    'timestamp': timezone.now().isoformat(),
                }
            )
            
            messages.warning(request, 'Multi-Factor Authentication has been disabled.')
        
        return redirect('authentication:profile')


class UserPreferencesView(MFARequiredMixin, LoginRequiredMixin, SecurityAuditMixin, FormView):
    """User preferences management view."""
    template_name = 'authentication/preferences.html'
    form_class = UserPreferencesForm
    success_url = reverse_lazy('authentication:profile')
    
    def get_form_kwargs(self):
        """Pass user instance to form."""
        kwargs = super().get_form_kwargs()
        kwargs['instance'] = self.request.user
        return kwargs
    
    def form_valid(self, form):
        """Save user preferences."""
        form.save()
        
        # Log preference changes
        security_logger.info(
            'User preferences updated',
            extra={
                'user_id': str(self.request.user.id),
                'username': self.request.user.username,
                'ip_address': self.get_client_ip(),
                'changes': form.changed_data,
                'timestamp': timezone.now().isoformat(),
            }
        )
        
        messages.success(self.request, 'Preferences updated successfully!')
        return super().form_valid(form)


class PasswordChangeView(MFARequiredMixin, LoginRequiredMixin, SecurityAuditMixin, FormView):
    """Secure password change view."""
    template_name = 'authentication/password_change.html'
    form_class = PasswordChangeForm
    success_url = reverse_lazy('authentication:profile')
    
    def get_form_kwargs(self):
        """Pass user instance to form."""
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs
    
    def form_valid(self, form):
        """Handle password change."""
        form.save()
        
        # Log password change
        security_logger.warning(
            'User password changed',
            extra={
                'user_id': str(self.request.user.id),
                'username': self.request.user.username,
                'ip_address': self.get_client_ip(),
                'timestamp': timezone.now().isoformat(),
            }
        )
        
        messages.success(self.request, 'Password changed successfully!')
        return super().form_valid(form)


# Utility function for MFA token verification with secret
def verify_mfa_token_with_secret(secret, token):
    """Verify MFA token with provided secret."""
    try:
        totp = pyotp.TOTP(secret)
        return totp.verify(token, valid_window=1)
    except Exception:
        return False


# =============================================================================
# Office Setup Wizard Views
# =============================================================================

class OfficeSetupWizardView(LoginRequiredMixin, SecurityAuditMixin, FormView):
    """
    Office setup wizard for first-time admin users.

    This view is shown when:
    1. User is the first user for an office, or
    2. User is an admin and office setup is not complete

    On completion:
    - Office information is saved
    - User is set as admin (if first user)
    - is_setup_complete is set to True
    """
    template_name = 'authentication/office_setup_wizard.html'
    form_class = OfficeSetupForm
    success_url = reverse_lazy('event_management:dashboard')

    def dispatch(self, request, *args, **kwargs):
        """Check if setup is needed or allowed."""
        if not request.user.is_authenticated:
            return redirect('authentication:login')

        office = getattr(request.user, 'office', None)

        # If no office, user needs to be assigned to one first
        if not office:
            messages.warning(
                request,
                'You need to be assigned to an office before completing setup.'
            )
            return redirect('authentication:profile')

        # If setup is already complete, redirect (unless user is admin reviewing)
        if office.is_setup_complete and not request.GET.get('edit'):
            return redirect(self.success_url)

        # Only admin can complete setup (or first user who becomes admin)
        if office.is_setup_complete and request.user.role != 'admin':
            messages.error(
                request,
                'Only office administrators can modify office settings.'
            )
            return redirect('authentication:profile')

        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        """Pre-populate form with existing office data."""
        initial = super().get_initial()
        office = self.request.user.office

        if office:
            initial.update({
                'member_name': office.member_name,
                'district': office.district,
                'dc_office_address': office.dc_office_address,
                'district_office_address': office.district_office_address,
            })

        return initial

    def get_context_data(self, **kwargs):
        """Add context for the setup wizard."""
        context = super().get_context_data(**kwargs)
        context['office'] = self.request.user.office
        context['is_editing'] = self.request.GET.get('edit') == 'true'
        return context

    def form_valid(self, form):
        """Save office setup and complete wizard."""
        office = self.request.user.office
        user = self.request.user

        # Update office information
        office.member_name = form.cleaned_data['member_name']
        office.district = form.cleaned_data['district']
        office.dc_office_address = form.cleaned_data.get('dc_office_address', '')
        office.district_office_address = form.cleaned_data.get('district_office_address', '')

        # Mark setup as complete
        if not office.is_setup_complete:
            office.is_setup_complete = True
            office.setup_completed_at = timezone.now()
            office.setup_completed_by = user

            # Ensure the office has its default roles and the first user
            # completing setup holds the locked admin role.
            roles = office.create_default_roles()
            if not user.is_office_admin:
                user.assign_role(roles['admin'])
                user.save()

        office.save()

        # Log the setup completion
        self.log_security_event(
            'office_setup_completed',
            f'Office setup completed for {office.name}',
            level='info',
            office_id=str(office.id),
            member_name=office.member_name,
            district=office.district
        )

        messages.success(
            self.request,
            f'Office setup complete! Welcome to HillDesk, {office.member_name}\'s office.'
        )

        return super().form_valid(form)


class RoleManagementView(OfficeAdminRequiredMixin, TemplateView):
    """
    Role management view for office administrators.

    Allows admins to:
    - View all users in their office
    - Change user roles (admin, scheduler, staff)
    - Link users to staff profiles
    """
    template_name = 'authentication/role_management.html'

    def get_context_data(self, **kwargs):
        """Add users, roles, and permission catalog to context."""
        context = super().get_context_data(**kwargs)

        office = self.request.user.office

        # Ensure the office has its default roles (defensive for older offices).
        office.create_default_roles()

        roles = list(office.roles.all())

        # Annotate each role with a readable permission summary for its card.
        role_cards = []
        for role in roles:
            if role.is_admin:
                perm_labels = ['All permissions']
            else:
                perm_labels = [
                    Permissions.permission_label(key)
                    for key in (role.permissions or [])
                ]
            role_cards.append({
                'role': role,
                'permission_labels': perm_labels,
                'user_count': role.users.count(),
            })

        # Get all users in the office
        users = User.objects.filter(office=office).order_by('username')

        user_data = []
        for user in users:
            user_data.append({
                'user': user,
                'role_form': RoleAssignmentForm(
                    office=office,
                    initial={'user_id': user.id, 'role': user.office_role_id},
                ),
                'is_current_user': user.id == self.request.user.id,
            })

        context['user_data'] = user_data
        context['role_cards'] = role_cards
        context['office'] = office
        context['permission_groups'] = Permissions.PERMISSION_GROUPS
        context['create_role_form'] = RoleForm(office=office)
        return context

    def post(self, request, *args, **kwargs):
        """Handle role assignment to a user."""
        office = request.user.office
        form = RoleAssignmentForm(request.POST, office=office)

        if form.is_valid():
            user_id = form.cleaned_data['user_id']
            new_role = form.cleaned_data['role']

            try:
                target_user = User.objects.get(id=user_id, office=office)

                # Must always keep at least one admin in the office.
                if (target_user.is_office_admin and not new_role.is_admin
                        and self._admin_count(office) <= 1):
                    messages.error(
                        request,
                        'Cannot remove the only admin. Assign another user the Admin role first.'
                    )
                    return redirect('authentication:role_management')

                old_role = target_user.role
                target_user.assign_role(new_role)
                target_user.save()

                security_logger.info(
                    f'Role changed for user {target_user.username}',
                    extra={
                        'user_id': str(request.user.id),
                        'target_user_id': str(target_user.id),
                        'old_role': old_role,
                        'new_role': new_role.slug,
                        'ip_address': request.META.get('REMOTE_ADDR'),
                        'timestamp': timezone.now().isoformat(),
                    }
                )

                messages.success(
                    request,
                    f'{target_user.get_full_name() or target_user.username}\'s role updated to {new_role.name}.'
                )

            except User.DoesNotExist:
                messages.error(request, 'User not found.')
        else:
            messages.error(request, 'Invalid role selection.')

        return redirect('authentication:role_management')

    @staticmethod
    def _admin_count(office):
        return User.objects.filter(office=office, office_role__is_admin=True).count()


def _log_role_errors(request, form):
    """Flash the first error from a RoleForm to the user."""
    for field, errors in form.errors.items():
        for error in errors:
            messages.error(request, error)
            return


class RoleCreateView(OfficeAdminRequiredMixin, View):
    """Create a new custom role for the admin's office."""

    def post(self, request, *args, **kwargs):
        office = request.user.office
        form = RoleForm(request.POST, office=office)
        if form.is_valid():
            role = form.save()
            security_logger.info(
                f'Role created: {role.name}',
                extra={
                    'user_id': str(request.user.id),
                    'role_slug': role.slug,
                    'permissions': role.permissions,
                    'ip_address': request.META.get('REMOTE_ADDR'),
                }
            )
            messages.success(request, f'Role "{role.name}" created.')
        else:
            _log_role_errors(request, form)
        return redirect('authentication:role_management')


class RoleEditView(OfficeAdminRequiredMixin, View):
    """Edit an existing (non-admin) role's name, color, and permissions."""

    def post(self, request, role_id, *args, **kwargs):
        from .models import Role
        office = request.user.office
        role = get_object_or_404(Role, id=role_id, office=office)

        if role.is_admin:
            messages.error(request, 'The Admin role cannot be edited.')
            return redirect('authentication:role_management')

        form = RoleForm(request.POST, instance=role, office=office)
        if form.is_valid():
            role = form.save()
            security_logger.info(
                f'Role updated: {role.name}',
                extra={
                    'user_id': str(request.user.id),
                    'role_slug': role.slug,
                    'permissions': role.permissions,
                    'ip_address': request.META.get('REMOTE_ADDR'),
                }
            )
            messages.success(request, f'Role "{role.name}" updated.')
        else:
            _log_role_errors(request, form)
        return redirect('authentication:role_management')


class RoleDeleteView(OfficeAdminRequiredMixin, View):
    """Delete a custom role (blocked for admin or if users are assigned)."""

    def post(self, request, role_id, *args, **kwargs):
        from .models import Role
        office = request.user.office
        role = get_object_or_404(Role, id=role_id, office=office)

        if role.is_admin:
            messages.error(request, 'The Admin role cannot be deleted.')
        elif role.users.exists():
            messages.error(
                request,
                f'Cannot delete "{role.name}" — {role.users.count()} user(s) still have it. '
                'Reassign them to another role first.'
            )
        else:
            name = role.name
            role.delete()
            security_logger.info(
                f'Role deleted: {name}',
                extra={
                    'user_id': str(request.user.id),
                    'role_slug': role.slug,
                    'ip_address': request.META.get('REMOTE_ADDR'),
                }
            )
            messages.success(request, f'Role "{name}" deleted.')
        return redirect('authentication:role_management')


class StaffProfileLinkView(OfficeAdminRequiredMixin, TemplateView):
    """
    View for linking users to staff profiles.

    This allows matching User accounts to OfficeStaff records,
    which is used for determining event assignment.
    """
    template_name = 'authentication/staff_profile_link.html'

    def get_context_data(self, **kwargs):
        """Add users and staff profiles to context."""
        from .models import OfficeStaff

        context = super().get_context_data(**kwargs)
        office = self.request.user.office

        # Get all users without staff profiles
        unlinked_users = User.objects.filter(
            office=office,
            staff_profile__isnull=True
        ).order_by('username')

        # Get all active staff profiles
        staff_profiles = OfficeStaff.objects.filter(
            office=office,
            is_active=True
        ).order_by('name')

        # Get already linked users
        linked_users = User.objects.filter(
            office=office,
            staff_profile__isnull=False
        ).select_related('staff_profile').order_by('username')

        context['unlinked_users'] = unlinked_users
        context['staff_profiles'] = staff_profiles
        context['linked_users'] = linked_users
        context['office'] = office

        return context

    def post(self, request, *args, **kwargs):
        """Handle staff profile linking."""
        from .models import OfficeStaff

        user_id = request.POST.get('user_id')
        staff_id = request.POST.get('staff_id')
        action = request.POST.get('action', 'link')

        try:
            target_user = User.objects.get(
                id=user_id,
                office=request.user.office
            )

            if action == 'unlink':
                # Unlink user from staff profile
                target_user.staff_profile = None
                target_user.save()

                messages.success(
                    request,
                    f'{target_user.username} unlinked from staff profile.'
                )

            elif action == 'link' and staff_id:
                # Link user to staff profile
                staff_profile = OfficeStaff.objects.get(
                    id=staff_id,
                    office=request.user.office
                )

                # Check if staff profile is already linked
                existing_link = User.objects.filter(
                    staff_profile=staff_profile
                ).exclude(id=target_user.id).first()

                if existing_link:
                    messages.warning(
                        request,
                        f'This staff profile is already linked to {existing_link.username}.'
                    )
                else:
                    target_user.staff_profile = staff_profile
                    target_user.save()

                    messages.success(
                        request,
                        f'{target_user.username} linked to {staff_profile.name}.'
                    )

        except (User.DoesNotExist, OfficeStaff.DoesNotExist):
            messages.error(request, 'User or staff profile not found.')

        return redirect('authentication:staff_profile_link')
