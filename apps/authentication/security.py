# SPDX-License-Identifier: Apache-2.0
"""
Security utilities for HillDesk.
Provides comprehensive security functions and decorators.
"""

import hashlib
import hmac
import secrets
import logging
from functools import wraps
from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponseForbidden
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from .utils import get_client_ip

User = get_user_model()
security_logger = logging.getLogger('security_audit')


class SecurityViolationError(Exception):
    """Exception raised when a security violation is detected."""
    pass


class RateLimiter:
    """Rate limiting utility for preventing abuse."""
    
    def __init__(self, key_prefix='rate_limit', max_requests=10, time_window=60):
        self.key_prefix = key_prefix
        self.max_requests = max_requests
        self.time_window = time_window
    
    def is_allowed(self, identifier):
        """Check if the request is allowed based on rate limiting."""
        cache_key = f"{self.key_prefix}:{identifier}"
        
        try:
            current_requests = cache.get(cache_key, 0)
            
            if current_requests >= self.max_requests:
                return False
            
            # Increment counter
            cache.set(cache_key, current_requests + 1, self.time_window)
            return True
        except Exception:
            # If cache fails, allow the request (fail open for availability)
            return True
    
    def get_remaining_requests(self, identifier):
        """Get the number of remaining requests for an identifier."""
        cache_key = f"{self.key_prefix}:{identifier}"
        current_requests = cache.get(cache_key, 0)
        return max(0, self.max_requests - current_requests)


def rate_limit(max_requests=10, time_window=60, key_func=None):
    """Decorator for rate limiting views."""
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            # Determine the key for rate limiting
            if key_func:
                key = key_func(request)
            else:
                key = get_client_ip(request) or 'unknown'
            
            limiter = RateLimiter(
                key_prefix=f"rate_limit_{view_func.__name__}",
                max_requests=max_requests,
                time_window=time_window
            )
            
            if not limiter.is_allowed(key):
                security_logger.warning(
                    'Rate limit exceeded',
                    extra={
                        'view': view_func.__name__,
                        'key': key,
                        'ip_address': get_client_ip(request),
                        'user_id': str(request.user.id) if request.user.is_authenticated else None,
                        'timestamp': timezone.now().isoformat(),
                    }
                )
                return HttpResponseForbidden("Rate limit exceeded. Please try again later.")
            
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


