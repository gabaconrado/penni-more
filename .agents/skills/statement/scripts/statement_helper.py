#!/usr/bin/env python3
"""Private-state, PDF extraction, rule matching, and CSV finalization helper."""

from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import io
import json
import os
import re
import stat
import sys
import tempfile
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from pypdf import PdfReader
from pypdf.errors import PdfReadError

SCHEMA_VERSION = 1
MAX_DOCUMENT_BYTES = 1024 * 1024
MAX_ROWS = 1000
MAX_AMOUNT = Decimal("9999999999999999.99")
CSV_HEADERS = (
    "type",
    "name",
    "description",
    "category",
    "date",
    "amount",
    "account_id",
    "target_account_id",
    "additional_data",
)
SAFE_BASENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}\.csv")
AMOUNT = re.compile(r"(?:0|[1-9][0-9]*)\.[0-9]{2}")
HASH = re.compile(r"[0-9a-f]{64}")
KEY = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")


class SafeError(Exception):
    """An expected failure whose diagnostics contain no private values."""

    def __init__(self, code: str, *, path: str | None = None, field: str | None = None):
        super().__init__(code)
        self.code = code
        self.path = path
        self.field = field

    def payload(self) -> dict[str, Any]:
        result: dict[str, Any] = {"ok": False, "error": self.code}
        if self.path is not None:
            result["path"] = self.path
        if self.field is not None:
            result["field"] = self.field
        return result


class DuplicateKey(ValueError):
    """A JSON object contains a duplicate key."""


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKey
        result[key] = value
    return result


def _stdin_json() -> Any:
    try:
        return json.load(sys.stdin, object_pairs_hook=_pairs)
    except (json.JSONDecodeError, UnicodeError, DuplicateKey) as error:
        raise SafeError("invalid_json", path="stdin") from error


