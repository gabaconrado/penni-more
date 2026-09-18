"""Persistence, form, and service tests for financial accounts."""

from threading import Event, Thread
from unittest.mock import patch

import pytest
from django import forms
from django.core.exceptions import ValidationError
from django.db import IntegrityError, close_old_connections, transaction
from django.db.models.deletion import ProtectedError

from penni_more.accounts.forms import AccountForm, AccountShareForm
from penni_more.accounts.models import Account, AccountShare, Currency
from penni_more.accounts.services import (
    AccountOwnerShareError,
    DuplicateAccountShareError,
    revoke_account_share,
    share_account,
)
from penni_more.users.models import User


def _cad() -> Currency:
    currency, _ = Currency.objects.get_or_create(
        code="CAD", defaults={"name": "Canadian dollar", "country": "Canada"}
    )
    return currency


@pytest.mark.django_db
def test_currency_normalizes_code_and_has_stable_labels() -> None:
    currency = Currency.objects.create(code=" usd ", name="US dollar", country="United States")

    assert currency.code == "USD"
    assert str(currency) == "USD — US dollar"

    currency.is_active = False
    assert str(currency) == "USD — US dollar (retired)"


@pytest.mark.django_db
def test_currency_validation_and_database_constraints() -> None:
    normalized = Currency(code=" eur ", name="Euro", country="European Union")
    normalized.full_clean()
    assert normalized.code == "EUR"

    with pytest.raises(IntegrityError), transaction.atomic():
        Currency.objects.bulk_create(
            [Currency(code="usd", name="US dollar", country="United States")]
        )
    with pytest.raises(IntegrityError), transaction.atomic():
        Currency.objects.create(code="USD", name="   ", country="United States")
    with pytest.raises(IntegrityError), transaction.atomic():
        Currency.objects.create(code="USD", name="US dollar", country="\t")


@pytest.mark.django_db
def test_currency_code_is_unique_after_normalization() -> None:
    Currency.objects.create(code="USD", name="US dollar", country="United States")

    with pytest.raises(IntegrityError), transaction.atomic():
        Currency.objects.create(code=" usd ", name="Another", country="Elsewhere")


@pytest.mark.django_db
def test_account_requires_currency_and_protects_referenced_currency(owner: User) -> None:
    with pytest.raises(IntegrityError), transaction.atomic():
        Account.objects.create(
            name="Missing currency",
            description="",
            account_type=Account.Type.BANK,
            owner=owner,
        )

    referenced = Currency.objects.create(code="USD", name="US dollar", country="United States")
    account = Account.objects.create(
        name="Dollar account",
        description="",
        account_type=Account.Type.BANK,
        owner=owner,
        currency=referenced,
    )
    with pytest.raises(ProtectedError):
        referenced.delete()
    assert Account.objects.filter(pk=account.pk, currency=referenced).exists()

    unreferenced = Currency.objects.create(code="EUR", name="Euro", country="European Union")
    unreferenced.delete()
    assert not Currency.objects.filter(pk=unreferenced.pk).exists()


@pytest.mark.django_db
def test_account_form_currency_policy_for_create_and_edit(owner: User) -> None:
    Currency.objects.get_or_create(
        code="BRL", defaults={"name": "Brazilian real", "country": "Brazil"}
    )
    active = Currency.objects.create(code="USD", name="US dollar", country="United States")
    current_retired = Currency.objects.create(
        code="EUR", name="Euro", country="European Union", is_active=False
    )
    other_retired = Currency.objects.create(
        code="GBP", name="Pound sterling", country="United Kingdom", is_active=False
    )
    account = Account.objects.create(
        name="European",
        description="",
        account_type=Account.Type.BANK,
        owner=owner,
        currency=current_retired,
    )

    create_field = AccountForm().fields["currency"]
    edit_field = AccountForm(instance=account).fields["currency"]
    assert isinstance(create_field, forms.ModelChoiceField)
    assert isinstance(edit_field, forms.ModelChoiceField)
    assert create_field.queryset is not None
    assert edit_field.queryset is not None
    create_ids = list(create_field.queryset.values_list("pk", flat=True))
    edit_codes = list(edit_field.queryset.values_list("code", flat=True))

    assert active.pk in create_ids
    assert current_retired.pk not in create_ids
    assert edit_codes == ["BRL", "CAD", "EUR", "USD"]
    assert current_retired.code in edit_codes
    assert other_retired.code not in edit_codes

    retained = AccountForm(
        {
            "name": account.name,
            "description": "",
            "account_type": account.account_type,
            "currency": current_retired.pk,
        },
        instance=account,
    )
    replacement = AccountForm(
        {
            "name": account.name,
            "description": "",
            "account_type": account.account_type,
            "currency": active.pk,
        },
        instance=account,
    )
    tampered = AccountForm(
        {
            "name": account.name,
            "description": "",
            "account_type": account.account_type,
            "currency": other_retired.pk,
        },
        instance=account,
    )

    assert retained.is_valid()
    assert replacement.is_valid()
    assert not tampered.is_valid()
    assert "currency" in tampered.errors


@pytest.mark.django_db
def test_account_form_rejects_currency_retired_before_post(owner: User) -> None:
    currency = Currency.objects.create(code="USD", name="US dollar", country="United States")
    displayed = AccountForm()
    displayed_field = displayed.fields["currency"]
    assert isinstance(displayed_field, forms.ModelChoiceField)
    assert displayed_field.queryset is not None
    assert currency in displayed_field.queryset

    currency.is_active = False
    currency.save(update_fields=("is_active",))
    submitted = AccountForm(
        {
            "name": "Dollar",
            "description": "",
            "account_type": Account.Type.BANK,
            "currency": currency.pk,
        }
    )

    assert not submitted.is_valid()
    assert "currency" in submitted.errors


@pytest.fixture
def owner() -> User:
    return User.objects.create_user("owner@example.com", "test-password")


@pytest.fixture
def recipient() -> User:
    return User.objects.create_user("recipient@example.com", "test-password")


@pytest.mark.django_db
def test_account_validation_requires_name_and_known_type(owner: User) -> None:
    missing_name = Account(
        name="", description="", account_type=Account.Type.BANK, owner=owner, currency=_cad()
    )
    invalid_type = Account(
        name="Savings", description="", account_type="cash", owner=owner, currency=_cad()
    )

    with pytest.raises(ValidationError) as missing_name_error:
        missing_name.full_clean()
    with pytest.raises(ValidationError) as invalid_type_error:
        invalid_type.full_clean()

    assert "name" in missing_name_error.value.message_dict
    assert "account_type" in invalid_type_error.value.message_dict


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("name", "account_type"),
    [
        ("", Account.Type.BANK),
        ("   \t", Account.Type.BANK),
        ("Savings", "cash"),
    ],
)
def test_database_rejects_blank_names_and_unknown_types(
    owner: User, name: str, account_type: str
) -> None:
    with pytest.raises(IntegrityError), transaction.atomic():
        Account.objects.create(
            name=name,
            description="",
            account_type=account_type,
            owner=owner,
            currency=_cad(),
        )

    assert not Account.objects.exists()


@pytest.mark.django_db
def test_account_accepts_blank_description_and_duplicate_names(owner: User) -> None:
    first = Account.objects.create(
        name="Everyday",
        description="",
        account_type=Account.Type.BANK,
        owner=owner,
        currency=_cad(),
    )
    second = Account(
        name="Everyday",
        description="",
        account_type=Account.Type.CARD,
        owner=owner,
        currency=_cad(),
    )

    second.full_clean()
    second.save()

    assert first.name == second.name
    assert Account.objects.filter(name="Everyday").count() == 2


@pytest.mark.django_db
def test_account_form_exposes_only_editable_information_and_rejects_whitespace_name(
    owner: User,
) -> None:
    form = AccountForm(
        {
            "name": "   ",
            "description": "Optional",
            "account_type": Account.Type.BANK,
            "currency": _cad().pk,
            "owner": owner.pk,
        }
    )

    assert tuple(form.fields) == ("name", "description", "account_type", "currency")
    assert not form.is_valid()
    assert "name" in form.errors


