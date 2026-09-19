"""Validated filter boundary for the financial dashboard."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from django import forms
from django.utils import timezone

from penni_more.accounts.models import Account
from penni_more.transactions.models import Category


class DashboardAccountChoiceField(forms.ModelMultipleChoiceField):  # type: ignore[type-arg]
    """Label an accessible account with enough detail to disambiguate it."""

    def label_from_instance(self, obj: Account) -> str:
        return f"{obj.name} — {obj.currency.code} (account ID: {obj.pk})"


class DashboardFilterForm(forms.Form):
    """Validate dates and selections within the request user's read scope."""

    start = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    end = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    accounts = DashboardAccountChoiceField(
        queryset=Account.objects.none(),
        required=False,
        error_messages={"invalid_choice": "Select a valid account."},
    )
    categories = forms.ModelMultipleChoiceField(
        queryset=Category.objects.none(),
        required=False,
        error_messages={"invalid_choice": "Select a valid category."},
    )

    def __init__(self, *args: Any, user: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        account_field = self.fields["accounts"]
        assert isinstance(account_field, forms.ModelMultipleChoiceField)
        account_field.queryset = Account.objects.accessible_to(user).select_related("currency")

        category_field = self.fields["categories"]
        assert isinstance(category_field, forms.ModelMultipleChoiceField)
        category_field.queryset = Category.objects.all()

    def clean(self) -> dict[str, Any]:
        """Require ordered dates and one currency across selected accounts."""
        cleaned = super().clean() or {}
        start = cleaned.get("start")
        end = cleaned.get("end")
        if isinstance(start, date) and isinstance(end, date) and start > end:
            self.add_error("end", "End date must be on or after start date.")

        accounts = cleaned.get("accounts")
        if accounts is not None:
            currency_ids = {account.currency_id for account in accounts}
            if len(currency_ids) > 1:
                self.add_error("accounts", "Selected accounts must use the same currency.")
        return cleaned


def dashboard_filter_initial() -> dict[str, Any]:
    """Build unbound defaults from one captured UTC date and the current catalog."""
    today = timezone.now().date()
    return {
        "start": today - timedelta(days=30),
        "end": today,
        "accounts": (),
        "categories": tuple(Category.objects.values_list("pk", flat=True)),
    }
