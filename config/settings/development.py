# SPDX-License-Identifier: Apache-2.0
"""
Development settings for HillDesk.

This configuration is for local development only.
- Uses SQLite database
- Uses local Django authentication (no SSO)
- Uses mock LLM provider by default (offline development)
- Optionally supports 'anthropic_dev' for API testing
"""

from .base import *
from django.core.exceptions import ImproperlyConfigured

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = ['localhost', '127.0.0.1', '0.0.0.0', 'testserver']  # nosec B104 (dev only; Docker demo)

# Database - SQLite for development
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        # DEMO_DB_DIR lets the Docker demo keep its database on a volume.
        'NAME': Path(os.environ.get('DEMO_DB_DIR', BASE_DIR)) / 'db.sqlite3',
    }
}

# =============================================================================
# Authentication: Local Django auth (no SSO in development)
# =============================================================================
USE_SSO = False
AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
]

# =============================================================================
# LLM Provider: Mock by default, anthropic_dev allowed for testing
# =============================================================================
# Override LLM_PROVIDER to ensure mock is default for development
LLM_PROVIDER = os.environ.get('LLM_PROVIDER', 'mock')

# Validate that only allowed providers are used in development
_ALLOWED_DEV_PROVIDERS = ['mock', 'anthropic_dev', 'bedrock']
if LLM_PROVIDER not in _ALLOWED_DEV_PROVIDERS:
    raise ImproperlyConfigured(
        f"Invalid LLM_PROVIDER '{LLM_PROVIDER}' for development. "
        f"Use one of: {_ALLOWED_DEV_PROVIDERS}"
    )

# CORS Configuration for development
CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]

CORS_ALLOW_CREDENTIALS = True

# Security Settings (relaxed for development)
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'SAMEORIGIN'  # Relaxed for development
SECURE_HSTS_SECONDS = 0  # Disabled for development
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False

# Session Configuration (relaxed for development)
SESSION_COOKIE_SECURE = False
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_EXPIRE_AT_BROWSER_CLOSE = False

# CSRF Configuration (relaxed for development)
CSRF_COOKIE_SECURE = False
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = 'Lax'

# Email backend for development (console)
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# Logging Configuration for development
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'level': 'DEBUG',
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'apps.authentication': {
            'handlers': ['console'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'apps.email_processing': {
            'handlers': ['console'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'apps.event_management': {
            'handlers': ['console'],
            'level': 'DEBUG',
            'propagate': False,
        },
    },
}

# Development-specific settings
INTERNAL_IPS = [
    '127.0.0.1',
    'localhost',
]

# Cache configuration for development (dummy cache)
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.dummy.DummyCache',
    }
}

# Celery configuration for development (eager execution)
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# Development-specific security settings (still maintain security awareness)
SECURITY_SETTINGS = {
    'INFORMATION_SECURITY_POLICY': True,
    'DATA_CLASSIFICATION_ENFORCEMENT': True,
    'SECURITY_OFFICER_REQUIRED': False,  # Relaxed for development
    'RISK_ASSESSMENT_REQUIRED': False,  # Relaxed for development
    'VENDOR_VETTING_REQUIRED': False,  # Relaxed for development
    'NIST_SP_800_53_COMPLIANCE': True,
    'ARCHITECTURE_DOCUMENTATION_REQUIRED': True,
    'SECURE_CODING_STANDARDS': True,
    'SECURITY_TESTING_REQUIRED': True,
    'PEER_REVIEW_REQUIRED': False,  # Relaxed for development
}

# Development authentication settings
AUTH_SETTINGS = {
    'OAUTH2_REQUIRED': False,  # Relaxed for development
    'MFA_REQUIRED': False,  # Relaxed for development
    'RBAC_ENABLED': True,
    'LEAST_PRIVILEGE': True,
    'SESSION_TIMEOUT': 86400,  # 24 hours for development
    'MAX_LOGIN_ATTEMPTS': 10,  # Relaxed for development
    'ACCOUNT_LOCKOUT_DURATION': 300,  # 5 minutes for development
}

# Mock external services for development
MOCK_MICROSOFT_GRAPH = True
MOCK_LLM_SERVICE = True

# Development API rate limiting (more permissive)
API_RATE_LIMITING = {
    'DEFAULT': '1000/hour',
    'LOGIN': '50/minute',
    'PASSWORD_RESET': '30/hour',
    'EMAIL_PROCESSING': '500/hour',
}

# Development tools
INSTALLED_APPS += [
    'django_extensions',
]

# Add CSP middleware for development
MIDDLEWARE += [
    'csp.middleware.CSPMiddleware',
]