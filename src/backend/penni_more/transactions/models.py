"""Persistence models and visibility rules for the transaction ledger."""

from __future__ import annotations

from datetime import date
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.db.models.lookups import Exact
from django.urls import reverse
from django.utils import timezone

from penni_more.accounts.models import Account


def utc_today() -> date:
    """Return today's date under the configured UTC application clock."""
    return timezone.now().date()


class Category(models.Model):
    """An administrator-managed transaction category."""

    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("name", "pk")
        verbose_name_plural = "categories"
        constraints = [
            models.CheckConstraint(
                condition=Q(name__regex=r"\S"),
                name="transactions_category_name_not_blank",
            ),
            models.UniqueConstraint(
                Lower("name"),
                name="transactions_category_name_ci_unique",
            ),
        ]

    def __str__(self) -> str:
        return self.name if self.is_active else f"{self.name} (inactive)"

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.name = self.name.strip()
        super().save(*args, **kwargs)

    def clean(self) -> None:
        super().clean()
        self.name = self.name.strip()
        if not self.name:
            raise ValidationError({"name": "Category name cannot be blank."})


class TransactionQuerySet(models.QuerySet["Transaction"]):
    """Query ledger rows using account access policy."""

    def accessible_to(self, user: Any) -> TransactionQuerySet:
        """Return rows where the user can access either affected account."""
        return self.filter(
            Q(account__owner=user)
            | Q(account__shares__recipient=user)
            | Q(target_account__owner=user)
            | Q(target_account__shares__recipient=user)
        ).distinct()

    def stable_order(self) -> TransactionQuerySet:
        """Apply the stable newest-first ledger order."""
        return self.order_by("-date", "-created_at", "-pk")


class Transaction(models.Model):
    """A mutable ledger event affecting one or two accounts."""

    class Type(models.TextChoices):
        EXPENSE = "expense", "Expense"
        INCOME = "income", "Income"
        TRANSFER = "transfer", "Transfer"

    transaction_type = models.CharField(max_length=8, choices=Type.choices)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, max_length=2000)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="transactions")
    date = models.DateField(default=utc_today)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name="transactions",
    )
    target_account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name="incoming_transfers",
        null=True,
        blank=True,
    )
    additional_data = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_transactions",
        editable=False,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = TransactionQuerySet.as_manager()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(name__regex=r"\S"),
                name="transactions_transaction_name_not_blank",
            ),
            models.CheckConstraint(
                condition=Q(amount__gt=0),
                name="transactions_transaction_amount_positive",
            ),
            models.CheckConstraint(
                condition=Q(transaction_type__in=("expense", "income", "transfer")),
                name="transactions_transaction_type_valid",
            ),
            models.CheckConstraint(
                condition=(
                    Q(transaction_type="transfer", target_account__isnull=False)
                    | (~Q(transaction_type="transfer") & Q(target_account__isnull=True))
                ),
                name="transactions_transaction_target_shape",
            ),
            models.CheckConstraint(
                condition=Q(target_account__isnull=True) | ~Q(account=models.F("target_account")),
                name="transactions_transaction_accounts_distinct",
            ),
            models.CheckConstraint(
                condition=Exact(
                    models.Func(
                        models.F("additional_data"),
                        function="jsonb_typeof",
                        output_field=models.CharField(),
                    ),
                    models.Value("object"),
                ),
                name="transactions_transaction_additional_data_object",
            ),
        ]
        indexes = [
            models.Index(fields=("account", "date"), name="transactions_account_date_idx"),
            models.Index(fields=("target_account", "date"), name="transactions_target_date_idx"),
            models.Index(
                fields=("-date", "-created_at", "-id"),
                name="transactions_list_order_idx",
            ),
        ]

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        return reverse("transactions:detail", args=(self.pk,))

    def clean(self) -> None:
        """Validate row-local and cross-account ledger invariants."""
        super().clean()
        self.name = self.name.strip()
        from .services import validate_transaction_values

        validate_transaction_values(
            transaction_type=self.transaction_type,
            amount=self.amount,
            account=self.account if self.account_id else None,
            target_account=self.target_account if self.target_account_id else None,
            category=self.category if self.category_id else None,
            additional_data=self.additional_data,
        )
