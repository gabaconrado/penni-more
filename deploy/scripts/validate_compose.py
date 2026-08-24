#!/usr/bin/env python3
"""Validate Compose documents against the vendored Compose specification."""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEPLOY_ROOT = ROOT / "deploy"


def load_document(path: Path) -> dict[str, Any]:
    """Load one Compose mapping or fail with its source path."""
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise SystemExit(f"{path}: expected a Compose mapping")
    return document


def merge_mappings(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """Merge the mapping-only parts used by this repository's Compose overrides."""
    merged = dict(base)
    for key, override_value in override.items():
        base_value = merged.get(key)
        if isinstance(base_value, Mapping) and isinstance(override_value, Mapping):
            merged[key] = merge_mappings(base_value, override_value)
        elif isinstance(base_value, list) and isinstance(override_value, list):
            merged[key] = [*base_value, *override_value]
        else:
            merged[key] = override_value
    return merged


def validate_schema(documents: Mapping[str, Mapping[str, Any]]) -> None:
    """Validate documents with check-jsonschema's bundled Compose schema."""
    with tempfile.TemporaryDirectory(prefix="penni-more-compose-") as temporary_dir:
        paths: list[str] = []
        for name, document in documents.items():
            path = Path(temporary_dir) / name
            path.write_text(yaml.safe_dump(dict(document), sort_keys=False), encoding="utf-8")
            paths.append(str(path))
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "check_jsonschema",
                "--builtin-schema",
                "vendor.compose-spec",
                *paths,
            ],
            check=False,
        )
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def validate_repository() -> None:
    """Validate base/merged documents and repository production policy."""
    base = load_document(DEPLOY_ROOT / "compose.yaml")
    local = load_document(DEPLOY_ROOT / "compose.local.yaml")
    production = load_document(DEPLOY_ROOT / "compose.production.yaml")
    merged_local = merge_mappings(base, local)
    merged_production = merge_mappings(base, production)
    validate_schema(
        {
            "compose.base.yaml": base,
            "compose.local.merged.yaml": merged_local,
            "compose.production.merged.yaml": merged_production,
        }
    )

    production_services = merged_production["services"]
    if "ports" in production_services["database"]:
        raise SystemExit("production database must not publish ports")
    if "api-docs" in production_services:
        raise SystemExit("production must not include API documentation")
    if "ports" in production_services["server"]:
        raise SystemExit("production server must not publish ports")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--schema-only",
        action="append",
        type=Path,
        default=[],
        metavar="PATH",
        help="validate an explicit fixture instead of repository documents",
    )
    arguments = parser.parse_args()
    if arguments.schema_only:
        validate_schema({path.name: load_document(path) for path in arguments.schema_only})
    else:
        validate_repository()


if __name__ == "__main__":
    main()
