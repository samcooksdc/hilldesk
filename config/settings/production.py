# SPDX-License-Identifier: Apache-2.0
"""
Production settings for HillDesk.

HOUSE PROFILE CONFIGURATION
===========================
This configuration enforces the production deployment requirements:
- Amazon Bedrock for ALL LLM functionality (no external SaaS APIs)
- Azure AD OIDC authentication via House Active Directory
- PostgreSQL database via RDS
- No public internet egress for AI services

CRITICAL: Do not modify LLM_PROVIDER or USE_SSO settings.
"""

from .base import *
from django.core.exceptions import ImproperlyConfigured

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = False


# =============================================================================
# Fail closed on secrets
# =============================================================================
# base.py carries public, dev-only fallbacks. In production every key must be
# supplied explicitly (AWS Secrets Manager -> env) or the app refuses to boot.
# =============================================================================
def _require_secret(name: str, forbidden: str) -> str:
    value = os.environ.get(name, '')
    if not value or value == forbidden or value.startswith('django-insecure-'):
        raise ImproperlyConfigured(
            f"{name} must be set to a unique, random value in production "
            f"(unset, or still the public development default)."
        )
    return value


SECRET_KEY = _require_secret('SECRET_KEY', DEV_ONLY_SECRET_KEY)
FIELD_ENCRYPTION_KEY = _require_secret('FIELD_ENCRYPTION_KEY', DEV_ONLY_FIELD_ENCRYPTION_KEY)
# Blind-index key: separate key preferred; may fall back to the (verified)
# production FIELD_ENCRYPTION_KEY, never to the dev default computed in base.py.
CONTACT_BLIND_INDEX_KEY = os.environ.get('CONTACT_BLIND_INDEX_KEY') or FIELD_ENCRYPTION_KEY
if CONTACT_BLIND_INDEX_KEY == DEV_ONLY_FIELD_ENCRYPTION_KEY:
    raise ImproperlyConfigured('CONTACT_BLIND_INDEX_KEY is the public development default.')

ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', '').split(',')

# =============================================================================
# PRODUCTION REQUIREMENT: LLM Provider - BEDROCK ONLY
# =============================================================================
# Production MUST use Amazon Bedrock. This is a non-negotiable requirement.
# Third-party SaaS LLM APIs (OpenAI, Anthropic, Azure OpenAI) are BLOCKED.
# =============================================================================
LLM_PROVIDER = 'bedrock'

# Block non-compliant LLM providers in production
_BLOCKED_PROVIDERS = ['anthropic_dev', 'openai', 'anthropic', 'azure_openai']
_configured_provider = os.environ.get('LLM_PROVIDER', 'bedrock')
if _configured_provider in _BLOCKED_PROVIDERS:
    raise ImproperlyConfigured(
        f"\n{'=' * 70}\n"
        f"  PRODUCTION CONFIGURATION VIOLATION\n"
        f"{'=' * 70}\n"
        f"  LLM_PROVIDER '{_configured_provider}' is NOT approved for production.\n"
        f"  Production MUST use 'bedrock' for all LLM functionality.\n"
        f"\n"
        f"  Blocked providers: {_BLOCKED_PROVIDERS}\n"
        f"\n"
        f"  Amazon Bedrock provides approved AI services within\n"
        f"  the House AWS GovCloud environment.\n"
        f"{'=' * 70}\n"
    )

# AWS GovCloud Configuration for Bedrock
AWS_REGION = os.environ.get('AWS_REGION', 'us-gov-west-1')

# =============================================================================
# PRODUCTION REQUIREMENT: Authentication - Azure AD OIDC
# =============================================================================
# Production MUST use Azure AD OIDC via House Active Directory.
# Local Django authentication is disabled in production.
# =============================================================================
USE_SSO = True

AUTHENTICATION_BACKENDS = [
    'apps.authentication.backends.AzureADBackend',
]

