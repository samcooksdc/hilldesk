# SPDX-License-Identifier: Apache-2.0
"""
Authentication middleware for HillDesk.
Provides security auditing and data classification functionality.
"""

import logging
from django.utils import timezone
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse
from .utils import get_client_ip, validate_session_security

security_logger = logging.getLogger('security_audit')


class SecurityAuditMiddleware:
    """
    Middleware for security auditing.
    Logs security-relevant events and enforces security policies.
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        # Process request
        self._process_request_security(request)
        
        # Get response
        response = self.get_response(request)
        
        # Process response
        self._process_response_security(request, response)
        
        return response
    
    def _process_request_security(self, request):
        """Process security aspects of the request."""
        # Check if session is available
        if not hasattr(request, 'session'):
            return
            
        # Initialize session security if needed
        if not request.session.get('security_initialized'):
            request.session['security_initialized'] = True
            request.session['session_start'] = timezone.now().isoformat()
            request.session['session_ip'] = get_client_ip(request)
            request.session['session_user_agent'] = request.META.get('HTTP_USER_AGENT', '')
            request.session['last_activity'] = timezone.now().isoformat()
        
        # Update last activity timestamp
        request.session['last_activity'] = timezone.now().isoformat()
        
        # Check for authenticated users
        if request.user.is_authenticated:
            # Validate session security
            if not validate_session_security(request):
                # Log potential session hijacking
                security_logger.warning(
                    'Potential session security issue detected',
                    extra={
                        'user_id': str(request.user.id),
                        'username': request.user.username,
                        'ip_address': get_client_ip(request),
                        'path': request.path,
                        'timestamp': timezone.now().isoformat(),
                    }
                )
                
                # For high-security paths, invalidate session
                high_security_paths = [
                    '/admin/',
                    '/auth/profile/',
                    '/auth/password-change/',
                    '/event-management/create/',
                    '/event-management/edit/',
                ]
                
                if any(request.path.startswith(path) for path in high_security_paths):
                    # Clear session and redirect to login
                    request.session.flush()
                    messages.error(request, 'Your session has been invalidated due to security concerns. Please log in again.')
                    
                    # We can't redirect here since middleware doesn't return responses
                    # Instead, we'll set a flag for the view to handle
                    request.session['security_redirect'] = reverse('authentication:login')
            
            # Check for account lockout
            if hasattr(request.user, 'account_locked_until') and request.user.account_locked_until:
                if request.user.account_locked_until > timezone.now():
                    # Account is locked
                    security_logger.warning(
                        'Locked account access attempt',
                        extra={
                            'user_id': str(request.user.id),
                            'username': request.user.username,
                            'ip_address': get_client_ip(request),
                            'path': request.path,
                            'locked_until': request.user.account_locked_until.isoformat(),
                            'timestamp': timezone.now().isoformat(),
                        }
                    )
                    
                    # Log the user out
                    from django.contrib.auth import logout
                    logout(request)
                    
                    # Set message
                    messages.error(
                        request, 
                        f'Your account is locked until {request.user.account_locked_until}. '
                        'Please try again later or contact support.'
                    )
    
    def _process_response_security(self, request, response):
        """Process security aspects of the response."""
        # Add security headers
        response['X-Content-Type-Options'] = 'nosniff'
        response['X-Frame-Options'] = 'DENY'
        response['X-XSS-Protection'] = '1; mode=block'
        response['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
        
        # Add Content-Security-Policy header for HTML responses
        if 'text/html' in response.get('Content-Type', ''):
            response['Content-Security-Policy'] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline'; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data:; "
                "font-src 'self'; "
                "connect-src 'self'; "
                "frame-ancestors 'none'; "
                "form-action 'self';"
            )
        
        # Log certain responses
        if hasattr(response, 'status_code'):
            if response.status_code >= 400:
                # Log error responses
                log_level = 'warning' if response.status_code < 500 else 'error'
                
                log_method = getattr(security_logger, log_level)
                log_method(
                    f'HTTP {response.status_code} response',
                    extra={
                        'status_code': response.status_code,
                        'path': request.path,
                        'method': request.method,
                        'ip_address': get_client_ip(request),
                        'user_id': str(request.user.id) if request.user.is_authenticated else None,
                        'username': request.user.username if request.user.is_authenticated else None,
                        'timestamp': timezone.now().isoformat(),
                    }
                )
        
        return response


class DataClassificationMiddleware:
    """
    Middleware for handling data classification.
    Enforces data handling policies based on classification levels.
    """
    
    # Classification levels
    CLASSIFICATION_LEVELS = {
        'public': 0,
        'internal': 1,
        'sensitive': 2,
        'restricted': 3,
    }
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        # Process request
        response = self.get_response(request)
        
        # Process response
        return self._process_response_classification(request, response)
    
    def _process_response_classification(self, request, response):
        """Process data classification for the response."""
        # Check if response has classification metadata
        classification = getattr(response, 'data_classification', None)
        
        if classification and classification in self.CLASSIFICATION_LEVELS:
            # Add classification header
            response['X-Data-Classification'] = classification.upper()
            
            # Log access to classified data
            if self.CLASSIFICATION_LEVELS[classification] >= self.CLASSIFICATION_LEVELS['sensitive']:
                security_logger.info(
                    f'Access to {classification} data',
                    extra={
                        'classification': classification,
                        'path': request.path,
                        'method': request.method,
                        'ip_address': get_client_ip(request),
                        'user_id': str(request.user.id) if request.user.is_authenticated else None,
                        'username': request.user.username if request.user.is_authenticated else None,
                        'timestamp': timezone.now().isoformat(),
                    }
                )
            
            # For restricted data, add additional headers
            if classification == 'restricted':
                response['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
                response['Pragma'] = 'no-cache'
                response['Expires'] = '0'
        
        return response


class SessionSecurityMiddleware:
    """
    Middleware for enhancing session security.
    Implements session timeout, IP binding, and other security measures.
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        # Check session timeout
        if self._check_session_timeout(request):
            # Session has timed out, redirect to login
            from django.contrib.auth import logout
            logout(request)
            messages.info(request, 'Your session has expired due to inactivity. Please log in again.')
            return redirect('authentication:login')
        
        # Process request
        response = self.get_response(request)
        
        return response
    
    def _check_session_timeout(self, request):
        """Check if the session has timed out due to inactivity."""
        if not request.user.is_authenticated or not hasattr(request, 'session'):
            return False
        
        # Get session timeout setting
        from django.conf import settings
        timeout = getattr(settings, 'SESSION_SECURITY_TIMEOUT', 3600)  # Default: 1 hour
        
        # Check last activity
        last_activity = request.session.get('last_activity')
        if not last_activity:
            # No activity recorded, update and continue
            request.session['last_activity'] = timezone.now().isoformat()
            return False
        
        # Parse last activity time
        try:
            from datetime import datetime
            last_time = datetime.fromisoformat(last_activity)
            
            # Convert to timezone-aware if needed
            if timezone.is_naive(last_time):
                last_time = timezone.make_aware(last_time)
            
            # Check if timeout exceeded
            inactivity_time = (timezone.now() - last_time).total_seconds()
            
            if inactivity_time > timeout:
                # Log timeout
                security_logger.info(
                    'Session timeout due to inactivity',
                    extra={
                        'user_id': str(request.user.id),
                        'username': request.user.username,
                        'ip_address': get_client_ip(request),
                        'inactivity_time': inactivity_time,
                        'timeout': timeout,
                        'timestamp': timezone.now().isoformat(),
                    }
                )
                return True
            
            # Update last activity time
            request.session['last_activity'] = timezone.now().isoformat()
            return False
            
        except Exception as e:
            # Log error and reset activity time
            security_logger.error(
                f'Error checking session timeout: {e}',
                extra={
                    'user_id': str(request.user.id) if request.user.is_authenticated else None,
                    'ip_address': get_client_ip(request),
                    'timestamp': timezone.now().isoformat(),
                }
            )
            request.session['last_activity'] = timezone.now().isoformat()
            return False