# SPDX-License-Identifier: Apache-2.0
"""
Base settings for HillDesk.
"""

import os
from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
# The fallbacks below are PUBLIC (this file is open source) and exist only so
# development and tests run without setup. production.py refuses to start if
# SECRET_KEY / FIELD_ENCRYPTION_KEY are unset or still equal these values.
DEV_ONLY_SECRET_KEY = 'django-insecure-dev-only-not-for-production'
# Kept at its historical value so existing local dev databases still decrypt.
DEV_ONLY_FIELD_ENCRYPTION_KEY = 'default-key-change-in-production-32-chars'
SECRET_KEY = os.environ.get('SECRET_KEY', DEV_ONLY_SECRET_KEY)

# Security Settings
DEBUG = False  # Override in development settings

# HTTPS and SSL Settings
SECURE_SSL_REDIRECT = os.environ.get('SECURE_SSL_REDIRECT', 'False').lower() == 'true'
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_HSTS_SECONDS = int(os.environ.get('SECURE_HSTS_SECONDS', '31536000'))  # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'

# Cookie Security
SESSION_COOKIE_SECURE = os.environ.get('SESSION_COOKIE_SECURE', 'False').lower() == 'true'
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Strict'
SESSION_COOKIE_AGE = 3600  # 1 hour
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_SAVE_EVERY_REQUEST = True

CSRF_COOKIE_SECURE = os.environ.get('CSRF_COOKIE_SECURE', 'False').lower() == 'true'
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = 'Strict'
CSRF_TRUSTED_ORIGINS = os.environ.get('CSRF_TRUSTED_ORIGINS', '').split(',') if os.environ.get('CSRF_TRUSTED_ORIGINS') else []

# X-Frame-Options
X_FRAME_OPTIONS = 'DENY'

# Content Security Policy (will be handled by middleware)
CSP_DEFAULT_SRC = ("'self'",)
CSP_SCRIPT_SRC = ("'self'", "'unsafe-inline'")
CSP_STYLE_SRC = ("'self'", "'unsafe-inline'")
CSP_STYLE_SRC_ELEM = ("'self'", "'unsafe-inline'")
CSP_IMG_SRC = ("'self'", "data:")
CSP_FONT_SRC = ("'self'",)  # fonts are self-hosted (static/fonts)
CSP_CONNECT_SRC = ("'self'",)
CSP_FRAME_ANCESTORS = ("'none'",)
CSP_FORM_ACTION = ("'self'",)

# Data Encryption Key for sensitive fields
FIELD_ENCRYPTION_KEY = os.environ.get('FIELD_ENCRYPTION_KEY', DEV_ONLY_FIELD_ENCRYPTION_KEY)

# Blind-index key for exact-match lookups on encrypted contact/organization
# fields (HMAC-SHA256). Separate from FIELD_ENCRYPTION_KEY so the match-index
# key can be rotated independently; falls back to FIELD_ENCRYPTION_KEY if unset.
CONTACT_BLIND_INDEX_KEY = os.environ.get('CONTACT_BLIND_INDEX_KEY', FIELD_ENCRYPTION_KEY)

# Password Validation (Enhanced)
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {
            'min_length': 12,
        }
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Allowed Hosts (Override in environment-specific settings)
ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'corsheaders',
    
    # Local apps
    'apps.authentication',
    'apps.email_processing',
    'apps.event_management',
    'apps.contacts',
    'apps.api',
]

MIDDLEWARE = [
    # Must stay first: answers /healthz/ before host checks and HTTPS redirect.
    'apps.authentication.health.HealthCheckMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # Custom security middleware for audit logging
    'apps.authentication.middleware.SecurityAuditMiddleware',
    'apps.authentication.middleware.DataClassificationMiddleware',
    'apps.authentication.middleware.SessionSecurityMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'apps.authentication.context_processors.authentication_context',
                'apps.authentication.context_processors.user_permissions',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# Password validation is already defined above with enhanced settings

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'America/New_York'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = 'static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATICFILES_DIRS = [
    os.path.join(BASE_DIR, 'static'),
]

MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Custom User Model
AUTH_USER_MODEL = 'authentication.User'

# Authentication URLs
LOGIN_URL = '/auth/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/auth/login/'

# REST Framework Configuration
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
        'rest_framework.authentication.TokenAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
}

# Email Configuration
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = os.environ.get('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', '587'))
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD')

# Microsoft Graph API Configuration
MICROSOFT_GRAPH_CLIENT_ID = os.environ.get('MICROSOFT_GRAPH_CLIENT_ID')
MICROSOFT_GRAPH_CLIENT_SECRET = os.environ.get('MICROSOFT_GRAPH_CLIENT_SECRET')
MICROSOFT_GRAPH_TENANT_ID = os.environ.get('MICROSOFT_GRAPH_TENANT_ID')

# Alternative names for compatibility
MICROSOFT_TENANT_ID = MICROSOFT_GRAPH_TENANT_ID
MICROSOFT_CLIENT_ID = MICROSOFT_GRAPH_CLIENT_ID
MICROSOFT_CLIENT_SECRET = MICROSOFT_GRAPH_CLIENT_SECRET

# Graph API Settings
GRAPH_API_SETTINGS = {
    'MAX_RETRIES': 3,
    'RETRY_DELAY': 1,  # seconds
    'RATE_LIMIT_DELAY': 60,  # seconds
    'TOKEN_CACHE_TIMEOUT': 3300,  # 55 minutes (tokens expire in 1 hour)
    'DEFAULT_EMAIL_BATCH_SIZE': 50,
    'MAX_EMAIL_BATCH_SIZE': 1000,
}

# Calendar Integration Settings
ENABLE_CALENDAR_SYNC = os.environ.get('ENABLE_CALENDAR_SYNC', 'True').lower() == 'true'

# =============================================================================
# LLM Provider Configuration
# =============================================================================
# Supported providers:
#   - 'bedrock': Amazon Bedrock (PRODUCTION - only approved provider)
#   - 'mock': Offline development mock provider
#   - 'anthropic_dev': [TEMPORARY] Direct Anthropic API for dev testing
#
# Default is 'mock' for safe offline development.
# Production MUST use 'bedrock' (enforced in production.py).
# =============================================================================
LLM_PROVIDER = os.environ.get('LLM_PROVIDER', 'mock')

# LLM Processing Settings
LLM_MIN_CONFIDENCE = float(os.environ.get('LLM_MIN_CONFIDENCE', '0.7'))
# NOTE: the classification model/threshold settings are gone — the deterministic
# funnel (apps/email_processing/funnel/) replaced the classification call.

# AWS / Amazon Bedrock Configuration
# Used when LLM_PROVIDER='bedrock'
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-1')
BEDROCK_EXTRACTION_MODEL = os.environ.get(
    'BEDROCK_EXTRACTION_MODEL',
    'anthropic.claude-3-sonnet-20240229-v1:0'
)
BEDROCK_KB_ID = os.environ.get('BEDROCK_KB_ID', None)

# =============================================================================
# Email Ingestion Pipeline
# =============================================================================
# Scope: the pipeline sweeps ONLY these shared scheduling mailboxes, replacing
# the old all-active-users polling. Comma-separated env override.
SCHEDULING_MAILBOXES = [
    m.strip() for m in os.environ.get('SCHEDULING_MAILBOXES', '').split(',') if m.strip()
]

# Domains treated as internal for the sender-reputation allowlist seed
# (mail.house.gov etc.). Domains of SCHEDULING_MAILBOXES are always included.
INTERNAL_EMAIL_DOMAINS = [
    d.strip().lower() for d in os.environ.get('INTERNAL_EMAIL_DOMAINS', '').split(',') if d.strip()
]

# Reconciliation sweep cadence (minutes). Sweep is the always-on front door;
# webhooks (below) are an optional latency accelerator layered on top.
INGEST_SWEEP_MINUTES = int(os.environ.get('INGEST_SWEEP_MINUTES', '5'))

