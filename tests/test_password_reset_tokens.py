# SPDX-License-Identifier: Apache-2.0
"""Password reset tokens are signed, time-limited and single-use."""
import base64

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.authentication.utils import generate_password_reset_token, verify_password_reset_token

User = get_user_model()


class PasswordResetTokenTests(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='resetter', email='resetter@example.com', password='original-pass-123'
        )

    def test_fresh_token_verifies(self) -> None:
        token = generate_password_reset_token(self.user)
        self.assertEqual(verify_password_reset_token(token), self.user)

    def test_token_dies_after_password_change(self) -> None:
        token = generate_password_reset_token(self.user)
        self.user.set_password('brand-new-pass-456')
        self.user.save()
        self.assertIsNone(verify_password_reset_token(token))

    def test_token_dies_after_sign_in(self) -> None:
        token = generate_password_reset_token(self.user)
        self.user.last_login = timezone.now()
        self.user.save(update_fields=['last_login'])
        self.assertIsNone(verify_password_reset_token(token))

    def test_expired_token_rejected(self) -> None:
        token = generate_password_reset_token(self.user)
        with override_settings(PASSWORD_RESET_TIMEOUT=0):
            self.assertIsNone(verify_password_reset_token(token))

    def test_tampered_token_rejected(self) -> None:
        token = generate_password_reset_token(self.user)
        other = User.objects.create_user(username='victim', email='victim@example.com', password='x-pass-789')
        data, signature = base64.urlsafe_b64decode(token).decode().rsplit(':', 1)
        _uid, _email, ts = data.split(':')
        forged = base64.urlsafe_b64encode(f"{other.id}:{other.email}:{ts}:{signature}".encode()).decode()
        self.assertIsNone(verify_password_reset_token(forged))
