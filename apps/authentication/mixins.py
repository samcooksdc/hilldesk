# SPDX-License-Identifier: Apache-2.0
"""
Authentication mixins for HillDesk.
Provides security and access control functionality.
"""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.contrib import messages
from django.utils import timezone
from django.conf import settings
import logging

security_logger = logging.getLogger('security_audit')


class SecurityAuditMixin:
    """
    Mixin for adding security auditing capabilities to views.
    Provides methods for logging security events and getting client information.
    """
    
    def get_client_ip(self):
        """Get the real client IP address."""
        request = getattr(self, 'request', None)
        if not request:
            return None
        
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
    
    def get_user_agent(self):
        """Get the user agent string."""
        request = getattr(self, 'request', None)
        if not request:
            return None
        return request.META.get('HTTP_USER_AGENT', '')
    
    def log_security_event(self, event_type, message, level='info', **extra_data):
        """Log a security event with standard format."""
        request = getattr(self, 'request', None)
        
        log_data = {
            'event_type': event_type,
            'timestamp': timezone.now().isoformat(),
            'ip_address': self.get_client_ip(),
            'user_agent': self.get_user_agent(),
            **extra_data
        }
        
        if request and hasattr(request, 'user') and request.user.is_authenticated:
            log_data.update({
                'user_id': str(request.user.id),
                'username': request.user.username,
            })
        
        # Log at appropriate level
        log_method = getattr(security_logger, level, security_logger.info)
        log_method(message, extra=log_data)


class MFARequiredMixin(SecurityAuditMixin):
    """
    Mixin that requires Multi-Factor Authentication for access.
    Redirects to MFA setup if not enabled, or MFA verification if not verified.
    """
    
    def dispatch(self, request, *args, **kwargs):
        """Check MFA requirements before allowing access."""
        if not request.user.is_authenticated:
            return redirect('authentication:login')
        
        # Check if MFA is required by settings
        mfa_required = getattr(settings, 'AUTH_SETTINGS', {}).get('MFA_REQUIRED', False)
        
        if mfa_required or request.user.mfa_enabled:
            # Check if user has MFA enabled
            if not request.user.mfa_enabled:
                self.log_security_event(
                    'mfa_setup_required',
                    'User accessing MFA-required resource without MFA enabled',
                    level='warning'
                )
                messages.warning(
                    request, 
                    'Multi-Factor Authentication is required. Please set up MFA to continue.'
                )
                return redirect('authentication:mfa_setup')
            
            # Check if MFA is verified for this session
            if not request.session.get('mfa_verified', False):
                self.log_security_event(
                    'mfa_verification_required',
                    'User accessing MFA-required resource without session verification',
                    level='warning'
                )
                request.session['mfa_user_id'] = str(request.user.id)
                return redirect('authentication:mfa_verify')
        
        return super().dispatch(request, *args, **kwargs)


class RoleRequiredMixin(SecurityAuditMixin, LoginRequiredMixin):
    """
    Mixin that requires specific user roles for access.
    """
    required_roles = []  # Override in subclass
    
    def dispatch(self, request, *args, **kwargs):
        """Check role requirements before allowing access."""
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        
        if self.required_roles:
            user_has_role = False
            
            # Check if user has any of the required roles
            for role in self.required_roles:
                if role == 'staff' and request.user.is_staff:
                    user_has_role = True
                    break
                elif role == 'superuser' and request.user.is_superuser:
                    user_has_role = True
                    break
                elif hasattr(request.user, 'groups'):
                    if request.user.groups.filter(name=role).exists():
                        user_has_role = True
                        break
            
            if not user_has_role:
                self.log_security_event(
                    'access_denied_insufficient_role',
                    f'User attempted to access resource requiring roles: {self.required_roles}',
                    level='warning',
                    required_roles=self.required_roles
                )
                raise PermissionDenied("You don't have permission to access this resource.")
        
        # Make sure we have a parent class with dispatch before calling super()
        parent_dispatch = getattr(super(), 'dispatch', None)
        if parent_dispatch and callable(parent_dispatch):
            return parent_dispatch(request, *args, **kwargs)
        else:
            # If no parent dispatch method, just return the response directly
            # This handles the case when used with View in tests
            if hasattr(self, 'get') and request.method == 'GET':
                return self.get(request, *args, **kwargs)
            elif hasattr(self, 'post') and request.method == 'POST':
                return self.post(request, *args, **kwargs)
            else:
                raise PermissionDenied("Method not allowed")


