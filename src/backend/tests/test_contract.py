"""Consumer checks that keep health behavior aligned with OpenAPI."""

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import yaml
from django.db import DatabaseError, connections
from django.test import Client

CONTRACT_PATH = Path(__file__).resolve().parents[2] / "contract" / "openapi.yaml"


def load_contract() -> dict[str, Any]:
    """Load the repository-owned OpenAPI document."""
    with CONTRACT_PATH.open(encoding="utf-8") as contract_file:
        contract = yaml.safe_load(contract_file)
    assert isinstance(contract, dict)
    return contract


def resolve_response_contract(
    contract: dict[str, Any], path: str, status_code: int
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve a local response and schema reference for one operation status."""
    response_reference = contract["paths"][path]["get"]["responses"][str(status_code)]["$ref"]
    response_name = response_reference.rsplit("/", maxsplit=1)[-1]
    response_contract = contract["components"]["responses"][response_name]
    schema_reference = response_contract["content"]["application/json"]["schema"]["$ref"]
    schema_name = schema_reference.rsplit("/", maxsplit=1)[-1]
    return response_contract, contract["components"]["schemas"][schema_name]


def assert_response_matches_contract(
    response: Any, response_contract: dict[str, Any], schema: dict[str, Any]
) -> None:
    """Compare an actual JSON response with its resolved contract components."""
    response_body = response.json()

    assert response.headers["Content-Type"] == "application/json"
    assert response_body == response_contract["content"]["application/json"]["example"]
    assert schema["additionalProperties"] is False
    assert set(response_body) == set(schema["required"])
    assert response_body["status"] in schema["properties"]["status"]["enum"]


@pytest.mark.django_db
def test_health_operations_match_contract(client: Client) -> None:
    contract = load_contract()

    expected_operations = {
        "/health/live": "getHealthLiveness",
        "/health/ready": "getHealthReadiness",
    }
    for path, operation_id in expected_operations.items():
        operation = contract["paths"][path]["get"]
        response = client.get(path)
        response_contract, schema = resolve_response_contract(contract, path, response.status_code)

        assert operation["operationId"] == operation_id
        assert operation["security"] == []
        assert_response_matches_contract(response, response_contract, schema)


def test_readiness_unavailable_response_matches_contract(client: Client) -> None:
    contract = load_contract()
    with patch.object(
        connections["default"],
        "cursor",
        side_effect=DatabaseError("private database diagnostic"),
    ):
        response = client.get("/health/ready")
    response_contract, schema = resolve_response_contract(
        contract, "/health/ready", response.status_code
    )

    assert response.status_code == 503
    assert_response_matches_contract(response, response_contract, schema)
