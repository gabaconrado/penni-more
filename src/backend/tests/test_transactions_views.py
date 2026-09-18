"""Request, authorization, filtering, and privacy tests for transactions."""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from penni_more.accounts.models import Account, AccountShare, Currency
from penni_more.transactions.forms import TransactionForm
from penni_more.transactions.models import Category, Transaction
from penni_more.transactions.services import delete_transaction
from penni_more.users.models import User


@pytest.fixture
def ledger() -> tuple[User, User, User, Account, Account, Category, Transaction]:
    owner = User.objects.create_user("owner@example.com", "password")
    target_owner = User.objects.create_user("target@example.com", "password")
    unrelated = User.objects.create_user("unrelated@example.com", "password")
    currency = Currency.objects.create(code="USD", name="US dollar", country="United States")
    source = Account.objects.create(
        name="Visible source",
        description="",
        account_type=Account.Type.BANK,
        owner=owner,
        currency=currency,
    )
    target = Account.objects.create(
        name="Secret target",
        description="",
        account_type=Account.Type.CARD,
        owner=target_owner,
        currency=currency,
    )
    category = Category.objects.create(name="Bills")
    item = Transaction.objects.create(
        transaction_type=Transaction.Type.TRANSFER,
        name="Card payment",
        description="private-safe row",
        category=category,
        date=timezone.now().date(),
        amount=Decimal("20.00"),
        account=source,
        target_account=target,
        additional_data={"Statement": "July"},
        created_by=owner,
    )
    return owner, target_owner, unrelated, source, target, category, item


@pytest.mark.django_db
def test_routes_redirect_anonymous_and_reject_wrong_methods(client: Client) -> None:
    urls = [
        reverse("transactions:list"),
        reverse("transactions:create"),
        reverse("transactions:import"),
        reverse("transactions:detail", args=(1,)),
    ]
    assert all(client.get(url).status_code == 302 for url in urls)


@pytest.mark.django_db
def test_transfer_visibility_masks_inaccessible_counterpart(
    client: Client, ledger: tuple[User, User, User, Account, Account, Category, Transaction]
) -> None:
    owner, target_owner, unrelated, _source, target, _category, item = ledger
    client.force_login(owner)
    response = client.get(reverse("transactions:detail", args=(item.pk,)))
    assert response.status_code == 200
    assert response.context["presentation"].target.is_private is True
    assert response.context["amount_currency_code"] == "USD"
    assert b"Private account" in response.content
    assert target.name.encode() not in response.content
    assert str(target.pk).encode() not in response.content

    client.force_login(target_owner)
    target_response = client.get(reverse("transactions:detail", args=(item.pk,)))
    assert target_response.status_code == 200
    assert target_response.context["can_edit"] is False

    client.force_login(unrelated)
    assert client.get(reverse("transactions:detail", args=(item.pk,))).status_code == 404
    assert client.post(reverse("transactions:update", args=(item.pk,))).status_code == 404


@pytest.mark.django_db
def test_private_target_edit_keep_sentinel_and_list_masking(
    client: Client, ledger: tuple[User, User, User, Account, Account, Category, Transaction]
) -> None:
    owner, target_owner, _unrelated, source, target, category, item = ledger
    client.force_login(owner)
    edit = client.get(reverse("transactions:update", args=(item.pk,)))
    target_choices = list(edit.context["form"].fields["target_account"].choices)
    assert ("__keep_private__", "Keep private account") in target_choices
    assert all(value != str(target.pk) for value, _label in target_choices)
    assert target.name.encode() not in edit.content

    kept = client.post(
        reverse("transactions:update", args=(item.pk,)),
        {
            "transaction_type": "transfer",
            "name": "Kept private",
            "description": "",
            "category": category.pk,
            "date": item.date.isoformat(),
            "amount": "20.00",
            "account": source.pk,
            "target_account": "__keep_private__",
            "additional_data": "",
        },
    )
    assert kept.status_code == 302
    item.refresh_from_db()
    assert item.target_account_id == target.pk

    client.force_login(target_owner)
    listing = client.get(reverse("transactions:list"))
    row = listing.context["page_obj"].object_list[0]
    assert row.source.is_private is True
    assert source.name.encode() not in listing.content
    assert b"Private account" in listing.content