@pytest.mark.django_db
def test_account_owner_cannot_change_through_validation_or_save(
    owner: User, recipient: User
) -> None:
    account = Account.objects.create(
        name="Savings",
        description="",
        account_type=Account.Type.BANK,
        owner=owner,
        currency=_cad(),
    )
    account.owner = recipient

    with pytest.raises(ValidationError, match="owner cannot be changed"):
        account.full_clean()
    with pytest.raises(ValidationError, match="owner cannot be changed"):
        account.save()

    account.refresh_from_db()
    assert account.owner == owner


@pytest.mark.django_db
def test_share_validation_rejects_owner_and_database_rejects_duplicate(
    owner: User, recipient: User
) -> None:
    account = Account.objects.create(
        name="Savings",
        description="",
        account_type=Account.Type.BANK,
        owner=owner,
        currency=_cad(),
    )
    self_share = AccountShare(account=account, recipient=owner)

    with pytest.raises(ValidationError, match="owner already has access"):
        self_share.full_clean()

    AccountShare.objects.create(account=account, recipient=recipient)
    with pytest.raises(IntegrityError), transaction.atomic():
        AccountShare.objects.create(account=account, recipient=recipient)


@pytest.mark.django_db
def test_share_form_resolves_case_insensitively_and_distinguishes_failures(
    owner: User, recipient: User
) -> None:
    account = Account.objects.create(
        name="Savings",
        description="",
        account_type=Account.Type.BANK,
        owner=owner,
        currency=_cad(),
    )

    valid = AccountShareForm({"email": "RECIPIENT@EXAMPLE.COM"}, account=account)
    unknown = AccountShareForm({"email": "missing@example.com"}, account=account)
    self_share = AccountShareForm({"email": "OWNER@EXAMPLE.COM"}, account=account)

    assert valid.is_valid()
    assert valid.recipient == recipient
    assert valid.cleaned_data["email"] == recipient.email
    assert not unknown.is_valid()
    assert unknown.errors.as_data()["email"][0].code == "unknown_user"
    assert not self_share.is_valid()
    assert self_share.errors.as_data()["email"][0].code == "owner"

    AccountShare.objects.create(account=account, recipient=recipient)
    duplicate = AccountShareForm({"email": recipient.email}, account=account)
    assert not duplicate.is_valid()
    assert duplicate.errors.as_data()["email"][0].code == "duplicate"


@pytest.mark.django_db
def test_share_service_translates_duplicate_into_domain_error(owner: User, recipient: User) -> None:
    account = Account.objects.create(
        name="Savings",
        description="",
        account_type=Account.Type.BANK,
        owner=owner,
        currency=_cad(),
    )

    share_account(account, recipient)

    with pytest.raises(DuplicateAccountShareError):
        share_account(account, recipient)


@pytest.mark.django_db
def test_share_service_rejects_account_owner_without_writing(owner: User) -> None:
    account = Account.objects.create(
        name="Savings",
        description="",
        account_type=Account.Type.BANK,
        owner=owner,
        currency=_cad(),
    )

    with pytest.raises(AccountOwnerShareError):
        share_account(account, owner)

    assert not AccountShare.objects.filter(account=account).exists()


@pytest.mark.django_db(transaction=True)
def test_share_revocation_uses_account_lock_protocol(owner: User, recipient: User) -> None:
    account = Account.objects.create(
        name="Shared bank",
        description="",
        account_type=Account.Type.BANK,
        owner=owner,
        currency=_cad(),
    )
    share = AccountShare.objects.create(account=account, recipient=recipient)
    started = Event()
    finished = Event()
    errors: list[Exception] = []

    def revoke_in_other_connection() -> None:
        close_old_connections()
        started.set()
        try:
            revoke_account_share(Account.objects.get(pk=account.pk), share.pk)
        except Exception as error:  # pragma: no cover - asserted below
            errors.append(error)
        finally:
            close_old_connections()
            finished.set()

    worker = Thread(target=revoke_in_other_connection)
    with transaction.atomic():
        Account.objects.select_for_update().get(pk=account.pk)
        worker.start()
        assert started.wait(timeout=2)
        assert not finished.wait(timeout=0.2)
    worker.join(timeout=2)

    assert finished.is_set()
    assert errors == []
    assert not AccountShare.objects.filter(pk=share.pk).exists()