# Graph change-notification webhook. Off by default; prod flips it on once the
# endpoint's reachability from the House network is confirmed. Sweep-first means
# a disabled/lapsed webhook degrades latency, not correctness.
GRAPH_WEBHOOK_ENABLED = os.environ.get('GRAPH_WEBHOOK_ENABLED', 'False').lower() == 'true'
# Shared secret echoed back in every notification; validated before we act on
# a notification. Secrets Manager in production.
GRAPH_WEBHOOK_CLIENT_STATE = os.environ.get('GRAPH_WEBHOOK_CLIENT_STATE', '')
# Public HTTPS URL Graph should POST notifications to (the /api/webhooks/graph/
# endpoint). Required to create subscriptions.
GRAPH_WEBHOOK_NOTIFICATION_URL = os.environ.get('GRAPH_WEBHOOK_NOTIFICATION_URL', '')

# Attachments at or below this size are stored inline (AttachmentBlob); larger
# ones are kept as metadata only and re-fetched from Graph on demand.
ATTACHMENT_STORE_MAX_BYTES = int(os.environ.get('ATTACHMENT_STORE_MAX_BYTES', str(10 * 1024 * 1024)))

# --- Funnel / post-processing knobs (consumed in later phases; defined here so
#     config lives in one place) ---
CANDIDATE_CAP = int(os.environ.get('CANDIDATE_CAP', '10'))
DEDUP_WINDOW_DAYS = int(os.environ.get('DEDUP_WINDOW_DAYS', '14'))
RATE_GATE_SENDER_LIMIT = int(os.environ.get('RATE_GATE_SENDER_LIMIT', '20'))
RATE_GATE_WINDOW_MINUTES = int(os.environ.get('RATE_GATE_WINDOW_MINUTES', '60'))
RATE_GATE_MAILBOX_LIMIT = int(os.environ.get('RATE_GATE_MAILBOX_LIMIT', '200'))
DIGEST_TOKEN_THRESHOLD = int(os.environ.get('DIGEST_TOKEN_THRESHOLD', '12'))
SERIES_HORIZON_DAYS = int(os.environ.get('SERIES_HORIZON_DAYS', '400'))
RESCORE_WINDOW_DAYS = int(os.environ.get('RESCORE_WINDOW_DAYS', '30'))

# =============================================================================
# Authentication Mode
# =============================================================================
# USE_SSO: Controls authentication backend selection
#   - True: Azure AD OIDC authentication (production)
#   - False: Django ModelBackend local authentication (development)
#
# When USE_SSO=True, mozilla-django-oidc URLs are included and
# the login view redirects to Azure AD.
# =============================================================================
USE_SSO = os.environ.get('USE_SSO', 'False').lower() == 'true'

# MFA Configuration
MFA_ISSUER_NAME = os.environ.get('MFA_ISSUER_NAME', 'HillDesk')

# Celery Configuration (for async tasks)
CELERY_BROKER_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE

# Cache Configuration
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': os.environ.get('REDIS_URL', 'redis://localhost:6379/1'),
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
        }
    }
}

# Data Classification Settings
DATA_CLASSIFICATION_LEVELS = [
    ('public', 'Public'),
    ('internal', 'Internal'),
    ('sensitive', 'Sensitive'),
    ('restricted', 'Restricted'),
]

# Event Status Choices (legacy tuple format for backwards compatibility)
EVENT_STATUS_CHOICES = [
    ('received', 'Received'),
    ('hold', 'Hold'),
    ('referred', 'Referred'),
    ('fyied', 'FYI\'ed'),
    ('scheduling_in_progress', 'Scheduling in Progress'),
    ('scheduled', 'Scheduled'),
    ('rsvped', 'RSVP\'ed'),
    ('regrets_sent', 'Regrets Sent'),
    ('passed', 'Passed'),
    ('canceled', 'Canceled / Request Withdrawn'),
    ('requires_hms_review', 'Requires HMS Review'),
]

