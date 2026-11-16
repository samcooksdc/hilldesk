# SPDX-License-Identifier: Apache-2.0
"""
Azure AD / Entra ID Authentication Backend.

This module provides OIDC authentication integration with Microsoft Entra ID
(formerly Azure AD) for production deployment with House Active Directory.

In production, users authenticate via SSO through the House AD infrastructure.
This backend handles:
- User creation on first SSO login (JIT provisioning)
- User attribute updates on subsequent logins
- Mapping Azure AD claims to Django User model fields

Production requirement: authentication MUST use Azure AD OIDC.

Usage:
    # In config/settings/production.py
    USE_SSO = True
    AUTHENTICATION_BACKENDS = ['apps.authentication.backends.AzureADBackend']
"""

import logging


logger = logging.getLogger(__name__)


# Only import mozilla-django-oidc if available
# This allows development environments to run without this dependency
try:
    from mozilla_django_oidc.auth import OIDCAuthenticationBackend

    class AzureADBackend(OIDCAuthenticationBackend):
        """
        Azure AD / Entra ID authentication backend.

        This backend is used in production to authenticate users via the House
        Active Directory through Microsoft Entra ID (Azure AD) OIDC.

        Features:
        - Just-in-Time (JIT) user provisioning on first login
        - Automatic user attribute synchronization
        - Azure AD Object ID tracking for user identification
        - Support for Azure AD group claims (future: RBAC mapping)
        """

        def create_user(self, claims: dict):
            """
            Create a new user on first SSO login (JIT provisioning).

            This is called when a user authenticates via Azure AD but doesn't
            yet have a Django user account.

            Args:
                claims: OIDC claims from Azure AD token

            Returns:
                The newly created User instance
            """
            # Let the parent class create the base user
            user = super().create_user(claims)

            # Set Azure AD-specific fields
            user.azure_ad_id = claims.get('oid')  # Azure AD Object ID
            user.email = claims.get('email') or claims.get('preferred_username', '')
            user.first_name = claims.get('given_name', '')
            user.last_name = claims.get('family_name', '')

            # Save the updated user
            user.save()

            logger.info(
                f"Created new SSO user: {user.username} "
                f"(Azure AD ID: {user.azure_ad_id})"
            )

            return user

        def update_user(self, user, claims: dict):
            """
            Update user attributes on subsequent SSO logins.

            This ensures user information stays in sync with Azure AD.

            Args:
                user: The existing User instance
                claims: OIDC claims from Azure AD token

            Returns:
                The updated User instance
            """
            # Update Azure AD fields
            user.azure_ad_id = claims.get('oid')
            user.email = claims.get('email') or claims.get('preferred_username', '')
            user.first_name = claims.get('given_name', '')
            user.last_name = claims.get('family_name', '')

            # Save the updated user
            user.save()

            logger.debug(
                f"Updated SSO user: {user.username} "
                f"(Azure AD ID: {user.azure_ad_id})"
            )

            return user

        def filter_users_by_claims(self, claims: dict):
            """
            Find existing users by Azure AD Object ID.

            This is called to determine if a user already exists before
            creating a new one.

            Args:
                claims: OIDC claims from Azure AD token

            Returns:
                QuerySet of matching users (should be 0 or 1)
            """
            azure_ad_id = claims.get('oid')

            if azure_ad_id:
                users = self.UserModel.objects.filter(azure_ad_id=azure_ad_id)
                if users.exists():
                    logger.debug(f"Found existing user with Azure AD ID: {azure_ad_id}")
                return users

            # Fallback: try to find by email
            email = claims.get('email') or claims.get('preferred_username')
            if email:
                users = self.UserModel.objects.filter(email=email)
                if users.exists():
                    logger.debug(f"Found existing user by email: {email}")
                return users

            return self.UserModel.objects.none()

        def verify_claims(self, claims: dict) -> bool:
            """
            Verify that required claims are present in the token.

            Args:
                claims: OIDC claims from Azure AD token

            Returns:
                True if required claims are present
            """
            # Azure AD Object ID is required
            if not claims.get('oid'):
                logger.error("Missing 'oid' claim in Azure AD token")
                return False

            return True

        def get_username(self, claims: dict) -> str:
            """
            Generate a username from Azure AD claims.

            Args:
                claims: OIDC claims from Azure AD token

            Returns:
                Username string for the Django user
            """
            # Prefer UPN (User Principal Name) or email
            username = claims.get('preferred_username') or claims.get('email')

            if username:
                # Strip domain for cleaner usernames if desired
                # username = username.split('@')[0]
                return username

            # Fallback to Azure AD Object ID
            return claims.get('oid', 'unknown')

except ImportError:
    # mozilla-django-oidc not installed - provide a stub for development
    logger.warning(
        "mozilla-django-oidc not installed. AzureADBackend will not be available. "
        "This is expected in development environments using local authentication."
    )

    class AzureADBackend:
        """
        Stub AzureADBackend for when mozilla-django-oidc is not installed.

        This allows the application to import this module without errors
        in development environments that don't have the OIDC dependency.
        """

        def __init__(self, *args, **kwargs):
            raise NotImplementedError(
                "AzureADBackend requires mozilla-django-oidc to be installed. "
                "Install it with: pip install mozilla-django-oidc\n"
                "For local development, use USE_SSO=False with Django's "
                "built-in ModelBackend instead."
            )
