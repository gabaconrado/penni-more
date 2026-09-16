"""Persistence models and visibility rules for financial accounts."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class AccountQuerySet(models.QuerySet["Account"]):
    """Query financial accounts visible to a user."""

    def accessible_to(self, user: Any) -> AccountQuerySet:
        """Return owned and shared accounts once in deterministic name order."""
        return (
            self.filter(Q(owner=user) | Q(shares__recipient=user)).distinct().order_by("name", "pk")
        )


class Account(models.Model):
    """A bank or credit-card account with one immutable owner."""

    class Type(models.TextChoices):
        BANK = "bank", "Bank"
        CARD = "card", "Card"

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    account_type = models.CharField(max_length=4, choices=Type.choices)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="owned_accounts",
        editable=False,
    )

    objects = AccountQuerySet.as_manager()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(name__regex=r"\S"),
                name="accounts_account_name_not_blank",
            ),
            models.CheckConstraint(
                condition=Q(account_type__in=("bank", "card")),
                name="accounts_account_type_valid",
            ),
        ]

    def __str__(self) -> str:
        return self.name

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Preserve immutable ownership even when callers omit validation."""
        if not self._state.adding and self.pk is not None:
            original_owner_id = (
                type(self).objects.values_list("owner_id", flat=True).get(pk=self.pk)
            )
            if self.owner_id != original_owner_id:
                raise ValidationError({"owner": "An account's owner cannot be changed."})
        super().save(*args, **kwargs)

    def clean(self) -> None:
        """Reject ownership transfer for an account that already exists."""
        super().clean()
        if not self._state.adding and self.pk is not None:
            original_owner_id = (
                type(self).objects.values_list("owner_id", flat=True).get(pk=self.pk)
            )
            if self.owner_id != original_owner_id:
                raise ValidationError({"owner": "An account's owner cannot be changed."})


class AccountShare(models.Model):
    """Read access granted to an account recipient."""

    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="shares")
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="account_shares",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("account", "recipient"),
                name="accounts_accountshare_account_recipient_unique",
            )
        ]

    def __str__(self) -> str:
        return f"{self.account} shared with {self.recipient}"

    def clean(self) -> None:
        """Prevent owners from sharing their own account with themselves."""
        super().clean()
        if self.account_id and self.recipient_id and self.account.owner_id == self.recipient_id:
            raise ValidationError({"recipient": "The account owner already has access."})
