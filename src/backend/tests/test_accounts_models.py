"""Persistence, form, and service tests for financial accounts."""

from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from penni_more.accounts.forms import AccountForm, AccountShareForm
from penni_more.accounts.models import Account, AccountShare
from penni_more.accounts.services import (
    AccountOwnerShareError,
    DuplicateAccountShareError,
    share_account,
)
from penni_more.users.models import User


@pytest.fixture
def owner() -> User:
    return User.objects.create_user("owner@example.com", "test-password")


@pytest.fixture
def recipient() -> User:
    return User.objects.create_user("recipient@example.com", "test-password")


@pytest.mark.django_db
def test_account_validation_requires_name_and_known_type(owner: User) -> None:
    missing_name = Account(name="", description="", account_type=Account.Type.BANK, owner=owner)
    invalid_type = Account(name="Savings", description="", account_type="cash", owner=owner)

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
        )

    assert not Account.objects.exists()


@pytest.mark.django_db
def test_account_accepts_blank_description_and_duplicate_names(owner: User) -> None:
    first = Account.objects.create(
        name="Everyday", description="", account_type=Account.Type.BANK, owner=owner
    )
    second = Account(name="Everyday", description="", account_type=Account.Type.CARD, owner=owner)

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
            "owner": owner.pk,
        }
    )

    assert tuple(form.fields) == ("name", "description", "account_type")
    assert not form.is_valid()
    assert "name" in form.errors


@pytest.mark.django_db
def test_account_owner_cannot_change_through_validation_or_save(
    owner: User, recipient: User
) -> None:
    account = Account.objects.create(
        name="Savings", description="", account_type=Account.Type.BANK, owner=owner
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
        name="Savings", description="", account_type=Account.Type.BANK, owner=owner
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
        name="Savings", description="", account_type=Account.Type.BANK, owner=owner
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
        name="Savings", description="", account_type=Account.Type.BANK, owner=owner
    )

    share_account(account, recipient)

    with pytest.raises(DuplicateAccountShareError):
        share_account(account, recipient)


@pytest.mark.django_db
def test_share_service_rejects_account_owner_without_writing(owner: User) -> None:
    account = Account.objects.create(
        name="Savings", description="", account_type=Account.Type.BANK, owner=owner
    )

    with pytest.raises(AccountOwnerShareError):
        share_account(account, owner)

    assert not AccountShare.objects.filter(account=account).exists()


@pytest.mark.django_db
def test_share_service_translates_only_losing_duplicate_integrity_error(
    owner: User, recipient: User
) -> None:
    account = Account.objects.create(
        name="Savings", description="", account_type=Account.Type.BANK, owner=owner
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
        name="Savings", description="", account_type=Account.Type.BANK, owner=owner
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
        name="Savings", description="", account_type=Account.Type.BANK, owner=owner
    )
    share = AccountShare.objects.create(account=account, recipient=recipient)

    account.delete()

    assert not AccountShare.objects.filter(pk=share.pk).exists()

    other_account = Account.objects.create(
        name="Card", description="", account_type=Account.Type.CARD, owner=owner
    )
    other_share = AccountShare.objects.create(account=other_account, recipient=recipient)
    owner.delete()

    assert not Account.objects.filter(pk=other_account.pk).exists()
    assert not AccountShare.objects.filter(pk=other_share.pk).exists()


@pytest.mark.django_db
def test_recipient_deletion_cascades_only_their_share(owner: User, recipient: User) -> None:
    account = Account.objects.create(
        name="Savings", description="", account_type=Account.Type.BANK, owner=owner
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
        name="Same", description="", account_type=Account.Type.CARD, owner=recipient
    )
    first = Account.objects.create(
        name="Same", description="", account_type=Account.Type.BANK, owner=owner
    )
    unrelated = Account.objects.create(
        name="Hidden", description="", account_type=Account.Type.BANK, owner=other
    )
    AccountShare.objects.create(account=first, recipient=recipient)

    accessible_ids = list(Account.objects.accessible_to(recipient).values_list("pk", flat=True))

    assert accessible_ids == sorted((first.pk, second.pk))
    assert unrelated.pk not in accessible_ids