@pytest.mark.django_db
def test_edit_source_choices_are_owned_only(
    client: Client, ledger: tuple[User, User, User, Account, Account, Category, Transaction]
) -> None:
    owner, target_owner, _unrelated, source, target, category, item = ledger
    item.transaction_type = Transaction.Type.EXPENSE
    item.target_account = None
    item.save()
    shared_source = Account.objects.create(
        name="Shared source",
        description="",
        account_type=Account.Type.BANK,
        owner=target_owner,
        currency=source.currency,
    )
    AccountShare.objects.create(account=shared_source, recipient=owner)
    client.force_login(owner)
    form_response = client.get(reverse("transactions:update", args=(item.pk,)))
    source_queryset = form_response.context["form"].fields["account"].queryset
    assert list(source_queryset) == [source]

    forged = client.post(
        reverse("transactions:update", args=(item.pk,)),
        {
            "transaction_type": "expense",
            "name": "Moved",
            "description": "",
            "category": category.pk,
            "date": item.date.isoformat(),
            "amount": "20.00",
            "account": shared_source.pk,
            "target_account": "",
            "additional_data": "",
        },
    )
    assert forged.status_code == 200
    assert "account" in forged.context["form"].errors
    item.refresh_from_db()
    assert item.account_id == source.pk


@pytest.mark.django_db
def test_create_for_shared_account_and_owner_controls_mutation(
    client: Client, ledger: tuple[User, User, User, Account, Account, Category, Transaction]
) -> None:
    owner, _target_owner, recipient, source, _target, category, _item = ledger
    AccountShare.objects.create(account=source, recipient=recipient)
    client.force_login(recipient)
    response = client.post(
        reverse("transactions:create"),
        {
            "transaction_type": "expense",
            "name": "Shared",
            "description": "",
            "category": category.pk,
            "date": "2026-09-18",
            "amount": "1.25",
            "account": source.pk,
            "target_account": "",
            "additional_data": "Statement = July",
        },
    )
    created = Transaction.objects.get(name="Shared")
    assert response.status_code == 302
    assert created.created_by == recipient
    assert client.get(reverse("transactions:update", args=(created.pk,))).status_code == 404

    client.force_login(owner)
    assert client.get(reverse("transactions:update", args=(created.pk,))).status_code == 200
    assert client.post(reverse("transactions:delete", args=(created.pk,))).status_code == 302
    assert not Transaction.objects.filter(pk=created.pk).exists()


@pytest.mark.django_db
def test_filters_are_session_backed_and_combine(
    client: Client, ledger: tuple[User, User, User, Account, Account, Category, Transaction]
) -> None:
    owner, _target_owner, _unrelated, source, _target, _category, item = ledger
    client.force_login(owner)
    response = client.post(
        reverse("transactions:filters"),
        {
            "account": source.pk,
            "month": item.date.strftime("%Y-%m"),
            "additional_key": "statement",
            "additional_value": "july",
        },
    )
    assert response.status_code == 302
    assert "statement" not in response.headers["Location"]
    listing = client.get(reverse("transactions:list"))
    assert [row.transaction.pk for row in listing.context["page_obj"].object_list] == [item.pk]
    assert listing.context["filters_active"] is True
    client.post(reverse("transactions:filters-clear"))
    assert "transactions_filters" not in client.session


