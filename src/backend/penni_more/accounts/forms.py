"""Validated HTML form boundaries for account operations."""

from typing import Any

from django import forms
from django.core.exceptions import ValidationError

from penni_more.users.models import User

from .models import Account, AccountShare


class AccountForm(forms.ModelForm):  # type: ignore[type-arg]
    """Create or edit owner-controlled account information."""

    class Meta:
        model = Account
        fields = ("name", "description", "account_type")


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
