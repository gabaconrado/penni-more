"""Tests for explicit environment and production-security settings."""

import json
import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

import pytest
from django.conf import settings

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_ENVIRONMENT = {
    "DJANGO_SECRET_KEY": "settings-test-only-9Qv7Lw2Ks8Fh4Zx6Bn3Cp5Rt1Ym0",
    "PENNI_MORE_DOMAIN": "money.example.test",
    "POSTGRES_PASSWORD": "settings-test-password",
}


def production_process(
    script: str, environment: Mapping[str, str]
) -> subprocess.CompletedProcess[str]:
    """Import production settings in an isolated interpreter."""
    process_environment = os.environ.copy()
    for name in PRODUCTION_ENVIRONMENT:
        process_environment.pop(name, None)
    process_environment.update(environment)
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=BACKEND_ROOT,
        env=process_environment,
        check=False,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize(
    ("missing_name", "environment"),
    [
        ("DJANGO_SECRET_KEY", {}),
        (
            "PENNI_MORE_DOMAIN",
            {"DJANGO_SECRET_KEY": PRODUCTION_ENVIRONMENT["DJANGO_SECRET_KEY"]},
        ),
        (
            "POSTGRES_PASSWORD",
            {
                "DJANGO_SECRET_KEY": PRODUCTION_ENVIRONMENT["DJANGO_SECRET_KEY"],
                "PENNI_MORE_DOMAIN": PRODUCTION_ENVIRONMENT["PENNI_MORE_DOMAIN"],
            },
        ),
    ],
)
def test_production_requires_core_environment(
    missing_name: str, environment: Mapping[str, str]
) -> None:
    process = production_process(
        "from penni_more.settings import production", environment=environment
    )

    assert process.returncode != 0
    assert f"The {missing_name} environment variable is required." in process.stderr


def test_production_security_settings() -> None:
    script = """
import json
from penni_more.settings import production
print(json.dumps({
    "allowed_hosts": production.ALLOWED_HOSTS,
    "csrf_origins": production.CSRF_TRUSTED_ORIGINS,
    "csrf_secure": production.CSRF_COOKIE_SECURE,
    "hsts_include_subdomains": production.SECURE_HSTS_INCLUDE_SUBDOMAINS,
    "hsts_preload": production.SECURE_HSTS_PRELOAD,
    "hsts_seconds": production.SECURE_HSTS_SECONDS,
    "session_secure": production.SESSION_COOKIE_SECURE,
    "ssl_redirect": production.SECURE_SSL_REDIRECT,
}))
"""
    process = production_process(script, environment=PRODUCTION_ENVIRONMENT)

    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout) == {
        "allowed_hosts": ["money.example.test"],
        "csrf_origins": ["https://money.example.test"],
        "csrf_secure": True,
        "hsts_include_subdomains": False,
        "hsts_preload": False,
        "hsts_seconds": 300,
        "session_secure": True,
        "ssl_redirect": True,
    }


def test_local_and_test_database_is_postgresql() -> None:
    assert settings.DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql"
