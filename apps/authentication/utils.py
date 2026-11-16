# SPDX-License-Identifier: Apache-2.0
"""
Authentication utilities for HillDesk.
Provides MFA, security, and authentication helper functions.
"""

import secrets
import string
import hashlib
import hmac
import base64
import pyotp
import qrcode
import io
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone
from django.urls import reverse
from cryptography.fernet import Fernet
import logging

User = get_user_model()
logger = logging.getLogger('apps.authentication')
security_logger = logging.getLogger('security_audit')


def generate_mfa_secret():
    """Generate a secure random secret for MFA."""
    return pyotp.random_base32()


def verify_mfa_token(user, token):
    """Verify MFA token for a user."""
    if not user.mfa_enabled:
        return False
    
    # Get the user's MFA secret (this would need to be stored securely)
    secret = getattr(user, 'mfa_secret', None)
    if not secret:
        return False
    
    try:
        totp = pyotp.TOTP(secret)
        return totp.verify(token, valid_window=1)
    except Exception as e:
        logger.error(f"MFA verification error for user {user.username}: {e}")
        return False


def generate_mfa_qr_code(user, secret):
    """Generate QR code for MFA setup."""
    issuer_name = getattr(settings, 'MFA_ISSUER_NAME', 'HillDesk')
    
    totp_uri = pyotp.totp.TOTP(secret).provisioning_uri(
        name=user.email or user.username,
        issuer_name=issuer_name
    )
    
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(totp_uri)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    
    return base64.b64encode(buffer.getvalue()).decode()


def generate_secure_token(length=32):
    """Generate a cryptographically secure random token."""
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def hash_token(token, salt=None):
    """Hash a token with optional salt."""
    if salt is None:
        salt = secrets.token_bytes(32)
    
    # Use PBKDF2 for secure hashing
    from django.contrib.auth.hashers import PBKDF2PasswordHasher
    hasher = PBKDF2PasswordHasher()
    return hasher.encode(token, salt)


def verify_token_hash(token, hashed_token):
    """Verify a token against its hash."""
    from django.contrib.auth.hashers import check_password
    return check_password(token, hashed_token)


def encrypt_sensitive_data(data, key=None):
    """Encrypt sensitive data using Fernet symmetric encryption."""
    if key is None:
        key = getattr(settings, 'FIELD_ENCRYPTION_KEY', None)
        if not key:
            raise ValueError("Encryption key not configured")
    
    # Ensure key is bytes
    if isinstance(key, str):
        key = key.encode()
    
    # Create Fernet instance
    f = Fernet(base64.urlsafe_b64encode(key[:32].ljust(32, b'0')))
    
    # Encrypt data
    if isinstance(data, str):
        data = data.encode()
    
    return f.encrypt(data).decode()


def decrypt_sensitive_data(encrypted_data, key=None):
    """Decrypt sensitive data using Fernet symmetric encryption."""
    if key is None:
        key = getattr(settings, 'FIELD_ENCRYPTION_KEY', None)
        if not key:
            raise ValueError("Encryption key not configured")
    
    # Ensure key is bytes
    if isinstance(key, str):
        key = key.encode()
    
    # Create Fernet instance
    f = Fernet(base64.urlsafe_b64encode(key[:32].ljust(32, b'0')))
    
    # Decrypt data
    if isinstance(encrypted_data, str):
        encrypted_data = encrypted_data.encode()
    
    return f.decrypt(encrypted_data).decode()


def _reset_signature(data, user):
    """HMAC over the token data plus state that changes once the token is used.

    Mixing in the current password hash and last login (as Django's own
    PasswordResetTokenGenerator does) makes a token stop working as soon as
    the password is changed or the user signs in, so it is single-use.
    """
    secret_key = getattr(settings, 'SECRET_KEY', '')
    last_login = user.last_login.replace(microsecond=0, tzinfo=None) if user.last_login else ''
    message = f"{data}:{user.password}:{last_login}"
    return hmac.new(secret_key.encode(), message.encode(), hashlib.sha256).hexdigest()


def generate_password_reset_token(user):
    """Generate a single-use, time-limited password reset token."""
    timestamp = str(int(timezone.now().timestamp()))
    data = f"{user.id}:{user.email}:{timestamp}"
    signature = _reset_signature(data, user)
    return base64.urlsafe_b64encode(f"{data}:{signature}".encode()).decode()


def verify_password_reset_token(token, max_age=None):
    """Return the user for a valid token, else None.

    Valid means: correctly signed, younger than ``max_age`` seconds (default
    settings.PASSWORD_RESET_TIMEOUT), and the user's password and last login
    are unchanged since it was issued (single use).
    """
    if max_age is None:
        max_age = getattr(settings, 'PASSWORD_RESET_TIMEOUT', 3600)
    try:
        decoded = base64.urlsafe_b64decode(token.encode()).decode()
        data, signature = decoded.rsplit(':', 1)
        user_id, email, timestamp = data.split(':')

        if timezone.now().timestamp() - int(timestamp) > max_age:
            return None

        user = User.objects.get(id=user_id, email=email)
        if not hmac.compare_digest(signature, _reset_signature(data, user)):
            return None
        return user

    except Exception as e:
        logger.error(f"Password reset token verification error: {e}")
        return None


