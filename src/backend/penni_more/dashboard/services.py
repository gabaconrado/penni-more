"""Exact, set-based aggregation for dashboard graphs."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import cast

from django.db.models import DecimalField, Q, Sum

from penni_more.accounts.models import Account
from penni_more.transactions.models import Category, Transaction

ZERO = Decimal("0.00")
ONE_HUNDRED = Decimal("100")
PERCENTAGE_PRECISION = Decimal("0.01")
TOTAL_FIELD: DecimalField[Decimal, Decimal] = DecimalField(max_digits=30, decimal_places=2)


@dataclass(frozen=True, slots=True)
class SummaryBar:
    """One exact total and its decorative relative size."""

    label: str
    amount: Decimal
    percentage: Decimal


@dataclass(frozen=True, slots=True)
class CategoryBar:
    """One selected category's exact expense total and relative size."""

    category_id: int
    label: str
    is_active: bool
    amount: Decimal
    percentage: Decimal


@dataclass(frozen=True, slots=True)
class DashboardGraphs:
    """The independently normalized dashboard graph datasets."""

    summary_bars: tuple[SummaryBar, ...]
    category_bars: tuple[CategoryBar, ...]


def _percentage(amount: Decimal, maximum: Decimal) -> Decimal:
    if maximum <= ZERO or amount <= ZERO:
        return ZERO
    value = (amount * ONE_HUNDRED / maximum).quantize(PERCENTAGE_PRECISION, rounding=ROUND_HALF_UP)
    return min(ONE_HUNDRED, max(ZERO, value))


def build_dashboard_graphs(
    *,
    accounts: Iterable[Account],
    categories: Iterable[Category],
    start: date,
    end: date,
) -> DashboardGraphs:
    """Aggregate validated model selections over an inclusive date range."""
    selected_accounts = tuple(accounts)
    selected_categories = tuple(categories)
    if not selected_accounts:
        raise ValueError("At least one validated account is required.")

    transactions = Transaction.objects.filter(
        account_id__in=(account.pk for account in selected_accounts),
        date__range=(start, end),
    )
    totals = transactions.aggregate(
        income=Sum(
            "amount",
            filter=Q(transaction_type=Transaction.Type.INCOME),
            default=ZERO,
            output_field=TOTAL_FIELD,
        ),
        expenses=Sum(
            "amount",
            filter=Q(transaction_type=Transaction.Type.EXPENSE),
            default=ZERO,
            output_field=TOTAL_FIELD,
        ),
    )
    income = cast(Decimal, totals["income"])
    expenses = cast(Decimal, totals["expenses"])
    summary_maximum = max(income, expenses)
    summary_bars = (
        SummaryBar("Income", income, _percentage(income, summary_maximum)),
        SummaryBar("Expenses", expenses, _percentage(expenses, summary_maximum)),
    )

    category_bars: tuple[CategoryBar, ...] = ()
    if selected_categories:
        grouped_rows = (
            transactions.filter(
                transaction_type=Transaction.Type.EXPENSE,
                category_id__in=(category.pk for category in selected_categories),
            )
            .values("category_id")
            .annotate(total=Sum("amount", output_field=TOTAL_FIELD))
        )
        totals_by_category = {
            cast(int, row["category_id"]): cast(Decimal, row["total"]) for row in grouped_rows
        }
        sorted_categories = tuple(
            sorted(
                selected_categories,
                key=lambda category: (
                    -totals_by_category.get(category.pk, ZERO),
                    category.name.casefold(),
                    category.name,
                    category.pk,
                ),
            )
        )
        category_bars = tuple(
            CategoryBar(
                category.pk,
                str(category),
                category.is_active,
                totals_by_category.get(category.pk, ZERO),
                ZERO,
            )
            for category in sorted_categories
        )
        category_maximum = max(bar.amount for bar in category_bars)
        category_bars = tuple(
            replace(bar, percentage=_percentage(bar.amount, category_maximum))
            for bar in category_bars
        )

    return DashboardGraphs(summary_bars=summary_bars, category_bars=category_bars)
