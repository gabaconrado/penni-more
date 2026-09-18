"""Bounded CSV preview parsing and atomic confirmation services."""

from __future__ import annotations

import csv
import io
import json
import secrets
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction as database_transaction
from django.utils import timezone

from penni_more.accounts.models import Account

from .forms import AMOUNT_PATTERN
from .models import Category, Transaction
from .services import (
    TransactionWriteError,
    _locked_references,
    normalize_additional_data,
    validate_transaction_values,
)

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
MAX_BYTES = 1024 * 1024
MAX_ROWS = 1000
PREVIEW_SESSION_KEY = "transactions_import_preview"
PREVIEW_TTL_SECONDS = 30 * 60


@dataclass(frozen=True)
class ImportPreview:
    """The outcome of validating an uploaded CSV without writing rows."""

    rows: tuple[dict[str, Any], ...]
    row_errors: tuple[dict[str, Any], ...]
    file_errors: tuple[str, ...]

    @property
    def is_valid(self) -> bool:
        return bool(self.rows) and not self.row_errors and not self.file_errors


class DuplicateJSONKey(ValueError):
    """A JSON object repeated a key ignoring case."""


def _json_object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    seen: set[str] = set()
    for key, value in pairs:
        folded = key.casefold()
        if folded in seen:
            raise DuplicateJSONKey
        seen.add(folded)
        result[key] = value
    return result


def _parse_json_cell(raw: str) -> dict[str, str]:
    if not raw.strip():
        return {}
    try:
        value = json.loads(raw, object_pairs_hook=_json_object_pairs)
    except (json.JSONDecodeError, DuplicateJSONKey) as error:
        raise ValidationError("Additional data must be a JSON object with unique keys.") from error
    if not isinstance(value, dict):
        raise ValidationError("Additional data must be a JSON object.")
    return normalize_additional_data(value)


def _positive_id(raw: str, label: str, *, required: bool) -> int | None:
    value = raw.strip()
    if not value and not required:
        return None
    try:
        parsed = int(value)
    except ValueError as error:
        raise ValidationError(f"{label} must be a positive integer.") from error
    if parsed <= 0:
        raise ValidationError(f"{label} must be a positive integer.")
    return parsed


def _parse_syntax(source_line: int, cells: list[str]) -> tuple[dict[str, Any] | None, list[str]]:
    errors: list[str] = []
    if len(cells) != len(CSV_HEADERS):
        return None, [f"Expected {len(CSV_HEADERS)} columns, found {len(cells)}."]
    values = dict(zip(CSV_HEADERS, cells, strict=True))
    transaction_type = values["type"]
    if transaction_type not in Transaction.Type.values:
        errors.append("Type must be expense, income, or transfer.")
    name = values["name"].strip()
    if not name:
        errors.append("Name cannot be blank.")
    elif len(name) > 255:
        errors.append("Name may contain at most 255 characters.")
    description = values["description"].strip()
    if len(description) > 2000:
        errors.append("Description may contain at most 2000 characters.")
    category_name = values["category"].strip()
    if not category_name:
        errors.append("Category cannot be blank.")
    try:
        parsed_date = date.fromisoformat(values["date"])
        if parsed_date.isoformat() != values["date"]:
            raise ValueError
    except ValueError:
        parsed_date = None
        errors.append("Date must use YYYY-MM-DD.")
    raw_amount = values["amount"].strip()
    if not AMOUNT_PATTERN.fullmatch(raw_amount):
        amount = None
        errors.append("Amount must be positive with exactly two decimal places.")
    else:
        try:
            amount = Decimal(raw_amount)
        except InvalidOperation:
            amount = None
            errors.append("Amount is invalid.")
    try:
        account_id = _positive_id(values["account_id"], "Account ID", required=True)
    except ValidationError as error:
        account_id = None
        errors.extend(error.messages)
    target_required = transaction_type == Transaction.Type.TRANSFER
    try:
        target_id = _positive_id(
            values["target_account_id"], "Target account ID", required=target_required
        )
    except ValidationError as error:
        target_id = None
        errors.extend(error.messages)
    if not target_required and values["target_account_id"].strip():
        errors.append("Target account ID must be blank unless type is transfer.")
    try:
        additional_data = _parse_json_cell(values["additional_data"])
    except ValidationError as error:
        additional_data = {}
        errors.extend(error.messages)
    if errors:
        return None, errors
    assert parsed_date is not None and amount is not None and account_id is not None
    return (
        {
            "source_line": source_line,
            "transaction_type": transaction_type,
            "name": name,
            "description": description,
            "category_name": category_name,
            "date": parsed_date.isoformat(),
            "amount": str(amount),
            "account_id": account_id,
            "target_account_id": target_id,
            "additional_data": additional_data,
        },
        [],
    )