def require_secure_transport(view_func):
    """Decorator to require HTTPS for sensitive views."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.is_secure() and not settings.DEBUG:
            security_logger.warning(
                'Insecure request to secure endpoint',
                extra={
                    'view': view_func.__name__,
                    'ip_address': get_client_ip(request),
                    'user_id': str(request.user.id) if request.user.is_authenticated else None,
                    'timestamp': timezone.now().isoformat(),
                }
            )
            raise PermissionDenied("This endpoint requires HTTPS")
        
        return view_func(request, *args, **kwargs)
    return wrapper


def log_sensitive_action(action_type, description=None):
    """Decorator to log sensitive actions."""
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            # Log the action before execution
            security_logger.info(
                f'Sensitive action: {action_type}',
                extra={
                    'action_type': action_type,
                    'description': description or f"Executing {view_func.__name__}",
                    'view': view_func.__name__,
                    'ip_address': get_client_ip(request),
                    'user_id': str(request.user.id) if request.user.is_authenticated else None,
                    'username': request.user.username if request.user.is_authenticated else None,
                    'timestamp': timezone.now().isoformat(),
                }
            )
            
            try:
                result = view_func(request, *args, **kwargs)
                
                # Log successful completion
                security_logger.info(
                    f'Sensitive action completed: {action_type}',
                    extra={
                        'action_type': action_type,
                        'status': 'success',
                        'view': view_func.__name__,
                        'ip_address': get_client_ip(request),
                        'user_id': str(request.user.id) if request.user.is_authenticated else None,
                        'username': request.user.username if request.user.is_authenticated else None,
                        'timestamp': timezone.now().isoformat(),
                    }
                )
                
                return result
                
            except Exception as e:
                # Log failed action
                security_logger.error(
                    f'Sensitive action failed: {action_type}',
                    extra={
                        'action_type': action_type,
                        'status': 'failed',
                        'error': str(e),
                        'view': view_func.__name__,
                        'ip_address': get_client_ip(request),
                        'user_id': str(request.user.id) if request.user.is_authenticated else None,
                        'username': request.user.username if request.user.is_authenticated else None,
                        'timestamp': timezone.now().isoformat(),
                    }
                )
                raise
        return wrapper
    return decorator


class SecurityHeaders:
    """Utility class for managing security headers."""
    
    @staticmethod
    def get_security_headers():
        """Get standard security headers."""
        return {
            'X-Content-Type-Options': 'nosniff',
            'X-Frame-Options': 'DENY',
            'X-XSS-Protection': '1; mode=block',
            'Referrer-Policy': 'strict-origin-when-cross-origin',
            'Permissions-Policy': 'geolocation=(), microphone=(), camera=()',
            'Strict-Transport-Security': 'max-age=31536000; includeSubDomains; preload',
        }
    
    @staticmethod
    def get_csp_header():
        """Get Content Security Policy header."""
        return (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "font-src 'self'; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "form-action 'self';"
        )


class InputSanitizer:
    """Utility class for input sanitization and validation."""
    
    @staticmethod
    def sanitize_string(value, max_length=None, allow_html=False):
        """Sanitize string input."""
        if not isinstance(value, str):
            value = str(value)
        
        # Remove null bytes
        value = value.replace('\x00', '')
        
        # Limit length if specified
        if max_length:
            value = value[:max_length]
        
        # Remove HTML if not allowed
        if not allow_html:
            import re
            value = re.sub(r'<[^>]+>', '', value)
        
        return value.strip()
    
    @staticmethod
    def validate_email(email):
        """Validate email format with additional security checks."""
        import re
        
        if not email or len(email) > 254:
            return False
        
        # Basic email regex
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(pattern, email):
            return False
        
        # Check for suspicious patterns
        suspicious_patterns = [
            r'\.{2,}',  # Multiple consecutive dots
            r'^\.|\.$',  # Starting or ending with dot
            r'@.*@',  # Multiple @ symbols
        ]
        
        for pattern in suspicious_patterns:
            if re.search(pattern, email):
                return False
        
        return True
    
    @staticmethod
    def validate_phone(phone):
        """Validate phone number format."""
        import re
        
        if not phone:
            return False
        
        # Remove all non-digit characters
        digits_only = re.sub(r'\D', '', phone)
        
        # Check length (US phone numbers)
        if len(digits_only) < 10 or len(digits_only) > 15:
            return False
        
        return True


class SecurityAuditor:
    """Utility class for security auditing and monitoring."""
    
    @staticmethod
    def log_data_access(user, data_type, data_id, action='read', classification='internal'):
        """Log data access for audit purposes."""
        security_logger.info(
            f'Data access: {action}',
            extra={
                'user_id': str(user.id) if user else None,
                'username': user.username if user else None,
                'data_type': data_type,
                'data_id': str(data_id),
                'action': action,
                'classification': classification,
                'timestamp': timezone.now().isoformat(),
            }
        )
    
    @staticmethod
    def log_permission_check(user, permission, resource, granted=False):
        """Log permission checks for audit purposes."""
        security_logger.info(
            f'Permission check: {permission}',
            extra={
                'user_id': str(user.id) if user else None,
                'username': user.username if user else None,
                'permission': permission,
                'resource': resource,
                'granted': granted,
                'timestamp': timezone.now().isoformat(),
            }
        )
    
    @staticmethod
    def log_configuration_change(user, setting_name, old_value, new_value):
        """Log configuration changes for audit purposes."""
        security_logger.warning(
            f'Configuration change: {setting_name}',
            extra={
                'user_id': str(user.id) if user else None,
                'username': user.username if user else None,
                'setting_name': setting_name,
                'old_value': str(old_value),
                'new_value': str(new_value),
                'timestamp': timezone.now().isoformat(),
            }
        )


class IntegrityChecker:
    """Utility class for data integrity checking."""
    
    @staticmethod
    def generate_checksum(data):
        """Generate SHA-256 checksum for data integrity."""
        if isinstance(data, str):
            data = data.encode()
        return hashlib.sha256(data).hexdigest()
    
    @staticmethod
    def verify_checksum(data, expected_checksum):
        """Verify data integrity using checksum."""
        actual_checksum = IntegrityChecker.generate_checksum(data)
        return hmac.compare_digest(actual_checksum, expected_checksum)
    
    @staticmethod
    def generate_secure_token(length=32):
        """Generate a cryptographically secure random token."""
        return secrets.token_urlsafe(length)


class SessionSecurity:
    """Utility class for session security management."""
    
    @staticmethod
    def validate_session_integrity(request):
        """Validate session integrity and detect tampering."""
        if not hasattr(request, 'session'):
            return False
        
        # Check for session fixation
        if not request.session.get('session_validated'):
            request.session['session_validated'] = True
            request.session['session_created'] = timezone.now().isoformat()
            return True
        
        # Check session age
        session_created = request.session.get('session_created')
        if session_created:
            from datetime import datetime
            created_time = datetime.fromisoformat(session_created)
            if timezone.is_naive(created_time):
                created_time = timezone.make_aware(created_time)
            
            # Session should not be older than 24 hours
            if (timezone.now() - created_time).total_seconds() > 86400:
                return False
        
        return True
    
    @staticmethod
    def regenerate_session_id(request):
        """Regenerate session ID to prevent session fixation."""
        if hasattr(request, 'session'):
            request.session.cycle_key()
            security_logger.info(
                'Session ID regenerated',
                extra={
                    'user_id': str(request.user.id) if request.user.is_authenticated else None,
                    'ip_address': get_client_ip(request),
                    'timestamp': timezone.now().isoformat(),
                }
            )