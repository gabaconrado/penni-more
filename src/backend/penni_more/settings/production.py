"""Security-focused production settings."""

import os
import re

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403

_STABLE_VERSION_PATTERN = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)")


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

_image_version = required_environment("PENNI_MORE_IMAGE_VERSION")
if _STABLE_VERSION_PATTERN.fullmatch(_image_version) is None:
    raise ImproperlyConfigured(
        "The PENNI_MORE_IMAGE_VERSION environment variable must be a stable semantic version "
        "in MAJOR.MINOR.PATCH format."
    )
PENNI_MORE_VERSION_LABEL = f"v{_image_version}"

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