@pytest.mark.django_db
def test_invalid_filter_reapplies_prior_state_or_suppresses_results(
    client: Client, ledger: tuple[User, User, User, Account, Account, Category, Transaction]
) -> None:
    owner, _target_owner, _unrelated, source, _target, _category, item = ledger
    client.force_login(owner)
    session = client.session
    session["transactions_filters"] = {
        "account": source.pk,
        "month": item.date.strftime("%Y-%m"),
        "additional_key": "",
        "additional_value": "",
    }
    session.save()
    response = client.post(
        reverse("transactions:filters"),
        {"account": source.pk, "month": "bad", "additional_key": "only-key"},
    )
    assert response.status_code == 200
    assert response.context["filters_active"] is True
    assert [row.transaction.pk for row in response.context["page_obj"].object_list] == [item.pk]
    assert b"attempted filters were not applied" in response.content
    assert b"previous validated filters remain active" in response.content

    session = client.session
    session.pop("transactions_filters", None)
    session.save()
    no_prior = client.post(
        reverse("transactions:filters"),
        {"month": "bad", "additional_key": "only-key"},
    )
    assert no_prior.context["filters_active"] is False
    assert list(no_prior.context["page_obj"].object_list) == []


@pytest.mark.django_db
def test_stale_account_filter_clears_after_share_revocation(client: Client) -> None:
    owner = User.objects.create_user("filter-owner@example.com", "password")
    recipient = User.objects.create_user("filter-recipient@example.com", "password")
    currency = Currency.objects.create(code="USD", name="US dollar", country="United States")
    shared = Account.objects.create(
        name="Formerly shared",
        description="",
        account_type=Account.Type.BANK,
        owner=owner,
        currency=currency,
    )
    share = AccountShare.objects.create(account=shared, recipient=recipient)
    client.force_login(recipient)
    session = client.session
    session["transactions_filters"] = {
        "account": shared.pk,
        "month": "",
        "additional_key": "",
        "additional_value": "",
    }
    session.save()
    share.delete()

    response = client.get(reverse("transactions:list"))

    assert response.status_code == 200
    assert response.context["filters_active"] is False
    assert client.session["transactions_filters"].get("account") is None
    assert shared.name.encode() not in response.content


@pytest.mark.django_db
def test_locked_update_and_delete_disappearance_return_404(
    client: Client, ledger: tuple[User, User, User, Account, Account, Category, Transaction]
) -> None:
    owner, _target_owner, _unrelated, source, target, category, item = ledger
    client.force_login(owner)
    AccountShare.objects.create(account=target, recipient=owner)
    update_data = {
        "transaction_type": "transfer",
        "name": "Changed",
        "description": "",
        "category": category.pk,
        "date": item.date.isoformat(),
        "amount": "20.00",
        "account": source.pk,
        "target_account": target.pk,
        "additional_data": "",
    }
    original_is_valid = TransactionForm.is_valid

    def validate_then_remove(form: TransactionForm) -> bool:
        valid = original_is_valid(form)
        Transaction.objects.filter(pk=item.pk).delete()
        return valid

    with patch.object(TransactionForm, "is_valid", validate_then_remove):
        assert (
            client.post(reverse("transactions:update", args=(item.pk,)), update_data).status_code
            == 404
        )

    replacement = Transaction.objects.create(
        transaction_type="expense",
        name="Delete race",
        description="",
        category=category,
        date=item.date,
        amount=Decimal("1.00"),
        account=source,
        additional_data={},
        created_by=owner,
    )

    def remove_then_delete(*, user: User, ledger_transaction: Transaction) -> None:
        Transaction.objects.filter(pk=ledger_transaction.pk).delete()
        delete_transaction(user=user, ledger_transaction=ledger_transaction)

    with patch("penni_more.transactions.views.delete_transaction", remove_then_delete):
        assert (
            client.post(reverse("transactions:delete", args=(replacement.pk,))).status_code == 404
        )


@pytest.mark.django_db
def test_import_confirmation_drift_omits_cached_account_data(
    client: Client, ledger: tuple[User, User, User, Account, Account, Category, Transaction]
) -> None:
    owner, _target_owner, _unrelated, source, target, category, existing = ledger
    existing.delete()
    share = AccountShare.objects.create(account=target, recipient=owner)
    client.force_login(owner)
    csv_body = (
        "type,name,description,category,date,amount,account_id,target_account_id,additional_data\n"
        f"transfer,Move,,{category.name},2026-09-18,1.00,{source.pk},{target.pk},\n"
    ).encode()
    preview = client.post(
        reverse("transactions:import"),
        {"csv_file": SimpleUploadedFile("rows.csv", csv_body, content_type="text/csv")},
    )
    assert preview.status_code == 200
    token = preview.context["preview_token"]
    share.delete()

    confirmation = client.post(reverse("transactions:import-confirm"), {"preview_token": token})

    assert confirmation.status_code == 200
    assert confirmation.context["preview_rows"] == ()
    assert target.name.encode() not in confirmation.content
    assert not Transaction.objects.exists()