@pytest.mark.django_db
def test_share_service_translates_only_losing_duplicate_integrity_error(
    owner: User, recipient: User
) -> None:
    account = Account.objects.create(
        name="Savings",
        description="",
        account_type=Account.Type.BANK,
        owner=owner,
        currency=_cad(),
    )
    AccountShare.objects.create(account=account, recipient=recipient)

    with (
        patch.object(
            AccountShare.objects,
            "get_or_create",
            side_effect=IntegrityError("simulated concurrent duplicate"),
        ),
        pytest.raises(DuplicateAccountShareError),
    ):
        share_account(account, recipient)


@pytest.mark.django_db
def test_share_service_reraises_unrelated_integrity_error(owner: User, recipient: User) -> None:
    account = Account.objects.create(
        name="Savings",
        description="",
        account_type=Account.Type.BANK,
        owner=owner,
        currency=_cad(),
    )

    with (
        patch.object(
            AccountShare.objects,
            "get_or_create",
            side_effect=IntegrityError("simulated unrelated constraint"),
        ),
        pytest.raises(IntegrityError, match="unrelated constraint"),
    ):
        share_account(account, recipient)

    assert not AccountShare.objects.filter(account=account, recipient=recipient).exists()


@pytest.mark.django_db
def test_owner_and_account_deletion_cascade_owned_data(owner: User, recipient: User) -> None:
    account = Account.objects.create(
        name="Savings",
        description="",
        account_type=Account.Type.BANK,
        owner=owner,
        currency=_cad(),
    )
    share = AccountShare.objects.create(account=account, recipient=recipient)

    account.delete()

    assert not AccountShare.objects.filter(pk=share.pk).exists()

    other_account = Account.objects.create(
        name="Card",
        description="",
        account_type=Account.Type.CARD,
        owner=owner,
        currency=_cad(),
    )
    other_share = AccountShare.objects.create(account=other_account, recipient=recipient)
    owner.delete()

    assert not Account.objects.filter(pk=other_account.pk).exists()
    assert not AccountShare.objects.filter(pk=other_share.pk).exists()


@pytest.mark.django_db
def test_recipient_deletion_cascades_only_their_share(owner: User, recipient: User) -> None:
    account = Account.objects.create(
        name="Savings",
        description="",
        account_type=Account.Type.BANK,
        owner=owner,
        currency=_cad(),
    )
    share = AccountShare.objects.create(account=account, recipient=recipient)

    recipient.delete()

    assert Account.objects.filter(pk=account.pk).exists()
    assert not AccountShare.objects.filter(pk=share.pk).exists()


@pytest.mark.django_db
def test_accessible_accounts_are_distinct_filtered_and_deterministically_ordered(
    owner: User, recipient: User
) -> None:
    other = User.objects.create_user("other@example.com", "test-password")
    second = Account.objects.create(
        name="Same",
        description="",
        account_type=Account.Type.CARD,
        owner=recipient,
        currency=_cad(),
    )
    first = Account.objects.create(
        name="Same",
        description="",
        account_type=Account.Type.BANK,
        owner=owner,
        currency=_cad(),
    )
    unrelated = Account.objects.create(
        name="Hidden",
        description="",
        account_type=Account.Type.BANK,
        owner=other,
        currency=_cad(),
    )
    AccountShare.objects.create(account=first, recipient=recipient)

    accessible_ids = list(Account.objects.accessible_to(recipient).values_list("pk", flat=True))

    assert accessible_ids == sorted((first.pk, second.pk))
    assert unrelated.pk not in accessible_ids