# Azure AD / Entra ID OIDC Configuration
AZURE_AD_TENANT_ID = os.environ.get('AZURE_AD_TENANT_ID')
OIDC_RP_CLIENT_ID = os.environ.get('AZURE_AD_CLIENT_ID')
OIDC_RP_CLIENT_SECRET = os.environ.get('AZURE_AD_CLIENT_SECRET')

# Microsoft Entra ID (Azure AD) OIDC Endpoints
OIDC_OP_AUTHORIZATION_ENDPOINT = (
    f"https://login.microsoftonline.com/{AZURE_AD_TENANT_ID}/oauth2/v2.0/authorize"
)
OIDC_OP_TOKEN_ENDPOINT = (
    f"https://login.microsoftonline.com/{AZURE_AD_TENANT_ID}/oauth2/v2.0/token"
)
OIDC_OP_USER_ENDPOINT = (
    f"https://login.microsoftonline.com/{AZURE_AD_TENANT_ID}/oidc/userinfo"
)
OIDC_OP_JWKS_ENDPOINT = (
    f"https://login.microsoftonline.com/{AZURE_AD_TENANT_ID}/discovery/v2.0/keys"
)

# OIDC Settings
OIDC_RP_SIGN_ALGO = 'RS256'
OIDC_USE_NONCE = True
OIDC_VERIFY_SSL = True
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/'

# Add OIDC to installed apps for production
INSTALLED_APPS += [
    'mozilla_django_oidc',
]

# Add OIDC middleware
MIDDLEWARE += [
    'mozilla_django_oidc.middleware.SessionRefresh',
]

# Database - PostgreSQL for production
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('DB_NAME'),
        'USER': os.environ.get('DB_USER'),
        'PASSWORD': os.environ.get('DB_PASSWORD'),
        'HOST': os.environ.get('DB_HOST'),
        'PORT': os.environ.get('DB_PORT', '5432'),
        'OPTIONS': {
            'sslmode': 'require',
        },
    }
}

# CORS Configuration for production
CORS_ALLOWED_ORIGINS = os.environ.get('CORS_ALLOWED_ORIGINS', '').split(',')
CORS_ALLOW_CREDENTIALS = True

# Security Settings (strict for production)
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
SECURE_HSTS_SECONDS = 31536000  # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Session Configuration (strict for production)
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Strict'
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_AGE = 3600  # 1 hour

# CSRF Configuration (strict for production)
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = 'Strict'

# Static files configuration for production
STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.StaticFilesStorage'

# AWS S3 Configuration (if using S3 for static files)
if os.environ.get('USE_S3') == 'True':
    AWS_ACCESS_KEY_ID = os.environ.get('AWS_ACCESS_KEY_ID')
    AWS_SECRET_ACCESS_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY')
    AWS_STORAGE_BUCKET_NAME = os.environ.get('AWS_STORAGE_BUCKET_NAME')
    AWS_S3_REGION_NAME = os.environ.get('AWS_S3_REGION_NAME', 'us-east-1')
    AWS_S3_CUSTOM_DOMAIN = f'{AWS_STORAGE_BUCKET_NAME}.s3.amazonaws.com'
    AWS_DEFAULT_ACL = None
    AWS_S3_OBJECT_PARAMETERS = {
        'CacheControl': 'max-age=86400',
    }
    
    # Static files
    STATICFILES_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage'
    STATIC_URL = f'https://{AWS_S3_CUSTOM_DOMAIN}/static/'
    
    # Media files
    DEFAULT_FILE_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage'
    MEDIA_URL = f'https://{AWS_S3_CUSTOM_DOMAIN}/media/'