def _strict_object(
    value: Any,
    allowed: set[str],
    required: set[str],
    field: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SafeError("invalid_type", field=field)
    unknown = set(value) - allowed
    missing = required - set(value)
    if unknown:
        raise SafeError("unknown_field", field=f"{field}.{min(unknown)}")
    if missing:
        raise SafeError("missing_field", field=f"{field}.{min(missing)}")
    return value


def _text(value: Any, field: str, *, minimum: int = 1, maximum: int = 500) -> str:
    if (
        not isinstance(value, str)
        or not minimum <= len(value) <= maximum
        or value.strip() != value
        or "\x00" in value
    ):
        raise SafeError("invalid_text", field=field)
    return value


def _key(value: Any, field: str) -> str:
    text = _text(value, field, maximum=64)
    if not KEY.fullmatch(text):
        raise SafeError("invalid_key", field=field)
    return text


def _list(value: Any, field: str, *, maximum: int, minimum: int = 0) -> list[Any]:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise SafeError("invalid_collection", field=field)
    return value


def _compile(pattern: Any, field: str) -> str:
    text = _text(pattern, field, maximum=500)
    _validate_safe_regex(text, field)
    try:
        re.compile(text)
    except re.error as error:
        raise SafeError("invalid_regex", field=field) from error
    return text


def _validate_safe_regex(pattern: str, field: str) -> None:
    """Reject constructs that can make Python's backtracking engine pathological."""
    index = 0
    previous_atom_was_quantified = False
    variable_quantifiers = 0
    variable_quantifier_end: int | None = None
    while index < len(pattern):
        character = pattern[index]
        atom_is_class = False
        if character == "\\":
            index += 1
            if index >= len(pattern):
                raise SafeError("unsafe_regex", field=field)
            escaped = pattern[index]
            if escaped.isalnum() and escaped not in "dDsSwW":
                raise SafeError("unsafe_regex", field=field)
            atom_is_class = escaped in "dDsSwW"
            index += 1
        elif character == "[":
            index += 1
            if index < len(pattern) and pattern[index] == "^":
                index += 1
            class_start = index
            escaped = False
            while index < len(pattern):
                item = pattern[index]
                if not escaped and item == "]":
                    break
                if not escaped and item == "[":
                    raise SafeError("unsafe_regex", field=field)
                escaped = not escaped and item == "\\"
                if item != "\\" or escaped is False:
                    escaped = False
                index += 1
            if index >= len(pattern) or index == class_start:
                raise SafeError("unsafe_regex", field=field)
            atom_is_class = True
            index += 1
        elif character == "^":
            if index != 0:
                raise SafeError("unsafe_regex", field=field)
            previous_atom_was_quantified = False
            index += 1
            continue
        elif character == "$":
            if index != len(pattern) - 1:
                raise SafeError("unsafe_regex", field=field)
            previous_atom_was_quantified = False
            index += 1
            continue
        elif character in "().|*+?{}":
            raise SafeError("unsafe_regex", field=field)
        else:
            index += 1

        quantified = False
        if index < len(pattern) and pattern[index] in "*+?":
            if not atom_is_class:
                raise SafeError("unsafe_regex", field=field)
            quantified = True
            variable_quantifiers += 1
            index += 1
            variable_quantifier_end = index
        elif index < len(pattern) and pattern[index] == "{":
            if not atom_is_class:
                raise SafeError("unsafe_regex", field=field)
            end = pattern.find("}", index + 1)
            if end < 0:
                raise SafeError("unsafe_regex", field=field)
            bounds = pattern[index + 1 : end]
            match = re.fullmatch(r"([0-9]+)(?:,([0-9]+))?", bounds)
            if match is None:
                raise SafeError("unsafe_regex", field=field)
            minimum = int(match.group(1))
            maximum = int(match.group(2) or match.group(1))
            if minimum > maximum or maximum > 1000:
                raise SafeError("unsafe_regex", field=field)
            quantified = True
            if minimum != maximum:
                variable_quantifiers += 1
                variable_quantifier_end = end + 1
            index = end + 1
        if variable_quantifiers > 1 or (quantified and previous_atom_was_quantified):
            raise SafeError("unsafe_regex", field=field)
        previous_atom_was_quantified = quantified
    if variable_quantifiers and (
        not pattern.startswith("^")
        or not pattern.endswith("$")
        or variable_quantifier_end != len(pattern) - 1
    ):
        raise SafeError("unsafe_regex", field=field)


def _additional_data(value: Any, field: str) -> dict[str, str]:
    if not isinstance(value, dict) or len(value) > 25:
        raise SafeError("invalid_additional_data", field=field)
    result: dict[str, str] = {}
    seen: set[str] = set()
    for raw_key, raw_value in value.items():
        key = _text(raw_key, f"{field}.key", maximum=100)
        item = _text(raw_value, f"{field}.value", maximum=500)
        folded = key.casefold()
        if folded in seen:
            raise SafeError("duplicate_additional_key", field=field)
        seen.add(folded)
        result[key] = item
    return result


def validate_config(value: Any) -> dict[str, Any]:
    config = _strict_object(
        value,
        {"schema_version", "accounts", "categories", "statement_profiles"},
        {"schema_version", "accounts", "categories", "statement_profiles"},
        "config",
    )
    if (
        isinstance(config["schema_version"], bool)
        or not isinstance(config["schema_version"], int)
        or config["schema_version"] != SCHEMA_VERSION
    ):
        raise SafeError("unsupported_schema", field="config.schema_version")

    accounts: list[dict[str, Any]] = []
    account_keys: set[str] = set()
    account_ids: set[int] = set()
    for index, raw in enumerate(
        _list(config["accounts"], "config.accounts", maximum=100, minimum=1)
    ):
        field = f"config.accounts[{index}]"
        account = _strict_object(
            raw,
            {"key", "account_id", "type", "currency", "role", "label"},
            {"key", "account_id", "type", "currency", "role", "label"},
            field,
        )
        key = _key(account["key"], f"{field}.key")
        account_id = account["account_id"]
        if (
            key in account_keys
            or isinstance(account_id, bool)
            or not isinstance(account_id, int)
        ):
            raise SafeError("duplicate_or_invalid_account", field=field)
        if account_id <= 0 or account_id in account_ids:
            raise SafeError("duplicate_or_invalid_account", field=field)
        account_type = account["type"]
        role = account["role"]
        currency = account["currency"]
        if account_type not in {"bank", "card"}:
            raise SafeError("invalid_account_type", field=f"{field}.type")
        if role not in {"owned", "accessible"}:
            raise SafeError("invalid_account_role", field=f"{field}.role")
        if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
            raise SafeError("invalid_currency", field=f"{field}.currency")
        label = _text(account["label"], f"{field}.label", maximum=200)
        account_keys.add(key)
        account_ids.add(account_id)
        accounts.append(
            {
                "key": key,
                "account_id": account_id,
                "type": account_type,
                "currency": currency,
                "role": role,
                "label": label,
            }
        )

    categories: list[str] = []
    category_keys: set[str] = set()
    for index, raw in enumerate(
        _list(config["categories"], "config.categories", maximum=500, minimum=1)
    ):
        category = _text(raw, f"config.categories[{index}]", maximum=255)
        folded = category.casefold()
        if folded in category_keys:
            raise SafeError("duplicate_category", field=f"config.categories[{index}]")
        category_keys.add(folded)
        categories.append(category)

    by_key = {account["key"]: account for account in accounts}
    profiles: list[dict[str, Any]] = []
    profile_keys: set[str] = set()
    optional = {"date_hint", "layout_hint", "parsing_notes"}
    required = {"key", "source_account", "issuer_pattern", "account_pattern"}
    for index, raw in enumerate(
        _list(
            config["statement_profiles"],
            "config.statement_profiles",
            maximum=100,
            minimum=1,
        )
    ):
        field = f"config.statement_profiles[{index}]"
        profile = _strict_object(raw, required | optional, required, field)
        profile_key = _key(profile["key"], f"{field}.key")
        source = _key(profile["source_account"], f"{field}.source_account")
        if profile_key in profile_keys:
            raise SafeError("duplicate_profile", field=field)
        if source not in by_key or by_key[source]["role"] != "owned":
            raise SafeError("invalid_profile_source", field=f"{field}.source_account")
        normalized: dict[str, Any] = {
            "key": profile_key,
            "source_account": source,
            "issuer_pattern": _compile(
                profile["issuer_pattern"], f"{field}.issuer_pattern"
            ),
            "account_pattern": _compile(
                profile["account_pattern"], f"{field}.account_pattern"
            ),
        }
        for name in optional:
            if name in profile:
                normalized[name] = _text(profile[name], f"{field}.{name}", maximum=2000)
        profile_keys.add(profile_key)
        profiles.append(normalized)
    return {
        "schema_version": SCHEMA_VERSION,
        "accounts": accounts,
        "categories": categories,
        "statement_profiles": profiles,
    }


def normalize_descriptor(value: str) -> str:
    """Return the deterministic representation used by every matcher."""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = "".join(
        character if character.isalnum() else " " for character in normalized
    )
    return " ".join(normalized.split())


def validate_patterns(value: Any, config: dict[str, Any]) -> dict[str, Any]:
    patterns = _strict_object(
        value,
        {"schema_version", "rules"},
        {"schema_version", "rules"},
        "patterns",
    )
    if (
        isinstance(patterns["schema_version"], bool)
        or not isinstance(patterns["schema_version"], int)
        or patterns["schema_version"] != SCHEMA_VERSION
    ):
        raise SafeError("unsupported_schema", field="patterns.schema_version")
    accounts = {account["key"]: account for account in config["accounts"]}
    categories = {category.casefold(): category for category in config["categories"]}
    rules: list[dict[str, Any]] = []
    rule_ids: set[str] = set()
    for index, raw in enumerate(
        _list(patterns["rules"], "patterns.rules", maximum=1000)
    ):
        field = f"patterns.rules[{index}]"
        rule = _strict_object(
            raw,
            {"id", "enabled", "source_account", "matcher", "result"},
            {"id", "enabled", "source_account", "matcher", "result"},
            field,
        )
        rule_id = _key(rule["id"], f"{field}.id")
        if rule_id in rule_ids:
            raise SafeError("duplicate_rule", field=field)
        if not isinstance(rule["enabled"], bool):
            raise SafeError("invalid_type", field=f"{field}.enabled")
        source = _key(rule["source_account"], f"{field}.source_account")
        if source not in accounts or accounts[source]["role"] != "owned":
            raise SafeError("invalid_rule_source", field=f"{field}.source_account")

        matcher = _strict_object(
            rule["matcher"], {"tokens", "regex"}, set(), f"{field}.matcher"
        )
        if not matcher:
            raise SafeError("empty_matcher", field=f"{field}.matcher")
        normalized_matcher: dict[str, Any] = {}
        if "tokens" in matcher:
            tokens: list[str] = []
            for token_index, raw_token in enumerate(
                _list(
                    matcher["tokens"], f"{field}.matcher.tokens", maximum=20, minimum=1
                )
            ):
                token_field = f"{field}.matcher.tokens[{token_index}]"
                token = _text(raw_token, token_field, maximum=100)
                if token != normalize_descriptor(token) or " " in token:
                    raise SafeError("invalid_normalized_token", field=token_field)
                if token in tokens:
                    raise SafeError("duplicate_token", field=token_field)
                tokens.append(token)
            normalized_matcher["tokens"] = tokens
        if "regex" in matcher:
            normalized_matcher["regex"] = _compile(
                matcher["regex"], f"{field}.matcher.regex"
            )

        result = _strict_object(
            rule["result"],
            {
                "type",
                "name",
                "description",
                "category",
                "target_account",
                "additional_data",
            },
            {"type", "name", "description", "category"},
            f"{field}.result",
        )
        transaction_type = result["type"]
        if transaction_type not in {"expense", "income", "transfer"}:
            raise SafeError("invalid_transaction_type", field=f"{field}.result.type")
        category = _text(result["category"], f"{field}.result.category", maximum=255)
        if category.casefold() not in categories:
            raise SafeError("unknown_category", field=f"{field}.result.category")
        normalized_result: dict[str, Any] = {
            "type": transaction_type,
            "name": _text(result["name"], f"{field}.result.name", maximum=255),
            "description": _text(
                result["description"],
                f"{field}.result.description",
                minimum=0,
                maximum=2000,
            ),
            "category": categories[category.casefold()],
        }
        if transaction_type == "transfer":
            target = _key(
                result.get("target_account"), f"{field}.result.target_account"
            )
            if target not in accounts or target == source:
                raise SafeError(
                    "invalid_transfer_target", field=f"{field}.result.target_account"
                )
            if accounts[target]["currency"] != accounts[source]["currency"]:
                raise SafeError(
                    "transfer_currency_mismatch", field=f"{field}.result.target_account"
                )
            normalized_result["target_account"] = target
        elif "target_account" in result:
            raise SafeError(
                "unexpected_transfer_target", field=f"{field}.result.target_account"
            )
        if "additional_data" in result:
            normalized_result["additional_data"] = _additional_data(
                result["additional_data"], f"{field}.result.additional_data"
            )
        rule_ids.add(rule_id)
        rules.append(
            {
                "id": rule_id,
                "enabled": rule["enabled"],
                "source_account": source,
                "matcher": normalized_matcher,
                "result": normalized_result,
            }
        )
    return {"schema_version": SCHEMA_VERSION, "rules": rules}


def match_rules(
    patterns: dict[str, Any], source_account: str, descriptor: str
) -> dict[str, Any]:
    normalized = normalize_descriptor(descriptor)
    words = set(normalized.split())
    matches = []
    for rule in patterns["rules"]:
        matcher = rule["matcher"]
        if not rule["enabled"] or rule["source_account"] != source_account:
            continue
        if "tokens" in matcher and not all(
            token in words for token in matcher["tokens"]
        ):
            continue
        if "regex" in matcher and re.search(matcher["regex"], normalized) is None:
            continue
        matches.append(rule)
    if not matches:
        return {"status": "none", "rule_ids": []}
    serialized = {
        json.dumps(
            rule["result"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        for rule in matches
    }
    if len(serialized) != 1:
        return {"status": "ambiguous", "rule_ids": [rule["id"] for rule in matches]}
    return {
        "status": "match",
        "rule_ids": [rule["id"] for rule in matches],
        "result": matches[0]["result"],
    }


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def _hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


@dataclass(frozen=True)
class State:
    config: dict[str, Any]
    patterns: dict[str, Any]
    config_hash: str
    patterns_hash: str


class StateStore:
    """Manage the fixed private paths without following symlinks."""

    def __init__(self, repository: Path):
        self.root = repository / ".local" / "statement"
        self.output = self.root / "output"
        self.config = self.root / "config.json"
        self.patterns = self.root / "patterns.json"

    @staticmethod
    def _reject_symlink(path: Path, role: str) -> None:
        if path.is_symlink():
            raise SafeError("symlink_not_allowed", path=role)

    def _guard_paths(self) -> None:
        self._reject_symlink(self.root.parent, "local_directory")
        self._reject_symlink(self.root, "state_directory")
        self._reject_symlink(self.output, "output_directory")
        self._reject_symlink(self.config, "config")
        self._reject_symlink(self.patterns, "patterns")

    def prepare_directories(self) -> None:
        self._guard_paths()
        self.root.mkdir(parents=True, mode=0o700, exist_ok=True)
        self._guard_paths()
        if not self.root.is_dir():
            raise SafeError("not_directory", path="state_directory")
        os.chmod(self.root, 0o700)
        self.output.mkdir(mode=0o700, exist_ok=True)
        self._guard_paths()
        if not self.output.is_dir():
            raise SafeError("not_directory", path="output_directory")
        os.chmod(self.output, 0o700)

    @contextmanager
    def mutation_lock(self) -> Iterator[None]:
        """Serialize state mutations on the stable private directory inode."""
        self._guard_paths()
        flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(self.root, flags)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
        except OSError as error:
            if "descriptor" in locals():
                os.close(descriptor)
            raise SafeError("lock_failed", path="state_directory") from error
        try:
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def _read(self, path: Path, role: str) -> bytes:
        self._reject_symlink(path, role)
        try:
            info = path.stat()
        except FileNotFoundError as error:
            raise SafeError("state_missing", path=role) from error
        if not stat.S_ISREG(info.st_mode):
            raise SafeError("not_regular_file", path=role)
        if info.st_mode & 0o077:
            raise SafeError("unsafe_permissions", path=role)
        if info.st_size > MAX_DOCUMENT_BYTES:
            raise SafeError("document_too_large", path=role)
        try:
            return path.read_bytes()
        except OSError as error:
            raise SafeError("read_failed", path=role) from error

    @staticmethod
    def _decode(content: bytes, role: str) -> Any:
        try:
            return json.loads(content, object_pairs_hook=_pairs)
        except (json.JSONDecodeError, UnicodeError, DuplicateKey) as error:
            raise SafeError("invalid_json", path=role) from error

    def load(self) -> State:
        self._guard_paths()
        config_bytes = self._read(self.config, "config")
        patterns_bytes = self._read(self.patterns, "patterns")
        config = validate_config(self._decode(config_bytes, "config"))
        patterns = validate_patterns(self._decode(patterns_bytes, "patterns"), config)
        return State(config, patterns, _hash(config_bytes), _hash(patterns_bytes))

    @staticmethod
    def _stage(directory: Path, content: bytes) -> Path:
        descriptor, raw_path = tempfile.mkstemp(prefix=".statement-", dir=directory)
        path = Path(raw_path)
        try:
            os.fchmod(descriptor, 0o600)
            stream = os.fdopen(descriptor, "wb")
            descriptor = -1
            with stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            if descriptor >= 0:
                os.close(descriptor)
            path.unlink(missing_ok=True)
            raise
        return path

    @staticmethod
    def _sync_directory(directory: Path) -> None:
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def initialize(self, config_value: Any) -> None:
        config = validate_config(config_value)
        patterns = validate_patterns(
            {"schema_version": SCHEMA_VERSION, "rules": []}, config
        )
        self.prepare_directories()
        with self.mutation_lock():
            if self.config.exists() or self.patterns.exists():
                raise SafeError("state_already_exists", path="state_directory")
            config_stage: Path | None = None
            patterns_stage: Path | None = None
            created: list[Path] = []
            try:
                config_stage = self._stage(self.root, _json_bytes(config))
                patterns_stage = self._stage(self.root, _json_bytes(patterns))
                os.link(config_stage, self.config)
                created.append(self.config)
                os.link(patterns_stage, self.patterns)
                created.append(self.patterns)
                self._sync_directory(self.root)
            except OSError as error:
                for path in created:
                    path.unlink(missing_ok=True)
                raise SafeError("write_failed", path="state_directory") from error
            finally:
                if config_stage is not None:
                    config_stage.unlink(missing_ok=True)
                if patterns_stage is not None:
                    patterns_stage.unlink(missing_ok=True)

    def update_config(self, value: Any) -> None:
        envelope = _strict_object(
            value,
            {"expected_config_hash", "config"},
            {"expected_config_hash", "config"},
            "update",
        )
        expected = envelope["expected_config_hash"]
        if not isinstance(expected, str) or not HASH.fullmatch(expected):
            raise SafeError("invalid_hash", field="update.expected_config_hash")
        self.prepare_directories()
        with self.mutation_lock():
            state = self.load()
            if expected != state.config_hash:
                raise SafeError("stale_state", path="config")
            config = validate_config(envelope["config"])
            validate_patterns(state.patterns, config)
            stage = self._stage(self.root, _json_bytes(config))
            original_config = self._read(self.config, "config")
            config_promoted = False
            try:
                os.replace(stage, self.config)
                config_promoted = True
                self._sync_directory(self.root)
            except OSError as error:
                if config_promoted:
                    rollback = self._stage(self.root, original_config)
                    try:
                        os.replace(rollback, self.config)
                    finally:
                        rollback.unlink(missing_ok=True)
                self._sync_directory(self.root)
                raise SafeError("write_failed", path="config") from error
            finally:
                stage.unlink(missing_ok=True)


def extract_pdf(path: Path) -> dict[str, Any]:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except FileNotFoundError as error:
        raise SafeError("pdf_not_found", path="pdf") from error
    except OSError as error:
        raise SafeError("pdf_open_failed", path="pdf") from error
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise SafeError("pdf_not_regular", path="pdf")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            try:
                reader = PdfReader(stream, strict=True)
                if reader.is_encrypted:
                    raise SafeError("pdf_encrypted", path="pdf")
                if not reader.pages:
                    raise SafeError("pdf_has_no_pages", path="pdf")
                pages = []
                for index, page in enumerate(reader.pages, start=1):
                    pages.append({"page": index, "text": page.extract_text() or ""})
            except SafeError:
                raise
            except (PdfReadError, ValueError, TypeError, OSError) as error:
                raise SafeError("pdf_malformed", path="pdf") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if not any(page["text"].strip() for page in pages):
        raise SafeError("pdf_has_no_text", path="pdf")
    return {"ok": True, "page_count": len(pages), "pages": pages}


def _money(
    value: Any, field: str, *, signed: bool = False, allow_zero: bool = False
) -> Decimal:
    if not isinstance(value, str):
        raise SafeError("invalid_amount", field=field)
    pattern = r"-?(?:0|[1-9][0-9]*)\.[0-9]{2}" if signed else AMOUNT.pattern
    if re.fullmatch(pattern, value) is None:
        raise SafeError("invalid_amount", field=field)
    try:
        amount = Decimal(value)
    except InvalidOperation as error:
        raise SafeError("invalid_amount", field=field) from error
    if (not signed and amount <= 0) or abs(amount) > MAX_AMOUNT:
        raise SafeError("invalid_amount", field=field)
    if signed and amount == 0 and not allow_zero:
        raise SafeError("invalid_amount", field=field)
    return amount


def _validate_row(
    value: Any,
    field: str,
    config: dict[str, Any],
    source_account: dict[str, Any],
    signed_amount: Decimal,
) -> dict[str, Any]:
    row = _strict_object(value, set(CSV_HEADERS), set(CSV_HEADERS), field)
    transaction_type = row["type"]
    if transaction_type not in {"expense", "income", "transfer"}:
        raise SafeError("invalid_transaction_type", field=f"{field}.type")
    name = _text(row["name"], f"{field}.name", maximum=255)
    description = _text(
        row["description"], f"{field}.description", minimum=0, maximum=2000
    )
    categories = {item.casefold(): item for item in config["categories"]}
    category = _text(row["category"], f"{field}.category", maximum=255)
    if category.casefold() not in categories:
        raise SafeError("unknown_category", field=f"{field}.category")
    raw_date = row["date"]
    try:
        if (
            not isinstance(raw_date, str)
            or date.fromisoformat(raw_date).isoformat() != raw_date
        ):
            raise ValueError
    except ValueError as error:
        raise SafeError("invalid_date", field=f"{field}.date") from error
    amount = _money(row["amount"], f"{field}.amount")
    if amount != abs(signed_amount):
        raise SafeError("settled_amount_mismatch", field=f"{field}.amount")
    accounts = {item["account_id"]: item for item in config["accounts"]}
    account_id = row["account_id"]
    target_id = row["target_account_id"]
    if (
        isinstance(account_id, bool)
        or not isinstance(account_id, int)
        or account_id not in accounts
    ):
        raise SafeError("unknown_account", field=f"{field}.account_id")
    account = accounts[account_id]
    if account["role"] != "owned":
        raise SafeError("account_not_owned", field=f"{field}.account_id")
    source_id = source_account["account_id"]
    if transaction_type == "transfer":
        if (
            isinstance(target_id, bool)
            or not isinstance(target_id, int)
            or target_id not in accounts
        ):
            raise SafeError("unknown_account", field=f"{field}.target_account_id")
        target = accounts[target_id]
        if account_id == target_id or account["type"] != "bank":
            raise SafeError("invalid_transfer", field=field)
        if account["currency"] != target["currency"]:
            raise SafeError("transfer_currency_mismatch", field=field)
        if signed_amount < 0 and (account_id != source_id or target_id == source_id):
            raise SafeError("direction_mismatch", field=field)
        if signed_amount > 0 and (target_id != source_id or account_id == source_id):
            raise SafeError("direction_mismatch", field=field)
    else:
        if target_id is not None:
            raise SafeError(
                "unexpected_transfer_target", field=f"{field}.target_account_id"
            )
        if account_id != source_id:
            raise SafeError("source_account_mismatch", field=f"{field}.account_id")
        if transaction_type == "expense" and signed_amount >= 0:
            raise SafeError("direction_mismatch", field=field)
        if transaction_type == "income" and signed_amount <= 0:
            raise SafeError("direction_mismatch", field=field)
        if transaction_type == "income" and account["type"] != "bank":
            raise SafeError("income_requires_bank", field=field)
    additional = _additional_data(row["additional_data"], f"{field}.additional_data")
    return {
        "type": transaction_type,
        "name": name,
        "description": description,
        "category": categories[category.casefold()],
        "date": raw_date,
        "amount": f"{amount:.2f}",
        "account_id": account_id,
        "target_account_id": target_id,
        "additional_data": additional,
    }


def _csv_bytes(rows: list[dict[str, Any]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=CSV_HEADERS, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        serialized = dict(row)
        serialized["target_account_id"] = row["target_account_id"] or ""
        serialized["additional_data"] = (
            json.dumps(
                row["additional_data"], ensure_ascii=False, separators=(",", ":")
            )
            if row["additional_data"]
            else ""
        )
        writer.writerow(serialized)
    content = stream.getvalue().encode()
    if len(content) > MAX_DOCUMENT_BYTES:
        raise SafeError("csv_too_large", path="output")
    return content


def finalize(store: StateStore, value: Any) -> dict[str, Any]:
    """Serialize and perform one approved CSV/pattern state mutation."""
    store.prepare_directories()
    with store.mutation_lock():
        return _finalize_locked(store, value)


def _finalize_locked(store: StateStore, value: Any) -> dict[str, Any]:
    envelope = _strict_object(
        value,
        {
            "source_account",
            "output_basename",
            "expected_config_hash",
            "expected_patterns_hash",
            "expected",
            "entries",
            "proposed_patterns",
        },
        {
            "source_account",
            "output_basename",
            "expected_config_hash",
            "expected_patterns_hash",
            "expected",
            "entries",
            "proposed_patterns",
        },
        "finalize",
    )
    state = store.load()
    for name, actual in (
        ("expected_config_hash", state.config_hash),
        ("expected_patterns_hash", state.patterns_hash),
    ):
        expected_hash = envelope[name]
        if not isinstance(expected_hash, str) or not HASH.fullmatch(expected_hash):
            raise SafeError("invalid_hash", field=f"finalize.{name}")
        if expected_hash != actual:
            raise SafeError(
                "stale_state", path=name.removeprefix("expected_").removesuffix("_hash")
            )
    source_key = _key(envelope["source_account"], "finalize.source_account")
    accounts = {account["key"]: account for account in state.config["accounts"]}
    if source_key not in accounts or accounts[source_key]["role"] != "owned":
        raise SafeError("invalid_source_account", field="finalize.source_account")
    source = accounts[source_key]
    basename = envelope["output_basename"]
    if not isinstance(basename, str) or not SAFE_BASENAME.fullmatch(basename):
        raise SafeError("unsafe_output_basename", field="finalize.output_basename")
    target = store.output / basename
    store._reject_symlink(target, "output")
    if target.exists():
        raise SafeError("output_exists", path="output")

    expected = _strict_object(
        envelope["expected"],
        {"count", "debit_total", "credit_total"},
        {"count", "debit_total", "credit_total"},
        "finalize.expected",
    )
    count = expected["count"]
    if (
        isinstance(count, bool)
        or not isinstance(count, int)
        or not 1 <= count <= MAX_ROWS
    ):
        raise SafeError("invalid_count", field="finalize.expected.count")
    expected_debits = _money(
        expected["debit_total"],
        "finalize.expected.debit_total",
        signed=True,
        allow_zero=True,
    )
    expected_credits = _money(
        expected["credit_total"],
        "finalize.expected.credit_total",
        signed=True,
        allow_zero=True,
    )
    if expected_debits < 0 or expected_credits < 0:
        raise SafeError("invalid_total", field="finalize.expected")
    entries = _list(
        envelope["entries"], "finalize.entries", maximum=MAX_ROWS, minimum=1
    )
    if len(entries) != count:
        raise SafeError("count_mismatch", field="finalize.entries")
    rows = []
    debits = Decimal("0.00")
    credits = Decimal("0.00")
    for index, raw in enumerate(entries, start=1):
        field = f"finalize.entries[{index - 1}]"
        entry = _strict_object(
            raw,
            {"ordinal", "signed_amount", "row"},
            {"ordinal", "signed_amount", "row"},
            field,
        )
        if entry["ordinal"] != index:
            raise SafeError("invalid_ordinal", field=f"{field}.ordinal")
        signed_amount = _money(
            entry["signed_amount"], f"{field}.signed_amount", signed=True
        )
        if signed_amount < 0:
            debits += -signed_amount
        else:
            credits += signed_amount
        rows.append(
            _validate_row(
                entry["row"], f"{field}.row", state.config, source, signed_amount
            )
        )
    if debits != expected_debits:
        raise SafeError("debit_total_mismatch", field="finalize.expected.debit_total")
    if credits != expected_credits:
        raise SafeError("credit_total_mismatch", field="finalize.expected.credit_total")
    proposed = validate_patterns(envelope["proposed_patterns"], state.config)
    csv_content = _csv_bytes(rows)
    pattern_content = _json_bytes(proposed)
    patterns_changed = proposed != state.patterns

    store.prepare_directories()
    csv_stage = store._stage(store.output, csv_content)
    pattern_stage = (
        store._stage(store.root, pattern_content) if patterns_changed else None
    )
    output_promoted = False
    patterns_promoted = False
    original_patterns = store._read(store.patterns, "patterns")
    try:
        os.link(csv_stage, target)
        output_promoted = True
        if pattern_stage is not None:
            os.replace(pattern_stage, store.patterns)
            patterns_promoted = True
        store._sync_directory(store.output)
        store._sync_directory(store.root)
    except OSError as error:
        if output_promoted:
            target.unlink(missing_ok=True)
            store._sync_directory(store.output)
        if patterns_promoted:
            rollback_stage = store._stage(store.root, original_patterns)
            try:
                os.replace(rollback_stage, store.patterns)
                store._sync_directory(store.root)
            finally:
                rollback_stage.unlink(missing_ok=True)
        raise SafeError("write_failed", path="finalization") from error
    finally:
        csv_stage.unlink(missing_ok=True)
        if pattern_stage is not None:
            pattern_stage.unlink(missing_ok=True)
    return {
        "ok": True,
        "rows": len(rows),
        "patterns_updated": patterns_changed,
        "output": str(target),
        "patterns": str(store.patterns),
    }


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _emit(value: Any) -> None:
    json.dump(value, sys.stdout, ensure_ascii=False, separators=(",", ":"))
    sys.stdout.write("\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Process private statement-import state safely."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    extract = commands.add_parser(
        "extract", help="extract page-indexed text from one PDF"
    )
    extract.add_argument("--pdf", required=True, type=Path)
    commands.add_parser(
        "validate-state", help="validate and return private state with hashes"
    )
    commands.add_parser(
        "initialize-state", help="create approved state from stdin JSON"
    )
    commands.add_parser("update-config", help="replace approved config from stdin JSON")
    commands.add_parser(
        "match-rules", help="match stdin descriptor against validated rules"
    )
    commands.add_parser(
        "finalize", help="validate and write an approved run from stdin JSON"
    )
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    store = StateStore(_repository_root())
    try:
        if arguments.command == "extract":
            result = extract_pdf(arguments.pdf)
        elif arguments.command == "validate-state":
            state = store.load()
            result = {
                "ok": True,
                "config": state.config,
                "patterns": state.patterns,
                "config_hash": state.config_hash,
                "patterns_hash": state.patterns_hash,
            }
        elif arguments.command == "initialize-state":
            store.initialize(_stdin_json())
            result = {"ok": True, "initialized": True}
        elif arguments.command == "update-config":
            store.update_config(_stdin_json())
            result = {"ok": True, "updated": True}
        elif arguments.command == "match-rules":
            payload = _strict_object(
                _stdin_json(),
                {"source_account", "descriptor"},
                {"source_account", "descriptor"},
                "match",
            )
            state = store.load()
            source = _key(payload["source_account"], "match.source_account")
            configured = {account["key"] for account in state.config["accounts"]}
            if source not in configured:
                raise SafeError("invalid_source_account", field="match.source_account")
            descriptor = _text(payload["descriptor"], "match.descriptor", maximum=2000)
            result = {"ok": True, **match_rules(state.patterns, source, descriptor)}
        else:
            result = finalize(store, _stdin_json())
    except SafeError as error:
        _emit(error.payload())
        return 2
    except Exception:  # noqa: BLE001 - suppress unexpected private-data-bearing exceptions.
        _emit({"ok": False, "error": "internal_error"})
        return 3
    _emit(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
