"""Django admin management for the currency catalog."""

from typing import Any, cast

from django import forms
from django.contrib import admin

from .models import Currency
from .validators import validate_flag_svg


class CurrencyAdminForm(forms.ModelForm):  # type: ignore[type-arg]
    """Accept SVG flags without exposing stored markup as an editable field."""

    flag_upload = forms.FileField(required=False, label="Flag SVG")
    clear_flag = forms.BooleanField(required=False, label="Clear existing flag")

    class Meta:
        model = Currency
        fields = ("code", "name", "country", "is_active")

    def clean_flag_upload(self) -> Any:
        upload = self.cleaned_data.get("flag_upload")
        if upload is None:
            return None
        validate_flag_svg(upload)
        upload.seek(0)
        return upload

    def clean(self) -> dict[str, Any]:
        cleaned_data = super().clean() or {}
        if cleaned_data.get("flag_upload") is not None and cleaned_data.get("clear_flag"):
            self.add_error("clear_flag", "Choose either a replacement flag or clear, not both.")
        return cleaned_data

    def save(self, commit: bool = True) -> Currency:
        currency = super().save(commit=False)
        upload = self.cleaned_data.get("flag_upload")
        if upload is not None:
            currency.flag_svg = validate_flag_svg(upload)
        elif self.cleaned_data.get("clear_flag"):
            currency.flag_svg = ""
        if commit:
            currency.save()
            self.save_m2m()
        return cast(Currency, currency)


@admin.register(Currency)
class CurrencyAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Manage active and retired currencies through standard model permissions."""

    form = CurrencyAdminForm
    list_display = ("code", "name", "country", "is_active", "has_flag")
    list_filter = ("is_active",)
    ordering = ("code",)
    search_fields = ("code", "name", "country")

    @admin.display(boolean=True, description="Flag")
    def has_flag(self, currency: Currency) -> bool:
        return bool(currency.flag_svg)
