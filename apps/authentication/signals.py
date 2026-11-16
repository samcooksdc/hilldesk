# SPDX-License-Identifier: Apache-2.0
"""
Authentication signals for HillDesk.
Handles user-related events and security logging.
"""

import logging
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.utils import timezone

User = get_user_model()
security_logger = logging.getLogger('security_audit')


@receiver(user_logged_in)
def user_logged_in_handler(sender, request, user, **kwargs):
    """Handle user login event."""
    # On first login (last_login still NULL because Django's update_last_login
    # receiver is wired to run AFTER ours via apps.py), force theme to light.
    # The theme toggle in Settings has been removed; dark mode remains in the
    # codebase but is not user-selectable.
    if user.last_login is None:
        if user.theme != 'light':
            user.theme = 'light'
            user.save(update_fields=['theme'])

    # Reset failed login attempts on successful login
    if user.failed_login_attempts > 0:
        user.failed_login_attempts = 0
        user.save(update_fields=['failed_login_attempts'])
    
    # Log successful login
    ip_address = get_client_ip(request)
    security_logger.info(
        'User login successful',
        extra={
            'user_id': str(user.id),
            'username': user.username,
            'ip_address': ip_address,
            'user_agent': request.META.get('HTTP_USER_AGENT', ''),
            'timestamp': timezone.now().isoformat(),
        }
    )
    
    # Store login info in session for security checks (if session is available)
    if hasattr(request, 'session'):
        request.session['session_start'] = timezone.now().isoformat()
        request.session['session_ip'] = ip_address
        request.session['session_user_agent'] = request.META.get('HTTP_USER_AGENT', '')
        request.session['last_activity'] = timezone.now().isoformat()


@receiver(user_logged_out)
def user_logged_out_handler(sender, request, user, **kwargs):
    """Handle user logout event."""
    if user:
        # Log logout
        security_logger.info(
            'User logout',
            extra={
                'user_id': str(user.id),
                'username': user.username,
                'ip_address': get_client_ip(request),
                'user_agent': request.META.get('HTTP_USER_AGENT', ''),
                'timestamp': timezone.now().isoformat(),
            }
        )


@receiver(user_login_failed)
def user_login_failed_handler(sender, credentials, request, **kwargs):
    """Handle failed login attempts."""
    username = credentials.get('username', '')
    
    # Prepare log data
    log_data = {
        'username': username,
        'timestamp': timezone.now().isoformat(),
    }
    
    # Add request data if available
    if request and hasattr(request, 'META'):
        log_data.update({
            'ip_address': get_client_ip(request),
            'user_agent': request.META.get('HTTP_USER_AGENT', ''),
        })
    
    # Log failed login attempt
    security_logger.warning(
        'Login attempt failed',
        extra=log_data
    )
    
    # Update failed login attempts counter
    if username:
        try:
            user = User.objects.get(username=username)
            user.failed_login_attempts += 1
            
            # Lock account after 5 failed attempts
            if user.failed_login_attempts >= 5:
                from datetime import timedelta
                user.account_locked_until = timezone.now() + timedelta(minutes=30)
                
                # Prepare lockout log data
                lockout_log_data = {
                    'user_id': str(user.id),
                    'username': user.username,
                    'failed_attempts': user.failed_login_attempts,
                    'locked_until': user.account_locked_until.isoformat(),
                    'timestamp': timezone.now().isoformat(),
                }
                
                # Add request data if available
                if request and hasattr(request, 'META'):
                    lockout_log_data['ip_address'] = get_client_ip(request)
                
                security_logger.warning(
                    'Account locked due to multiple failed login attempts',
                    extra=lockout_log_data
                )
            
            user.save(update_fields=['failed_login_attempts', 'account_locked_until'])
            
        except User.DoesNotExist:
            # Don't reveal if user exists or not
            pass


@receiver(post_save, sender=User)
def user_post_save_handler(sender, instance, created, **kwargs):
    """Handle user creation and modification events."""
    if created:
        # Log user creation
        security_logger.info(
            'User account created',
            extra={
                'user_id': str(instance.id),
                'username': instance.username,
                'email': instance.email,
                'is_staff': instance.is_staff,
                'is_superuser': instance.is_superuser,
                'timestamp': timezone.now().isoformat(),
            }
        )
    else:
        # Log user modification
        security_logger.info(
            'User account modified',
            extra={
                'user_id': str(instance.id),
                'username': instance.username,
                'timestamp': timezone.now().isoformat(),
            }
        )


@receiver(pre_save, sender=User)
def user_pre_save_handler(sender, instance, **kwargs):
    """Handle user changes before saving."""
    if instance.pk:
        try:
            old_instance = User.objects.get(pk=instance.pk)
            
            # Check for security-relevant changes
            if old_instance.is_active != instance.is_active:
                log_level = 'warning' if not instance.is_active else 'info'
                status = 'deactivated' if not instance.is_active else 'activated'
                
                security_logger.log(
                    getattr(logging, log_level.upper()),
                    f'User account {status}',
                    extra={
                        'user_id': str(instance.id),
                        'username': instance.username,
                        'timestamp': timezone.now().isoformat(),
                    }
                )
            
            if old_instance.is_staff != instance.is_staff:
                security_logger.warning(
                    'User staff status changed',
                    extra={
                        'user_id': str(instance.id),
                        'username': instance.username,
                        'old_status': old_instance.is_staff,
                        'new_status': instance.is_staff,
                        'timestamp': timezone.now().isoformat(),
                    }
                )
            
            if old_instance.is_superuser != instance.is_superuser:
                security_logger.warning(
                    'User superuser status changed',
                    extra={
                        'user_id': str(instance.id),
                        'username': instance.username,
                        'old_status': old_instance.is_superuser,
                        'new_status': instance.is_superuser,
                        'timestamp': timezone.now().isoformat(),
                    }
                )
                
        except User.DoesNotExist:
            # This is a new user
            pass


def get_client_ip(request):
    """Get the client IP address from request."""
    if not request or not hasattr(request, 'META'):
        return None
        
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip