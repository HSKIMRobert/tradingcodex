from __future__ import annotations

import os
from pathlib import Path

from tradingcodex_service.runtime_profile import (
    DEFAULT_LOCAL_SECRET_KEY,
    REMOTE_PROFILE,
    assert_runtime_profile_configured,
    service_profile,
)

SERVICE_DIR = Path(__file__).resolve().parent
BASE_DIR = SERVICE_DIR.parent


def default_db_name() -> str:
    configured = os.environ.get("TRADINGCODEX_DB_NAME")
    if configured:
        path = Path(configured).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        return str(path)
    home = Path(os.environ.get("TRADINGCODEX_HOME", "~/.tradingcodex")).expanduser().resolve()
    path = home / "state" / "tradingcodex.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)

SERVICE_PROFILE = service_profile()
assert_runtime_profile_configured()

SECRET_KEY = os.environ.get("TRADINGCODEX_SECRET_KEY", DEFAULT_LOCAL_SECRET_KEY)
DEBUG = os.environ.get("TRADINGCODEX_DEBUG", "1") == "1"
ALLOWED_HOSTS = [
    item.strip()
    for item in os.environ.get("TRADINGCODEX_ALLOWED_HOSTS", "127.0.0.1,localhost,testserver").split(",")
    if item.strip()
]
CSRF_TRUSTED_ORIGINS = [
    item.strip()
    for item in os.environ.get("TRADINGCODEX_CSRF_TRUSTED_ORIGINS", "").split(",")
    if item.strip()
]
if SERVICE_PROFILE == REMOTE_PROFILE:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(os.environ.get("TRADINGCODEX_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = os.environ.get("TRADINGCODEX_HSTS_INCLUDE_SUBDOMAINS", "1") == "1"
ROOT_URLCONF = "tradingcodex_service.urls"
ASGI_APPLICATION = "tradingcodex_service.asgi.application"
WSGI_APPLICATION = "tradingcodex_service.wsgi.application"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "ninja",
    "apps.audit",
    "apps.harness",
    "apps.integrations",
    "apps.mcp",
    "apps.orders",
    "apps.policy",
    "apps.portfolio",
    "apps.workflows",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": default_db_name(),
        "OPTIONS": {"timeout": int(os.environ.get("TRADINGCODEX_SQLITE_TIMEOUT", "30"))},
    }
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATICFILES_DIRS = [SERVICE_DIR / "static"]

SERVICE_LOG_DIR = Path(os.environ.get("TRADINGCODEX_HOME", "~/.tradingcodex")).expanduser().resolve() / "state" / "run"
SERVICE_LOG_DIR.mkdir(parents=True, exist_ok=True)
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "redacted": {
            "()": "tradingcodex_service.log_safety.RedactingFormatter",
            "format": "{asctime} {levelname} {name} {message}",
            "style": "{",
        }
    },
    "handlers": {
        "service_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(SERVICE_LOG_DIR / "service.log"),
            "maxBytes": int(os.environ.get("TRADINGCODEX_SERVICE_LOG_MAX_BYTES", str(5 * 1024 * 1024))),
            "backupCount": int(os.environ.get("TRADINGCODEX_SERVICE_LOG_BACKUPS", "3")),
            "formatter": "redacted",
            "encoding": "utf-8",
        }
    },
    "root": {"handlers": ["service_file"], "level": os.environ.get("TRADINGCODEX_LOG_LEVEL", "INFO")},
    "loggers": {
        "django": {"handlers": ["service_file"], "level": os.environ.get("TRADINGCODEX_LOG_LEVEL", "INFO"), "propagate": False},
    },
}

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates", BASE_DIR / "tradingcodex_service" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

TRADINGCODEX = {
    "max_single_order_base": int(os.environ.get("TRADINGCODEX_MAX_SINGLE_ORDER_BASE", "100000")),
    "allowed_adapters": ["stub-execution", "paper-trading"],
    "enabled_live_execution": False,
}
