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
    "PENNI_MORE_IMAGE_VERSION": "0.2.0",
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
        (
            "PENNI_MORE_IMAGE_VERSION",
            {
                "DJANGO_SECRET_KEY": PRODUCTION_ENVIRONMENT["DJANGO_SECRET_KEY"],
                "PENNI_MORE_DOMAIN": PRODUCTION_ENVIRONMENT["PENNI_MORE_DOMAIN"],
                "POSTGRES_PASSWORD": PRODUCTION_ENVIRONMENT["POSTGRES_PASSWORD"],
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


def test_production_formats_release_version() -> None:
    process = production_process(
        "from penni_more.settings import production; print(production.PENNI_MORE_VERSION_LABEL)",
        environment=PRODUCTION_ENVIRONMENT,
    )

    assert process.returncode == 0, process.stderr
    assert process.stdout == "v0.2.0\n"


@pytest.mark.parametrize(
    "image_version",
    [
        " ",
        "0.2",
        "01.2.0",
        "0.02.0",
        "0.2.00",
        "v0.2.0",
        "0.2.0-rc.1",
        "0.2.0+build.1",
        "1.2.3.4",
        "latest",
    ],
)
def test_production_rejects_invalid_release_version(image_version: str) -> None:
    environment = {**PRODUCTION_ENVIRONMENT, "PENNI_MORE_IMAGE_VERSION": image_version}

    process = production_process(
        "from penni_more.settings import production", environment=environment
    )

    assert process.returncode != 0
    if image_version.strip():
        assert "must be a stable semantic version in MAJOR.MINOR.PATCH format" in process.stderr
        assert image_version not in process.stderr
    else:
        assert "The PENNI_MORE_IMAGE_VERSION environment variable is required." in process.stderr


def test_production_trims_release_version() -> None:
    environment = {
        **PRODUCTION_ENVIRONMENT,
        "PENNI_MORE_IMAGE_VERSION": "  0.2.0\t",
    }

    process = production_process(
        "from penni_more.settings import production; print(production.PENNI_MORE_VERSION_LABEL)",
        environment=environment,
    )

    assert process.returncode == 0, process.stderr
    assert process.stdout == "v0.2.0\n"


def test_local_release_version_is_deterministic() -> None:
    environment = os.environ.copy()
    environment["PENNI_MORE_IMAGE_VERSION"] = "9.8.7"

    process = subprocess.run(
        [
            sys.executable,
            "-c",
            "from penni_more.settings import local; print(local.PENNI_MORE_VERSION_LABEL)",
        ],
        cwd=BACKEND_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert process.returncode == 0, process.stderr
    assert process.stdout == "dev\n"


def test_local_and_test_database_is_postgresql() -> None:
    assert settings.DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql"