@pytest.mark.django_db
def test_owner_updates_transaction_and_inactive_category_blocks_edit(
    client: Client, ledger: tuple[User, User, User, Account, Account, Category, Transaction]
) -> None:
    owner, _target_owner, _unrelated, source, target, category, item = ledger
    AccountShare.objects.create(account=target, recipient=owner)
    creator_id = item.created_by_id
    created_at = item.created_at
    client.force_login(owner)
    data = {
        "transaction_type": "transfer",
        "name": "Updated transfer",
        "description": "Changed",
        "category": category.pk,
        "date": item.date.isoformat(),
        "amount": "021.00",
        "account": source.pk,
        "target_account": target.pk,
        "additional_data": "Statement = August",
    }
    response = client.post(reverse("transactions:update", args=(item.pk,)), data)
    assert response.status_code == 302
    item.refresh_from_db()
    assert (item.name, item.amount, item.additional_data) == (
        "Updated transfer",
        Decimal("21.00"),
        {"Statement": "August"},
    )
    assert item.created_by_id == creator_id
    assert item.created_at == created_at
    assert item.updated_at >= created_at

    category.is_active = False
    category.save()
    rejected = client.post(reverse("transactions:update", args=(item.pk,)), data)
    assert rejected.status_code == 200
    assert "category" in rejected.context["form"].errors


@pytest.mark.django_db
def test_stable_pagination_future_state_and_rendered_form_error(
    client: Client, ledger: tuple[User, User, User, Account, Account, Category, Transaction]
) -> None:
    owner, _target_owner, _unrelated, source, _target, category, existing = ledger
    existing.delete()
    today = timezone.now().date()
    Transaction.objects.bulk_create(
        [
            Transaction(
                transaction_type="expense",
                name=f"Row {index:02d}",
                description="",
                category=category,
                date=today,
                amount=Decimal("1.00"),
                account=source,
                additional_data={},
                created_by=owner,
            )
            for index in range(55)
        ]
    )
    future = Transaction.objects.create(
        transaction_type="expense",
        name="Future",
        description="",
        category=category,
        date=today + timedelta(days=1),
        amount=Decimal("1.00"),
        account=source,
        additional_data={},
        created_by=owner,
    )
    client.force_login(owner)
    first = client.get(reverse("transactions:list"))
    second = client.get(reverse("transactions:list") + "?page=2")
    first_ids = [row.transaction.pk for row in first.context["page_obj"].object_list]
    second_ids = [row.transaction.pk for row in second.context["page_obj"].object_list]
    expected = list(
        Transaction.objects.order_by("-date", "-created_at", "-pk").values_list("pk", flat=True)
    )
    assert len(first_ids) == 50
    assert first_ids + second_ids == expected
    detail = client.get(reverse("transactions:detail", args=(future.pk,)))
    assert detail.context["is_future"] is True
    assert b"will not affect current balances" in detail.content

    invalid = client.post(
        reverse("transactions:create"),
        {
            "transaction_type": "income",
            "name": " ",
            "category": category.pk,
            "date": today.isoformat(),
            "amount": "1.0",
            "account": source.pk,
        },
    )
    assert invalid.status_code == 200
    assert invalid.context["form"].is_bound
    assert b"Please correct the errors below" in invalid.content


