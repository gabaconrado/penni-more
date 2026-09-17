"""Currency admin and SVG upload boundary tests."""

from typing import Any

import pytest
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile, UploadedFile
from django.test import Client
from django.urls import reverse
from django.utils.datastructures import MultiValueDict

from penni_more.accounts.admin import CurrencyAdminForm
from penni_more.accounts.models import Account, Currency
from penni_more.accounts.validators import MAX_FLAG_SVG_BYTES
from penni_more.users.models import User

VALID_SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"></svg>'


def cad() -> Currency:
    currency, _ = Currency.objects.get_or_create(
        code="CAD", defaults={"name": "Canadian dollar", "country": "Canada"}
    )
    return currency


def upload(
    content: bytes = VALID_SVG,
    *,
    name: str = "flag.svg",
    content_type: str | None = "image/svg+xml",
) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, content, content_type=content_type or "")


def uploaded_files(flag: UploadedFile) -> MultiValueDict[str, UploadedFile]:
    return MultiValueDict({"flag_upload": [flag]})


def form_data(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "code": "USD",
        "name": "US dollar",
        "country": "United States",
        "is_active": True,
    }
    data.update(overrides)
    return data


@pytest.mark.django_db
def test_currency_admin_form_add_replace_preserve_and_clear_flag() -> None:
    add_form = CurrencyAdminForm(form_data(), uploaded_files(upload()))
    assert add_form.is_valid(), add_form.errors
    currency = add_form.save()
    assert currency.flag_svg == VALID_SVG.decode()

    preserve_form = CurrencyAdminForm(form_data(name="Dollar"), instance=currency)
    assert preserve_form.is_valid(), preserve_form.errors
    preserve_form.save()
    currency.refresh_from_db()
    assert currency.flag_svg == VALID_SVG.decode()

    replacement = b'<svg xmlns="http://www.w3.org/2000/svg"><path/></svg>'
    replace_form = CurrencyAdminForm(
        form_data(), uploaded_files(upload(replacement)), instance=currency
    )
    assert replace_form.is_valid(), replace_form.errors
    replace_form.save()
    currency.refresh_from_db()
    assert currency.flag_svg == replacement.decode()

    clear_form = CurrencyAdminForm(form_data(clear_flag=True), instance=currency)
    assert clear_form.is_valid(), clear_form.errors
    clear_form.save()
    currency.refresh_from_db()
    assert currency.flag_svg == ""


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("flag", "error_code"),
    [
        (upload(name="flag.txt"), "extension"),
        (upload(content_type="text/plain"), "type"),
        (upload(b"\xff"), "encoding"),
        (
            upload(
                b"<svg\x00 xmlns='http://www.w3.org/2000/svg'/>",
            ),
            "nul",
        ),
        (
            upload(
                b"<!DOCTYPE svg><svg xmlns='http://www.w3.org/2000/svg'/>",
            ),
            "declaration",
        ),
        (
            upload(
                b"<!ENTITY x 'x'><svg xmlns='http://www.w3.org/2000/svg'/>",
            ),
            "declaration",
        ),
        (upload(b"<svg"), "xml"),
        (
            upload(
                b"<html xmlns='http://www.w3.org/2000/svg'/>",
            ),
            "root",
        ),
        (upload(b"x" * (MAX_FLAG_SVG_BYTES + 1)), "size"),
    ],
)
def test_currency_admin_form_rejects_invalid_uploads_without_writing(
    flag: SimpleUploadedFile, error_code: str
) -> None:
    form = CurrencyAdminForm(form_data(), uploaded_files(flag))

    assert not form.is_valid()
    assert form.errors.as_data()["flag_upload"][0].code == error_code
    assert not Currency.objects.filter(code="USD").exists()


@pytest.mark.django_db
def test_currency_admin_form_accepts_missing_content_type_and_rejects_clear_with_upload() -> None:
    accepted = CurrencyAdminForm(form_data(), uploaded_files(upload(content_type=None)))
    conflict = CurrencyAdminForm(form_data(clear_flag=True), uploaded_files(upload()))

    assert accepted.is_valid(), accepted.errors
    assert not conflict.is_valid()
    assert "clear_flag" in conflict.errors


@pytest.mark.django_db
def test_currency_admin_honors_model_permissions(client: Client) -> None:
    staff = User.objects.create_user("staff@example.com", "test-password", is_staff=True)
    staff.user_permissions.add(
        Permission.objects.get(content_type__app_label="accounts", codename="view_currency")
    )
    client.force_login(staff)
    currency = cad()

    changelist = client.get(reverse("admin:accounts_currency_changelist"))
    add = client.get(reverse("admin:accounts_currency_add"))
    change = client.get(reverse("admin:accounts_currency_change", args=(currency.pk,)))

    assert changelist.status_code == 200
    assert add.status_code == 403
    assert change.status_code == 200
    assert b'name="code"' not in change.content


@pytest.mark.django_db
def test_currency_admin_reports_protected_deletion(client: Client) -> None:
    admin_user = User.objects.create_superuser("admin@example.com", "test-password")
    owner = User.objects.create_user("owner@example.com", "test-password")
    currency = cad()
    account = Account.objects.create(
        name="Protected",
        description="",
        account_type=Account.Type.BANK,
        owner=owner,
        currency=currency,
    )
    client.force_login(admin_user)
    delete_url = reverse("admin:accounts_currency_delete", args=(currency.pk,))

    response = client.post(delete_url, {"post": "yes"})

    assert response.status_code == 200
    assert b"cannot delete currency" in response.content.lower()
    assert Currency.objects.filter(pk=currency.pk).exists()
    assert Account.objects.filter(pk=account.pk).exists()
