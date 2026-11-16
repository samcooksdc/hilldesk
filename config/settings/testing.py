# SPDX-License-Identifier: Apache-2.0
"""
Testing settings for HillDesk.
"""

from .base import *

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = ['localhost', '127.0.0.1', 'testserver']

# Database - Use in-memory SQLite for faster tests
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

# Password validation (simplified for testing)
AUTH_PASSWORD_VALIDATORS = []

# Email backend for testing
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'

# Cache configuration for testing (dummy cache)
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.dummy.DummyCache',
    }
}

# Celery configuration for testing (eager execution)
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# Logging Configuration for testing (minimal)
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'level': 'CRITICAL',
            'class': 'logging.StreamHandler',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'CRITICAL',
    },
}

# Security settings (relaxed for testing)
SECURE_BROWSER_XSS_FILTER = False
SECURE_CONTENT_TYPE_NOSNIFF = False
X_FRAME_OPTIONS = 'SAMEORIGIN'
SECURE_HSTS_SECONDS = 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False

# Session Configuration (relaxed for testing)
SESSION_COOKIE_SECURE = False
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'

# CSRF Configuration (relaxed for testing)
CSRF_COOKIE_SECURE = False
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = 'Lax'

# Static files (simplified for testing)
STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.StaticFilesStorage'

# Test-specific settings
TEST_RUNNER = 'django.test.runner.DiscoverRunner'

# Mock external services for testing
MICROSOFT_GRAPH_CLIENT_ID = 'test-client-id'
MICROSOFT_GRAPH_CLIENT_SECRET = 'test-client-secret'
MICROSOFT_GRAPH_TENANT_ID = 'test-tenant-id'
# base.py copies these into the MICROSOFT_* aliases the code reads; keep them in sync.
MICROSOFT_TENANT_ID = MICROSOFT_GRAPH_TENANT_ID
MICROSOFT_CLIENT_ID = MICROSOFT_GRAPH_CLIENT_ID
MICROSOFT_CLIENT_SECRET = MICROSOFT_GRAPH_CLIENT_SECRET

LLM_API_KEY = 'test-api-key'
LLM_API_URL = 'http://localhost:8080/test'

# Disable migrations for faster tests
class DisableMigrations:
    def __contains__(self, item):
        return True
    
    def __getitem__(self, item):
        return None

MIGRATION_MODULES = DisableMigrations()

# Security testing settings
SECURITY_TESTING = {
    'ENABLED': True,
    'STATIC_ANALYSIS': True,
    'DYNAMIC_ANALYSIS': True,
    'DEPENDENCY_SCANNING': True,
    'AUTHENTICATION_TESTING': True,
    'AUTHORIZATION_TESTING': True,
    'INPUT_VALIDATION_TESTING': True,
    'ENCRYPTION_TESTING': True,
}

# Test security configurations (still secure but appropriate for testing)
SECURITY_SETTINGS = {
    'INFORMATION_SECURITY_POLICY': True,
    'DATA_CLASSIFICATION_ENFORCEMENT': True,
    'SECURITY_OFFICER_REQUIRED': False,  # Not required for testing
    'RISK_ASSESSMENT_REQUIRED': False,  # Not required for testing
    'VENDOR_VETTING_REQUIRED': False,  # Not required for testing
    'NIST_SP_800_53_COMPLIANCE': True,
    'ARCHITECTURE_DOCUMENTATION_REQUIRED': True,
    'SECURE_CODING_STANDARDS': True,
    'SECURITY_TESTING_REQUIRED': True,
    'PEER_REVIEW_REQUIRED': True,
}

# Test authentication settings
AUTH_SETTINGS = {
    'OAUTH2_REQUIRED': True,  # Test OAuth2 functionality
    'MFA_REQUIRED': True,  # Test MFA functionality
    'RBAC_ENABLED': True,
    'LEAST_PRIVILEGE': True,
    'SESSION_TIMEOUT': 3600,  # 1 hour for testing
    'MAX_LOGIN_ATTEMPTS': 3,
    'ACCOUNT_LOCKOUT_DURATION': 300,  # 5 minutes for testing
}

# Test data protection settings
DATA_PROTECTION = {
    'ENCRYPTION_AT_REST': 'AES-256',
    'ENCRYPTION_IN_TRANSIT': 'TLS-1.2+',
    'CUSTOMER_MANAGED_KEYS': True,
    'KEY_ROTATION_DAYS': 90,
    'PII_PSEUDONYMIZATION': True,
    'DATA_LOSS_PREVENTION': True,
}

# Test audit logging (simplified but functional)
AUDIT_LOGGING = {
    'LOG_ALL_USER_ACTIONS': True,
    'LOG_API_CALLS': True,
    'LOG_ADMIN_OPERATIONS': True,
    'REAL_TIME_SIEM_FORWARDING': False,  # Disabled for testing
    'IMMUTABLE_LOGS': True,
    'LOG_RETENTION_YEARS': 1,  # Shorter for testing
    'TAMPER_PROTECTION': True,
}

# Mock services for testing
MOCK_MICROSOFT_GRAPH = True

# Event saves must not trigger real Outlook calls; calendar tests opt in with
# @override_settings(ENABLE_CALENDAR_SYNC=True) and mock the Graph client.
ENABLE_CALENDAR_SYNC = False
MOCK_LLM_SERVICE = True
MOCK_SIEM = True
MOCK_SECRET_VAULT = True

# Test API rate limiting
API_RATE_LIMITING = {
    'DEFAULT': '10000/hour',  # Very permissive for testing
    'LOGIN': '100/minute',
    'PASSWORD_RESET': '100/hour',
    'EMAIL_PROCESSING': '1000/hour',
}

# Test file upload settings
FILE_UPLOAD_MAX_MEMORY_SIZE = 1048576  # 1MB for testing
ALLOWED_UPLOAD_EXTENSIONS = ['.txt', '.pdf']
FILE_UPLOAD_VIRUS_SCAN = False  # Disabled for testing

# Test monitoring (disabled for performance)
MONITORING_ENABLED = False
SECURITY_MONITORING_ENABLED = False
ANOMALY_DETECTION_ENABLED = False
REAL_TIME_ALERTING = False