@pytest.mark.django_db
def test_transaction_mutations_enforce_csrf_and_methods(
    ledger: tuple[User, User, User, Account, Account, Category, Transaction],
) -> None:
    owner, _target_owner, _unrelated, _source, _target, _category, item = ledger
    client = Client(enforce_csrf_checks=True)
    client.force_login(owner)
    post_urls = [
        reverse("transactions:create"),
        reverse("transactions:update", args=(item.pk,)),
        reverse("transactions:delete", args=(item.pk,)),
        reverse("transactions:filters"),
        reverse("transactions:filters-clear"),
        reverse("transactions:import"),
        reverse("transactions:import-confirm"),
    ]
    assert all(client.post(url).status_code == 403 for url in post_urls)
    assert client.get(reverse("transactions:filters")).status_code == 405
    assert client.get(reverse("transactions:filters-clear")).status_code == 405
    assert client.get(reverse("transactions:import-confirm")).status_code == 405


@pytest.mark.django_db
def test_valid_import_preview_and_confirmation_endpoint_can_repeat(
    client: Client, ledger: tuple[User, User, User, Account, Account, Category, Transaction]
) -> None:
    owner, _target_owner, _unrelated, source, _target, category, existing = ledger
    existing.delete()
    client.force_login(owner)
    csv_body = (
        "type,name,description,category,date,amount,account_id,target_account_id,additional_data\n"
        f"expense,Imported,,{category.name},2026-09-18,01.00,00{source.pk},,\n"
    ).encode()
    preview = client.post(
        reverse("transactions:import"),
        {"csv_file": SimpleUploadedFile("rows.csv", csv_body, content_type="text/csv")},
    )
    assert preview.status_code == 200
    assert preview.context["preview_rows"][0]["account_id"] == source.pk
    assert source.name.encode() in preview.content
    token = preview.context["preview_token"]

    first = client.post(reverse("transactions:import-confirm"), {"preview_token": token})
    second = client.post(reverse("transactions:import-confirm"), {"preview_token": token})
    assert first.status_code == second.status_code == 302
    assert Transaction.objects.filter(name="Imported").count() == 2


@pytest.mark.django_db
def test_request_level_replaced_mismatched_and_expired_previews(
    client: Client, ledger: tuple[User, User, User, Account, Account, Category, Transaction]
) -> None:
    owner, _target_owner, _unrelated, source, _target, category, existing = ledger
    existing.delete()
    client.force_login(owner)

    def preview(name: str) -> str:
        body = (
            "type,name,description,category,date,amount,account_id,target_account_id,additional_data\n"
            f"expense,{name},,{category.name},2026-09-18,1.00,{source.pk},,\n"
        ).encode()
        response = client.post(
            reverse("transactions:import"),
            {"csv_file": SimpleUploadedFile("rows.csv", body, content_type="text/csv")},
        )
        return str(response.context["preview_token"])

    replaced = preview("First")
    active = preview("Second")
    replaced_response = client.post(
        reverse("transactions:import-confirm"), {"preview_token": replaced}
    )
    assert replaced_response.status_code == 200
    assert b"unavailable or expired" in replaced_response.content
    assert not Transaction.objects.exists()

    mismatched = client.post(
        reverse("transactions:import-confirm"), {"preview_token": "forged-token"}
    )
    assert mismatched.status_code == 200
    assert client.session["transactions_import_preview"]["token"] == active

    session = client.session
    session["transactions_import_preview"]["created_at"] -= 1801
    session.save()
    expired = client.post(reverse("transactions:import-confirm"), {"preview_token": active})
    assert expired.status_code == 200
    assert "transactions_import_preview" not in client.session


@pytest.mark.django_db
def test_account_contexts_include_balances_and_history_flags(
    client: Client, ledger: tuple[User, User, User, Account, Account, Category, Transaction]
) -> None:
    owner, _target_owner, _unrelated, source, _target, _category, _item = ledger
    client.force_login(owner)
    listing = client.get(reverse("accounts:list"))
    listed = next(item for item in listing.context["accounts"] if item.pk == source.pk)
    assert listed.current_balance == Decimal("-20.00")
    detail = client.get(reverse("accounts:detail", args=(source.pk,)))
    assert detail.context["csv_account_id"] == source.pk
    assert detail.context["account_type_locked"] is True
    assert detail.context["can_delete_account"] is False
    assert client.post(reverse("accounts:delete", args=(source.pk,))).status_code == 200
    assert Account.objects.filter(pk=source.pk).exists()
