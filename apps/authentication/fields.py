# SPDX-License-Identifier: Apache-2.0
"""
Encrypted field classes for HillDesk.
Provides secure storage for sensitive data using AES-256 encryption.
"""

import base64
from django.db import models
from django.conf import settings
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import logging

logger = logging.getLogger('apps.authentication')


# Cache of the PBKDF2-derived Fernet key (and Fernet instance) per raw setting
# key. The derivation is deterministic (static salt), so deriving once and
# reusing is equivalent — but PBKDF2 at 100k iterations is expensive, and the
# previous code ran it on EVERY field encrypt/decrypt. Caching makes bulk
# decryption (e.g. listing contacts/orgs) orders of magnitude faster.
_DERIVED_KEY_CACHE = {}
_FERNET_CACHE = {}


class EncryptionMixin:
    """Mixin for handling field encryption and decryption."""

    def get_encryption_key(self):
        """Get or derive the Fernet key from settings (cached per raw key)."""
        key = getattr(settings, 'FIELD_ENCRYPTION_KEY', None)
        if not key:
            raise ValueError("FIELD_ENCRYPTION_KEY not configured in settings")

        # Ensure key is bytes and proper length for Fernet
        if isinstance(key, str):
            key = key.encode()

        cached = _DERIVED_KEY_CACHE.get(key)
        if cached is not None:
            return cached

        # Use PBKDF2 to derive a proper key from the setting (once per key)
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b'congressional_scheduling_salt',  # In production, use a random salt
            iterations=100000,
        )
        derived_key = base64.urlsafe_b64encode(kdf.derive(key))
        _DERIVED_KEY_CACHE[key] = derived_key
        return derived_key

    def _get_fernet(self):
        """Return a cached Fernet instance for the current key."""
        derived = self.get_encryption_key()
        f = _FERNET_CACHE.get(derived)
        if f is None:
            f = Fernet(derived)
            _FERNET_CACHE[derived] = f
        return f
    
    def encrypt_value(self, value):
        """Encrypt a value using Fernet symmetric encryption."""
        if value is None:
            return value
        if value == '':
            return value
        
        try:
            f = self._get_fernet()

            if isinstance(value, str):
                value = value.encode()

            encrypted_value = f.encrypt(value)
            return base64.urlsafe_b64encode(encrypted_value).decode()
        except Exception as e:
            logger.error(f"Encryption error: {e}")
            raise
    
    def decrypt_value(self, encrypted_value):
        """Decrypt a value using Fernet symmetric encryption."""
        if encrypted_value is None or encrypted_value == '':
            return encrypted_value
        
        try:
            f = self._get_fernet()

            # Decode from base64
            encrypted_data = base64.urlsafe_b64decode(encrypted_value.encode())
            
            decrypted_value = f.decrypt(encrypted_data)
            return decrypted_value.decode()
        except Exception as e:
            logger.error(f"Decryption error: {e}")
            # Return the original value if decryption fails (for backwards compatibility)
            return encrypted_value


class EncryptedCharField(EncryptionMixin, models.CharField):
    """CharField that automatically encrypts/decrypts data."""
    
    def __init__(self, *args, **kwargs):
        # Increase max_length to accommodate encrypted data
        if 'max_length' in kwargs:
            kwargs['max_length'] = kwargs['max_length'] * 4  # Account for encryption overhead
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        """Report the *declared* max_length, not the widened one.

        ``__init__`` multiplies max_length by 4 for ciphertext overhead. If
        deconstruct() returned the widened value, every migration load would
        widen it again and ``makemigrations`` would emit a new AlterField on
        every run. Dividing here keeps declared -> stored -> rebuilt stable.
        """
        name, path, args, kwargs = super().deconstruct()
        if 'max_length' in kwargs:
            kwargs['max_length'] = kwargs['max_length'] // 4
        return name, path, args, kwargs
    
    def from_db_value(self, value, expression, connection):
        """Decrypt value when loading from database."""
        if value is None:
            return value
        return self.decrypt_value(value)
    
    def to_python(self, value):
        """Convert value to Python representation."""
        if isinstance(value, str) or value is None:
            return value
        return str(value)
    
    def get_prep_value(self, value):
        """Encrypt value before saving to database."""
        if value is None:
            return value
        return self.encrypt_value(str(value))


class EncryptedTextField(EncryptionMixin, models.TextField):
    """TextField that automatically encrypts/decrypts data."""
    
    def from_db_value(self, value, expression, connection):
        """Decrypt value when loading from database."""
        if value is None:
            return value
        return self.decrypt_value(value)
    
    def to_python(self, value):
        """Convert value to Python representation."""
        if isinstance(value, str) or value is None:
            return value
        return str(value)
    
    def get_prep_value(self, value):
        """Encrypt value before saving to database."""
        if value is None:
            return value
        return self.encrypt_value(str(value))


