# SPDX-License-Identifier: Apache-2.0
from django.test import TestCase, RequestFactory, override_settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError, PermissionDenied
from django.http import HttpResponse
from django.utils import timezone
from django.contrib.sessions.middleware import SessionMiddleware
from django.contrib.auth.middleware import AuthenticationMiddleware
from datetime import timedelta
import uuid
import pyotp

User = get_user_model()


class UserModelTest(TestCase):
    """Test cases for the custom User model."""
    
    def setUp(self):
        """Set up test data."""
        self.user_data = {
            'username': 'testuser',
            'email': 'test@example.com',
            'first_name': 'Test',
            'last_name': 'User',
            'password': 'testpass123'
        }
    
    def test_create_user(self):
        """Test creating a user with default values."""
        user = User.objects.create_user(**self.user_data)
        
        self.assertEqual(user.username, 'testuser')
        self.assertEqual(user.email, 'test@example.com')
        self.assertEqual(user.theme, 'light')
        self.assertEqual(user.accent_color, 'blue')
        self.assertEqual(user.default_view, 'list')
        self.assertFalse(user.mfa_enabled)
        self.assertEqual(user.failed_login_attempts, 0)
        self.assertIsNone(user.account_locked_until)
        self.assertIsInstance(user.id, uuid.UUID)
    
    def test_create_user_with_custom_preferences(self):
        """Test creating a user with custom preferences."""
        user_data = self.user_data.copy()
        user_data.update({
            'theme': 'dark',
            'accent_color': 'red',
            'default_view': 'calendar',
            'mfa_enabled': True
        })
        
        user = User.objects.create_user(**user_data)
        
        self.assertEqual(user.theme, 'dark')
        self.assertEqual(user.accent_color, 'red')
        self.assertEqual(user.default_view, 'calendar')
        self.assertTrue(user.mfa_enabled)
    
    def test_user_str_representation(self):
        """Test the string representation of the user."""
        user = User.objects.create_user(**self.user_data)
        self.assertEqual(str(user), 'testuser')
    
    def test_user_uuid_primary_key(self):
        """Test that user uses UUID as primary key."""
        user = User.objects.create_user(**self.user_data)
        self.assertIsInstance(user.id, uuid.UUID)
        self.assertIsInstance(user.pk, uuid.UUID)
    
    def test_user_audit_fields(self):
        """Test that audit fields are automatically populated."""
        user = User.objects.create_user(**self.user_data)
        
        self.assertIsNotNone(user.created)
        self.assertIsNotNone(user.modified)
        self.assertLessEqual(user.created, user.modified)
    
    def test_user_theme_choices(self):
        """Test that theme field only accepts valid choices."""
        user = User.objects.create_user(**self.user_data)
        
        # Valid choices
        user.theme = 'light'
        user.save()
        user.theme = 'dark'
        user.save()
        
        # Invalid choice should still save (Django doesn't enforce at DB level)
        # but validation should catch it
        user.theme = 'invalid'
        with self.assertRaises(ValidationError):
            user.full_clean()
    
    def test_user_accent_color_choices(self):
        """Test that accent_color field only accepts valid choices."""
        user = User.objects.create_user(**self.user_data)
        
        # Valid choices
        user.accent_color = 'blue'
        user.save()
        user.accent_color = 'red'
        user.save()
        
        # Invalid choice validation
        user.accent_color = 'invalid'
        with self.assertRaises(ValidationError):
            user.full_clean()
    
    def test_user_default_view_choices(self):
        """Test that default_view field only accepts valid choices."""
        user = User.objects.create_user(**self.user_data)
        
        # Valid choices
        user.default_view = 'list'
        user.save()
        user.default_view = 'calendar'
        user.save()
        
        # Invalid choice validation
        user.default_view = 'invalid'
        with self.assertRaises(ValidationError):
            user.full_clean()
    
    def test_user_security_fields(self):
        """Test user security-related fields."""
        user = User.objects.create_user(**self.user_data)
        
        # Test MFA field
        self.assertFalse(user.mfa_enabled)
        user.mfa_enabled = True
        user.save()
        self.assertTrue(user.mfa_enabled)
        
        # Test MFA secret field
        user.mfa_secret = 'JBSWY3DPEHPK3PXP'
        user.save()
        self.assertEqual(user.mfa_secret, 'JBSWY3DPEHPK3PXP')
        
        # Test failed login attempts
        self.assertEqual(user.failed_login_attempts, 0)
        user.failed_login_attempts = 3
        user.save()
        self.assertEqual(user.failed_login_attempts, 3)
        
        # Test account lockout
        self.assertIsNone(user.account_locked_until)
        from django.utils import timezone
        lockout_time = timezone.now()
        user.account_locked_until = lockout_time
        user.save()
        self.assertEqual(user.account_locked_until, lockout_time)
    
    def test_user_meta_options(self):
        """Test User model meta options."""
        User.objects.create_user(**self.user_data)
        
        # Test db_table
        self.assertEqual(User._meta.db_table, 'auth_user')
        
        # Test verbose names
        self.assertEqual(User._meta.verbose_name, 'User')
        self.assertEqual(User._meta.verbose_name_plural, 'Users')
    
    def test_create_superuser(self):
        """Test creating a superuser."""
        superuser = User.objects.create_superuser(
            username='admin',
            email='admin@example.com',
            password='adminpass123'
        )
        
        self.assertTrue(superuser.is_staff)
        self.assertTrue(superuser.is_superuser)
        self.assertEqual(superuser.username, 'admin')
    
    def test_user_permissions_inheritance(self):
        """Test that User inherits from AbstractUser properly."""
        user = User.objects.create_user(**self.user_data)
        
        # Test inherited fields exist
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.is_active)
        self.assertIsNotNone(user.date_joined)
        
        # Test inherited methods exist
        self.assertTrue(hasattr(user, 'check_password'))
        self.assertTrue(hasattr(user, 'set_password'))
        self.assertTrue(hasattr(user, 'get_full_name'))
        self.assertTrue(hasattr(user, 'get_short_name'))