# Logging Configuration for production
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'json': {
            # Literal JSON braces are doubled so str.format-style ('{') parsing
            # accepts them; unescaped braces made logging.config raise at boot.
            'format': '{{"level": "{levelname}", "time": "{asctime}", "module": "{module}", "message": "{message}"}}',
            'style': '{',
        },
    },
    'handlers': {
        # JSON to stdout by default (containers: ECS/CloudWatch collect it).
        # Set LOG_DIR to keep rotating files instead (see _enable_file_logging).
        'file': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'stream': 'ext://sys.stdout',
            'formatter': 'json',
        },
        'security_file': {
            'level': 'WARNING',
            'class': 'logging.StreamHandler',
            'stream': 'ext://sys.stdout',
            'formatter': 'json',
        },
        'console': {
            'level': 'ERROR',
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['file', 'console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['file', 'console'],
            'level': 'INFO',
            'propagate': False,
        },
        'django.security': {
            'handlers': ['security_file'],
            'level': 'WARNING',
            'propagate': False,
        },
        'apps.authentication': {
            'handlers': ['file', 'security_file'],
            'level': 'INFO',
            'propagate': False,
        },
        'apps.email_processing': {
            'handlers': ['file'],
            'level': 'INFO',
            'propagate': False,
        },
        'apps.event_management': {
            'handlers': ['file'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}

def _enable_file_logging(log_dir: str) -> None:
    """Opt-in rotating files for hosts without a log collector."""
    LOGGING['handlers']['file'] = {
        'level': 'INFO', 'class': 'logging.handlers.RotatingFileHandler',
        'filename': os.path.join(log_dir, 'django.log'),
        'maxBytes': 10 * 1024 * 1024, 'backupCount': 5, 'formatter': 'json',
    }
    LOGGING['handlers']['security_file'] = {
        'level': 'WARNING', 'class': 'logging.handlers.RotatingFileHandler',
        'filename': os.path.join(log_dir, 'security.log'),
        'maxBytes': 10 * 1024 * 1024, 'backupCount': 10, 'formatter': 'json',
    }


if os.environ.get('LOG_DIR'):
    _enable_file_logging(os.environ['LOG_DIR'])

# Additional security middleware for production
if 'django.middleware.security.SecurityMiddleware' not in MIDDLEWARE:
    MIDDLEWARE.insert(0, 'django.middleware.security.SecurityMiddleware')

# Serve collected static files from the app container (no S3/nginx required).
# Must sit directly after SecurityMiddleware.
MIDDLEWARE.insert(
    MIDDLEWARE.index('django.middleware.security.SecurityMiddleware') + 1,
    'whitenoise.middleware.WhiteNoiseMiddleware',
)

# Password validation (stricter for production)
AUTH_PASSWORD_VALIDATORS.extend([
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {
            'min_length': 12,
        }
    },
])

# Cache configuration for production (Redis)
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': os.environ.get('REDIS_URL'),
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            'CONNECTION_POOL_KWARGS': {
                'ssl_cert_reqs': None,
            },
        }
    }
}

# Session backend (use cache for production)
SESSION_ENGINE = 'django.contrib.sessions.backends.cache'
SESSION_CACHE_ALIAS = 'default'

# Email configuration for production
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_USE_TLS = True

# Celery configuration for production
CELERY_TASK_ALWAYS_EAGER = False
CELERY_TASK_EAGER_PROPAGATES = False
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_ACKS_LATE = True

# Data encryption key (for sensitive fields): validated at the top of this file.

# Rate limiting
RATELIMIT_ENABLE = True
RATELIMIT_USE_CACHE = 'default'

# Additional Security Headers
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'
SECURE_CROSS_ORIGIN_OPENER_POLICY = 'same-origin'

# Content Security Policy
CSP_DEFAULT_SRC = ("'self'",)
CSP_SCRIPT_SRC = ("'self'", "'unsafe-inline'")
CSP_STYLE_SRC = ("'self'", "'unsafe-inline'")
CSP_IMG_SRC = ("'self'", "data:", "https:")
CSP_FONT_SRC = ("'self'",)  # fonts are self-hosted (static/fonts)
CSP_CONNECT_SRC = ("'self'",)
CSP_FRAME_ANCESTORS = ("'none'",)

