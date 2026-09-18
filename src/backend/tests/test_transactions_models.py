"""Model, validation, service, and balance tests for transactions."""

from datetime import timedelta
from decimal import Decimal
from typing import Any, cast

import pytest
from django import forms
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.utils import timezone

from penni_more.accounts.models import Account, AccountShare, Currency
from penni_more.transactions.forms import TransactionFilterForm, TransactionForm
from penni_more.transactions.models import Category, Transaction
from penni_more.transactions.services import (
    LedgerIntegrityError,
    TransactionWriteError,
    balances_for_accounts,
    create_transaction,
    normalize_additional_data,
    parse_additional_data_text,
)
from penni_more.users.models import User


@pytest.fixture
def owner() -> User:
    return User.objects.create_user("ledger-owner@example.com", "password")


@pytest.fixture
def currency() -> Currency:
    return Currency.objects.create(code="USD", name="US dollar", country="United States")


@pytest.fixture
def category() -> Category:
    return Category.objects.create(name=" Groceries ")


def account(owner: User, currency: Currency, kind: str, name: str) -> Account:
    return Account.objects.create(
        name=name, description="", account_type=kind, owner=owner, currency=currency
    )


@pytest.mark.django_db
def test_category_normalizes_and_is_unique_ignoring_case(category: Category) -> None:
    assert category.name == "Groceries"
    with pytest.raises(IntegrityError), transaction.atomic():
        Category.objects.create(name="gRoCeRiEs")
    with pytest.raises(IntegrityError), transaction.atomic():
        Category.objects.create(name="  ")


@pytest.mark.django_db
def test_database_constraints_reject_invalid_transaction_shapes(
    owner: User, currency: Currency, category: Category
) -> None:
    bank = account(owner, currency, Account.Type.BANK, "Bank")
    invalid = [
        {"name": " ", "amount": Decimal("1.00"), "transaction_type": "expense"},
        {"name": "Valid", "amount": Decimal("0.00"), "transaction_type": "expense"},
        {"name": "Valid", "amount": Decimal("1.00"), "transaction_type": "unknown"},
        {
            "name": "Valid",
            "amount": Decimal("1.00"),
            "transaction_type": "transfer",
        },
    ]
    for values in invalid:
        with pytest.raises(IntegrityError), transaction.atomic():
            Transaction.objects.create(
                date=timezone.now().date(),
                description="",
                category=category,
                account=bank,
                created_by=owner,
                additional_data={},
                **values,
            )
    with pytest.raises(IntegrityError), transaction.atomic():
        Transaction.objects.create(
            transaction_type=Transaction.Type.TRANSFER,
            name="Same",
            description="",
            category=category,
            date=timezone.now().date(),
            amount=Decimal("1.00"),
            account=bank,
            target_account=bank,
            additional_data={},
            created_by=owner,
        )
    with pytest.raises(IntegrityError), transaction.atomic():
        Transaction.objects.create(
            transaction_type=Transaction.Type.EXPENSE,
            name="Invalid JSON shape",
            description="",
            category=category,
            date=timezone.now().date(),
            amount=Decimal("1.00"),
            account=bank,
            additional_data=[],
            created_by=owner,
        )


@pytest.mark.django_db
def test_type_rules_and_exact_amount_form_boundary(
    owner: User, currency: Currency, category: Category
) -> None:
    card = account(owner, currency, Account.Type.CARD, "Card")
    form = TransactionForm(
        {
            "transaction_type": Transaction.Type.INCOME,
            "name": "Pay",
            "description": "",
            "category": category.pk,
            "date": "2026-09-18",
            "amount": "10.0",
            "account": card.pk,
            "target_account": "",
            "additional_data": "",
        },
        user=owner,
        mode="create",
    )
    assert not form.is_valid()
    assert {"amount", "account"}.issubset(form.errors)


