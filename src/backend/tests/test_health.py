"""Request tests for operational health endpoints."""

from unittest.mock import patch

import pytest
from django.db import DatabaseError, connections
from django.test import Client


def test_liveness_is_generic_and_does_not_query_database(client: Client) -> None:
    with patch.object(
        connections["default"],
        "cursor",
        side_effect=AssertionError("liveness must not access the database"),
    ):
        response = client.get("/health/live")

    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/json"
    assert response.json() == {"status": "ok"}


@pytest.mark.django_db
def test_readiness_succeeds_when_postgresql_is_available(client: Client) -> None:
    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/json"
    assert response.json() == {"status": "ok"}


def test_readiness_failure_is_generic(client: Client) -> None:
    database = connections["default"]
    with patch.object(
        database,
        "cursor",
        side_effect=DatabaseError("private database diagnostic"),
    ):
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.headers["Content-Type"] == "application/json"
    assert response.json() == {"status": "unavailable"}
    assert b"private database diagnostic" not in response.content


@pytest.mark.parametrize("method", ["head", "post", "put", "patch", "delete", "options"])
@pytest.mark.parametrize("path", ["/health/live", "/health/ready"])
def test_health_endpoints_reject_unsupported_methods_without_querying_database(
    client: Client, method: str, path: str
) -> None:
    with patch.object(
        connections["default"],
        "cursor",
        side_effect=AssertionError("unsupported methods must not access the database"),
    ):
        response = getattr(client, method)(path)

    assert response.status_code == 405
    assert response.headers["Allow"] == "GET"
