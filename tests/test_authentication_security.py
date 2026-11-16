# SPDX-License-Identifier: Apache-2.0
"""
Security-specific tests for HillDesk.
Tests encryption, security utilities, and security middleware.
"""

from django.test import TestCase, RequestFactory, override_settings
from django.contrib.auth import get_user_model
from django.core.management import call_command

from apps.authentication.fields import DataClassificationField
from apps.authentication.security import RateLimiter, SecurityHeaders, InputSanitizer, SecurityAuditor, IntegrityChecker
from apps.authentication.utils import encrypt_sensitive_data, decrypt_sensitive_data

User = get_user_model()


class EncryptedFieldsTest(TestCase):
    """Test cases for encrypted field functionality."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
    
    def test_encrypted_char_field_encryption(self):
        """Test that EncryptedCharField encrypts and decrypts data correctly."""
        # Set MFA secret
        secret = 'JBSWY3DPEHPK3PXP'
        self.user.mfa_secret = secret
        self.user.save()
        
        # Refresh from database
        self.user.refresh_from_db()
        
        # The decrypted value should match what we set
        self.assertEqual(self.user.mfa_secret, secret)
        
        # The raw database value should be different (encrypted)
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute("SELECT mfa_secret FROM auth_user WHERE id = %s", [str(self.user.id)])
            result = cursor.fetchone()
            if result:
                raw_value = result[0]
                self.assertNotEqual(raw_value, secret)
                self.assertIsNotNone(raw_value)
    
    def test_data_classification_field(self):
        """Test DataClassificationField functionality."""
        # Test default value
        self.assertEqual(self.user.data_classification, 'internal')
        
        # Test setting different values
        self.user.data_classification = 'sensitive'
        self.user.save()
        self.user.refresh_from_db()
        self.assertEqual(self.user.data_classification, 'sensitive')
        
        # Test choices
        field = DataClassificationField()
        choices = [choice[0] for choice in field.choices]
        expected_choices = ['public', 'internal', 'sensitive', 'restricted']
        self.assertEqual(choices, expected_choices)


class SecurityUtilitiesTest(TestCase):
    """Test cases for security utilities."""
    
    def setUp(self):
        """Set up test data."""
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
    
    @override_settings(CACHES={
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        }
    })
    def test_rate_limiter(self):
        """Test rate limiting functionality."""
        limiter = RateLimiter(max_requests=3, time_window=60)
        
        # First 3 requests should be allowed
        for i in range(3):
            self.assertTrue(limiter.is_allowed('test_key'))
        
        # 4th request should be blocked
        self.assertFalse(limiter.is_allowed('test_key'))
        
        # Different key should still be allowed
        self.assertTrue(limiter.is_allowed('different_key'))
    
    def test_security_headers(self):
        """Test security headers utility."""
        headers = SecurityHeaders.get_security_headers()
        
        expected_headers = [
            'X-Content-Type-Options',
            'X-Frame-Options',
            'X-XSS-Protection',
            'Referrer-Policy',
            'Permissions-Policy',
            'Strict-Transport-Security'
        ]
        
        for header in expected_headers:
            self.assertIn(header, headers)
        
        # Test CSP header
        csp = SecurityHeaders.get_csp_header()
        self.assertIn("default-src 'self'", csp)
        self.assertIn("frame-ancestors 'none'", csp)
    
    def test_input_sanitizer(self):
        """Test input sanitization functionality."""
        # Test string sanitization
        dirty_string = "<script>alert('xss')</script>Hello World"
        clean_string = InputSanitizer.sanitize_string(dirty_string)
        self.assertEqual(clean_string, "alert('xss')Hello World")
        
        # Test with HTML allowed
        clean_with_html = InputSanitizer.sanitize_string(dirty_string, allow_html=True)
        self.assertEqual(clean_with_html, dirty_string)
        
        # Test max length
        long_string = "a" * 100
        truncated = InputSanitizer.sanitize_string(long_string, max_length=50)
        self.assertEqual(len(truncated), 50)
        
        # Test email validation
        self.assertTrue(InputSanitizer.validate_email('test@example.com'))
        self.assertFalse(InputSanitizer.validate_email('invalid-email'))
        self.assertFalse(InputSanitizer.validate_email('test@'))
        self.assertFalse(InputSanitizer.validate_email('test..test@example.com'))
        
        # Test phone validation
        self.assertTrue(InputSanitizer.validate_phone('555-123-4567'))
        self.assertTrue(InputSanitizer.validate_phone('(555) 123-4567'))
        self.assertTrue(InputSanitizer.validate_phone('5551234567'))
        self.assertFalse(InputSanitizer.validate_phone('123'))
        self.assertFalse(InputSanitizer.validate_phone('abc-def-ghij'))
    
    def test_security_auditor(self):
        """Test security auditing functionality."""
        # Test data access logging
        SecurityAuditor.log_data_access(
            user=self.user,
            data_type='user_profile',
            data_id=self.user.id,
            action='read',
            classification='internal'
        )
        
        # Test permission check logging
        SecurityAuditor.log_permission_check(
            user=self.user,
            permission='view_profile',
            resource='user_profile',
            granted=True
        )
        
        # Test configuration change logging
        SecurityAuditor.log_configuration_change(
            user=self.user,
            setting_name='session_timeout',
            old_value='3600',
            new_value='1800'
        )
        
        # No assertions needed, just checking that logging doesn't raise exceptions
    
    def test_integrity_checker(self):
        """Test data integrity checking functionality."""
        test_data = "This is test data for integrity checking"
        
        # Generate checksum
        checksum = IntegrityChecker.generate_checksum(test_data)
        self.assertIsInstance(checksum, str)
        self.assertEqual(len(checksum), 64)  # SHA-256 hex digest length
        
        # Verify checksum
        self.assertTrue(IntegrityChecker.verify_checksum(test_data, checksum))
        
        # Test with modified data
        modified_data = test_data + " modified"
        self.assertFalse(IntegrityChecker.verify_checksum(modified_data, checksum))
        
        # Test secure token generation
        token = IntegrityChecker.generate_secure_token()
        self.assertIsInstance(token, str)
        self.assertGreaterEqual(len(token), 32)
        
        # Test different length
        short_token = IntegrityChecker.generate_secure_token(16)
        self.assertLess(len(short_token), len(token))


class SecurityMiddlewareTest(TestCase):
    """Test cases for security middleware functionality."""
    
    def setUp(self):
        """Set up test data."""
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
    
    def test_security_headers_added(self):
        """Test that security headers are added by middleware."""
        from apps.authentication.middleware import SecurityAuditMiddleware
        
        request = self.factory.get('/test/')
        request.user = self.user
        request.session = {}
        
        def get_response(request):
            from django.http import HttpResponse
            return HttpResponse('OK')
        
        middleware = SecurityAuditMiddleware(get_response)
        response = middleware(request)
        
        # Check that security headers are present
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(response['X-Frame-Options'], 'DENY')
        self.assertEqual(response['X-XSS-Protection'], '1; mode=block')
        self.assertEqual(response['Referrer-Policy'], 'strict-origin-when-cross-origin')
    
    def test_data_classification_middleware(self):
        """Test data classification middleware."""
        from apps.authentication.middleware import DataClassificationMiddleware
        
        request = self.factory.get('/test/')
        request.user = self.user
        
        def get_response(request):
            from django.http import HttpResponse
            response = HttpResponse('OK')
            response.data_classification = 'sensitive'
            return response
        
        middleware = DataClassificationMiddleware(get_response)
        response = middleware(request)
        
        # Check that classification header is added
        self.assertEqual(response['X-Data-Classification'], 'SENSITIVE')


class SecurityManagementCommandsTest(TestCase):
    """Test cases for security management commands."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        # Create a superuser
        self.superuser = User.objects.create_superuser(
            username='admin',
            email='admin@example.com',
            password='adminpass123'
        )
    
    def test_security_audit_command(self):
        """Test security audit management command."""
        # Test that the command runs without errors
        try:
            call_command('security_audit', '--check-passwords')
            call_command('security_audit', '--check-permissions')
        except Exception as e:
            self.fail(f"Security audit command failed: {e}")
    
    def test_check_security_config_command(self):
        """Test security configuration check command."""
        # Test that the command runs without errors
        try:
            call_command('check_security_config')
        except SystemExit:
            # Command may exit with error code if issues found, which is expected
            pass
        except Exception as e:
            self.fail(f"Security config check command failed: {e}")


