"""Tests for dashboard filter validation and exact graph aggregation."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from django import forms
from django.db import connection
from django.test.utils import CaptureQueriesContext

from penni_more.accounts.models import Account, AccountShare, Currency
from penni_more.dashboard.forms import DashboardFilterForm, dashboard_filter_initial
from penni_more.dashboard.services import build_dashboard_graphs
from penni_more.transactions.models import Category, Transaction
from penni_more.users.models import User


def _user(email: str) -> User:
    return User.objects.create_user(email, "test-password")


def _currency(code: str) -> Currency:
    return Currency.objects.create(code=code, name=code, country="Test country")


def _account(owner: User, currency: Currency, name: str) -> Account:
    return Account.objects.create(
        owner=owner,
        currency=currency,
        name=name,
        account_type=Account.Type.BANK,
    )


def _transaction(
    *,
    creator: User,
    account: Account,
    category: Category,
    kind: str,
    amount: str,
    when: date,
    target: Account | None = None,
) -> Transaction:
    return Transaction.objects.create(
        created_by=creator,
        account=account,
        target_account=target,
        category=category,
        transaction_type=kind,
        name="Dashboard row",
        amount=Decimal(amount),
        date=when,
    )


@pytest.mark.django_db
def test_initial_filters_capture_today_once_and_include_inactive_categories(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active = Category.objects.create(name="Active")
    inactive = Category.objects.create(name="Past", is_active=False)
    calls = 0

    def fixed_now() -> datetime:
        nonlocal calls
        calls += 1
        return datetime(2027, 1, 15, 23, 59, tzinfo=UTC)

    monkeypatch.setattr("penni_more.dashboard.forms.timezone.now", fixed_now)

    initial = dashboard_filter_initial()

    assert calls == 1
    assert initial == {
        "start": date(2026, 12, 16),
        "end": date(2027, 1, 15),
        "accounts": (),
        "categories": (active.pk, inactive.pk),
    }


@pytest.mark.django_db
def test_form_limits_accounts_to_owned_and_shared_and_accepts_empty_selections() -> None:
    viewer = _user("viewer@example.com")
    owner = _user("owner@example.com")
    outsider = _user("outsider@example.com")
    usd = _currency("USD")
    owned = _account(viewer, usd, "Owned")
    shared = _account(owner, usd, "Shared")
    hidden = _account(outsider, usd, "Hidden")
    AccountShare.objects.create(account=shared, recipient=viewer)

    form = DashboardFilterForm(
        {"start": "2026-09-01", "end": "2026-09-19", "accounts": [], "categories": []},
        user=viewer,
    )

    assert form.is_valid(), form.errors
    account_field = form.fields["accounts"]
    assert isinstance(account_field, forms.ModelMultipleChoiceField)
    assert account_field.queryset is not None
    assert list(account_field.queryset) == [owned, shared]
    assert hidden not in account_field.queryset
    assert list(form.cleaned_data["accounts"]) == []
    assert list(form.cleaned_data["categories"]) == []


@pytest.mark.django_db
def test_form_rejects_mixed_currencies_date_order_and_forged_choices() -> None:
    viewer = _user("viewer@example.com")
    outsider = _user("outsider@example.com")
    usd = _currency("USD")
    eur = _currency("EUR")
    usd_account = _account(viewer, usd, "USD")
    eur_account = _account(viewer, eur, "EUR")
    hidden = _account(outsider, usd, "Hidden")

    mixed = DashboardFilterForm(
        {
            "start": "2026-09-20",
            "end": "2026-09-19",
            "accounts": [usd_account.pk, eur_account.pk],
            "categories": [],
        },
        user=viewer,
    )
    forged = DashboardFilterForm(
        {
            "start": "2026-09-01",
            "end": "2026-09-19",
            "accounts": [hidden.pk],
            "categories": [999999],
        },
        user=viewer,
    )

    assert not mixed.is_valid()
    assert "same currency" in str(mixed.errors["accounts"])
    assert "on or after" in str(mixed.errors["end"])
    assert not forged.is_valid()
    assert "valid account" in str(forged.errors["accounts"])
    assert "valid category" in str(forged.errors["categories"])


@pytest.mark.django_db
def test_graphs_aggregate_exact_selected_primary_rows_and_fill_and_sort_categories() -> None:
    owner = _user("owner@example.com")
    usd = _currency("USD")
    selected = _account(owner, usd, "Selected")
    target = _account(owner, usd, "Target")
    unselected = _account(owner, usd, "Other")
    food = Category.objects.create(name="food")
    bills = Category.objects.create(name="Bills")
    zero = Category.objects.create(name="Archived", is_active=False)
    excluded = Category.objects.create(name="Not selected")

    _transaction(
        creator=owner,
        account=selected,
        category=food,
        kind=Transaction.Type.INCOME,
        amount="10.01",
        when=date(2026, 9, 1),
    )
    _transaction(
        creator=owner,
        account=selected,
        category=food,
        kind=Transaction.Type.INCOME,
        amount="0.02",
        when=date(2026, 9, 30),
    )
    _transaction(
        creator=owner,
        account=selected,
        category=food,
        kind=Transaction.Type.EXPENSE,
        amount="3.00",
        when=date(2026, 9, 10),
    )
    _transaction(
        creator=owner,
        account=selected,
        category=bills,
        kind=Transaction.Type.EXPENSE,
        amount="7.00",
        when=date(2026, 9, 11),
    )
    _transaction(
        creator=owner,
        account=selected,
        category=excluded,
        kind=Transaction.Type.EXPENSE,
        amount="4.00",
        when=date(2026, 9, 11),
    )
    _transaction(
        creator=owner,
        account=selected,
        target=target,
        category=food,
        kind=Transaction.Type.TRANSFER,
        amount="900.00",
        when=date(2026, 9, 12),
    )
    _transaction(
        creator=owner,
        account=unselected,
        category=food,
        kind=Transaction.Type.EXPENSE,
        amount="800.00",
        when=date(2026, 9, 12),
    )
    _transaction(
        creator=owner,
        account=target,
        target=selected,
        category=food,
        kind=Transaction.Type.TRANSFER,
        amount="700.00",
        when=date(2026, 9, 12),
    )
    _transaction(
        creator=owner,
        account=selected,
        category=food,
        kind=Transaction.Type.EXPENSE,
        amount="600.00",
        when=date(2026, 8, 31),
    )

    with CaptureQueriesContext(connection) as queries:
        graphs = build_dashboard_graphs(
            accounts=(selected,),
            categories=(food, zero, bills),
            start=date(2026, 9, 1),
            end=date(2026, 9, 30),
        )

    assert len(queries) == 2
    assert [(bar.label, bar.amount) for bar in graphs.summary_bars] == [
        ("Income", Decimal("10.03")),
        ("Expenses", Decimal("14.00")),
    ]
    assert [bar.percentage for bar in graphs.summary_bars] == [
        Decimal("71.64"),
        Decimal("100"),
    ]
    assert [(bar.label, bar.amount) for bar in graphs.category_bars] == [
        ("Bills", Decimal("7.00")),
        ("food", Decimal("3.00")),
        ("Archived (inactive)", Decimal("0.00")),
    ]
    assert [bar.percentage for bar in graphs.category_bars] == [
        Decimal("100"),
        Decimal("42.86"),
        Decimal("0.00"),
    ]
    assert all(Decimal("0") <= bar.percentage <= Decimal("100") for bar in graphs.summary_bars)
    assert all(Decimal("0") <= bar.percentage <= Decimal("100") for bar in graphs.category_bars)
    assert all(bar.category_id != excluded.pk for bar in graphs.category_bars)


@pytest.mark.django_db
def test_graph_query_count_does_not_grow_with_many_accounts_or_categories() -> None:
    owner = _user("owner@example.com")
    usd = _currency("USD")
    accounts = tuple(_account(owner, usd, f"Account {index}") for index in range(5))
    categories = tuple(Category.objects.create(name=f"Category {index}") for index in range(8))

    with CaptureQueriesContext(connection) as queries:
        graphs = build_dashboard_graphs(
            accounts=accounts,
            categories=categories,
            start=date(2026, 9, 1),
            end=date(2026, 9, 30),
        )

    assert len(queries) == 2
    assert len(graphs.category_bars) == 8


@pytest.mark.django_db
def test_graphs_keep_two_zero_summary_bars_and_skip_category_query_when_none_selected() -> None:
    owner = _user("owner@example.com")
    account = _account(owner, _currency("USD"), "Empty")

    with CaptureQueriesContext(connection) as queries:
        graphs = build_dashboard_graphs(
            accounts=(account,), categories=(), start=date(2026, 9, 1), end=date(2026, 9, 30)
        )

    assert len(queries) == 1
    assert [(bar.label, bar.amount, bar.percentage) for bar in graphs.summary_bars] == [
        ("Income", Decimal("0.00"), Decimal("0.00")),
        ("Expenses", Decimal("0.00"), Decimal("0.00")),
    ]
    assert graphs.category_bars == ()