@pytest.mark.django_db
def test_account_choices_disambiguate_duplicate_names_with_accessible_ids(
    owner: User, currency: Currency, category: Category
) -> None:
    first = account(owner, currency, Account.Type.BANK, "Duplicate")
    second = account(owner, currency, Account.Type.BANK, "Duplicate")
    form = TransactionForm(user=owner, mode="create")
    edit_form = TransactionForm(user=owner, mode="edit")
    filter_form = TransactionFilterForm(user=owner)
    source_field = form.fields["account"]
    target_field = form.fields["target_account"]
    assert isinstance(source_field, forms.ModelChoiceField)
    assert isinstance(target_field, forms.ChoiceField)
    source_labels = [label for _value, label in cast(Any, source_field.choices)]
    target_labels = [label for _value, label in cast(Any, target_field.choices)]
    edit_labels = [label for _value, label in cast(Any, edit_form.fields["account"]).choices]
    filter_labels = [label for _value, label in cast(Any, filter_form.fields["account"]).choices]

    first_label = f"Duplicate — Bank, USD (CSV account ID: {first.pk})"
    second_label = f"Duplicate — Bank, USD (CSV account ID: {second.pk})"
    assert first_label in source_labels
    assert second_label in source_labels
    assert first_label in target_labels
    assert second_label in target_labels
    assert first_label in edit_labels
    assert second_label in edit_labels
    assert first_label in filter_labels
    assert second_label in filter_labels
    assert first_label != second_label


@pytest.mark.django_db
def test_manual_type_account_currency_and_access_matrix(
    owner: User, currency: Currency, category: Category
) -> None:
    other = User.objects.create_user("matrix-other@example.com", "password")
    bank = account(owner, currency, Account.Type.BANK, "Bank")
    card = account(owner, currency, Account.Type.CARD, "Card")
    inaccessible = account(other, currency, Account.Type.BANK, "Private")
    eur = Currency.objects.create(code="EUR", name="Euro", country="European Union")
    euro_bank = account(owner, eur, Account.Type.BANK, "Euro bank")

    def form(kind: str, source: Account, target: Account | None = None) -> TransactionForm:
        return TransactionForm(
            {
                "transaction_type": kind,
                "name": "Matrix",
                "description": "",
                "category": category.pk,
                "date": "2026-09-18",
                "amount": "1.00",
                "account": source.pk,
                "target_account": target.pk if target is not None else "",
                "additional_data": "",
            },
            user=owner,
            mode="create",
        )

    assert form(Transaction.Type.EXPENSE, bank).is_valid()
    assert form(Transaction.Type.EXPENSE, card).is_valid()
    assert form(Transaction.Type.INCOME, bank).is_valid()
    assert not form(Transaction.Type.INCOME, card).is_valid()
    assert not form(Transaction.Type.TRANSFER, card, bank).is_valid()
    assert not form(Transaction.Type.TRANSFER, bank, bank).is_valid()
    assert not form(Transaction.Type.TRANSFER, bank, euro_bank).is_valid()
    assert not form(Transaction.Type.EXPENSE, inaccessible).is_valid()


@pytest.mark.django_db
def test_additional_data_normalization_and_manual_parser() -> None:
    assert parse_additional_data_text(" Statement = July\nnote = a=b ") == {
        "Statement": "July",
        "note": "a=b",
    }
    for value in ("missing", " = value", "Key = one\nkey = two"):
        with pytest.raises(ValidationError):
            parse_additional_data_text(value)
    with pytest.raises(ValidationError):
        normalize_additional_data({f"k{i}": "v" for i in range(26)})


@pytest.mark.django_db
def test_balances_derive_all_signs_and_exclude_future(
    owner: User, currency: Currency, category: Category
) -> None:
    bank = account(owner, currency, Account.Type.BANK, "Bank")
    savings = account(owner, currency, Account.Type.BANK, "Savings")
    card = account(owner, currency, Account.Type.CARD, "Card")
    today = timezone.now().date()
    base = {"category": category, "date": today, "additional_data": {}}
    for kind, amount, source, target in (
        (Transaction.Type.INCOME, "100.00", bank, None),
        (Transaction.Type.EXPENSE, "20.00", bank, None),
        (Transaction.Type.EXPENSE, "30.00", card, None),
        (Transaction.Type.TRANSFER, "15.00", bank, savings),
        (Transaction.Type.TRANSFER, "10.00", bank, card),
    ):
        create_transaction(
            user=owner,
            values={
                **base,
                "transaction_type": kind,
                "name": kind,
                "description": "",
                "amount": Decimal(amount),
                "account": source,
                "target_account": target,
            },
        )
    create_transaction(
        user=owner,
        values={
            **base,
            "transaction_type": Transaction.Type.INCOME,
            "name": "Future",
            "description": "",
            "date": today + timedelta(days=1),
            "amount": Decimal("999.00"),
            "account": bank,
            "target_account": None,
        },
    )
    balances = balances_for_accounts([bank, savings, card], cutoff=today)
    assert balances == {
        bank.pk: Decimal("55.00"),
        savings.pk: Decimal("15.00"),
        card.pk: Decimal("20.00"),
    }