class DataClassificationMixin(SecurityAuditMixin, LoginRequiredMixin):
    """
    Mixin for handling data classification requirements.
    """
    required_classification_level = 'internal'  # Override in subclass
    
    classification_hierarchy = {
        'public': 0,
        'internal': 1,
        'sensitive': 2,
        'restricted': 3,
    }
    
    def dispatch(self, request, *args, **kwargs):
        """Check data classification access requirements."""
        if not request.user.is_authenticated:
            return redirect('authentication:login')
        
        # Get user's maximum classification level
        user_max_level = self.get_user_classification_level(request.user)
        required_level = self.classification_hierarchy.get(self.required_classification_level, 1)
        
        if user_max_level < required_level:
            self.log_security_event(
                'access_denied_insufficient_classification',
                f'User attempted to access {self.required_classification_level} data',
                level='warning',
                user_classification_level=user_max_level,
                required_classification_level=required_level
            )
            raise PermissionDenied("You don't have clearance to access this data.")
        
        return super().dispatch(request, *args, **kwargs)
    
    def get_user_classification_level(self, user):
        """Get the user's maximum data classification level."""
        if user.is_superuser:
            return 3  # Restricted access
        elif user.is_staff:
            return 2  # Sensitive access
        else:
            return 1  # Internal access


class SessionSecurityMixin(SecurityAuditMixin, LoginRequiredMixin):
    """
    Mixin for enhanced session security.
    """
    
    def dispatch(self, request, *args, **kwargs):
        """Check session security requirements."""
        if request.user.is_authenticated:
            # Check session timeout
            session_timeout = getattr(settings, 'AUTH_SETTINGS', {}).get('SESSION_TIMEOUT', 3600)
            last_activity = request.session.get('last_activity')
            
            if last_activity:
                from datetime import datetime
                last_activity_time = datetime.fromisoformat(last_activity)
                time_since_activity = (timezone.now() - last_activity_time).total_seconds()
                
                if time_since_activity > session_timeout:
                    self.log_security_event(
                        'session_timeout',
                        'User session timed out due to inactivity',
                        level='info',
                        time_since_activity=time_since_activity,
                        session_timeout=session_timeout
                    )
                    
                    # Clear session and redirect to login
                    request.session.flush()
                    messages.info(request, 'Your session has expired due to inactivity. Please log in again.')
                    return redirect('authentication:login')
            
            # Update last activity
            request.session['last_activity'] = timezone.now().isoformat()
            
            # Check for session hijacking indicators
            self.check_session_security(request)
        
        return super().dispatch(request, *args, **kwargs)
    
    def check_session_security(self, request):
        """Check for potential session hijacking."""
        # Check IP address consistency
        session_ip = request.session.get('session_ip')
        current_ip = self.get_client_ip()
        
        if session_ip and session_ip != current_ip:
            self.log_security_event(
                'session_ip_change',
                'Session IP address changed - possible session hijacking',
                level='warning',
                session_ip=session_ip,
                current_ip=current_ip
            )
            
            # For high-security environments, you might want to invalidate the session
            # request.session.flush()
            # messages.error(request, 'Security alert: Session invalidated due to IP change.')
            # return redirect('authentication:login')
        
        if not session_ip:
            request.session['session_ip'] = current_ip
        
        # Check User-Agent consistency
        session_ua = request.session.get('session_user_agent')
        current_ua = self.get_user_agent()
        
        if session_ua and session_ua != current_ua:
            self.log_security_event(
                'session_user_agent_change',
                'Session User-Agent changed - possible session hijacking',
                level='warning',
                session_user_agent=session_ua[:100],  # Truncate for logging
                current_user_agent=current_ua[:100]
            )
        
        if not session_ua:
            request.session['session_user_agent'] = current_ua


class RateLimitMixin(SecurityAuditMixin):
    """
    Mixin for implementing rate limiting on views.
    """
    rate_limit_key = None  # Override in subclass
    rate_limit_count = 10  # Override in subclass
    rate_limit_period = 3600  # Override in subclass (seconds)
    
    def dispatch(self, request, *args, **kwargs):
        """Check rate limiting before processing request."""
        if self.rate_limit_key:
            # Create rate limit key
            key_parts = [self.rate_limit_key]
            
            if request.user.is_authenticated:
                key_parts.append(str(request.user.id))
            else:
                key_parts.append(self.get_client_ip() or 'unknown')
            
            rate_key = ':'.join(key_parts)
            
            # Check rate limit (this would integrate with Redis or similar)
            if self.is_rate_limited(rate_key):
                self.log_security_event(
                    'rate_limit_exceeded',
                    f'Rate limit exceeded for key: {rate_key}',
                    level='warning',
                    rate_limit_key=rate_key,
                    rate_limit_count=self.rate_limit_count,
                    rate_limit_period=self.rate_limit_period
                )
                
                raise PermissionDenied("Rate limit exceeded. Please try again later.")
        
        return super().dispatch(request, *args, **kwargs)
    
    def is_rate_limited(self, key):
        """Check if the key is rate limited."""
        # This is a placeholder - in production, you'd use Redis or similar
        # For now, we'll just return False to allow requests
        return False


class AdminRequiredMixin(RoleRequiredMixin):
    """Mixin that requires admin/staff access."""
    required_roles = ['staff']


