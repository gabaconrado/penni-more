"""Security-focused production settings."""

import os

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403


def required_environment(name: str) -> str:
    """Return a non-empty required setting or fail during settings initialization."""
    value = os.getenv(name, "").strip()
    if not value:
        raise ImproperlyConfigured(f"The {name} environment variable is required.")
    return value


DEBUG = False
SECRET_KEY = required_environment("DJANGO_SECRET_KEY")

DOMAIN = required_environment("PENNI_MORE_DOMAIN")
ALLOWED_HOSTS = [DOMAIN]
CSRF_TRUSTED_ORIGINS = [f"https://{DOMAIN}"]

DATABASES["default"]["PASSWORD"] = required_environment("POSTGRES_PASSWORD")

SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = int(os.getenv("DJANGO_SECURE_HSTS_SECONDS", "300"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

# The staged HSTS policy deliberately excludes subdomains and browser preload until certificate
# renewal has proven reliable.
SILENCED_SYSTEM_CHECKS = ["security.W005", "security.W021"]