# OAuth2 and Authentication Settings
OAUTH2_PROVIDER = {
    'SCOPES': {
        'read': 'Read scope',
        'write': 'Write scope',
    },
    'ACCESS_TOKEN_EXPIRE_SECONDS': 3600,
    'REFRESH_TOKEN_EXPIRE_SECONDS': 86400,
    'AUTHORIZATION_CODE_EXPIRE_SECONDS': 600,
    'ROTATE_REFRESH_TOKEN': True,
}

# Multi-Factor Authentication
MFA_ENABLED = True
MFA_ISSUER_NAME = 'HillDesk'
MFA_TOTP_DIGITS = 6
MFA_TOTP_PERIOD = 30

# Account Security
ACCOUNT_LOCKOUT_THRESHOLD = 3
ACCOUNT_LOCKOUT_DURATION = 1800  # 30 minutes
PASSWORD_RESET_TIMEOUT = 3600  # 1 hour
SESSION_SECURITY_WARN_AFTER = 2700  # 45 minutes
SESSION_SECURITY_EXPIRE_AFTER = 3600  # 1 hour

# Data Classification and Handling
DATA_CLASSIFICATION_REQUIRED = True
SENSITIVE_DATA_ENCRYPTION = True
DATA_RETENTION_POLICIES = {
    'audit_logs': 1095,  # 3 years in days
    'security_logs': 1095,  # 3 years in days
    'user_sessions': 30,  # 30 days
    'email_processing': 2555,  # 7 years for congressional records
}

# API Security
API_RATE_LIMITING = {
    'DEFAULT': '100/hour',
    'LOGIN': '5/minute',
    'PASSWORD_RESET': '3/hour',
    'EMAIL_PROCESSING': '50/hour',
}

# File Upload Security
FILE_UPLOAD_MAX_MEMORY_SIZE = 2621440  # 2.5MB
FILE_UPLOAD_PERMISSIONS = 0o644
ALLOWED_UPLOAD_EXTENSIONS = ['.pdf', '.doc', '.docx', '.txt']
FILE_UPLOAD_VIRUS_SCAN = True

# Database Security
DATABASES['default']['OPTIONS'].update({
    'sslmode': 'require',
    'sslcert': os.environ.get('DB_SSL_CERT'),
    'sslkey': os.environ.get('DB_SSL_KEY'),
    'sslrootcert': os.environ.get('DB_SSL_ROOT_CERT'),
})

# Backup and Recovery
BACKUP_ENCRYPTION_KEY = os.environ.get('BACKUP_ENCRYPTION_KEY')
BACKUP_RETENTION_DAYS = 90
BACKUP_VERIFICATION_REQUIRED = True

# Monitoring and Alerting
MONITORING_ENABLED = True
SECURITY_MONITORING_ENABLED = True
ANOMALY_DETECTION_ENABLED = True
REAL_TIME_ALERTING = True

# Third-party Integration Security
MICROSOFT_GRAPH_SCOPES = [
    'https://graph.microsoft.com/Mail.Read',
    'https://graph.microsoft.com/Mail.Send',
    'https://graph.microsoft.com/Calendars.ReadWrite',
]

# Network Security
ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', '').split(',')
INTERNAL_IPS = os.environ.get('INTERNAL_IPS', '').split(',')

# Error Handling and Reporting
ADMINS = [
    ('Security Team', os.environ.get('SECURITY_EMAIL', 'security@example.com')),
    ('System Admin', os.environ.get('ADMIN_EMAIL', 'admin@example.com')),
]

MANAGERS = ADMINS

# Email Security
EMAIL_USE_SSL = False  # Using TLS instead
EMAIL_USE_TLS = True
EMAIL_SSL_CERTFILE = None
EMAIL_SSL_KEYFILE = None
EMAIL_TIMEOUT = 60

# Additional Security Middleware
MIDDLEWARE.extend([
    'django_ratelimit.middleware.RatelimitMiddleware',
    'csp.middleware.CSPMiddleware',
])
