# SPDX-License-Identifier: Apache-2.0
"""
Django management command for checking security configuration.
"""

from django.core.management.base import BaseCommand
from django.conf import settings
import os


class Command(BaseCommand):
    help = 'Check security configuration and settings'
    
    def handle(self, *args, **options):
        self.stdout.write(
            self.style.SUCCESS('Checking security configuration...')
        )
        
        issues = []
        warnings = []
        
        # Check DEBUG setting
        if settings.DEBUG:
            if os.environ.get('ENVIRONMENT') == 'production':
                issues.append('DEBUG is True in production environment')
            else:
                warnings.append('DEBUG is True (acceptable in development)')
        
        # Check SECRET_KEY
        if settings.SECRET_KEY == getattr(settings, 'DEV_ONLY_SECRET_KEY', None):
            issues.append('Using default SECRET_KEY (security risk)')
        elif 'django-insecure' in settings.SECRET_KEY:
            issues.append('Using insecure SECRET_KEY')
        
        # Check HTTPS settings
        if not getattr(settings, 'SECURE_SSL_REDIRECT', False):
            warnings.append('SECURE_SSL_REDIRECT is not enabled')
        
        if not getattr(settings, 'SECURE_HSTS_SECONDS', 0):
            warnings.append('SECURE_HSTS_SECONDS is not set')
        
        # Check cookie security
        if not getattr(settings, 'SESSION_COOKIE_SECURE', False):
            warnings.append('SESSION_COOKIE_SECURE is not enabled')
        
        if not getattr(settings, 'CSRF_COOKIE_SECURE', False):
            warnings.append('CSRF_COOKIE_SECURE is not enabled')
        
        if not getattr(settings, 'SESSION_COOKIE_HTTPONLY', True):
            issues.append('SESSION_COOKIE_HTTPONLY is not enabled')
        
        # Check session settings
        session_age = getattr(settings, 'SESSION_COOKIE_AGE', 1209600)
        if session_age > 3600:
            warnings.append(f'SESSION_COOKIE_AGE is {session_age} seconds (consider reducing for security)')
        
        # Check password validation
        validators = getattr(settings, 'AUTH_PASSWORD_VALIDATORS', [])
        if len(validators) < 4:
            warnings.append('Less than 4 password validators configured')
        
        # Check allowed hosts
        allowed_hosts = getattr(settings, 'ALLOWED_HOSTS', [])
        if '*' in allowed_hosts:
            issues.append('ALLOWED_HOSTS contains wildcard (*) - security risk')
        
        # Check database encryption
        field_encryption_key = getattr(settings, 'FIELD_ENCRYPTION_KEY', None)
        if not field_encryption_key:
            warnings.append('FIELD_ENCRYPTION_KEY is not configured')
        elif field_encryption_key == getattr(settings, 'DEV_ONLY_FIELD_ENCRYPTION_KEY', None):
            issues.append('Using default FIELD_ENCRYPTION_KEY (security risk)')
        
        # Check logging configuration
        logging_config = getattr(settings, 'LOGGING', {})
        if not logging_config:
            warnings.append('LOGGING is not configured')
        else:
            # Check for security logger
            loggers = logging_config.get('loggers', {})
            if 'security_audit' not in loggers:
                warnings.append('security_audit logger is not configured')
        
        # Check middleware
        middleware = getattr(settings, 'MIDDLEWARE', [])
        required_middleware = [
            'django.middleware.security.SecurityMiddleware',
            'django.middleware.csrf.CsrfViewMiddleware',
            'django.middleware.clickjacking.XFrameOptionsMiddleware',
        ]
        
        for mw in required_middleware:
            if mw not in middleware:
                issues.append(f'Required middleware missing: {mw}')
        
        # Check custom security middleware
        custom_middleware = [
            'apps.authentication.middleware.SecurityAuditMiddleware',
            'apps.authentication.middleware.DataClassificationMiddleware',
        ]
        
        for mw in custom_middleware:
            if mw not in middleware:
                warnings.append(f'Custom security middleware not enabled: {mw}')
        
        # Check X-Frame-Options
        x_frame_options = getattr(settings, 'X_FRAME_OPTIONS', None)
        if x_frame_options != 'DENY':
            warnings.append('X_FRAME_OPTIONS should be set to DENY for maximum security')
        
        # Check file permissions (basic check)
        settings_file = os.path.join(settings.BASE_DIR, 'config', 'settings', 'base.py')
        if os.path.exists(settings_file):
            file_stat = os.stat(settings_file)
            file_mode = oct(file_stat.st_mode)[-3:]
            if file_mode != '644':
                warnings.append(f'Settings file permissions are {file_mode} (recommend 644)')
        
        # Display results
        if issues:
            self.stdout.write(
                self.style.ERROR('CRITICAL SECURITY ISSUES FOUND:')
            )
            for issue in issues:
                self.stdout.write(f'  ❌ {issue}')
            self.stdout.write('')
        
        if warnings:
            self.stdout.write(
                self.style.WARNING('SECURITY WARNINGS:')
            )
            for warning in warnings:
                self.stdout.write(f'  ⚠️  {warning}')
            self.stdout.write('')
        
        if not issues and not warnings:
            self.stdout.write(
                self.style.SUCCESS('✅ No security configuration issues found!')
            )
        else:
            total_issues = len(issues) + len(warnings)
            self.stdout.write(
                self.style.HTTP_INFO(f'Total issues found: {total_issues} ({len(issues)} critical, {len(warnings)} warnings)')
            )
        
        # Provide recommendations
        self.stdout.write('')
        self.stdout.write('SECURITY RECOMMENDATIONS:')
        self.stdout.write('  1. Enable HTTPS in production (SECURE_SSL_REDIRECT=True)')
        self.stdout.write('  2. Set secure cookies (SESSION_COOKIE_SECURE=True)')
        self.stdout.write('  3. Configure HSTS (SECURE_HSTS_SECONDS=31536000)')
        self.stdout.write('  4. Use strong SECRET_KEY and FIELD_ENCRYPTION_KEY')
        self.stdout.write('  5. Enable comprehensive logging')
        self.stdout.write('  6. Regular security audits with: python manage.py security_audit')
        
        if issues:
            exit(1)  # Exit with error code if critical issues found