def send_password_reset_email(user, token):
    """Send password reset email to user."""
    reset_url = reverse('authentication:password_reset_confirm', kwargs={'token': token})
    
    context = {
        'user': user,
        'reset_url': reset_url,
        'site_name': 'HillDesk',
        'expiry_hours': 1,
    }
    
    subject = 'Password Reset - HillDesk'
    html_message = render_to_string('authentication/emails/password_reset.html', context)
    text_message = render_to_string('authentication/emails/password_reset.txt', context)
    
    try:
        send_mail(
            subject=subject,
            message=text_message,
            html_message=html_message,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@example.com'),
            recipient_list=[user.email],
            fail_silently=False,
        )
        
        security_logger.info(
            'Password reset email sent',
            extra={
                'user_id': str(user.id),
                'username': user.username,
                'email': user.email,
                'timestamp': timezone.now().isoformat(),
            }
        )
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to send password reset email to {user.email}: {e}")
        return False


def check_password_strength(password):
    """Check password strength and return score and feedback."""
    score = 0
    feedback = []
    
    # Length check
    if len(password) >= 12:
        score += 2
    elif len(password) >= 8:
        score += 1
    else:
        feedback.append("Password should be at least 12 characters long")
    
    # Character variety checks
    if any(c.islower() for c in password):
        score += 1
    else:
        feedback.append("Include lowercase letters")
    
    if any(c.isupper() for c in password):
        score += 1
    else:
        feedback.append("Include uppercase letters")
    
    if any(c.isdigit() for c in password):
        score += 1
    else:
        feedback.append("Include numbers")
    
    if any(c in "!@#$%^&*(),.?\":{}|<>" for c in password):
        score += 1
    else:
        feedback.append("Include special characters")
    
    # Common password check
    common_passwords = [
        'password', '123456', 'qwerty', 'abc123', 'password123',
        'admin', 'letmein', 'welcome', 'monkey', '1234567890'
    ]
    
    if password.lower() not in common_passwords:
        score += 1
    else:
        feedback.append("Avoid common passwords")
    
    # Determine strength level
    if score >= 6:
        strength = "Strong"
    elif score >= 4:
        strength = "Medium"
    else:
        strength = "Weak"
    
    return {
        'score': score,
        'max_score': 7,
        'strength': strength,
        'feedback': feedback
    }


def log_authentication_event(event_type, user=None, request=None, **extra_data):
    """Log authentication-related events."""
    log_data = {
        'event_type': event_type,
        'timestamp': timezone.now().isoformat(),
        **extra_data
    }
    
    if user:
        log_data.update({
            'user_id': str(user.id),
            'username': user.username,
        })
    
    if request:
        log_data.update({
            'ip_address': get_client_ip(request),
            'user_agent': request.META.get('HTTP_USER_AGENT', ''),
        })
    
    security_logger.info(f"Authentication event: {event_type}", extra=log_data)


def get_client_ip(request):
    """Get the real client IP address from request."""
    if not request or not hasattr(request, 'META'):
        return None
        
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def is_safe_url(url, allowed_hosts=None):
    """Check if a URL is safe for redirects."""
    if not url:
        return False
    
    # Basic checks
    if url.startswith('//') or url.startswith('http://') or url.startswith('https://'):
        # External URL - check against allowed hosts
        if allowed_hosts:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            return parsed.netloc in allowed_hosts
        return False
    
    # Relative URL - should be safe
    return url.startswith('/')


def create_audit_log_entry(user, action, resource, old_value=None, new_value=None, request=None):
    """Create an audit log entry for user actions."""
    
    log_data = {
        'user': user,
        'field': action,
        'old_value': str(old_value) if old_value is not None else '',
        'new_value': str(new_value) if new_value is not None else '',
    }
    
    if request:
        log_data.update({
            'ip_address': get_client_ip(request),
            'user_agent': request.META.get('HTTP_USER_AGENT', ''),
        })
    
    # This would create an audit log entry
    # Implementation depends on your audit logging model
    security_logger.info(
        f"Audit log: {action} on {resource}",
        extra={
            'user_id': str(user.id),
            'username': user.username,
            'action': action,
            'resource': resource,
            'old_value': old_value,
            'new_value': new_value,
            'timestamp': timezone.now().isoformat(),
            **log_data
        }
    )


def validate_session_security(request):
    """Validate session security and detect potential issues."""
    if not request.user.is_authenticated:
        return True
    
    issues = []
    
    # Check session age
    session_start = request.session.get('session_start')
    if session_start:
        from datetime import datetime
        start_time = datetime.fromisoformat(session_start)
        session_age = (timezone.now() - start_time).total_seconds()
        max_session_age = getattr(settings, 'AUTH_SETTINGS', {}).get('SESSION_TIMEOUT', 3600) * 2
        
        if session_age > max_session_age:
            issues.append('Session too old')
    
    # Check IP consistency
    session_ip = request.session.get('session_ip')
    current_ip = get_client_ip(request)
    
    if session_ip and session_ip != current_ip:
        issues.append('IP address changed')
    
    # Log any issues
    if issues:
        security_logger.warning(
            'Session security issues detected',
            extra={
                'user_id': str(request.user.id),
                'username': request.user.username,
                'issues': issues,
                'session_ip': session_ip,
                'current_ip': current_ip,
                'timestamp': timezone.now().isoformat(),
            }
        )
        return False
    
    return True