class EncryptionUtilsTest(TestCase):
    """Test cases for encryption utilities."""
    
    @override_settings(FIELD_ENCRYPTION_KEY='test-key-for-encryption-testing-32-chars')
    def test_encrypt_decrypt_sensitive_data(self):
        """Test encryption and decryption of sensitive data."""
        original_data = "This is sensitive information"
        
        # Test encryption
        encrypted_data = encrypt_sensitive_data(original_data)
        self.assertNotEqual(encrypted_data, original_data)
        self.assertIsInstance(encrypted_data, str)
        
        # Test decryption
        decrypted_data = decrypt_sensitive_data(encrypted_data)
        self.assertEqual(decrypted_data, original_data)
        
        # Test with empty data - encryption functions will encrypt empty strings
        empty_encrypted = encrypt_sensitive_data("")
        self.assertNotEqual(empty_encrypted, "")  # Empty strings get encrypted
        self.assertEqual(decrypt_sensitive_data(empty_encrypted), "")


class SecurityDecoratorsTest(TestCase):
    """Test cases for security decorators."""
    
    def setUp(self):
        """Set up test data."""
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
    
    @override_settings(CACHES={
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        }
    })
    def test_rate_limit_decorator(self):
        """Test rate limiting decorator."""
        from apps.authentication.security import rate_limit
        
        @rate_limit(max_requests=2, time_window=60)
        def test_view(request):
            from django.http import HttpResponse
            return HttpResponse('OK')
        
        request = self.factory.get('/test/')
        request.user = self.user
        request.META['REMOTE_ADDR'] = '127.0.0.1'
        
        # First two requests should succeed
        response1 = test_view(request)
        self.assertEqual(response1.status_code, 200)
        
        response2 = test_view(request)
        self.assertEqual(response2.status_code, 200)
        
        # Third request should be rate limited
        response3 = test_view(request)
        self.assertEqual(response3.status_code, 403)
    
    @override_settings(DEBUG=False)
    def test_require_secure_transport_decorator(self):
        """Test secure transport requirement decorator."""
        from apps.authentication.security import require_secure_transport
        from django.core.exceptions import PermissionDenied
        
        @require_secure_transport
        def test_view(request):
            from django.http import HttpResponse
            return HttpResponse('OK')
        
        # Test with insecure request
        request = self.factory.get('/test/')
        request.user = self.user
        
        with self.assertRaises(PermissionDenied):
            test_view(request)
        
        # Test with secure request
        request = self.factory.get('/test/', secure=True)
        request.user = self.user
        
        response = test_view(request)
        self.assertEqual(response.status_code, 200)
    
    def test_log_sensitive_action_decorator(self):
        """Test sensitive action logging decorator."""
        from apps.authentication.security import log_sensitive_action
        
        @log_sensitive_action('test_action', 'Testing sensitive action logging')
        def test_view(request):
            from django.http import HttpResponse
            return HttpResponse('OK')
        
        request = self.factory.get('/test/')
        request.user = self.user
        
        response = test_view(request)
        self.assertEqual(response.status_code, 200)
        
        # Test with exception
        @log_sensitive_action('test_action_error', 'Testing error logging')
        def test_view_error(request):
            raise ValueError("Test error")
        
        with self.assertRaises(ValueError):
            test_view_error(request)