@pytest.mark.django_db
def test_balance_aggregation_is_database_side_bounded_and_fails_closed(
    owner: User,
    currency: Currency,
    category: Category,
    django_assert_num_queries: Any,
) -> None:
    bank = account(owner, currency, Account.Type.BANK, "Bank")
    for index in range(100):
        Transaction.objects.create(
            transaction_type=Transaction.Type.EXPENSE,
            name=f"Expense {index}",
            description="",
            category=category,
            date=timezone.now().date(),
            amount=Decimal("1.00"),
            account=bank,
            additional_data={},
            created_by=owner,
        )
    with django_assert_num_queries(1):
        assert balances_for_accounts([bank])[bank.pk] == Decimal("-100.00")

    card = account(owner, currency, Account.Type.CARD, "Card")
    Transaction.objects.create(
        transaction_type=Transaction.Type.INCOME,
        name="Invalid persisted combination",
        description="",
        category=category,
        date=timezone.now().date(),
        amount=Decimal("1.00"),
        account=card,
        additional_data={},
        created_by=owner,
    )
    with pytest.raises(LedgerIntegrityError, match="incompatible"):
        balances_for_accounts([card])

    Transaction.objects.filter(account=card).delete()
    target = account(owner, currency, Account.Type.BANK, "Target")
    Transaction.objects.create(
        transaction_type=Transaction.Type.TRANSFER,
        name="Invalid card source",
        description="",
        category=category,
        date=timezone.now().date(),
        amount=Decimal("1.00"),
        account=card,
        target_account=target,
        additional_data={},
        created_by=owner,
    )
    with pytest.raises(LedgerIntegrityError, match="incompatible"):
        balances_for_accounts([card, target])


@pytest.mark.django_db
def test_access_and_history_protect_account_type_and_deletion(
    owner: User, currency: Currency, category: Category
) -> None:
    recipient = User.objects.create_user("shared@example.com", "password")
    bank = account(owner, currency, Account.Type.BANK, "Bank")
    AccountShare.objects.create(account=bank, recipient=recipient)
    item = create_transaction(
        user=recipient,
        values={
            "transaction_type": Transaction.Type.EXPENSE,
            "name": "Shared expense",
            "description": "",
            "category": category,
            "date": timezone.now().date(),
            "amount": Decimal("1.00"),
            "account": bank,
            "target_account": None,
            "additional_data": {},
        },
    )
    assert item.created_by == recipient
    bank.account_type = Account.Type.CARD
    with pytest.raises(ValidationError, match="cannot change"):
        bank.save()
    with pytest.raises(ProtectedError):
        Account.objects.filter(pk=bank.pk).delete()
    category.is_active = False
    category.save()
    with pytest.raises(TransactionWriteError):
        create_transaction(
            user=recipient,
            values={
                "transaction_type": Transaction.Type.EXPENSE,
                "name": "Invalid",
                "description": "",
                "category": category,
                "date": timezone.now().date(),
                "amount": Decimal("1.00"),
                "account": bank,
                "target_account": None,
                "additional_data": {},
            },
        )


@pytest.mark.django_db
def test_target_side_history_locks_account_type_and_delete(
    owner: User, currency: Currency, category: Category
) -> None:
    source = account(owner, currency, Account.Type.BANK, "Source")
    target = account(owner, currency, Account.Type.CARD, "Target")
    create_transaction(
        user=owner,
        values={
            "transaction_type": Transaction.Type.TRANSFER,
            "name": "Payment",
            "description": "",
            "category": category,
            "date": timezone.now().date(),
            "amount": Decimal("5.00"),
            "account": source,
            "target_account": target,
            "additional_data": {},
        },
    )
    target.account_type = Account.Type.BANK
    with pytest.raises(ValidationError, match="cannot change"):
        target.save()
    with pytest.raises(ProtectedError):
        target.delete()