class SuperuserRequiredMixin(RoleRequiredMixin):
    """Mixin that requires superuser access."""
    required_roles = ['superuser']


# =============================================================================
# HillDesk Role-Based Mixins (Admin/Scheduler/Staff hierarchy)
# =============================================================================

class OfficeAdminRequiredMixin(SecurityAuditMixin, LoginRequiredMixin):
    """
    Mixin that requires office admin role for access.
    Used for role management and office settings pages.
    """

    def dispatch(self, request, *args, **kwargs):
        """Check if user holds a locked admin role."""
        if not request.user.is_authenticated:
            return redirect('authentication:login')

        if not getattr(request.user, 'is_office_admin', False):
            self.log_security_event(
                'access_denied_not_admin',
                'Non-admin user attempted to access admin-only resource',
                level='warning',
                user_role=getattr(request.user, 'role', 'unknown'),
                requested_path=request.path
            )
            raise PermissionDenied("You must be an office admin to access this page.")

        return super().dispatch(request, *args, **kwargs)


class RequirePermissionMixin(SecurityAuditMixin, LoginRequiredMixin):
    """
    Mixin that requires a specific permission key for access.

    Set ``required_permission`` on the subclass to a permission constant from
    ``apps.authentication.permissions.Permissions``.
    """
    required_permission = None

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('authentication:login')

        from .permissions import Permissions
        perm = self.required_permission
        if perm is None or not Permissions.has_permission(request.user, perm):
            self.log_security_event(
                'access_denied_missing_permission',
                'User lacked required permission for resource',
                level='warning',
                user_role=getattr(request.user, 'role', 'unknown'),
                required_permission=perm,
                requested_path=request.path
            )
            raise PermissionDenied("You do not have permission to access this page.")

        return super().dispatch(request, *args, **kwargs)


class SchedulerRequiredMixin(RequirePermissionMixin):
    """
    Mixin for views guarding event status changes / approval workflow.

    Now permission-based: requires the ``change_event_status`` capability
    (which the old admin/scheduler roles held). Kept for backward compatibility.
    """

    @property
    def required_permission(self):
        from .permissions import Permissions
        return Permissions.CHANGE_EVENT_STATUS


class OfficeSetupRequiredMixin(SecurityAuditMixin, LoginRequiredMixin):
    """
    Mixin that redirects users to office setup if setup is not complete.
    Used for main application pages that require office configuration.
    """

    def dispatch(self, request, *args, **kwargs):
        """Check if office setup is complete."""
        if not request.user.is_authenticated:
            return redirect('authentication:login')

        office = getattr(request.user, 'office', None)

        # If user has no office, redirect to office assignment
        if not office:
            messages.warning(
                request,
                'You need to be assigned to an office before accessing this page.'
            )
            return redirect('authentication:profile')

        # If office setup is not complete and user is admin, redirect to setup
        if not office.is_setup_complete:
            user_role = getattr(request.user, 'role', 'staff')
            if user_role == 'admin':
                messages.info(
                    request,
                    'Please complete your office setup to continue.'
                )
                return redirect('authentication:office_setup')
            else:
                messages.info(
                    request,
                    'Your office administrator needs to complete the office setup.'
                )

        return super().dispatch(request, *args, **kwargs)


class EventEditPermissionMixin(SecurityAuditMixin, LoginRequiredMixin):
    """
    Mixin for views that edit events.
    Determines if user can edit directly or must create suggestions.

    Sets `self.can_edit_directly` and `self.requires_suggestion` on dispatch.
    """

    def dispatch(self, request, *args, **kwargs):
        """Check event edit permissions."""
        if not request.user.is_authenticated:
            return redirect('authentication:login')

        # Get event from kwargs (subclass must set event_kwarg_name or override get_event)
        event = self.get_event_for_permission_check(request, *args, **kwargs)

        if event:
            from .permissions import Permissions

            self.can_edit_directly = Permissions.can_edit_event(request.user, event)
            self.requires_suggestion = Permissions.staff_edit_requires_review(request.user, event)

            # Store for template/view use
            request.can_edit_directly = self.can_edit_directly
            request.requires_suggestion = self.requires_suggestion
        else:
            # No event found, allow access (will be handled by view)
            self.can_edit_directly = True
            self.requires_suggestion = False
            request.can_edit_directly = True
            request.requires_suggestion = False

        return super().dispatch(request, *args, **kwargs)

    def get_event_for_permission_check(self, request, *args, **kwargs):
        """
        Get the event for permission checking.
        Override in subclass if event is retrieved differently.
        """
        from apps.event_management.models import Event

        # Try common patterns for event ID in URL
        event_id = kwargs.get('event_id') or kwargs.get('pk') or kwargs.get('id')

        if event_id:
            try:
                return Event.objects.get(id=event_id)
            except Event.DoesNotExist:
                return None

        return None