class EncryptedEmailField(EncryptionMixin, models.EmailField):
    """EmailField that automatically encrypts/decrypts data."""
    
    def __init__(self, *args, **kwargs):
        # Increase max_length to accommodate encrypted data
        if 'max_length' in kwargs:
            kwargs['max_length'] = kwargs['max_length'] * 4
        else:
            kwargs['max_length'] = 254 * 4  # Default email field length * 4
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        """Report the *declared* max_length, not the widened one.

        ``__init__`` multiplies max_length by 4 for ciphertext overhead. If
        deconstruct() returned the widened value, every migration load would
        widen it again and ``makemigrations`` would emit a new AlterField on
        every run. Dividing here keeps declared -> stored -> rebuilt stable.
        """
        name, path, args, kwargs = super().deconstruct()
        if 'max_length' in kwargs:
            kwargs['max_length'] = kwargs['max_length'] // 4
        return name, path, args, kwargs
    
    def from_db_value(self, value, expression, connection):
        """Decrypt value when loading from database."""
        if value is None:
            return value
        return self.decrypt_value(value)
    
    def to_python(self, value):
        """Convert value to Python representation."""
        if isinstance(value, str) or value is None:
            return value
        return str(value)
    
    def get_prep_value(self, value):
        """Encrypt value before saving to database."""
        if value is None:
            return value
        return self.encrypt_value(str(value))


class EncryptedJSONField(EncryptionMixin, models.JSONField):
    """JSONField that automatically encrypts/decrypts data."""
    
    def from_db_value(self, value, expression, connection):
        """Decrypt value when loading from database."""
        if value is None:
            return value
        
        # First decrypt the value
        decrypted_value = self.decrypt_value(value)
        
        # Then parse as JSON
        import json
        try:
            return json.loads(decrypted_value)
        except (json.JSONDecodeError, TypeError):
            return decrypted_value
    
    def get_prep_value(self, value):
        """Encrypt value before saving to database."""
        if value is None:
            return value
        
        # First convert to JSON string
        import json
        json_value = json.dumps(value)
        
        # Then encrypt
        return self.encrypt_value(json_value)


class DataClassificationField(models.CharField):
    """Field for storing data classification levels."""
    
    CLASSIFICATION_CHOICES = [
        ('public', 'Public'),
        ('internal', 'Internal'),
        ('sensitive', 'Sensitive'),
        ('restricted', 'Restricted'),
    ]
    
    def __init__(self, *args, **kwargs):
        kwargs['max_length'] = 20
        kwargs['choices'] = self.CLASSIFICATION_CHOICES
        kwargs['default'] = 'internal'
        super().__init__(*args, **kwargs)


class AuditTrailMixin(models.Model):
    """Mixin for adding audit trail fields to models."""
    
    created = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='%(class)s_created'
    )
    modified = models.DateTimeField(auto_now=True)
    modified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='%(class)s_modified'
    )
    data_classification = DataClassificationField()
    
    class Meta:
        abstract = True


class SecureModelMixin(AuditTrailMixin):
    """Mixin for models that need comprehensive security features."""
    
    # Track changes for audit purposes
    _original_values = None
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._original_values = self._get_field_values()
    
    def _get_field_values(self):
        """Get current field values for change tracking.

        Use ``field.attname`` (the raw column, e.g. ``created_by_id`` for FKs)
        rather than ``field.name``. Accessing ``field.name`` on a ForeignKey
        triggers a lazy DB fetch of the related object on EVERY instantiation —
        a massive N+1 when loading many rows (contacts, child emails/phones).
        """
        values = {}
        for field in self._meta.fields:
            attname = field.attname
            if hasattr(self, attname):
                values[attname] = getattr(self, attname)
        return values
    
    def save(self, *args, **kwargs):
        """Override save to track changes."""
        if self.pk:
            # Track changes for existing objects
            current_values = self._get_field_values()
            changes = {}
            
            for field_name, current_value in current_values.items():
                original_value = self._original_values.get(field_name)
                if original_value != current_value:
                    changes[field_name] = {
                        'old': original_value,
                        'new': current_value
                    }
            
            # Log changes if any
            if changes:
                logger.info(
                    f"Model {self.__class__.__name__} changes",
                    extra={
                        'model': self.__class__.__name__,
                        'object_id': str(self.pk),
                        'changes': changes,
                        'data_classification': getattr(self, 'data_classification', 'internal'),
                    }
                )
        
        super().save(*args, **kwargs)
        
        # Update original values after save
        self._original_values = self._get_field_values()
    
    def delete(self, *args, **kwargs):
        """Override delete to log deletion."""
        logger.warning(
            f"Model {self.__class__.__name__} deleted",
            extra={
                'model': self.__class__.__name__,
                'object_id': str(self.pk),
                'data_classification': getattr(self, 'data_classification', 'internal'),
            }
        )
        super().delete(*args, **kwargs)
    
    class Meta:
        abstract = True