def parse_csv_upload(upload: Any, *, user: Any) -> ImportPreview:
    """Parse and validate a bounded CSV entirely without ledger writes."""
    raw = upload.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        return ImportPreview((), (), ("CSV files may not exceed 1 MiB.",))
    if b"\x00" in raw:
        return ImportPreview((), (), ("CSV files may not contain NUL bytes.",))
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return ImportPreview((), (), ("CSV files must use UTF-8 encoding.",))
    parsed: list[dict[str, Any]] = []
    row_errors: list[dict[str, Any]] = []
    try:
        rows = csv.reader(io.StringIO(text, newline=""), strict=True)
        header: list[str] | None = None
        for cells in rows:
            if not cells or all(not cell.strip() for cell in cells):
                continue
            if header is None:
                header = cells
                if tuple(header) != CSV_HEADERS:
                    return ImportPreview(
                        (),
                        (),
                        ("CSV headers must exactly match the documented order.",),
                    )
                continue
            if len(parsed) + len(row_errors) >= MAX_ROWS:
                return ImportPreview((), (), ("CSV files may contain at most 1000 data rows.",))
            normalized, errors = _parse_syntax(rows.line_num, cells)
            if errors:
                row_errors.append({"source_line": rows.line_num, "errors": errors})
            elif normalized is not None:
                parsed.append(normalized)
    except csv.Error:
        return ImportPreview((), (), ("The CSV is malformed.",))
    if header is None:
        return ImportPreview((), (), ("The CSV is empty.",))
    if not parsed and not row_errors:
        return ImportPreview((), (), ("The CSV contains no data rows.",))

    account_ids = {
        item_id
        for row in parsed
        for item_id in (row["account_id"], row["target_account_id"])
        if item_id is not None
    }
    accounts = {
        item.pk: item
        for item in Account.objects.filter(pk__in=account_ids).select_related("currency", "owner")
    }
    category_names = {row["category_name"].casefold() for row in parsed}
    categories = {
        item.name.casefold(): item
        for item in Category.objects.filter(is_active=True)
        if item.name.casefold() in category_names
    }
    accessible_ids = set(Account.objects.accessible_to(user).values_list("pk", flat=True))
    valid_rows: list[dict[str, Any]] = []
    for row in parsed:
        errors = []
        account = accounts.get(row["account_id"])
        target = accounts.get(row["target_account_id"])
        category = categories.get(row["category_name"].casefold())
        if account is None or account.owner_id != user.pk:
            errors.append("Account ID must identify an account you own.")
        if row["target_account_id"] is not None and (
            target is None or target.pk not in accessible_ids
        ):
            errors.append("Target account ID must identify an accessible account.")
        if category is None:
            errors.append("Category must identify an active category.")
        if not errors:
            try:
                validate_transaction_values(
                    transaction_type=row["transaction_type"],
                    amount=Decimal(row["amount"]),
                    account=account,
                    target_account=target,
                    category=category,
                    additional_data=row["additional_data"],
                )
            except TransactionWriteError as error:
                errors.extend(error.messages)
        if errors:
            row_errors.append({"source_line": row["source_line"], "errors": errors})
            continue
        assert account is not None and category is not None
        valid_rows.append(
            {
                **row,
                "category_id": category.pk,
                "category": category.name,
                "account": account.name,
                "target_account": target.name if target is not None else None,
            }
        )
    return ImportPreview(tuple(valid_rows), tuple(row_errors), ())


def store_preview(session: Any, rows: Iterable[dict[str, Any]]) -> str:
    """Replace the session's one active normalized preview."""
    token = secrets.token_urlsafe(32)
    session[PREVIEW_SESSION_KEY] = {
        "token": token,
        "created_at": int(timezone.now().timestamp()),
        "rows": list(rows),
    }
    session.modified = True
    return token


def load_preview(session: Any, token: str) -> list[dict[str, Any]] | None:
    """Load a matching unexpired preview without consuming it."""
    payload = session.get(PREVIEW_SESSION_KEY)
    if not isinstance(payload, dict):
        session.pop(PREVIEW_SESSION_KEY, None)
        session.modified = True
        return None
    if not secrets.compare_digest(str(payload.get("token", "")), token):
        return None
    try:
        age = int(timezone.now().timestamp()) - int(payload["created_at"])
    except KeyError, TypeError, ValueError:
        session.pop(PREVIEW_SESSION_KEY, None)
        session.modified = True
        return None
    rows = payload.get("rows")
    if age < 0 or age > PREVIEW_TTL_SECONDS or not isinstance(rows, list):
        session.pop(PREVIEW_SESSION_KEY, None)
        session.modified = True
        return None
    return rows


def confirm_import(*, user: Any, rows: list[dict[str, Any]]) -> int:
    """Revalidate and atomically insert every normalized preview row."""
    account_ids = {
        item_id
        for row in rows
        for item_id in (row["account_id"], row.get("target_account_id"))
        if item_id is not None
    }
    category_ids = {row["category_id"] for row in rows}
    with database_transaction.atomic():
        accounts, categories = _locked_references(account_ids, category_ids)
        accessible_ids = set(Account.objects.accessible_to(user).values_list("pk", flat=True))
        instances: list[Transaction] = []
        row_errors: list[str] = []
        for row in rows:
            account = accounts.get(row["account_id"])
            raw_target_id = row.get("target_account_id")
            target = accounts.get(raw_target_id) if isinstance(raw_target_id, int) else None
            category = categories.get(row["category_id"])
            errors: list[str] = []
            if account is None or account.owner_id != user.pk:
                errors.append("Account is no longer available.")
            if row.get("target_account_id") is not None and (
                target is None or target.pk not in accessible_ids
            ):
                errors.append("Target account is no longer available.")
            try:
                normalized = validate_transaction_values(
                    transaction_type=row["transaction_type"],
                    amount=Decimal(row["amount"]),
                    account=account,
                    target_account=target,
                    category=category,
                    additional_data=row["additional_data"],
                )
            except TransactionWriteError as error:
                normalized = {}
                errors.extend(error.messages)
            if errors:
                row_errors.append(f"Row {row['source_line']}: {'; '.join(errors)}")
                continue
            instances.append(
                Transaction(
                    transaction_type=row["transaction_type"],
                    name=row["name"],
                    description=row["description"],
                    category=category,
                    date=date.fromisoformat(row["date"]),
                    amount=Decimal(row["amount"]),
                    account=account,
                    target_account=target,
                    additional_data=normalized,
                    created_by=user,
                )
            )
        if row_errors:
            raise TransactionWriteError(row_errors)
        Transaction.objects.bulk_create(instances)
    return len(instances)