class UserSecurityTest(TestCase):
    """Test cases for User model security features."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='securitytest',
            email='security@example.com',
            password='testpass123'
        )
    
    def test_password_hashing(self):
        """Test that passwords are properly hashed."""
        # Password should not be stored in plain text
        self.assertNotEqual(self.user.password, 'testpass123')
        
        # But should be verifiable
        self.assertTrue(self.user.check_password('testpass123'))
        self.assertFalse(self.user.check_password('wrongpassword'))
    
    def test_failed_login_tracking(self):
        """Test failed login attempt tracking."""
        self.assertEqual(self.user.failed_login_attempts, 0)
        
        # Simulate failed login attempts
        self.user.failed_login_attempts += 1
        self.user.save()
        self.assertEqual(self.user.failed_login_attempts, 1)
    
    def test_account_lockout_functionality(self):
        """Test account lockout functionality."""
        from django.utils import timezone
        from datetime import timedelta
        
        # Initially not locked
        self.assertIsNone(self.user.account_locked_until)
        
        # Lock account for 30 minutes
        lockout_time = timezone.now() + timedelta(minutes=30)
        self.user.account_locked_until = lockout_time
        self.user.save()
        
        # Verify lockout
        self.assertEqual(self.user.account_locked_until, lockout_time)
        
        # Test if account is currently locked
        self.assertGreater(self.user.account_locked_until, timezone.now())
    
    def test_mfa_enablement(self):
        """Test MFA enablement functionality."""
        # Initially disabled
        self.assertFalse(self.user.mfa_enabled)
        
        # Enable MFA
        self.user.mfa_enabled = True
        self.user.save()
        
        # Verify enabled
        self.assertTrue(self.user.mfa_enabled)
        
        # Disable MFA
        self.user.mfa_enabled = False
        self.user.save()
        
        # Verify disabled
        self.assertFalse(self.user.mfa_enabled)


class AuthenticationFormsTest(TestCase):
    """Test cases for authentication forms."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        self.user_data = {
            'username': 'testuser',
            'password': 'testpass123'
        }
    
    def test_custom_authentication_form_valid(self):
        """Test valid authentication form."""
        from apps.authentication.forms import CustomAuthenticationForm
        
        form = CustomAuthenticationForm(data=self.user_data)
        self.assertTrue(form.is_valid())
        self.assertEqual(form.get_user(), self.user)
    
    def test_custom_authentication_form_invalid(self):
        """Test invalid authentication form."""
        from apps.authentication.forms import CustomAuthenticationForm
        from django.test import RequestFactory
        
        invalid_data = {
            'username': 'testuser',
            'password': 'wrongpassword'
        }
        
        factory = RequestFactory()
        request = factory.get('/')
        
        request.session = {}
        form = CustomAuthenticationForm(request=request, data=invalid_data)
        self.assertFalse(form.is_valid())
        self.assertTrue(len(form.errors) > 0)
    
    def test_mfa_setup_form_valid(self):
        """Test valid MFA setup form."""
        from apps.authentication.forms import MFASetupForm
        
        form = MFASetupForm(data={'token': '123456'})
        self.assertTrue(form.is_valid())
    
    def test_mfa_setup_form_invalid(self):
        """Test invalid MFA setup form."""
        from apps.authentication.forms import MFASetupForm
        
        # Test invalid token format
        form = MFASetupForm(data={'token': 'abc123'})
        self.assertFalse(form.is_valid())
        
        # Test wrong length
        form = MFASetupForm(data={'token': '12345'})
        self.assertFalse(form.is_valid())
    
    def test_user_preferences_form(self):
        """Test user preferences form."""
        from apps.authentication.forms import UserPreferencesForm
        
        form = UserPreferencesForm(
            instance=self.user,
            data={
                'theme': 'dark',
                'accent_color': 'red',
                'default_view': 'calendar',
                'first_name': 'Test',
                'last_name': 'User',
                'email': 'test@example.com'
            }
        )
        
        self.assertTrue(form.is_valid())
        user = form.save()
        self.assertEqual(user.theme, 'dark')
        self.assertEqual(user.accent_color, 'red')
        self.assertEqual(user.default_view, 'calendar')
    
    def test_user_registration_form_valid(self):
        """Test valid user registration form."""
        from apps.authentication.forms import UserRegistrationForm
        
        form_data = {
            'username': 'newuser',
            'email': 'newuser@example.com',
            'first_name': 'New',
            'last_name': 'User',
            'password1': 'StrongP@ssw0rd123',
            'password2': 'StrongP@ssw0rd123'
        }
        
        form = UserRegistrationForm(data=form_data)
        self.assertTrue(form.is_valid())
        
        # Test saving the form creates a user
        user = form.save()
        self.assertEqual(user.username, 'newuser')
        self.assertEqual(user.email, 'newuser@example.com')
        self.assertTrue(user.check_password('StrongP@ssw0rd123'))
    
    def test_user_registration_form_password_validation(self):
        """Test password validation in registration form."""
        from apps.authentication.forms import UserRegistrationForm
        
        # Test weak password
        form_data = {
            'username': 'newuser',
            'email': 'newuser@example.com',
            'first_name': 'New',
            'last_name': 'User',
            'password1': 'weak',
            'password2': 'weak'
        }
        
        form = UserRegistrationForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('password1', form.errors)
        
        # Test password mismatch
        form_data = {
            'username': 'newuser',
            'email': 'newuser@example.com',
            'first_name': 'New',
            'last_name': 'User',
            'password1': 'StrongP@ssw0rd123',
            'password2': 'DifferentP@ssw0rd123'
        }
        
        form = UserRegistrationForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('password2', form.errors)
    
    def test_password_change_form(self):
        """Test password change form."""
        from apps.authentication.forms import PasswordChangeForm
        
        # Test valid form
        form_data = {
            'old_password': 'testpass123',
            'new_password1': 'NewStrongP@ssw0rd123',
            'new_password2': 'NewStrongP@ssw0rd123'
        }
        
        form = PasswordChangeForm(user=self.user, data=form_data)
        self.assertTrue(form.is_valid())
        
        # Save the form and verify password changed
        form.save()
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('NewStrongP@ssw0rd123'))