# Default Event Status Choices for Office customization (with colors)
DEFAULT_EVENT_STATUS_CHOICES = [
    {'value': 'received', 'label': 'Received', 'color': '#3b82f6', 'bg_color': '#dbeafe', 'is_active': True, 'order': 1},
    {'value': 'hold', 'label': 'Hold', 'color': '#f59e0b', 'bg_color': '#fef3c7', 'is_active': True, 'order': 2},
    {'value': 'referred', 'label': 'Referred', 'color': '#8b5cf6', 'bg_color': '#ede9fe', 'is_active': True, 'order': 3},
    {'value': 'fyied', 'label': 'FYI\'ed', 'color': '#f97316', 'bg_color': '#ffedd5', 'is_active': True, 'order': 4},
    {'value': 'scheduling_in_progress', 'label': 'Scheduling in Progress', 'color': '#22c55e', 'bg_color': '#dcfce7', 'is_active': True, 'order': 5},
    {'value': 'scheduled', 'label': 'Scheduled', 'color': '#10b981', 'bg_color': '#d1fae5', 'is_active': True, 'order': 6},
    {'value': 'rsvped', 'label': 'RSVP\'ed', 'color': '#06b6d4', 'bg_color': '#cffafe', 'is_active': True, 'order': 7},
    {'value': 'regrets_sent', 'label': 'Regrets Sent', 'color': '#ef4444', 'bg_color': '#fee2e2', 'is_active': True, 'order': 8},
    {'value': 'passed', 'label': 'Passed', 'color': '#6b7280', 'bg_color': '#f3f4f6', 'is_active': True, 'order': 9},
    {'value': 'canceled', 'label': 'Canceled / Request Withdrawn', 'color': '#9ca3af', 'bg_color': '#f9fafb', 'is_active': True, 'order': 10},
    {'value': 'requires_hms_review', 'label': 'Requires HMS Review', 'color': '#eab308', 'bg_color': '#fef9c3', 'is_active': True, 'order': 11},
]

# Staff Recommendation Choices
STAFF_RECOMMENDATION_CHOICES = [
    ('1', '1 - Yes'),
    ('2', '2 - Probably'),
    ('3', '3 - Lean Yes'),
    ('4', '4 - FYI'),
    ('5', '5 - Maybe'),
    ('6', '6 - Lean Staff'),
    ('7', '7 - Lean Pass'),
    ('8', '8 - Probably Not'),
    ('9', '9 - Staff'),
    ('pass', 'Pass'),
]

# Event Type Choices (legacy tuple format for backwards compatibility)
EVENT_TYPE_CHOICES = [
    ('event', 'Event'),
    ('meeting', 'Meeting'),
    ('speaking', 'Speaking'),
]

# Default Event Type Choices for Office customization (no colors)
DEFAULT_EVENT_TYPE_CHOICES = [
    {'value': 'event', 'label': 'Event', 'is_active': True, 'order': 1},
    {'value': 'meeting', 'label': 'Meeting', 'is_active': True, 'order': 2},
    {'value': 'speaking', 'label': 'Speaking', 'is_active': True, 'order': 3},
]

# Default Event Format Choices for Office customization (no colors)
DEFAULT_EVENT_FORMAT_CHOICES = [
    {'value': 'in-person', 'label': 'In Person', 'is_active': True, 'order': 1},
    {'value': 'virtual', 'label': 'Virtual', 'is_active': True, 'order': 2},
    {'value': 'hybrid', 'label': 'Hybrid', 'is_active': True, 'order': 3},
]

DEFAULT_EVENT_DURATION_CHOICES = [
    {'value': '30min', 'label': '30 minutes'},
    {'value': '1hr', 'label': '1 hour'},
    {'value': '1.5hr', 'label': '1.5 hours'},
    {'value': '2hr', 'label': '2 hours'},
    {'value': '3hr', 'label': '3 hours'},
    {'value': 'half-day', 'label': 'Half day'},
    {'value': 'full-day', 'label': 'Full day'},
    {'value': 'custom', 'label': 'Custom'},
]

