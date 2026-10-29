"""
Django settings for oweru_tech_solutions project.
"""

import os as _os
from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


def _load_env_file(path):
    """Minimal .env loader, so secrets live in one file instead of the registry.

    Real environment variables always win, which keeps any shell session or
    deployment able to override the file. No extra dependency needed.
    """
    try:
        # utf-8-sig tolerates a byte-order mark, which Notepad and PowerShell
        # add when saving a .env file as UTF-8.
        with open(path, 'r', encoding='utf-8-sig') as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, _, value = line.partition('=')
                _os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    except OSError:
        pass


# Load .env before anything below reads the environment.
_load_env_file(BASE_DIR / '.env')


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/6.1/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
# Read from the environment so no key is ever committed. The fallback is a
# deliberately useless development key - set DJANGO_SECRET_KEY for real use.
SECRET_KEY = (
    _os.environ.get('DJANGO_SECRET_KEY')
    or _os.environ.get('SECRET_KEY')
    or 'django-insecure-local-dev-only'
)

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = ['*']


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    'core',
]

# Where @login_required sends people — the Django admin login styles the built-in users
LOGIN_URL = '/portal/login/'
LOGIN_REDIRECT_URL = '/admin-app/dashboard/'
LOGOUT_REDIRECT_URL = '/'

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'oweru_tech_solutions.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'oweru_tech_solutions.wsgi.application'


# ============================================================
# Database
# ============================================================
# The defaults match the original local setup, so an existing checkout keeps
# running with no .env file at all. Point DB_* at your own PostgreSQL, or set
# DB_ENGINE=sqlite for a zero-setup development database.

if _os.environ.get('DB_ENGINE', 'postgresql').strip().lower() == 'sqlite':
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': _os.environ.get('DB_NAME', 'oweru_tech'),
            'USER': _os.environ.get('DB_USER', 'postgres'),
            'PASSWORD': _os.environ.get('DB_PASSWORD', '123'),
            'HOST': _os.environ.get('DB_HOST', 'localhost'),
            'PORT': _os.environ.get('DB_PORT', '5432'),
        }
    }

# A full connection string wins over the individual DB_* values.
# Example: postgres://user:password@host:5432/dbname
_db_url = _os.environ.get('DATABASE_URL', '').strip()
if _db_url.startswith(('postgres://', 'postgresql://')):
    from urllib.parse import urlparse as _urlparse
    _u = _urlparse(_db_url)
    DATABASES['default'] = {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': _u.path.lstrip('/'),
        'USER': _u.username,
        'PASSWORD': _u.password,
        'HOST': _u.hostname,
        'PORT': _u.port or '5432',
    }
elif _db_url.startswith('sqlite'):
    DATABASES['default'] = {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }


# Custom User Model
AUTH_USER_MODEL = 'core.User'


# Password validation

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Media files
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'


# Email
# Real sending uses SMTP settings from environment variables so secrets are
# never committed. Leave EMAIL_HOST empty to keep the console backend.

EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
EMAIL_HOST = _os.environ.get('SMTP_HOST', '')
EMAIL_PORT = int(_os.environ.get('SMTP_PORT', '587') or 587)
EMAIL_USE_TLS = _os.environ.get('SMTP_USE_TLS', 'true').lower() in ('1', 'true', 'yes')
EMAIL_TIMEOUT = int(_os.environ.get('SMTP_TIMEOUT', '20') or 20)
EMAIL_HOST_USER = _os.environ.get('SMTP_USER', '')
EMAIL_HOST_PASSWORD = _os.environ.get('SMTP_PASSWORD', '')

if EMAIL_HOST:
    EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'

DEFAULT_FROM_EMAIL = _os.environ.get('SMTP_FROM', 'Oweru Tech Solutions <hello@oweru.tech>')
NOTIFY_EMAIL = _os.environ.get('SMTP_NOTIFY_TO', 'hello@oweru.tech')

# Base URL for building links in emails (set to your domain in production)
BASE_URL = _os.environ.get('SITE_URL', 'http://127.0.0.1:8000')

# Scanner settings
SCANNER_USER_AGENT = 'Oweru Tech Solutions Health Scanner/1.0 (https://oweru.tech; hello@oweru.tech)'
SCANNER_RATE_LIMIT_MS = 2000
SCANNER_MAX_PAGES = 10
SCANNER_DAILY_TARGET = 50
SCANNER_GOVERNMENT_EXCLUDED = True


# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# ============================================================
# Vercel (serverless) adjustments
# Activate only when running on Vercel, never locally.
# ============================================================
if _os.environ.get('VERCEL'):
    DEBUG = _os.environ.get('DJANGO_DEBUG', 'false').lower() in ('1', 'true', 'yes')
    ALLOWED_HOSTS = ['*']

    # Stateless, in-memory sessions so pages render without a database.
    SESSION_ENGINE = 'django.contrib.sessions.backends.cache'
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        }
    }

    # No DATABASE_URL on Vercel means a throwaway SQLite file that renders
    # pages but stores nothing.
    if not _os.environ.get('DATABASE_URL', '').strip():
        DATABASES['default'] = {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }