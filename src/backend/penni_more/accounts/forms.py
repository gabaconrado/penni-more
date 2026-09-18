"""Validated HTML form boundaries for account operations."""

from typing import Any

from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q

from penni_more.users.models import User

from .models import Account, AccountShare, Currency


class AccountForm(forms.ModelForm):  # type: ignore[type-arg]
    """Create or edit owner-controlled account information."""

    class Meta:
        model = Account
        fields = ("name", "description", "account_type", "currency")

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        allowed = Currency.objects.filter(is_active=True)
        if self.instance.pk is not None and self.instance.currency_id is not None:
            allowed = Currency.objects.filter(Q(is_active=True) | Q(pk=self.instance.currency_id))
        currency_field = self.fields["currency"]
        assert isinstance(currency_field, forms.ModelChoiceField)
        currency_field.queryset = allowed.order_by("code")
        if self.instance.pk is not None and self.instance.has_transactions():
            self.fields["account_type"].disabled = True
            self.fields[
                "account_type"
            ].help_text = "Account type cannot change after transactions exist."


class AccountShareForm(forms.Form):
    """Resolve one existing user as a new account recipient."""

    email = forms.EmailField(widget=forms.EmailInput(attrs={"autocomplete": "email"}))

    def __init__(self, *args: Any, account: Account, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.account = account
        self.recipient: User | None = None

    def clean_email(self) -> str:
        """Resolve email without case sensitivity and reject invalid recipients."""
        email = str(self.cleaned_data["email"]).strip().lower()
        try:
            recipient = User.objects.get(email__iexact=email)
        except User.DoesNotExist as error:
            raise ValidationError(
                "No user exists with this email address.", code="unknown_user"
            ) from error

        if recipient.pk == self.account.owner_id:
            raise ValidationError("The account owner already has access.", code="owner")
        if AccountShare.objects.filter(account=self.account, recipient=recipient).exists():
            raise ValidationError("This user already has access.", code="duplicate")

        self.recipient = recipient
        return recipient.email