DEFAULT_REMINDER_TIME_CHOICES = [
    {'value': '15min', 'label': '15 minutes before'},
    {'value': '30min', 'label': '30 minutes before'},
    {'value': '1hr', 'label': '1 hour before'},
    {'value': '1day', 'label': '1 day before'},
]

# Timezone choices (global, not customizable per account)
TIMEZONE_CHOICES = [
    ('America/New_York', 'Eastern Time'),
    ('America/Chicago', 'Central Time'),
    ('America/Denver', 'Mountain Time'),
    ('America/Los_Angeles', 'Pacific Time'),
    ('America/Anchorage', 'Alaska Time'),
    ('Pacific/Honolulu', 'Hawaii Time'),
    ('UTC', 'UTC'),
]

# Security Configuration - NIST SP 800-53 Compliance
SECURITY_SETTINGS = {
    'INFORMATION_SECURITY_POLICY': True,
    'DATA_CLASSIFICATION_ENFORCEMENT': True,
    'SECURITY_OFFICER_REQUIRED': True,
    'RISK_ASSESSMENT_REQUIRED': True,
    'VENDOR_VETTING_REQUIRED': True,
    'NIST_SP_800_53_COMPLIANCE': True,
    'ARCHITECTURE_DOCUMENTATION_REQUIRED': True,
    'SECURE_CODING_STANDARDS': True,
    'SECURITY_TESTING_REQUIRED': True,
    'PEER_REVIEW_REQUIRED': True,
}

# Authentication and Authorization Settings
AUTH_SETTINGS = {
    'OAUTH2_REQUIRED': True,
    'MFA_REQUIRED': True,
    'RBAC_ENABLED': True,
    'LEAST_PRIVILEGE': True,
    'SESSION_TIMEOUT': 3600,  # 1 hour
    'MAX_LOGIN_ATTEMPTS': 3,
    'ACCOUNT_LOCKOUT_DURATION': 1800,  # 30 minutes
}

# Data Protection Settings
DATA_PROTECTION = {
    'ENCRYPTION_AT_REST': 'AES-256',
    'ENCRYPTION_IN_TRANSIT': 'TLS-1.2+',
    'CUSTOMER_MANAGED_KEYS': True,
    'KEY_ROTATION_DAYS': 90,
    'PII_PSEUDONYMIZATION': True,
    'DATA_LOSS_PREVENTION': True,
}

# Audit and Logging Settings
AUDIT_LOGGING = {
    'LOG_ALL_USER_ACTIONS': True,
    'LOG_API_CALLS': True,
    'LOG_ADMIN_OPERATIONS': True,
    'REAL_TIME_SIEM_FORWARDING': True,
    'IMMUTABLE_LOGS': True,
    'LOG_RETENTION_YEARS': 3,
    'TAMPER_PROTECTION': True,
}

# Vulnerability Management
VULNERABILITY_MANAGEMENT = {
    'AUTOMATED_SCANNING': True,
    'CRITICAL_PATCH_HOURS': 48,
    'HIGH_PATCH_HOURS': 48,
    'MEDIUM_PATCH_DAYS': 7,
    'QUARTERLY_VULN_SCANS': True,
    'ANNUAL_PENETRATION_TESTS': True,
}

# Infrastructure Security
INFRASTRUCTURE_SECURITY = {
    'INFRASTRUCTURE_AS_CODE': True,
    'POLICY_AS_CODE': True,
    'INSECURE_CONFIG_BLOCKING': True,
    'MULTI_REGION_REPLICATION': True,
    'ENCRYPTED_BACKUPS': True,
    'DAILY_BACKUPS': True,
    'QUARTERLY_RESTORE_TESTS': True,
}

# Incident Response
INCIDENT_RESPONSE = {
    'PLAYBOOKS_REQUIRED': True,
    'QUARTERLY_TABLETOP_EXERCISES': True,
    'DATA_BREACH_PROCEDURES': True,
    'DOS_PROCEDURES': True,
    'CREDENTIAL_COMPROMISE_PROCEDURES': True,
}

