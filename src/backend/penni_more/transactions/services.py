"""Domain validation, locking writes, privacy, and ledger aggregation."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db import connection
from django.db import transaction as database_transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from penni_more.accounts.models import Account

from .models import Category, Transaction

MAX_ADDITIONAL_PAIRS = 25
MAX_ADDITIONAL_KEY_LENGTH = 100
MAX_ADDITIONAL_VALUE_LENGTH = 500
MAX_AMOUNT = Decimal("9999999999999999.99")


class TransactionWriteError(ValidationError):
    """A transaction write failed current domain policy."""


class TransactionUnavailableError(TransactionWriteError):
    """A transaction disappeared or became unavailable during a locked write."""


class LedgerIntegrityError(RuntimeError):
    """Persisted ledger data violates a cross-row domain invariant."""


@dataclass(frozen=True)
class AccountPresentation:
    """An account reference safe to expose to one viewer."""

    is_private: bool
    name: str
    url: str | None


@dataclass(frozen=True)
class TransactionData:
    """Non-account transaction fields safe to expose in rendered contexts."""

    pk: int
    transaction_type: str
    name: str
    description: str
    category: Category
    date: date
    amount: Decimal
    additional_data: dict[str, str]
    created_by: Any
    created_at: Any
    updated_at: Any
    amount_currency_code: str

    def get_transaction_type_display(self) -> str:
        return str(Transaction.Type(self.transaction_type).label)


@dataclass(frozen=True)
class TransactionPresentation:
    """A transaction paired with privacy-safe account references."""

    transaction: TransactionData
    source: AccountPresentation
    target: AccountPresentation | None


def normalize_additional_data(value: Mapping[Any, Any]) -> dict[str, str]:
    """Normalize and bound a flat string mapping with case-insensitive keys."""
    if not isinstance(value, Mapping):
        raise ValidationError("Additional data must be an object.")
    if len(value) > MAX_ADDITIONAL_PAIRS:
        raise ValidationError(f"Additional data may contain at most {MAX_ADDITIONAL_PAIRS} pairs.")
    normalized: dict[str, str] = {}
    seen: set[str] = set()
    for raw_key, raw_value in value.items():
        if not isinstance(raw_key, str) or not isinstance(raw_value, str):
            raise ValidationError("Additional data keys and values must be text.")
        key = raw_key.strip()
        item_value = raw_value.strip()
        if not key or not item_value:
            raise ValidationError("Additional data keys and values cannot be blank.")
        if len(key) > MAX_ADDITIONAL_KEY_LENGTH:
            raise ValidationError(
                f"Additional data keys may contain at most {MAX_ADDITIONAL_KEY_LENGTH} characters."
            )
        if len(item_value) > MAX_ADDITIONAL_VALUE_LENGTH:
            raise ValidationError(
                "Additional data values may contain at most "
                f"{MAX_ADDITIONAL_VALUE_LENGTH} characters."
            )
        folded = key.casefold()
        if folded in seen:
            raise ValidationError("Additional data keys must be unique ignoring case.")
        seen.add(folded)
        normalized[key] = item_value
    return normalized


def parse_additional_data_text(value: str) -> dict[str, str]:
    """Parse one `key = value` pair per nonblank line."""
    pairs: dict[str, str] = {}
    seen: set[str] = set()
    for line_number, line in enumerate(value.splitlines(), start=1):
        if not line.strip():
            continue
        if "=" not in line:
            raise ValidationError(f"Line {line_number} must contain an equals sign.")
        key, item_value = line.split("=", 1)
        folded = key.strip().casefold()
        if folded in seen:
            raise ValidationError("Additional data keys must be unique ignoring case.")
        seen.add(folded)
        pairs[key] = item_value
    return normalize_additional_data(pairs)


def format_additional_data_text(value: Mapping[str, str]) -> str:
    """Format structured data for the manual textarea boundary."""
    return "\n".join(f"{key} = {item_value}" for key, item_value in value.items())


def validate_transaction_values(
    *,
    transaction_type: str,
    amount: Decimal,
    account: Account | None,
    target_account: Account | None,
    category: Category | None,
    additional_data: Mapping[Any, Any],
) -> dict[str, str]:
    """Validate all ledger invariants independent of transport."""
    errors: dict[str, str] = {}
    if transaction_type not in Transaction.Type.values:
        errors["transaction_type"] = "Select a valid transaction type."
    if amount is None or amount <= 0 or amount > MAX_AMOUNT:
        errors["amount"] = "Amount must be between 0.01 and 9999999999999999.99."
    if account is None:
        errors["account"] = "Select an account."
    elif transaction_type == Transaction.Type.INCOME and account.account_type != Account.Type.BANK:
        errors["account"] = "Income requires a bank account."
    elif (
        transaction_type == Transaction.Type.TRANSFER and account.account_type != Account.Type.BANK
    ):
        errors["account"] = "A transfer source must be a bank account."
    if transaction_type == Transaction.Type.TRANSFER:
        if target_account is None:
            errors["target_account"] = "Select a transfer target."
        elif account is not None:
            if target_account.pk == account.pk:
                errors["target_account"] = "Source and target accounts must be different."
            elif target_account.currency_id != account.currency_id:
                errors["target_account"] = "Transfer accounts must use the same currency."
    elif target_account is not None:
        errors["target_account"] = "Only transfers may have a target account."
    if category is None or not category.is_active:
        errors["category"] = "Select an active category."
    try:
        normalized = normalize_additional_data(additional_data)
    except ValidationError as error:
        errors["additional_data"] = "; ".join(error.messages)
        normalized = {}
    if errors:
        raise TransactionWriteError(errors)
    return normalized


def _accessible_ids(user: Any) -> set[int]:
    return set(Account.objects.accessible_to(user).values_list("pk", flat=True))


def can_mutate(transaction: Transaction, user: Any) -> bool:
    """Return whether the user owns the primary/source account."""
    return bool(transaction.account.owner_id == user.pk)


def present_account(account: Account, accessible_ids: set[int]) -> AccountPresentation:
    """Mask an inaccessible account without retaining an identifying value."""
    if account.pk not in accessible_ids:
        return AccountPresentation(is_private=True, name="Private account", url=None)
    return AccountPresentation(
        is_private=False,
        name=account.name,
        url=reverse("accounts:detail", args=(account.pk,)),
    )


def present_transaction(
    ledger_transaction: Transaction, accessible_ids: set[int]
) -> TransactionPresentation:
    """Build a viewer-safe transaction presentation."""
    target = ledger_transaction.target_account
    if ledger_transaction.account_id in accessible_ids:
        currency_code = ledger_transaction.account.currency.code
    elif target is not None and target.pk in accessible_ids:
        currency_code = target.currency.code
    else:
        currency_code = ""
    return TransactionPresentation(
        transaction=TransactionData(
            pk=ledger_transaction.pk,
            transaction_type=ledger_transaction.transaction_type,
            name=ledger_transaction.name,
            description=ledger_transaction.description,
            category=ledger_transaction.category,
            date=ledger_transaction.date,
            amount=ledger_transaction.amount,
            additional_data=dict(ledger_transaction.additional_data),
            created_by=ledger_transaction.created_by,
            created_at=ledger_transaction.created_at,
            updated_at=ledger_transaction.updated_at,
            amount_currency_code=currency_code,
        ),
        source=present_account(ledger_transaction.account, accessible_ids),
        target=present_account(target, accessible_ids) if target is not None else None,
    )


def _locked_references(
    account_ids: Iterable[int], category_ids: Iterable[int]
) -> tuple[dict[int, Account], dict[int, Category]]:
    accounts = {
        item.pk: item
        for item in Account.objects.select_for_update()
        .select_related("currency", "owner")
        .filter(pk__in=sorted(set(account_ids)))
        .order_by("pk")
    }
    categories = {
        item.pk: item
        for item in Category.objects.select_for_update()
        .filter(pk__in=sorted(set(category_ids)))
        .order_by("pk")
    }
    return accounts, categories


def _validate_access(
    *,
    user: Any,
    account: Account,
    target: Account | None,
    source_must_be_owned: bool,
    retained_private_target_id: int | None = None,
) -> None:
    accessible = _accessible_ids(user)
    if account.pk not in accessible or (source_must_be_owned and account.owner_id != user.pk):
        raise TransactionWriteError({"account": "Select a valid account."})
    if (
        target is not None
        and target.pk not in accessible
        and target.pk != retained_private_target_id
    ):
        raise TransactionWriteError({"target_account": "Select a valid account."})


def create_transaction(
    *, user: Any, values: Mapping[str, Any], owner_only: bool = False
) -> Transaction:
    """Create one ledger row after locked policy revalidation."""
    account = values["account"]
    target = values.get("target_account")
    category = values["category"]
    ids = [account.pk]
    if target is not None:
        ids.append(target.pk)
    with database_transaction.atomic():
        accounts, categories = _locked_references(ids, [category.pk])
        locked_account = accounts.get(account.pk)
        locked_target = accounts.get(target.pk) if target is not None else None
        locked_category = categories.get(category.pk)
        if locked_account is None or (target is not None and locked_target is None):
            raise TransactionWriteError("An account is no longer available.")
        _validate_access(
            user=user,
            account=locked_account,
            target=locked_target,
            source_must_be_owned=owner_only,
        )
        normalized = validate_transaction_values(
            transaction_type=values["transaction_type"],
            amount=values["amount"],
            account=locked_account,
            target_account=locked_target,
            category=locked_category,
            additional_data=values.get("additional_data", {}),
        )
        assert locked_category is not None
        return Transaction.objects.create(
            transaction_type=values["transaction_type"],
            name=str(values["name"]).strip(),
            description=str(values.get("description", "")).strip(),
            category=locked_category,
            date=values["date"],
            amount=values["amount"],
            account=locked_account,
            target_account=locked_target,
            additional_data=normalized,
            created_by=user,
        )


def update_transaction(
    *, user: Any, ledger_transaction: Transaction, values: Mapping[str, Any]
) -> Transaction:
    """Replace a mutable ledger row after locked authorization and validation."""
    account = values["account"]
    target = values.get("target_account")
    category = values["category"]
    ids = [account.pk]
    if target is not None:
        ids.append(target.pk)
    with database_transaction.atomic():
        try:
            locked_transaction = (
                Transaction.objects.select_for_update()
                .select_related("account")
                .get(pk=ledger_transaction.pk)
            )
        except Transaction.DoesNotExist as error:
            raise TransactionUnavailableError("This transaction is not available.") from error
        if not can_mutate(locked_transaction, user):
            raise TransactionWriteError("This transaction is not available.")
        accounts, categories = _locked_references(ids, [category.pk])
        locked_account = accounts.get(account.pk)
        locked_target = accounts.get(target.pk) if target is not None else None
        locked_category = categories.get(category.pk)
        if locked_account is None or (target is not None and locked_target is None):
            raise TransactionWriteError("An account is no longer available.")
        _validate_access(
            user=user,
            account=locked_account,
            target=locked_target,
            source_must_be_owned=True,
            retained_private_target_id=locked_transaction.target_account_id,
        )
        normalized = validate_transaction_values(
            transaction_type=values["transaction_type"],
            amount=values["amount"],
            account=locked_account,
            target_account=locked_target,
            category=locked_category,
            additional_data=values.get("additional_data", {}),
        )
        assert locked_category is not None
        for field in ("transaction_type", "date", "amount"):
            setattr(locked_transaction, field, values[field])
        locked_transaction.name = str(values["name"]).strip()
        locked_transaction.description = str(values.get("description", "")).strip()
        locked_transaction.account = locked_account
        locked_transaction.target_account = locked_target
        locked_transaction.category = locked_category
        locked_transaction.additional_data = normalized
        locked_transaction.save()
        return locked_transaction


def delete_transaction(*, user: Any, ledger_transaction: Transaction) -> None:
    """Delete one row only while its current source owner is authorized."""
    with database_transaction.atomic():
        try:
            locked = (
                Transaction.objects.select_for_update()
                .select_related("account")
                .get(pk=ledger_transaction.pk)
            )
        except Transaction.DoesNotExist as error:
            raise TransactionUnavailableError("This transaction is not available.") from error
        if not can_mutate(locked, user):
            raise TransactionWriteError("This transaction is not available.")
        locked.delete()


def balances_for_accounts(
    accounts: Iterable[Account], *, cutoff: date | None = None
) -> dict[int, Decimal]:
    """Calculate balances for many accounts with bounded ledger queries."""
    account_ids = [account.pk for account in accounts]
    balances = {account_id: Decimal("0.00") for account_id in account_ids}
    if not account_ids:
        return balances
    effective_cutoff = cutoff or timezone.now().date()
    sql = """
        WITH requested(account_id) AS (
            SELECT unnest(%s::bigint[])
        ),
        relevant AS (
            SELECT
                ledger.transaction_type,
                ledger.amount,
                ledger.account_id,
                ledger.target_account_id,
                source.account_type AS source_type,
                target.account_type AS target_type
            FROM transactions_transaction AS ledger
            JOIN accounts_account AS source ON source.id = ledger.account_id
            LEFT JOIN accounts_account AS target ON target.id = ledger.target_account_id
            WHERE ledger.date <= %s
              AND (
                  ledger.account_id = ANY(%s::bigint[])
                  OR ledger.target_account_id = ANY(%s::bigint[])
              )
        ),
        integrity AS (
            SELECT COALESCE(bool_and(
                CASE
                    WHEN transaction_type = 'expense'
                        THEN source_type IN ('bank', 'card') AND target_account_id IS NULL
                    WHEN transaction_type = 'income'
                        THEN source_type = 'bank' AND target_account_id IS NULL
                    WHEN transaction_type = 'transfer'
                        THEN source_type = 'bank'
                            AND target_type IN ('bank', 'card')
                            AND target_account_id IS NOT NULL
                            AND account_id <> target_account_id
                    ELSE FALSE
                END
            ), TRUE) AS is_valid
            FROM relevant
        ),
        effects AS (
            SELECT
                account_id,
                CASE
                    WHEN transaction_type = 'expense' AND source_type = 'bank' THEN -amount
                    WHEN transaction_type = 'expense' AND source_type = 'card' THEN amount
                    WHEN transaction_type = 'income' AND source_type = 'bank' THEN amount
                    WHEN transaction_type = 'transfer' AND source_type = 'bank' THEN -amount
                    ELSE 0::numeric
                END AS effect
            FROM relevant
            WHERE account_id = ANY(%s::bigint[])

            UNION ALL

            SELECT
                target_account_id AS account_id,
                CASE
                    WHEN target_type = 'bank' THEN amount
                    WHEN target_type = 'card' THEN -amount
                    ELSE 0::numeric
                END AS effect
            FROM relevant
            WHERE transaction_type = 'transfer'
              AND target_account_id = ANY(%s::bigint[])
        ),
        totals AS (
            SELECT account_id, SUM(effect) AS total
            FROM effects
            GROUP BY account_id
        )
        SELECT requested.account_id, COALESCE(totals.total, 0::numeric), integrity.is_valid
        FROM requested
        CROSS JOIN integrity
        LEFT JOIN totals ON totals.account_id = requested.account_id
        ORDER BY requested.account_id
    """
    with connection.cursor() as cursor:
        cursor.execute(
            sql,
            [
                account_ids,
                effective_cutoff,
                account_ids,
                account_ids,
                account_ids,
                account_ids,
            ],
        )
        rows = cursor.fetchall()
    if any(not is_valid for _account_id, _total, is_valid in rows):
        raise LedgerIntegrityError("Persisted transaction/account types are incompatible.")
    for account_id, total, _is_valid in rows:
        balances[account_id] = Decimal(total).quantize(Decimal("0.01"))
    return balances


def account_has_transactions(account: Account) -> bool:
    """Return whether an account participates on either side of a ledger row."""
    return Transaction.objects.filter(Q(account=account) | Q(target_account=account)).exists()


def filter_additional_data(queryset: Any, *, key: str, value: str) -> Any:
    """Apply a parameterized case-insensitive exact JSON key/value predicate."""
    return queryset.extra(
        where=[
            'EXISTS (SELECT 1 FROM jsonb_each_text("transactions_transaction".'
            '"additional_data") AS item(key, value) '
            "WHERE lower(item.key) = lower(%s) AND lower(item.value) = lower(%s))"
        ],
        params=[key, value],
    )
