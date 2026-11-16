# SPDX-License-Identifier: Apache-2.0
"""
Django management command for security auditing and monitoring.
"""

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.conf import settings
import os
from datetime import timedelta

User = get_user_model()


class Command(BaseCommand):
    help = 'Perform security audit and generate security reports'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--check-passwords',
            action='store_true',
            help='Check for weak passwords',
        )
        parser.add_argument(
            '--check-permissions',
            action='store_true',
            help='Check user permissions and roles',
        )
        parser.add_argument(
            '--check-sessions',
            action='store_true',
            help='Check for suspicious sessions',
        )
        parser.add_argument(
            '--check-logs',
            action='store_true',
            help='Analyze security logs for anomalies',
        )
        parser.add_argument(
            '--generate-report',
            action='store_true',
            help='Generate comprehensive security report',
        )
        parser.add_argument(
            '--days',
            type=int,
            default=7,
            help='Number of days to analyze (default: 7)',
        )
    
    def handle(self, *args, **options):
        self.stdout.write(
            self.style.SUCCESS('Starting security audit...')
        )
        
        if options['check_passwords']:
            self.check_passwords()
        
        if options['check_permissions']:
            self.check_permissions()
        
        if options['check_sessions']:
            self.check_sessions()
        
        if options['check_logs']:
            self.check_logs(options['days'])
        
        if options['generate_report']:
            self.generate_report(options['days'])
        
        # If no specific checks requested, run all
        if not any([
            options['check_passwords'],
            options['check_permissions'],
            options['check_sessions'],
            options['check_logs'],
            options['generate_report']
        ]):
            self.check_passwords()
            self.check_permissions()
            self.check_sessions()
            self.check_logs(options['days'])
            self.generate_report(options['days'])
        
        self.stdout.write(
            self.style.SUCCESS('Security audit completed.')
        )
    
    def check_passwords(self):
        """Check for weak passwords and security issues."""
        self.stdout.write('Checking password security...')
        
        issues = []
        
        # Check for users without MFA
        users_without_mfa = User.objects.filter(mfa_enabled=False, is_active=True)
        if users_without_mfa.exists():
            issues.append(f"{users_without_mfa.count()} active users without MFA enabled")
        
        # Check for locked accounts
        locked_accounts = User.objects.filter(
            account_locked_until__gt=timezone.now()
        )
        if locked_accounts.exists():
            issues.append(f"{locked_accounts.count()} accounts currently locked")
        
        # Check for accounts with high failed login attempts
        high_failed_attempts = User.objects.filter(failed_login_attempts__gte=3)
        if high_failed_attempts.exists():
            issues.append(f"{high_failed_attempts.count()} accounts with high failed login attempts")
        
        # Check for inactive superusers
        inactive_superusers = User.objects.filter(
            is_superuser=True,
            is_active=False
        )
        if inactive_superusers.exists():
            issues.append(f"{inactive_superusers.count()} inactive superuser accounts (should be deleted)")
        
        if issues:
            self.stdout.write(
                self.style.WARNING('Password security issues found:')
            )
            for issue in issues:
                self.stdout.write(f'  - {issue}')
        else:
            self.stdout.write(
                self.style.SUCCESS('No password security issues found.')
            )
    
    def check_permissions(self):
        """Check user permissions and roles."""
        self.stdout.write('Checking user permissions...')
        
        issues = []
        
        # Check for users with superuser privileges
        superusers = User.objects.filter(is_superuser=True, is_active=True)
        if superusers.count() > 2:
            issues.append(f"High number of superusers: {superusers.count()} (recommend max 2)")
        
        # Check for staff users
        staff_users = User.objects.filter(is_staff=True, is_active=True)
        self.stdout.write(f'Active staff users: {staff_users.count()}')
        
        # Check for users with no recent login
        cutoff_date = timezone.now() - timedelta(days=90)
        inactive_users = User.objects.filter(
            is_active=True,
            last_login__lt=cutoff_date
        )
        if inactive_users.exists():
            issues.append(f"{inactive_users.count()} users haven't logged in for 90+ days")
        
        if issues:
            self.stdout.write(
                self.style.WARNING('Permission issues found:')
            )
            for issue in issues:
                self.stdout.write(f'  - {issue}')
        else:
            self.stdout.write(
                self.style.SUCCESS('No permission issues found.')
            )
    
    def check_sessions(self):
        """Check for suspicious sessions."""
        self.stdout.write('Checking session security...')
        
        # This would require implementing session tracking
        # For now, just check basic session configuration
        issues = []
        
        if not getattr(settings, 'SESSION_COOKIE_SECURE', False) and not settings.DEBUG:
            issues.append('SESSION_COOKIE_SECURE is not enabled in production')
        
        if not getattr(settings, 'SESSION_COOKIE_HTTPONLY', True):
            issues.append('SESSION_COOKIE_HTTPONLY is not enabled')
        
        if getattr(settings, 'SESSION_COOKIE_AGE', 1209600) > 3600:
            issues.append('SESSION_COOKIE_AGE is longer than 1 hour (security risk)')
        
        if issues:
            self.stdout.write(
                self.style.WARNING('Session security issues found:')
            )
            for issue in issues:
                self.stdout.write(f'  - {issue}')
        else:
            self.stdout.write(
                self.style.SUCCESS('No session security issues found.')
            )
    
    def check_logs(self, days):
        """Analyze security logs for anomalies."""
        self.stdout.write(f'Analyzing security logs for the last {days} days...')
        
        # Check if log files exist
        log_dir = os.path.join(settings.BASE_DIR, 'logs')
        security_log = os.path.join(log_dir, 'security.log')
        
        if not os.path.exists(security_log):
            self.stdout.write(
                self.style.WARNING('Security log file not found. Logging may not be configured properly.')
            )
            return
        
        # Basic log analysis
        try:
            with open(security_log, 'r') as f:
                lines = f.readlines()
            
            # Count different types of events
            login_failures = sum(1 for line in lines if 'Login attempt failed' in line)
            account_lockouts = sum(1 for line in lines if 'Account locked' in line)
            mfa_failures = sum(1 for line in lines if 'MFA verification failed' in line)
            
            self.stdout.write('Recent security events:')
            self.stdout.write(f'  - Login failures: {login_failures}')
            self.stdout.write(f'  - Account lockouts: {account_lockouts}')
            self.stdout.write(f'  - MFA failures: {mfa_failures}')
            
            if login_failures > 50:
                self.stdout.write(
                    self.style.WARNING(f'High number of login failures: {login_failures}')
                )
            
            if account_lockouts > 10:
                self.stdout.write(
                    self.style.WARNING(f'High number of account lockouts: {account_lockouts}')
                )
        
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Error analyzing logs: {e}')
            )
    
    def generate_report(self, days):
        """Generate comprehensive security report."""
        self.stdout.write('Generating security report...')
        
        report_lines = []
        report_lines.append('=' * 50)
        report_lines.append('HILLDESK - SECURITY REPORT')
        report_lines.append('=' * 50)
        report_lines.append(f'Generated: {timezone.now().strftime("%Y-%m-%d %H:%M:%S")}')
        report_lines.append(f'Analysis Period: Last {days} days')
        report_lines.append('')
        
        # User statistics
        total_users = User.objects.count()
        active_users = User.objects.filter(is_active=True).count()
        staff_users = User.objects.filter(is_staff=True, is_active=True).count()
        superusers = User.objects.filter(is_superuser=True, is_active=True).count()
        mfa_enabled = User.objects.filter(mfa_enabled=True, is_active=True).count()
        
        report_lines.append('USER STATISTICS:')
        report_lines.append(f'  Total users: {total_users}')
        report_lines.append(f'  Active users: {active_users}')
        report_lines.append(f'  Staff users: {staff_users}')
        report_lines.append(f'  Superusers: {superusers}')
        report_lines.append(f'  Users with MFA: {mfa_enabled}')
        report_lines.append(f'  MFA adoption rate: {(mfa_enabled/active_users*100):.1f}%' if active_users > 0 else '  MFA adoption rate: 0%')
        report_lines.append('')
        
        # Security settings
        report_lines.append('SECURITY SETTINGS:')
        report_lines.append(f'  DEBUG mode: {settings.DEBUG}')
        report_lines.append(f'  HTTPS redirect: {getattr(settings, "SECURE_SSL_REDIRECT", False)}')
        report_lines.append(f'  Secure cookies: {getattr(settings, "SESSION_COOKIE_SECURE", False)}')
        report_lines.append(f'  HSTS enabled: {getattr(settings, "SECURE_HSTS_SECONDS", 0) > 0}')
        report_lines.append('')
        
        # Save report
        report_path = os.path.join(settings.BASE_DIR, 'logs', f'security_report_{timezone.now().strftime("%Y%m%d_%H%M%S")}.txt')
        
        try:
            with open(report_path, 'w') as f:
                f.write('\n'.join(report_lines))
            
            self.stdout.write(
                self.style.SUCCESS(f'Security report saved to: {report_path}')
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Error saving report: {e}')
            )
            
        # Also display report summary
        self.stdout.write('\nSECURITY REPORT SUMMARY:')
        for line in report_lines:
            self.stdout.write(line)