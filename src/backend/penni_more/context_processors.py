"""Shared template context for application-wide presentation."""

from django.conf import settings
from django.http import HttpRequest


def release_version(_request: HttpRequest) -> dict[str, str]:
    """Expose the configured non-secret release label to rendered templates."""
    return {"penni_more_version": settings.PENNI_MORE_VERSION_LABEL}
