# SPDX-License-Identifier: Apache-2.0
"""
Authentication forms for HillDesk.
Implements secure forms with validation and security features.
"""

from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm as DjangoPasswordChangeForm
from django.contrib.auth import get_user_model, authenticate
from django.core.exceptions import ValidationError
from django.utils import timezone
import re

User = get_user_model()


class CustomAuthenticationForm(AuthenticationForm):
    """
    Custom authentication form with enhanced security features.
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Add CSS classes and security attributes
        self.fields['username'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'Username',
            'autocomplete': 'username',
            'required': True,
        })
        
        self.fields['password'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'Password',
            'autocomplete': 'current-password',
            'required': True,
        })
    
    def clean(self):
        """Enhanced authentication with security checks."""
        username = self.cleaned_data.get('username')
        password = self.cleaned_data.get('password')
        
        if username and password:
            # Check if user exists and account is not locked
            try:
                user = User.objects.get(username=username)
                
                # Check account lockout
                if (user.account_locked_until and 
                    user.account_locked_until > timezone.now()):
                    raise ValidationError(
                        "Account is temporarily locked due to multiple failed login attempts. "
                        f"Please try again after {user.account_locked_until.strftime('%Y-%m-%d %H:%M:%S')}."
                    )
                
                # Authenticate user
                self.user_cache = authenticate(
                    self.request,
                    username=username,
                    password=password
                )
                
                if self.user_cache is None:
                    raise self.get_invalid_login_error()
                else:
                    self.confirm_login_allowed(self.user_cache)
                    
            except User.DoesNotExist:
                # Don't reveal if user exists or not
                raise self.get_invalid_login_error()
        
        return self.cleaned_data
    
    def get_invalid_login_error(self):
        """Return a generic error message for failed login attempts."""
        return ValidationError(
            "Please enter a correct username and password. Note that both fields may be case-sensitive.",
            code='invalid_login',
        )


class MFASetupForm(forms.Form):
    """Form for setting up Multi-Factor Authentication."""
    
    token = forms.CharField(
        max_length=6,
        min_length=6,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '000000',
            'autocomplete': 'one-time-code',
            'pattern': '[0-9]{6}',
            'title': 'Enter the 6-digit code from your authenticator app',
        }),
        help_text='Enter the 6-digit code from your authenticator app'
    )
    
    def clean_token(self):
        """Validate MFA token format."""
        token = self.cleaned_data.get('token')
        
        if not token:
            raise ValidationError('Token is required.')
        
        if not token.isdigit():
            raise ValidationError('Token must contain only digits.')
        
        if len(token) != 6:
            raise ValidationError('Token must be exactly 6 digits.')
        
        return token


class MFAVerificationForm(forms.Form):
    """Form for verifying Multi-Factor Authentication."""
    
    token = forms.CharField(
        max_length=6,
        min_length=6,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '000000',
            'autocomplete': 'one-time-code',
            'pattern': '[0-9]{6}',
            'title': 'Enter the 6-digit code from your authenticator app',
            'autofocus': True,
        }),
        help_text='Enter the 6-digit code from your authenticator app'
    )
    
    def clean_token(self):
        """Validate MFA token format."""
        token = self.cleaned_data.get('token')
        
        if not token:
            raise ValidationError('Verification code is required.')
        
        if not token.isdigit():
            raise ValidationError('Verification code must contain only digits.')
        
        if len(token) != 6:
            raise ValidationError('Verification code must be exactly 6 digits.')
        
        return token


class UserPreferencesForm(forms.ModelForm):
    """Form for managing user preferences."""
    
    class Meta:
        model = User
        fields = ['theme', 'accent_color', 'default_view', 'first_name', 'last_name', 'email']
        widgets = {
            'theme': forms.Select(attrs={'class': 'form-control'}),
            'accent_color': forms.Select(attrs={'class': 'form-control'}),
            'default_view': forms.Select(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Add help text
        self.fields['theme'].help_text = 'Choose your preferred interface theme'
        self.fields['accent_color'].help_text = 'Choose your preferred accent color'
        self.fields['default_view'].help_text = 'Choose your default view for the schedule page'
        self.fields['email'].help_text = 'Your email address for notifications and account recovery'
    
    def clean_email(self):
        """Validate email uniqueness."""
        email = self.cleaned_data.get('email')
        
        if email:
            # Check if email is already used by another user
            existing_user = User.objects.filter(email=email).exclude(pk=self.instance.pk).first()
            if existing_user:
                raise ValidationError('This email address is already in use.')
        
        return email


class PasswordChangeForm(DjangoPasswordChangeForm):
    """Enhanced password change form with security requirements."""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Add CSS classes and security attributes
        for field_name, field in self.fields.items():
            field.widget.attrs.update({
                'class': 'form-control',
                'autocomplete': 'new-password' if 'new' in field_name else 'current-password',
            })
        
        # Update help text with security requirements
        self.fields['new_password1'].help_text = (
            'Your password must contain at least 12 characters, including uppercase and lowercase letters, '
            'numbers, and special characters. It cannot be too similar to your other personal information.'
        )
    
    def clean_new_password1(self):
        """Enhanced password validation."""
        password = self.cleaned_data.get('new_password1')
        
        if not password:
            return password
        
        # Minimum length check (stricter than default)
        if len(password) < 12:
            raise ValidationError('Password must be at least 12 characters long.')
        
        # Complexity requirements
        if not re.search(r'[A-Z]', password):
            raise ValidationError('Password must contain at least one uppercase letter.')
        
        if not re.search(r'[a-z]', password):
            raise ValidationError('Password must contain at least one lowercase letter.')
        
        if not re.search(r'\d', password):
            raise ValidationError('Password must contain at least one number.')
        
        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
            raise ValidationError('Password must contain at least one special character.')
        
        # Check against common passwords
        common_passwords = [
            'password', '123456', 'qwerty', 'abc123', 'password123',
            'admin', 'letmein', 'welcome', 'monkey', '1234567890'
        ]
        
        if password.lower() in common_passwords:
            raise ValidationError('This password is too common. Please choose a more secure password.')
        
        # Check for user information in password
        user = getattr(self, 'user', None)
        if user:
            user_info = [
                user.username.lower(),
                user.first_name.lower(),
                user.last_name.lower(),
                user.email.split('@')[0].lower() if user.email else '',
            ]
            
            for info in user_info:
                if info and len(info) > 2 and info in password.lower():
                    raise ValidationError(
                        'Password cannot contain your personal information.'
                    )
        
        return password


class UserRegistrationForm(forms.ModelForm):
    """Form for user registration with security features."""
    
    password1 = forms.CharField(
        label='Password',
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'autocomplete': 'new-password',
        }),
        help_text=(
            'Your password must contain at least 12 characters, including uppercase and lowercase letters, '
            'numbers, and special characters.'
        )
    )
    
    password2 = forms.CharField(
        label='Confirm Password',
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'autocomplete': 'new-password',
        }),
        help_text='Enter the same password as before, for verification.'
    )
    
    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email']
        widgets = {
            'username': forms.TextInput(attrs={
                'class': 'form-control',
                'autocomplete': 'username',
            }),
            'first_name': forms.TextInput(attrs={
                'class': 'form-control',
                'autocomplete': 'given-name',
            }),
            'last_name': forms.TextInput(attrs={
                'class': 'form-control',
                'autocomplete': 'family-name',
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-control',
                'autocomplete': 'email',
            }),
        }
    
    def clean_username(self):
        """Validate username requirements."""
        username = self.cleaned_data.get('username')
        
        if not username:
            return username
        
        # Username requirements
        if len(username) < 3:
            raise ValidationError('Username must be at least 3 characters long.')
        
        if not re.match(r'^[a-zA-Z0-9_.-]+$', username):
            raise ValidationError(
                'Username can only contain letters, numbers, underscores, dots, and hyphens.'
            )
        
        # Check for reserved usernames
        reserved_usernames = [
            'admin', 'administrator', 'root', 'system', 'api', 'www',
            'mail', 'email', 'support', 'help', 'info', 'contact'
        ]
        
        if username.lower() in reserved_usernames:
            raise ValidationError('This username is reserved. Please choose another.')
        
        return username
    
    def clean_email(self):
        """Validate email requirements."""
        email = self.cleaned_data.get('email')
        
        if email:
            # Check if email is already registered
            if User.objects.filter(email=email).exists():
                raise ValidationError('This email address is already registered.')
        
        return email
    
    def clean_password1(self):
        """Validate password requirements."""
        password = self.cleaned_data.get('password1')
        
        if not password:
            return password
        
        # Use the same validation as PasswordChangeForm
        form = PasswordChangeForm(user=None)
        form.cleaned_data = {'new_password1': password}
        
        try:
            return form.clean_new_password1()
        except ValidationError as e:
            raise ValidationError(e.messages)
    
    def clean_password2(self):
        """Validate password confirmation."""
        password1 = self.cleaned_data.get('password1')
        password2 = self.cleaned_data.get('password2')
        
        if password1 and password2:
            if password1 != password2:
                raise ValidationError('The two password fields didn\'t match.')
        
        return password2
    
    def save(self, commit=True):
        """Save user with hashed password."""
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password1'])
        
        if commit:
            user.save()
        
        return user


class AccountRecoveryForm(forms.Form):
    """Form for account recovery/password reset."""

    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your email address',
            'autocomplete': 'email',
        }),
        help_text='Enter the email address associated with your account'
    )

    def clean_email(self):
        """Validate that email exists in system."""
        email = self.cleaned_data.get('email')

        if email:
            if not User.objects.filter(email=email).exists():
                # Don't reveal if email exists or not for security
                pass  # We'll handle this in the view

        return email


# =============================================================================
# Office Setup and Role Management Forms
# =============================================================================

class OfficeSetupForm(forms.Form):
    """
    Form for the office setup wizard.
    Used by the first admin user to configure office settings.
    """

    member_name = forms.CharField(
        max_length=200,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'e.g., Rep. Jane Smith',
        }),
        label='Member Name',
        help_text='Full name of the Member of Congress'
    )

    district = forms.CharField(
        max_length=100,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'e.g., NY-01',
        }),
        label='Congressional District',
        help_text='Congressional district (e.g., NY-01, CA-45)'
    )

    dc_office_address = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Washington D.C. office address',
        }),
        label='D.C. Office Address',
        help_text='Washington D.C. office address (optional)'
    )

    district_office_address = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'District office address',
        }),
        label='District Office Address',
        help_text='District office address (optional)'
    )

    def clean_district(self):
        """Validate district format."""
        district = self.cleaned_data.get('district')

        if district:
            # Allow flexible formats but ensure it looks reasonable
            district = district.strip().upper()

            # Basic validation - should contain state abbreviation and number
            if len(district) < 3:
                raise ValidationError(
                    'Please enter a valid district format (e.g., NY-01, CA-45)'
                )

        return district


class RoleAssignmentForm(forms.Form):
    """
    Form for assigning an office Role to a user.
    The available roles are the calling office's own Role objects.
    """

    user_id = forms.UUIDField(
        widget=forms.HiddenInput(),
    )

    role = forms.ModelChoiceField(
        queryset=None,  # set in __init__ from office
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Role',
        empty_label=None,
        help_text='Select the role for this user'
    )

    def __init__(self, *args, office=None, **kwargs):
        super().__init__(*args, **kwargs)
        from .models import Role
        qs = Role.objects.filter(office=office) if office is not None else Role.objects.none()
        self.fields['role'].queryset = qs
        # Show just the role name in the dropdown (not "Name (Office)").
        self.fields['role'].label_from_instance = lambda role: role.name


class RoleForm(forms.ModelForm):
    """
    Create/edit an office Role with a multiselect of permissions.

    Permission choices come from the catalog in
    ``apps.authentication.permissions.Permissions.PERMISSION_GROUPS``. The form
    exposes ``permission_groups`` so the template can render grouped checkboxes.
    """

    permissions = forms.MultipleChoiceField(
        required=False,
        widget=forms.CheckboxSelectMultiple,
        choices=[],
    )

    class Meta:
        from .models import Role as _Role
        model = _Role
        fields = ['name', 'description', 'permissions']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., Intern, Press Aide',
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'What is this role for? (optional)',
            }),
        }

    def __init__(self, *args, office=None, **kwargs):
        super().__init__(*args, **kwargs)
        from .permissions import Permissions
        self.office = office
        self.permission_groups = Permissions.PERMISSION_GROUPS
        # Accept any real permission key for validation; clean_permissions strips
        # admin-only keys so submitting one degrades gracefully instead of
        # failing the whole form. The template renders only toggleable options.
        self.fields['permissions'].choices = [
            (key, key) for key in Permissions.all_permissions()
        ]
        # Pre-check current permissions when editing
        if self.instance and self.instance.pk:
            self.fields['permissions'].initial = list(self.instance.permissions or [])

    def clean_name(self):
        name = (self.cleaned_data.get('name') or '').strip()
        if not name:
            raise ValidationError('Role name is required.')
        from .models import Role
        # Enforce unique name within the office (case-insensitive), excluding self
        clash = Role.objects.filter(office=self.office, name__iexact=name)
        if self.instance and self.instance.pk:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise ValidationError('A role with this name already exists in your office.')
        return name

    def clean_permissions(self):
        from .permissions import Permissions
        selected = set(self.cleaned_data.get('permissions') or [])
        # Guard against tampering: only toggleable keys are allowed.
        valid = set(Permissions.toggleable_permissions())
        selected &= valid
        # Expand to the dependency closure so a role never holds a capability
        # without its prerequisites (e.g. edit_all implies view_all).
        expanded = Permissions.expand_permissions(selected) & valid
        return sorted(expanded)

    def save(self, commit=True):
        from django.utils.text import slugify
        from .models import Role
        role = super().save(commit=False)
        role.office = self.office
        # Generate a stable, unique slug from the name on first save only.
        if not role.slug:
            base = slugify(role.name) or 'role'
            slug = base
            i = 2
            while Role.objects.filter(office=self.office, slug=slug).exclude(pk=role.pk).exists():
                slug = f'{base}-{i}'
                i += 1
            role.slug = slug
        if commit:
            role.save()
        return role