class SecurityIntegrationTest(TestCase):
    """Integration tests for security features."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
    
    def test_user_model_with_encrypted_fields(self):
        """Test User model with encrypted MFA secret."""
        # Set MFA secret
        secret = 'JBSWY3DPEHPK3PXP'
        self.user.mfa_secret = secret
        self.user.mfa_enabled = True
        self.user.data_classification = 'sensitive'
        self.user.save()
        
        # Refresh from database
        self.user.refresh_from_db()
        
        # Verify values
        self.assertEqual(self.user.mfa_secret, secret)
        self.assertTrue(self.user.mfa_enabled)
        self.assertEqual(self.user.data_classification, 'sensitive')
    
    def test_security_logging_integration(self):
        """Test that security logging works with the authentication system."""
        from django.contrib.auth.signals import user_logged_in, user_login_failed
        
        # Test successful login logging
        request = RequestFactory().get('/')
        user_logged_in.send(sender=User, request=request, user=self.user)
        
        # Test failed login logging
        user_login_failed.send(
            sender=User,
            credentials={'username': 'testuser'},
            request=request
        )
        
        # No assertions needed, just checking that signals don't raise exceptions
    
    @override_settings(CACHES={
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        }
    })
    def test_comprehensive_security_workflow(self):
        """Test a comprehensive security workflow."""
        # 1. Create user with encrypted data
        self.user.mfa_secret = 'JBSWY3DPEHPK3PXP'
        self.user.data_classification = 'restricted'
        self.user.save()
        
        # 2. Test rate limiting with a smaller limit for testing
        limiter = RateLimiter(max_requests=2, time_window=60)
        user_key = f'user_{self.user.id}'
        
        # First 2 requests should be allowed
        self.assertTrue(limiter.is_allowed(user_key))
        self.assertTrue(limiter.is_allowed(user_key))
        
        # Third request should be blocked
        self.assertFalse(limiter.is_allowed(user_key))
        
        # 3. Test input sanitization
        clean_input = InputSanitizer.sanitize_string('<script>alert("xss")</script>Hello')
        self.assertEqual(clean_input, 'alert("xss")Hello')
        
        # 4. Test integrity checking
        data = f"user_data_{self.user.id}"
        checksum = IntegrityChecker.generate_checksum(data)
        self.assertTrue(IntegrityChecker.verify_checksum(data, checksum))
        
        # 5. Test security auditing
        SecurityAuditor.log_data_access(
            user=self.user,
            data_type='user_profile',
            data_id=self.user.id,
            classification='restricted'
        )
        
        # All tests passed if we reach here without exceptions