"""Forms for application authentication and admin user management."""

from typing import Any

from django import forms
from django.contrib.auth.forms import (
    AuthenticationForm,
    UserChangeForm,
    UserCreationForm,
)
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from .managers import normalize_email_address
from .models import User


class EmailAuthenticationForm(AuthenticationForm):
    """Present Django session authentication as email and password only."""

    username = forms.EmailField(
        label=_("Email"),
        widget=forms.EmailInput(attrs={"autocomplete": "email"}),
    )
    password = forms.CharField(
        label=_("Password"),
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )

    error_messages = {
        "invalid_login": _("Please enter a correct email address and password."),
        "inactive": _("Please enter a correct email address and password."),
    }


class CanonicalEmailFormMixin:
    """Normalize email and report case-insensitive duplicates as form errors."""

    instance: User
    cleaned_data: dict[str, Any]

    def clean_email(self) -> str:
        """Return a canonical email if no other user owns it."""
        email = normalize_email_address(str(self.cleaned_data.get("email", "")))
        duplicate = User.objects.filter(email__iexact=email)
        if self.instance.pk:
            duplicate = duplicate.exclude(pk=self.instance.pk)
        if duplicate.exists():
            raise ValidationError(
                _("A user with that email address already exists."),
                code="duplicate_email",
            )
        return email


class AdminUserCreationForm(CanonicalEmailFormMixin, UserCreationForm):  # type: ignore[type-arg]
    """Create users in admin without a username field."""

    class Meta:
        model = User
        fields = ("email",)


class AdminUserChangeForm(CanonicalEmailFormMixin, UserChangeForm):  # type: ignore[type-arg]
    """Change users in admin without a username field."""

    class Meta:
        model = User
        fields = "__all__"