class AuthenticationViewsTest(TestCase):
    """Test cases for authentication views."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        self.client.login(username='testuser', password='testpass123')
    
    def test_login_view_get(self):
        """Test login view GET request."""
        self.client.logout()
        response = self.client.get('/auth/login/')
        self.assertEqual(response.status_code, 200)
    
    def test_profile_view_authenticated(self):
        """Profile requires MFA: a signed-in user without MFA is sent to set it up."""
        response = self.client.get('/auth/profile/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('mfa', response.url)
    
    def test_profile_view_unauthenticated(self):
        """Test profile view redirects unauthenticated users."""
        self.client.logout()
        response = self.client.get('/auth/profile/')
        self.assertEqual(response.status_code, 302)  # Redirect to login
    
    def test_logout_view(self):
        """Test logout view."""
        # Logout is POST-only (Django 5), which blocks cross-site logout links.
        self.assertEqual(self.client.get('/auth/logout/').status_code, 405)
        response = self.client.post('/auth/logout/')
        self.assertEqual(response.status_code, 302)  # Redirect to login page
        
        # Verify user is logged out
        response = self.client.get('/auth/profile/')
        self.assertEqual(response.status_code, 302)  # Redirect to login


class AuthenticationUtilsTest(TestCase):
    """Test cases for authentication utilities."""
    
    def test_generate_mfa_secret(self):
        """Test MFA secret generation."""
        from apps.authentication.utils import generate_mfa_secret
        
        secret = generate_mfa_secret()
        self.assertIsInstance(secret, str)
        self.assertEqual(len(secret), 32)  # Base32 secret length
    
    def test_generate_secure_token(self):
        """Test secure token generation."""
        from apps.authentication.utils import generate_secure_token
        
        token = generate_secure_token()
        self.assertIsInstance(token, str)
        self.assertEqual(len(token), 32)  # Default length
        
        # Test custom length
        token = generate_secure_token(16)
        self.assertEqual(len(token), 16)
    
    def test_check_password_strength(self):
        """Test password strength checking."""
        from apps.authentication.utils import check_password_strength
        
        # Test weak password
        result = check_password_strength('password')
        self.assertEqual(result['strength'], 'Weak')
        self.assertGreater(len(result['feedback']), 0)
        
        # Test strong password
        result = check_password_strength('MyStr0ng!P@ssw0rd123')
        self.assertEqual(result['strength'], 'Strong')
        self.assertEqual(len(result['feedback']), 0)
    
    def test_get_client_ip(self):
        """Test client IP extraction."""
        from apps.authentication.utils import get_client_ip
        from django.test import RequestFactory
        
        factory = RequestFactory()
        
        # Test direct IP
        request = factory.get('/')
        request.META['REMOTE_ADDR'] = '192.168.1.1'
        ip = get_client_ip(request)
        self.assertEqual(ip, '192.168.1.1')
        
        # Test forwarded IP
        request = factory.get('/')
        request.META['HTTP_X_FORWARDED_FOR'] = '10.0.0.1, 192.168.1.1'
        request.META['REMOTE_ADDR'] = '192.168.1.1'
        ip = get_client_ip(request)
        self.assertEqual(ip, '10.0.0.1')
    
    def test_encrypt_decrypt_sensitive_data(self):
        """Test encryption and decryption of sensitive data."""
        from apps.authentication.utils import encrypt_sensitive_data, decrypt_sensitive_data
        
        # Set a test encryption key
        test_key = b'0123456789abcdef0123456789abcdef'
        
        # Test encryption and decryption
        original_data = "sensitive information"
        encrypted_data = encrypt_sensitive_data(original_data, test_key)
        
        # Encrypted data should be different from original
        self.assertNotEqual(encrypted_data, original_data)
        
        # Decrypted data should match original
        decrypted_data = decrypt_sensitive_data(encrypted_data, test_key)
        self.assertEqual(decrypted_data, original_data)
    
    def test_generate_password_reset_token(self):
        """Test password reset token generation and verification."""
        from apps.authentication.utils import generate_password_reset_token, verify_password_reset_token
        
        # Create a test user
        user = User.objects.create_user(
            username='resetuser',
            email='reset@example.com',
            password='testpass123'
        )
        
        # Generate token
        token = generate_password_reset_token(user)
        self.assertIsInstance(token, str)
        
        # Verify token
        verified_user = verify_password_reset_token(token)
        self.assertEqual(verified_user, user)
        
        # Test expired token
        with override_settings(PASSWORD_RESET_TIMEOUT=0):  # Force token to expire
            expired_user = verify_password_reset_token(token)
            self.assertIsNone(expired_user)
    
    def test_validate_session_security(self):
        """Test session security validation."""
        from apps.authentication.utils import validate_session_security
        from django.test import RequestFactory
        
        factory = RequestFactory()
        request = factory.get('/')
        
        # Create a test user
        user = User.objects.create_user(
            username='sessionuser',
            email='session@example.com',
            password='testpass123'
        )
        
        request.user = user
        request.session = {}
        
        # New session should be valid
        self.assertTrue(validate_session_security(request))
        
        # Test with session data
        request.session['session_start'] = timezone.now().isoformat()
        request.session['session_ip'] = '192.168.1.1'
        request.session['session_user_agent'] = 'Test User Agent'
        
        # Session with matching IP should be valid
        request.META['REMOTE_ADDR'] = '192.168.1.1'
        self.assertTrue(validate_session_security(request))
        
        # Session with different IP should be invalid
        request.META['REMOTE_ADDR'] = '192.168.1.2'
        self.assertFalse(validate_session_security(request))


class AuthenticationMiddlewareTest(TestCase):
    """Test cases for authentication middleware."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.factory = RequestFactory()
    
    def test_security_audit_middleware(self):
        """Test security audit middleware functionality."""
        from apps.authentication.middleware import SecurityAuditMiddleware
        
        request = self.factory.get('/test/')
        request.user = self.user
        
        # Add session middleware to populate request.session
        session_middleware = SessionMiddleware(lambda req: None)
        session_middleware.process_request(request)
        request.session.save()
        
        # Create middleware instance
        def get_response(request):
            return HttpResponse('OK')
        
        middleware = SecurityAuditMiddleware(get_response)
        
        # Test middleware processing
        response = middleware(request)
        self.assertEqual(response.status_code, 200)
        
        # Test security headers
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(response['X-Frame-Options'], 'DENY')
        self.assertEqual(response['X-XSS-Protection'], '1; mode=block')
    
    def test_data_classification_middleware(self):
        """Test data classification middleware functionality."""
        from apps.authentication.middleware import DataClassificationMiddleware
        
        request = self.factory.get('/test/')
        request.user = self.user
        
        # Create middleware instance
        def get_response(request):
            response = HttpResponse('OK')
            response.data_classification = 'sensitive'
            return response
        
        middleware = DataClassificationMiddleware(get_response)
        
        # Test middleware processing
        response = middleware(request)
        self.assertEqual(response.status_code, 200)
        
        # Test classification header
        self.assertEqual(response['X-Data-Classification'], 'SENSITIVE')
    
    def test_session_security_middleware(self):
        """Test session security middleware functionality."""
        from apps.authentication.middleware import SessionSecurityMiddleware
        
        request = self.factory.get('/test/')
        request.user = self.user
        request.session = {}
        
        # Add session middleware to populate request.session
        session_middleware = SessionMiddleware(lambda req: None)
        session_middleware.process_request(request)
        request.session.save()
        
        # Add auth middleware, then set the user explicitly (the middleware
        # would otherwise replace it with AnonymousUser for this bare session).
        auth_middleware = AuthenticationMiddleware(lambda req: None)
        auth_middleware.process_request(request)
        request.user = self.user
        from django.contrib.messages.storage.fallback import FallbackStorage
        request._messages = FallbackStorage(request)  # the timeout path adds a message
        
        # Create middleware instance
        def get_response(request):
            return HttpResponse('OK')
        
        middleware = SessionSecurityMiddleware(get_response)
        
        # Test middleware processing with valid session
        request.session['last_activity'] = timezone.now().isoformat()
        response = middleware(request)
        self.assertEqual(response.status_code, 200)
        
        # Test middleware processing with expired session
        request.session['last_activity'] = (timezone.now() - timedelta(hours=2)).isoformat()
        response = middleware(request)
        # Should redirect to login page
        self.assertEqual(response.status_code, 302)


