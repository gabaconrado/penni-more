"""Validated HTML form boundaries for transaction operations."""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from typing import Any

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from penni_more.accounts.models import Account

from .models import Category, Transaction
from .services import format_additional_data_text, parse_additional_data_text

AMOUNT_PATTERN = re.compile(r"^[0-9]+\.[0-9]{2}$")
PRIVATE_TARGET_VALUE = "__keep_private__"


def _account_label(account: Account) -> str:
    return (
        f"{account.name} — {account.get_account_type_display()}, {account.currency.code} "
        f"(CSV account ID: {account.pk})"
    )


class AccountChoiceField(forms.ModelChoiceField):  # type: ignore[type-arg]
    """Disambiguate accessible accounts with their user-visible CSV IDs."""

    def label_from_instance(self, obj: Account) -> str:
        return _account_label(obj)


class ExactAmountField(forms.DecimalField):
    """Accept a positive magnitude only with exactly two decimal places."""

    def to_python(self, value: Any) -> Any:
        if value in self.empty_values:
            return super().to_python(value)
        raw = str(value).strip()
        if not AMOUNT_PATTERN.fullmatch(raw):
            raise ValidationError(
                "Enter a positive amount with exactly two decimal places.", code="format"
            )
        return super().to_python(raw)


class TransactionForm(forms.ModelForm):  # type: ignore[type-arg]
    """Create or edit one ledger row within the request user's account scope."""

    amount = ExactAmountField(max_digits=18, decimal_places=2, min_value=Decimal("0.01"))
    additional_data = forms.CharField(
        required=False,
        widget=forms.Textarea,
        help_text="Enter one key = value pair per line.",
    )
    target_account = forms.ChoiceField(required=False)
    account = AccountChoiceField(queryset=Account.objects.none())

    class Meta:
        model = Transaction
        fields = (
            "transaction_type",
            "name",
            "description",
            "category",
            "date",
            "amount",
            "account",
            "target_account",
            "additional_data",
        )
        widgets = {"date": forms.DateInput(attrs={"type": "date"})}

    def __init__(
        self,
        *args: Any,
        user: Any,
        mode: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.user = user
        self.mode = mode
        accessible = Account.objects.accessible_to(user).select_related("currency", "owner")
        source = accessible if mode == "create" else accessible.filter(owner=user)
        account_field = self.fields["account"]
        assert isinstance(account_field, forms.ModelChoiceField)
        account_field.queryset = source
        category_field = self.fields["category"]
        assert isinstance(category_field, forms.ModelChoiceField)
        category_field.queryset = Category.objects.filter(is_active=True).order_by("name", "pk")

        target_choices: list[tuple[str, str]] = [("", "---------")]
        target_choices.extend((str(item.pk), _account_label(item)) for item in accessible)
        self.private_target: Account | None = None
        if (
            mode == "edit"
            and self.instance.pk is not None
            and self.instance.target_account_id is not None
            and not accessible.filter(pk=self.instance.target_account_id).exists()
        ):
            self.private_target = self.instance.target_account
            target_choices.append((PRIVATE_TARGET_VALUE, "Keep private account"))
        target_field = self.fields["target_account"]
        assert isinstance(target_field, forms.ChoiceField)
        target_field.choices = target_choices

        if not self.is_bound:
            if self.instance.pk is None:
                self.initial["date"] = timezone.now().date()
            else:
                self.initial["additional_data"] = format_additional_data_text(
                    self.instance.additional_data
                )
                if self.private_target is not None:
                    self.initial["target_account"] = PRIVATE_TARGET_VALUE
                elif self.instance.target_account_id is not None:
                    self.initial["target_account"] = str(self.instance.target_account_id)

    def clean_name(self) -> str:
        name = str(self.cleaned_data["name"]).strip()
        if not name:
            raise ValidationError("Name cannot be blank.")
        return name

    def clean_description(self) -> str:
        return str(self.cleaned_data.get("description", "")).strip()

    def clean_date(self) -> Any:
        value = self.cleaned_data["date"]
        if value is None:
            raise ValidationError("Enter a date.")
        return value

    def clean_target_account(self) -> Account | None:
        raw = str(self.cleaned_data.get("target_account", ""))
        if not raw:
            return None
        if raw == PRIVATE_TARGET_VALUE:
            if self.private_target is None:
                raise ValidationError("Select a valid account.")
            return self.private_target
        try:
            return Account.objects.accessible_to(self.user).get(pk=int(raw))
        except (Account.DoesNotExist, TypeError, ValueError) as error:
            raise ValidationError("Select a valid account.") from error

    def clean_additional_data(self) -> dict[str, str]:
        return parse_additional_data_text(str(self.cleaned_data.get("additional_data", "")))

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean() or {}
        transaction_type = cleaned.get("transaction_type")
        account = cleaned.get("account")
        target = cleaned.get("target_account")
        if (
            transaction_type == Transaction.Type.INCOME
            and account is not None
            and account.account_type != Account.Type.BANK
        ):
            self.add_error("account", "Income requires a bank account.")
        if transaction_type == Transaction.Type.TRANSFER:
            if account is not None and account.account_type != Account.Type.BANK:
                self.add_error("account", "A transfer source must be a bank account.")
            if target is None:
                self.add_error("target_account", "Select a transfer target.")
            elif account is not None:
                if target.pk == account.pk:
                    self.add_error(
                        "target_account", "Source and target accounts must be different."
                    )
                elif target.currency_id != account.currency_id:
                    self.add_error(
                        "target_account", "Transfer accounts must use the same currency."
                    )
        elif target is not None:
            self.add_error("target_account", "Only transfers may have a target account.")
        return cleaned


class TransactionFilterForm(forms.Form):
    """Validate session-persisted transaction filters."""

    account = AccountChoiceField(queryset=Account.objects.none(), required=False)
    month = forms.CharField(required=False, max_length=7)
    additional_key = forms.CharField(required=False, max_length=100)
    additional_value = forms.CharField(required=False, max_length=500)

    def __init__(self, *args: Any, user: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        account_field = self.fields["account"]
        assert isinstance(account_field, forms.ModelChoiceField)
        account_field.queryset = Account.objects.accessible_to(user)

    def clean_month(self) -> str:
        value = str(self.cleaned_data.get("month", "")).strip()
        if value:
            try:
                datetime.strptime(value, "%Y-%m")
            except ValueError as error:
                raise ValidationError("Enter a month in YYYY-MM format.") from error
        return value

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean() or {}
        key = str(cleaned.get("additional_key", "")).strip()
        value = str(cleaned.get("additional_value", "")).strip()
        cleaned["additional_key"] = key
        cleaned["additional_value"] = value
        if bool(key) != bool(value):
            message = "Provide both an additional-data key and value."
            self.add_error("additional_key", message)
            self.add_error("additional_value", message)
        return cleaned


class CSVImportForm(forms.Form):
    """Accept one bounded CSV upload."""

    csv_file = forms.FileField()

    def clean_csv_file(self) -> Any:
        upload = self.cleaned_data["csv_file"]
        if upload.size > 1024 * 1024:
            raise ValidationError("CSV files may not exceed 1 MiB.")
        return upload


class ImportConfirmationForm(forms.Form):
    """Accept only an opaque server-side preview token."""

    preview_token = forms.CharField(max_length=200)
