# SPDX-License-Identifier: Apache-2.0
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
import uuid

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
        
        invalid_data = {
            'username': 'testuser',
            'password': 'wrongpassword'
        }
        
        form = CustomAuthenticationForm(data=invalid_data)
        self.assertFalse(form.is_valid())
    
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


class AuthenticationMiddlewareTest(TestCase):
    """Test cases for authentication middleware."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
    
    def test_security_audit_middleware(self):
        """Test security audit middleware functionality."""
        from apps.authentication.middleware import SecurityAuditMiddleware
        from django.test import RequestFactory
        
        factory = RequestFactory()
        request = factory.get('/test/')
        request.user = self.user
        
        # Create middleware instance
        def get_response(request):
            from django.http import HttpResponse
            return HttpResponse('OK')
        
        middleware = SecurityAuditMiddleware(get_response)
        
        # Test middleware processing
        response = middleware(request)
        self.assertEqual(response.status_code, 200)


class AuthenticationMixinsTest(TestCase):
    """Test cases for authentication mixins."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
    
    def test_security_audit_mixin(self):
        """Test security audit mixin functionality."""
        from apps.authentication.mixins import SecurityAuditMixin
        from django.test import RequestFactory
        
        factory = RequestFactory()
        request = factory.get('/test/')
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