class AuthenticationMixinsTest(TestCase):
    """Test cases for authentication mixins."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.factory = RequestFactory()
    
    def test_security_audit_mixin(self):
        """Test security audit mixin functionality."""
        from apps.authentication.mixins import SecurityAuditMixin
        
        request = self.factory.get('/test/')
        request.user = self.user
        
        # Create mixin instance
        mixin = SecurityAuditMixin()
        mixin.request = request
        
        # Test IP extraction
        ip = mixin.get_client_ip()
        self.assertIsNotNone(ip)
        
        # Test user agent extraction
        user_agent = mixin.get_user_agent()
        self.assertIsNotNone(user_agent)
        
        # Test logging
        mixin.log_security_event('test_event', 'Test security event')
        # No assertion needed, just checking it doesn't raise an exception
    
    def test_mfa_required_mixin(self):
        """Test MFA required mixin functionality."""
        from apps.authentication.mixins import MFARequiredMixin
        from django.views import View
        
        # Create a test view with MFARequiredMixin
        class TestView(MFARequiredMixin, View):
            def get(self, request):
                return HttpResponse('OK')
        
        view = TestView.as_view()
        
        # Test with authenticated user without MFA
        request = self.factory.get('/test/')
        request.user = self.user
        
        # Add session middleware + message storage (RequestFactory has neither)
        session_middleware = SessionMiddleware(lambda req: None)
        session_middleware.process_request(request)
        request.session.save()
        from django.contrib.messages.storage.fallback import FallbackStorage
        request._messages = FallbackStorage(request)
        
        # Should redirect to MFA setup
        response = view(request)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/mfa/setup/', response.url)
        
        # Test with MFA enabled but not verified
        self.user.mfa_enabled = True
        self.user.save()
        
        response = view(request)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/mfa/verify/', response.url)
        
        # Test with MFA verified
        request.session['mfa_verified'] = True
        
        # Need to add messages middleware for this test
        from django.contrib.messages.storage.fallback import FallbackStorage
        
        request._messages = FallbackStorage(request)
        
        response = view(request)
        self.assertEqual(response.status_code, 200)
    
    def test_role_required_mixin(self):
        """Test role required mixin functionality."""
        from apps.authentication.mixins import RoleRequiredMixin
        from django.views import View
        
        # Create a test view with RoleRequiredMixin
        class TestView(RoleRequiredMixin, View):
            required_roles = ['staff']
            
            def get(self, request):
                return HttpResponse('OK')
        
        view = TestView.as_view()
        
        # Test with user without required role
        request = self.factory.get('/test/')
        request.user = self.user
        
        with self.assertRaises(PermissionDenied):
            view(request)
        
        # Test with user with required role
        self.user.is_staff = True
        self.user.save()
        
        response = view(request)
        self.assertEqual(response.status_code, 200)
    
    def test_data_classification_mixin(self):
        """Test data classification mixin functionality."""
        from apps.authentication.mixins import DataClassificationMixin
        from django.views import View
        
        # Create a test view with DataClassificationMixin
        class TestView(DataClassificationMixin, View):
            required_classification_level = 'sensitive'
            
            def get(self, request):
                return HttpResponse('OK')
        
        view = TestView.as_view()
        
        # Test with user without sufficient classification level
        request = self.factory.get('/test/')
        request.user = self.user
        
        with self.assertRaises(PermissionDenied):
            view(request)
        
        # Test with user with sufficient classification level
        self.user.is_staff = True  # Staff users have sensitive access
        self.user.save()
        
        response = view(request)
        self.assertEqual(response.status_code, 200)


class AuthenticationContextProcessorTest(TestCase):
    """Test cases for authentication context processors."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123',
            theme='dark',
            accent_color='red',
            default_view='calendar'
        )
        self.factory = RequestFactory()
    
    def test_authentication_context_processor(self):
        """Test authentication context processor."""
        from apps.authentication.context_processors import authentication_context
        
        # Test with authenticated user
        request = self.factory.get('/')
        request.user = self.user
        
        context = authentication_context(request)
        
        self.assertEqual(context['user_theme'], 'dark')
        self.assertEqual(context['user_accent_color'], 'red')
        self.assertEqual(context['user_default_view'], 'calendar')
        self.assertFalse(context['mfa_enabled'])
        
        # Test with MFA enabled
        self.user.mfa_enabled = True
        self.user.save()
        
        context = authentication_context(request)
        self.assertTrue(context['mfa_enabled'])
        
        # Test with anonymous user
        from django.contrib.auth.models import AnonymousUser
        request.user = AnonymousUser()
        
        context = authentication_context(request)
        self.assertNotIn('user_theme', context)
        self.assertNotIn('user_accent_color', context)
        self.assertNotIn('user_default_view', context)
        self.assertNotIn('mfa_enabled', context)


