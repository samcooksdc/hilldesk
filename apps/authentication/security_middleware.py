# SPDX-License-Identifier: Apache-2.0
"""
Enhanced security middleware for HillDesk.
Provides additional security features beyond the basic middleware.
"""

import logging
import re
from django.utils import timezone
from django.http import HttpResponseBadRequest, HttpResponseForbidden
from django.conf import settings
from .security import SecurityHeaders, RateLimiter
from .utils import get_client_ip

security_logger = logging.getLogger('security_audit')


class InputValidationMiddleware:
    """
    Middleware for validating and sanitizing input data.
    Prevents common injection attacks and malicious input.
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
        self.rate_limiter = RateLimiter(
            key_prefix='input_validation',
            max_requests=100,
            time_window=60
        )
    
    def __call__(self, request):
        # Validate input before processing
        if not self._validate_request(request):
            return HttpResponseBadRequest("Invalid request data")
        
        response = self.get_response(request)
        return response
    
    def _validate_request(self, request):
        """Validate request data for security issues."""
        client_ip = get_client_ip(request)
        
        # Rate limiting for input validation
        if not self.rate_limiter.is_allowed(client_ip or 'unknown'):
            security_logger.warning(
                'Input validation rate limit exceeded',
                extra={
                    'ip_address': client_ip,
                    'user_id': str(request.user.id) if request.user.is_authenticated else None,
                    'timestamp': timezone.now().isoformat(),
                }
            )
            return False
        
        # Check for suspicious patterns in URL
        suspicious_url_patterns = [
            r'\.\./',  # Directory traversal
            r'<script',  # XSS attempts
            r'javascript:',  # JavaScript injection
            r'data:',  # Data URI schemes
            r'vbscript:',  # VBScript injection
            r'onload=',  # Event handler injection
            r'onerror=',  # Error handler injection
        ]
        
        for pattern in suspicious_url_patterns:
            if re.search(pattern, request.path, re.IGNORECASE):
                security_logger.warning(
                    'Suspicious URL pattern detected',
                    extra={
                        'pattern': pattern,
                        'url': request.path,
                        'ip_address': client_ip,
                        'user_id': str(request.user.id) if request.user.is_authenticated else None,
                        'timestamp': timezone.now().isoformat(),
                    }
                )
                return False
        
        # Check POST data for suspicious content
        if request.method == 'POST' and hasattr(request, 'POST'):
            for key, value in request.POST.items():
                if not self._validate_input_value(key, value, client_ip):
                    return False
        
        # Check for oversized requests
        content_length = request.META.get('CONTENT_LENGTH')
        if content_length:
            try:
                content_length = int(content_length)
                max_size = getattr(settings, 'MAX_REQUEST_SIZE', 10 * 1024 * 1024)  # 10MB default
                if content_length > max_size:
                    security_logger.warning(
                        'Oversized request detected',
                        extra={
                            'content_length': content_length,
                            'max_size': max_size,
                            'ip_address': client_ip,
                            'user_id': str(request.user.id) if request.user.is_authenticated else None,
                            'timestamp': timezone.now().isoformat(),
                        }
                    )
                    return False
            except ValueError:
                pass
        
        return True
    
    def _validate_input_value(self, key, value, client_ip):
        """Validate individual input values."""
        if not value:
            return True
        
        # Check for SQL injection patterns
        sql_patterns = [
            r'union\s+select',
            r'drop\s+table',
            r'delete\s+from',
            r'insert\s+into',
            r'update\s+set',
            r'exec\s*\(',
            r'script\s*>',
            r'<\s*script',
        ]
        
        for pattern in sql_patterns:
            if re.search(pattern, str(value), re.IGNORECASE):
                security_logger.warning(
                    'SQL injection attempt detected',
                    extra={
                        'pattern': pattern,
                        'field': key,
                        'value': str(value)[:100],  # Truncate for logging
                        'ip_address': client_ip,
                        'timestamp': timezone.now().isoformat(),
                    }
                )
                return False
        
        # Check for XSS patterns
        xss_patterns = [
            r'<script[^>]*>',
            r'javascript:',
            r'onload\s*=',
            r'onerror\s*=',
            r'onclick\s*=',
            r'onmouseover\s*=',
        ]
        
        for pattern in xss_patterns:
            if re.search(pattern, str(value), re.IGNORECASE):
                security_logger.warning(
                    'XSS attempt detected',
                    extra={
                        'pattern': pattern,
                        'field': key,
                        'value': str(value)[:100],  # Truncate for logging
                        'ip_address': client_ip,
                        'timestamp': timezone.now().isoformat(),
                    }
                )
                return False
        
        return True


class SecurityHeadersMiddleware:
    """
    Middleware for adding comprehensive security headers.
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        response = self.get_response(request)
        
        # Add security headers
        security_headers = SecurityHeaders.get_security_headers()
        for header, value in security_headers.items():
            response[header] = value
        
        # Add Content Security Policy for HTML responses
        if 'text/html' in response.get('Content-Type', ''):
            response['Content-Security-Policy'] = SecurityHeaders.get_csp_header()
        
        # Add data classification header if available
        if hasattr(response, 'data_classification'):
            response['X-Data-Classification'] = response.data_classification.upper()
        
        # Add security timestamp
        response['X-Security-Timestamp'] = timezone.now().isoformat()
        
        return response