# Compliance and Training
COMPLIANCE_TRAINING = {
    'ANNUAL_SECURITY_TRAINING': True,
    'TRAINING_DOCUMENTATION': True,
    'UNDERSTANDING_VERIFICATION': True,
    'CONGRESSIONAL_IT_COMPLIANCE': True,
    'FEDRAMP_COMPLIANCE': True,
}

# Input Validation and Sanitization
INPUT_VALIDATION = {
    'SANITIZE_ALL_INPUTS': True,
    'PREVENT_INJECTION_ATTACKS': True,
    'VALIDATE_ALL_INPUTS': True,
    'OWASP_TOP_10_PROTECTION': True,
    'CWE_TOP_25_PROTECTION': True,
}

# Monitoring and Alerting
MONITORING_ALERTING = {
    'OPERATIONAL_BASELINES': True,
    'ANOMALY_DETECTION': True,
    'REAL_TIME_ALERTS': True,
    'INCIDENT_RESPONSE_INTEGRATION': True,
    'SECURITY_MONITORING': True,
}

# Comprehensive Logging Configuration
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'security': {
            'format': '{"timestamp": "{asctime}", "level": "{levelname}", "user_id": "{user_id}", "action": "{action}", "resource": "{resource}", "ip_address": "{ip_address}", "user_agent": "{user_agent}", "message": "{message}"}',
            'style': '{',
        },
        'audit': {
            'format': '{"timestamp": "{asctime}", "event_type": "audit", "user_id": "{user_id}", "action": "{action}", "resource_affected": "{resource}", "old_value": "{old_value}", "new_value": "{new_value}", "ip_address": "{ip_address}"}',
            'style': '{',
        },
    },
    'handlers': {
        'file': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': os.path.join(BASE_DIR, 'logs', 'django.log'),
            'maxBytes': 1024*1024*10,  # 10MB
            'backupCount': 5,
            'formatter': 'verbose',
        },
        'security_file': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': os.path.join(BASE_DIR, 'logs', 'security.log'),
            'maxBytes': 1024*1024*10,  # 10MB
            'backupCount': 10,
            'formatter': 'security',
        },
        'audit_file': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': os.path.join(BASE_DIR, 'logs', 'audit.log'),
            'maxBytes': 1024*1024*10,  # 10MB
            'backupCount': 20,
            'formatter': 'audit',
        },
        'console': {
            'level': 'DEBUG',
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console', 'file'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': False,
        },
        'django.security': {
            'handlers': ['security_file'],
            'level': 'INFO',
            'propagate': False,
        },
        'apps.authentication': {
            'handlers': ['console', 'file', 'security_file', 'audit_file'],
            'level': 'INFO',
            'propagate': False,
        },
        'apps.email_processing': {
            'handlers': ['console', 'file', 'audit_file'],
            'level': 'INFO',
            'propagate': False,
        },
        'apps.event_management': {
            'handlers': ['console', 'file', 'audit_file'],
            'level': 'INFO',
            'propagate': False,
        },
        'apps.api': {
            'handlers': ['console', 'file', 'security_file'],
            'level': 'INFO',
            'propagate': False,
        },
        'security_audit': {
            'handlers': ['security_file', 'audit_file'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}


# =============================================================================
# Export Settings
# =============================================================================
EXPORT_MAX_SYNC_EVENTS = 200          # Events above this trigger async Celery export
EXPORT_TEMPLATE_MAX_SIZE = 5 * 1024 * 1024  # 5 MB max upload size for .docx templates


# =============================================================================
# Event Attachment Settings
# =============================================================================
EVENT_ATTACHMENT_MAX_SIZE = 10 * 1024 * 1024  # 10 MB max per attached file
EVENT_ATTACHMENT_ALLOWED_EXTENSIONS = [
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.txt', '.csv', '.png', '.jpg', '.jpeg',
]

# Ceiling enforced by SecurityAuditMiddleware on total request body size. Must sit
# above EVENT_ATTACHMENT_MAX_SIZE so a max-size file plus multipart overhead is not
# rejected before the upload view runs.
MAX_REQUEST_SIZE = 12 * 1024 * 1024  # 12 MB