class AuthenticationSignalsTest(TestCase):
    """Test cases for authentication signals."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.factory = RequestFactory()
    
    def test_user_logged_in_signal(self):
        """Test user_logged_in signal handler."""
        from django.contrib.auth.signals import user_logged_in
        
        # Create a request
        request = self.factory.get('/')
        request.session = {}
        
        # Manually trigger the signal
        user_logged_in.send(sender=User, request=request, user=self.user)
        
        # Check that failed login attempts were reset
        self.user.refresh_from_db()
        self.assertEqual(self.user.failed_login_attempts, 0)
        
        # Check that session data was set
        self.assertIn('session_start', request.session)
        self.assertIn('session_ip', request.session)
        self.assertIn('session_user_agent', request.session)
        self.assertIn('last_activity', request.session)
    
    def test_user_login_failed_signal(self):
        """Test user_login_failed signal handler."""
        from django.contrib.auth.signals import user_login_failed
        
        # Create a request
        request = self.factory.get('/')
        
        # Set initial failed login attempts
        self.user.failed_login_attempts = 0
        self.user.save()
        
        # Manually trigger the signal
        user_login_failed.send(
            sender=User,
            credentials={'username': 'testuser'},
            request=request
        )
        
        # Check that failed login attempts were incremented
        self.user.refresh_from_db()
        self.assertEqual(self.user.failed_login_attempts, 1)
        
        # Test account lockout after 5 failed attempts
        self.user.failed_login_attempts = 4
        self.user.save()
        
        # Trigger the signal again
        user_login_failed.send(
            sender=User,
            credentials={'username': 'testuser'},
            request=request
        )
        
        # Check that account is now locked
        self.user.refresh_from_db()
        self.assertEqual(self.user.failed_login_attempts, 5)
        self.assertIsNotNone(self.user.account_locked_until)
        self.assertGreater(self.user.account_locked_until, timezone.now())


class AuthenticationSecurityTest(TestCase):
    """Test cases for authentication security features."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='securitytest',
            email='security@example.com',
            password='testpass123'
        )
    
    def test_account_lockout(self):
        """Test account lockout functionality."""
        from django.utils import timezone
        from datetime import timedelta
        
        # Test failed login attempts
        self.assertEqual(self.user.failed_login_attempts, 0)
        
        # Simulate failed login attempts
        self.user.failed_login_attempts = 3
        self.user.account_locked_until = timezone.now() + timedelta(minutes=30)
        self.user.save()
        
        # Verify lockout
        self.assertTrue(self.user.account_locked_until > timezone.now())
    
    def test_mfa_secret_field(self):
        """Test MFA secret field functionality."""
        # Test MFA secret storage
        self.user.mfa_secret = 'JBSWY3DPEHPK3PXP'
        self.user.mfa_enabled = True
        self.user.save()
        
        # Verify MFA settings
        self.assertTrue(self.user.mfa_enabled)
        self.assertEqual(self.user.mfa_secret, 'JBSWY3DPEHPK3PXP')
    
    def test_password_validation(self):
        """Test password validation requirements."""
        from apps.authentication.forms import PasswordChangeForm
        
        # Test weak password
        form = PasswordChangeForm(
            user=self.user,
            data={
                'old_password': 'testpass123',
                'new_password1': 'weak',
                'new_password2': 'weak'
            }
        )
        
        self.assertFalse(form.is_valid())
        self.assertIn('new_password1', form.errors)
    
    def test_session_security(self):
        """Test session security features."""
        from apps.authentication.utils import validate_session_security
        from django.test import RequestFactory
        
        factory = RequestFactory()
        request = factory.get('/test/')
        request.user = self.user
        request.session = {}
        
        # Test session validation
        is_valid = validate_session_security(request)
        self.assertTrue(is_valid)  # Should be valid for new session
    
    def test_verify_mfa_token(self):
        """Test MFA token verification."""
        from apps.authentication.utils import verify_mfa_token
        
        # Set up MFA for user
        secret = 'JBSWY3DPEHPK3PXP'  # Test secret
        self.user.mfa_secret = secret
        self.user.mfa_enabled = True
        self.user.save()
        
        # Generate a valid token
        totp = pyotp.TOTP(secret)
        valid_token = totp.now()
        
        # Test valid token
        self.assertTrue(verify_mfa_token(self.user, valid_token))
        
        # Test invalid token
        invalid_token = '000000'
        self.assertFalse(verify_mfa_token(self.user, invalid_token))
        
        # Test with MFA disabled
        self.user.mfa_enabled = False
        self.user.save()
        self.assertFalse(verify_mfa_token(self.user, valid_token))