class ThreatDetectionMiddleware:
    """
    Middleware for detecting and responding to security threats.
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
        self.threat_patterns = self._load_threat_patterns()
    
    def __call__(self, request):
        # Check for threats before processing
        threat_detected = self._detect_threats(request)
        
        if threat_detected:
            return HttpResponseForbidden("Request blocked due to security policy")
        
        response = self.get_response(request)
        return response
    
    def _load_threat_patterns(self):
        """Load threat detection patterns."""
        return {
            'user_agent_threats': [
                r'sqlmap',
                r'nikto',
                r'nessus',
                r'openvas',
                r'nmap',
                r'masscan',
                r'zap',
                r'burp',
            ],
            'path_threats': [
                r'/\.env',
                r'/config\.php',
                r'/wp-admin',
                r'/phpmyadmin',
                r'/admin\.php',
                r'/shell\.php',
                r'/backdoor',
            ],
            'parameter_threats': [
                r'cmd=',
                r'exec=',
                r'system=',
                r'shell=',
                r'passthru=',
                r'eval=',
            ]
        }
    
    def _detect_threats(self, request):
        """Detect various types of security threats."""
        client_ip = get_client_ip(request)
        user_agent = request.META.get('HTTP_USER_AGENT', '')
        
        # Check user agent for known attack tools
        for pattern in self.threat_patterns['user_agent_threats']:
            if re.search(pattern, user_agent, re.IGNORECASE):
                security_logger.error(
                    'Malicious user agent detected',
                    extra={
                        'pattern': pattern,
                        'user_agent': user_agent,
                        'ip_address': client_ip,
                        'path': request.path,
                        'timestamp': timezone.now().isoformat(),
                    }
                )
                return True
        
        # Check path for suspicious requests
        for pattern in self.threat_patterns['path_threats']:
            if re.search(pattern, request.path, re.IGNORECASE):
                security_logger.error(
                    'Suspicious path access attempt',
                    extra={
                        'pattern': pattern,
                        'path': request.path,
                        'ip_address': client_ip,
                        'user_agent': user_agent,
                        'timestamp': timezone.now().isoformat(),
                    }
                )
                return True
        
        # Check query parameters for threats
        query_string = request.META.get('QUERY_STRING', '')
        for pattern in self.threat_patterns['parameter_threats']:
            if re.search(pattern, query_string, re.IGNORECASE):
                security_logger.error(
                    'Malicious parameter detected',
                    extra={
                        'pattern': pattern,
                        'query_string': query_string,
                        'ip_address': client_ip,
                        'timestamp': timezone.now().isoformat(),
                    }
                )
                return True
        
        return False


class RequestLoggingMiddleware:
    """
    Middleware for comprehensive request logging.
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        start_time = timezone.now()
        
        # Log request
        self._log_request(request, start_time)
        
        response = self.get_response(request)
        
        # Log response
        end_time = timezone.now()
        self._log_response(request, response, start_time, end_time)
        
        return response
    
    def _log_request(self, request, timestamp):
        """Log incoming request details."""
        # Only log sensitive endpoints or POST requests
        sensitive_paths = ['/auth/', '/admin/', '/api/']
        is_sensitive = any(request.path.startswith(path) for path in sensitive_paths)
        
        if is_sensitive or request.method in ['POST', 'PUT', 'DELETE']:
            security_logger.info(
                f'Request: {request.method} {request.path}',
                extra={
                    'method': request.method,
                    'path': request.path,
                    'ip_address': get_client_ip(request),
                    'user_agent': request.META.get('HTTP_USER_AGENT', ''),
                    'user_id': str(request.user.id) if request.user.is_authenticated else None,
                    'username': request.user.username if request.user.is_authenticated else None,
                    'timestamp': timestamp.isoformat(),
                    'request_id': getattr(request, 'request_id', None),
                }
            )
    
    def _log_response(self, request, response, start_time, end_time):
        """Log response details."""
        duration = (end_time - start_time).total_seconds()
        
        # Log errors and slow requests
        if response.status_code >= 400 or duration > 5.0:
            log_level = 'error' if response.status_code >= 500 else 'warning'
            log_method = getattr(security_logger, log_level)
            
            log_method(
                f'Response: {response.status_code} for {request.method} {request.path}',
                extra={
                    'method': request.method,
                    'path': request.path,
                    'status_code': response.status_code,
                    'duration': duration,
                    'ip_address': get_client_ip(request),
                    'user_id': str(request.user.id) if request.user.is_authenticated else None,
                    'username': request.user.username if request.user.is_authenticated else None,
                    'timestamp': end_time.isoformat(),
                    'request_id': getattr(request, 'request_id', None),
                }
            )