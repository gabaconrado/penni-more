"""Request and authorization tests for account management."""

import hashlib
from typing import Any
from unittest.mock import patch

import pytest
from django.contrib.messages import get_messages
from django.test import Client
from django.urls import reverse

from penni_more.accounts.forms import AccountForm
from penni_more.accounts.models import Account, AccountShare, Currency
from penni_more.users.models import User


def _cad() -> Currency:
    currency, _ = Currency.objects.get_or_create(
        code="CAD", defaults={"name": "Canadian dollar", "country": "Canada"}
    )
    return currency


@pytest.fixture
def owner() -> User:
    return User.objects.create_user("owner@example.com", "test-password")


@pytest.fixture
def recipient() -> User:
    return User.objects.create_user("recipient@example.com", "test-password")


@pytest.fixture
def unrelated() -> User:
    return User.objects.create_user("unrelated@example.com", "test-password")


@pytest.fixture
def account(owner: User) -> Account:
    return Account.objects.create(
        name="Everyday account",
        description="Household spending",
        account_type=Account.Type.BANK,
        owner=owner,
        currency=_cad(),
    )


def login(client: Client, user: User) -> None:
    client.force_login(user)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "url",
    [
        reverse("accounts:list"),
        reverse("accounts:create"),
        reverse("accounts:detail", args=(1,)),
        reverse("accounts:update", args=(1,)),
        reverse("accounts:delete", args=(1,)),
        reverse("accounts:share", args=(1,)),
        reverse("accounts:revoke", args=(1, 1)),
        reverse("accounts:currency-flag", args=(1,)),
    ],
)
def test_every_account_route_redirects_anonymous_users(client: Client, url: str) -> None:
    response = client.get(url)

    assert response.status_code == 302
    assert response.headers["Location"] == f"{reverse('login')}?next={url}"


@pytest.mark.django_db
def test_list_contains_only_owned_and_shared_accounts_once(
    client: Client, owner: User, recipient: User, unrelated: User
) -> None:
    owned = Account.objects.create(
        name="Owned",
        description="",
        account_type=Account.Type.BANK,
        owner=recipient,
        currency=_cad(),
    )
    shared = Account.objects.create(
        name="Shared",
        description="",
        account_type=Account.Type.CARD,
        owner=owner,
        currency=_cad(),
    )
    hidden = Account.objects.create(
        name="Hidden",
        description="",
        account_type=Account.Type.BANK,
        owner=unrelated,
        currency=_cad(),
    )
    AccountShare.objects.create(account=shared, recipient=recipient)
    login(client, recipient)

    response = client.get(reverse("accounts:list"))

    assert response.status_code == 200
    assert list(response.context["accounts"]) == [owned, shared]
    assert hidden not in response.context["accounts"]


@pytest.mark.django_db
def test_create_assigns_request_user_and_ignores_submitted_owner(
    client: Client, owner: User, unrelated: User
) -> None:
    login(client, owner)

    response = client.post(
        reverse("accounts:create"),
        {
            "name": "Travel card",
            "description": "Trips",
            "account_type": Account.Type.CARD,
            "currency": _cad().pk,
            "owner": unrelated.pk,
        },
    )

    account = Account.objects.get(name="Travel card")
    assert account.owner == owner
    assert response.status_code == 302
    assert response.headers["Location"] == reverse("accounts:detail", args=(account.pk,))
    assert [str(message) for message in get_messages(response.wsgi_request)] == ["Account created."]


@pytest.mark.django_db
def test_invalid_create_renders_bound_errors_without_persisting(
    client: Client, owner: User
) -> None:
    login(client, owner)

    response = client.post(
        reverse("accounts:create"),
        {
            "name": "   ",
            "description": "Kept",
            "account_type": "cash",
            "currency": _cad().pk,
        },
    )

    assert response.status_code == 200
    assert response.context["form"].is_bound
    assert set(response.context["form"].errors) == {"name", "account_type"}
    assert not Account.objects.exists()


@pytest.mark.django_db
def test_detail_context_is_private_to_owner(
    client: Client, account: Account, owner: User, recipient: User
) -> None:
    share = AccountShare.objects.create(account=account, recipient=recipient)
    login(client, owner)

    owner_response = client.get(reverse("accounts:detail", args=(account.pk,)))

    assert owner_response.status_code == 200
    assert owner_response.context["is_owner"] is True
    assert list(owner_response.context["shares"]) == [share]
    assert "share_form" in owner_response.context

    login(client, recipient)
    recipient_response = client.get(reverse("accounts:detail", args=(account.pk,)))

    assert recipient_response.status_code == 200
    assert recipient_response.context["is_owner"] is False
    assert "shares" not in recipient_response.context
    assert "share_form" not in recipient_response.context


@pytest.mark.django_db
def test_recipient_html_never_exposes_other_recipients(
    client: Client, account: Account, recipient: User
) -> None:
    other_recipient = User.objects.create_user("private-recipient@example.com", "test-password")
    AccountShare.objects.create(account=account, recipient=recipient)
    AccountShare.objects.create(account=account, recipient=other_recipient)
    login(client, recipient)

    response = client.get(reverse("accounts:detail", args=(account.pk,)))

    assert response.status_code == 200
    assert other_recipient.email.encode() not in response.content


@pytest.mark.django_db
def test_rendered_account_and_email_content_is_escaped(client: Client) -> None:
    unsafe_email = "owner+<unsafe>@example.com"
    unsafe_name = "<script>alert('account')</script>"
    unsafe_description = '"><img src=x onerror=alert(1)>'
    owner = User.objects.create_user(unsafe_email, "test-password")
    account = Account.objects.create(
        name=unsafe_name,
        description=unsafe_description,
        account_type=Account.Type.BANK,
        owner=owner,
        currency=_cad(),
    )
    login(client, owner)

    list_response = client.get(reverse("accounts:list"))
    detail_response = client.get(reverse("accounts:detail", args=(account.pk,)))

    for response in (list_response, detail_response):
        assert response.status_code == 200
        assert unsafe_name.encode() not in response.content
        assert unsafe_description.encode() not in response.content
        assert b"&lt;script&gt;alert(&#x27;account&#x27;)&lt;/script&gt;" in response.content
        assert b"&quot;&gt;&lt;img src=x onerror=alert(1)&gt;" in response.content
    assert unsafe_email.encode() not in detail_response.content
    assert b"owner+&lt;unsafe&gt;@example.com" in detail_response.content


@pytest.mark.django_db
def test_list_queries_are_bounded_with_multiple_accounts(
    client: Client,
    owner: User,
    recipient: User,
    django_assert_num_queries: Any,
) -> None:
    for index in range(4):
        account = Account.objects.create(
            name=f"Account {index}",
            description="",
            account_type=Account.Type.BANK,
            owner=owner,
            currency=_cad(),
        )
        AccountShare.objects.create(account=account, recipient=recipient)
    login(client, recipient)

    with django_assert_num_queries(3):
        response = client.get(reverse("accounts:list"))

    assert response.status_code == 200


@pytest.mark.django_db
def test_owner_detail_queries_are_bounded_with_multiple_shares(
    client: Client,
    account: Account,
    owner: User,
    django_assert_num_queries: Any,
) -> None:
    for index in range(4):
        recipient = User.objects.create_user(f"recipient-{index}@example.com", "test-password")
        AccountShare.objects.create(account=account, recipient=recipient)
    login(client, owner)

    with django_assert_num_queries(4):
        response = client.get(reverse("accounts:detail", args=(account.pk,)))

    assert response.status_code == 200


@pytest.mark.django_db
def test_unrelated_user_cannot_view_detail(
    client: Client, account: Account, unrelated: User
) -> None:
    login(client, unrelated)

    response = client.get(reverse("accounts:detail", args=(account.pk,)))

    assert response.status_code == 404


@pytest.mark.django_db
@pytest.mark.parametrize("route_name", ["update", "delete", "share"])
@pytest.mark.parametrize("access", ["recipient", "unrelated"])
def test_non_owner_cannot_reach_owner_routes(
    client: Client,
    account: Account,
    recipient: User,
    unrelated: User,
    route_name: str,
    access: str,
) -> None:
    if access == "recipient":
        AccountShare.objects.create(account=account, recipient=recipient)
    login(client, recipient if access == "recipient" else unrelated)
    url = reverse(f"accounts:{route_name}", args=(account.pk,))

    response = client.post(url)

    assert response.status_code == 404


@pytest.mark.django_db
def test_update_changes_only_account_information(
    client: Client, account: Account, owner: User
) -> None:
    login(client, owner)

    response = client.post(
        reverse("accounts:update", args=(account.pk,)),
        {
            "name": "Renamed",
            "description": "Changed",
            "account_type": Account.Type.CARD,
            "currency": _cad().pk,
        },
    )

    account.refresh_from_db()
    assert (account.name, account.description, account.account_type, account.owner) == (
        "Renamed",
        "Changed",
        Account.Type.CARD,
        owner,
    )
    assert response.status_code == 302
    assert response.headers["Location"] == reverse("accounts:detail", args=(account.pk,))


@pytest.mark.django_db
def test_update_allows_current_retired_currency_but_rejects_another(
    client: Client, account: Account, owner: User
) -> None:
    current = account.currency
    current.is_active = False
    current.save(update_fields=("is_active",))
    other = Currency.objects.create(
        code="USD", name="US dollar", country="United States", is_active=False
    )
    login(client, owner)
    url = reverse("accounts:update", args=(account.pk,))
    data = {
        "name": account.name,
        "description": account.description,
        "account_type": account.account_type,
        "currency": current.pk,
    }

    retained = client.post(url, data)
    rejected = client.post(url, {**data, "currency": other.pk})

    assert retained.status_code == 302
    assert rejected.status_code == 200
    assert "currency" in rejected.context["form"].errors
    account.refresh_from_db()
    assert account.currency == current


@pytest.mark.django_db
def test_update_rechecks_replacement_retired_after_form_validation(
    client: Client, account: Account, owner: User
) -> None:
    original_currency = account.currency
    replacement = Currency.objects.create(code="USD", name="US dollar", country="United States")
    login(client, owner)
    original_is_valid = AccountForm.is_valid

    def validate_then_retire(form: AccountForm) -> bool:
        is_valid = original_is_valid(form)
        assert is_valid
        Currency.objects.filter(pk=replacement.pk).update(is_active=False)
        return is_valid

    with patch.object(AccountForm, "is_valid", validate_then_retire):
        response = client.post(
            reverse("accounts:update", args=(account.pk,)),
            {
                "name": "Should not persist",
                "description": account.description,
                "account_type": account.account_type,
                "currency": replacement.pk,
            },
        )

    assert response.status_code == 200
    assert "currency" in response.context["form"].errors
    account.refresh_from_db()
    assert account.name == "Everyday account"
    assert account.currency == original_currency


@pytest.mark.django_db
def test_create_rejects_retired_currency(client: Client, owner: User) -> None:
    retired = Currency.objects.create(
        code="USD", name="US dollar", country="United States", is_active=False
    )
    login(client, owner)

    response = client.post(
        reverse("accounts:create"),
        {
            "name": "Dollar",
            "description": "",
            "account_type": Account.Type.BANK,
            "currency": retired.pk,
        },
    )

    assert response.status_code == 200
    assert "currency" in response.context["form"].errors
    assert not Account.objects.filter(name="Dollar").exists()


@pytest.mark.django_db
def test_create_rechecks_currency_retired_after_form_validation(
    client: Client, owner: User
) -> None:
    currency = Currency.objects.create(code="USD", name="US dollar", country="United States")
    login(client, owner)
    original_is_valid = AccountForm.is_valid

    def validate_then_retire(form: AccountForm) -> bool:
        is_valid = original_is_valid(form)
        assert is_valid
        Currency.objects.filter(pk=currency.pk).update(is_active=False)
        return is_valid

    with patch.object(AccountForm, "is_valid", validate_then_retire):
        response = client.post(
            reverse("accounts:create"),
            {
                "name": "Raced retirement",
                "description": "",
                "account_type": Account.Type.BANK,
                "currency": currency.pk,
            },
        )

    assert response.status_code == 200
    assert "currency" in response.context["form"].errors
    assert not Account.objects.filter(name="Raced retirement").exists()


@pytest.mark.django_db
def test_currency_flag_returns_contained_svg_with_deterministic_headers(
    client: Client, owner: User
) -> None:
    currency = Currency.objects.get(code="CAD")
    login(client, owner)

    response = client.get(reverse("accounts:currency-flag", args=(currency.pk,)))
    body = currency.flag_svg.encode()

    assert response.status_code == 200
    assert response.content == body
    assert response.headers["Content-Type"] == "image/svg+xml; charset=utf-8"
    assert response.headers["Content-Disposition"] == 'inline; filename="CAD-flag.svg"'
    assert response.headers["Content-Security-Policy"] == "default-src 'none'; sandbox"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Cross-Origin-Resource-Policy"] == "same-origin"
    assert response.headers["Cache-Control"] == "private, max-age=300"
    assert response.headers["ETag"] == f'"{hashlib.sha256(body).hexdigest()}"'


@pytest.mark.django_db
def test_currency_flag_returns_404_for_unknown_or_empty_and_rejects_post(
    client: Client, owner: User
) -> None:
    empty = Currency.objects.create(code="USD", name="US dollar", country="United States")
    login(client, owner)

    missing = client.get(reverse("accounts:currency-flag", args=(999999,)))
    empty_response = client.get(reverse("accounts:currency-flag", args=(empty.pk,)))
    post = client.post(reverse("accounts:currency-flag", args=(empty.pk,)))

    assert missing.status_code == 404
    assert empty_response.status_code == 404
    assert post.status_code == 405


@pytest.mark.django_db
def test_stored_svg_is_not_inserted_inline_in_account_html(
    client: Client, account: Account, owner: User
) -> None:
    login(client, owner)

    responses = [
        client.get(reverse("accounts:list")),
        client.get(reverse("accounts:detail", args=(account.pk,))),
        client.get(reverse("accounts:update", args=(account.pk,))),
    ]

    assert all(response.status_code == 200 for response in responses)
    assert all(account.currency.flag_svg.encode() not in response.content for response in responses)


@pytest.mark.django_db
def test_delete_get_confirms_and_post_cascades_shares(
    client: Client, account: Account, owner: User, recipient: User
) -> None:
    share = AccountShare.objects.create(account=account, recipient=recipient)
    login(client, owner)
    url = reverse("accounts:delete", args=(account.pk,))

    get_response = client.get(url)

    assert get_response.status_code == 200
    assert get_response.context["account"] == account
    assert Account.objects.filter(pk=account.pk).exists()

    post_response = client.post(url)

    assert post_response.status_code == 302
    assert post_response.headers["Location"] == reverse("accounts:list")
    assert not Account.objects.filter(pk=account.pk).exists()
    assert not AccountShare.objects.filter(pk=share.pk).exists()


@pytest.mark.django_db
def test_share_success_and_validation_errors(
    client: Client, account: Account, owner: User, recipient: User
) -> None:
    login(client, owner)
    url = reverse("accounts:share", args=(account.pk,))

    unknown_response = client.post(url, {"email": "missing@example.com"})

    assert unknown_response.status_code == 200
    assert unknown_response.context["share_form"].data["email"] == "missing@example.com"
    assert "No user exists" in unknown_response.context["share_form"].errors["email"][0]

    self_response = client.post(url, {"email": owner.email})

    assert self_response.status_code == 200
    assert "owner already has access" in self_response.context["share_form"].errors["email"][0]

    success_response = client.post(url, {"email": recipient.email.upper()})

    assert success_response.status_code == 302
    assert success_response.headers["Location"] == reverse("accounts:detail", args=(account.pk,))
    assert AccountShare.objects.filter(account=account, recipient=recipient).exists()

    duplicate_response = client.post(url, {"email": recipient.email})

    assert duplicate_response.status_code == 200
    assert "already has access" in duplicate_response.context["share_form"].errors["email"][0]
    assert AccountShare.objects.filter(account=account, recipient=recipient).count() == 1


@pytest.mark.django_db
def test_revoke_requires_matching_nested_share_and_owner(
    client: Client, account: Account, owner: User, recipient: User
) -> None:
    other_account = Account.objects.create(
        name="Other",
        description="",
        account_type=Account.Type.CARD,
        owner=owner,
        currency=_cad(),
    )
    share = AccountShare.objects.create(account=other_account, recipient=recipient)
    login(client, owner)

    mismatch_response = client.post(reverse("accounts:revoke", args=(account.pk, share.pk)))

    assert mismatch_response.status_code == 404
    assert AccountShare.objects.filter(pk=share.pk).exists()

    response = client.post(reverse("accounts:revoke", args=(other_account.pk, share.pk)))

    assert response.status_code == 302
    assert response.headers["Location"] == reverse("accounts:detail", args=(other_account.pk,))
    assert not AccountShare.objects.filter(pk=share.pk).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("access", ["recipient", "unrelated"])
def test_non_owner_cannot_revoke_share(
    client: Client,
    account: Account,
    recipient: User,
    unrelated: User,
    access: str,
) -> None:
    share = AccountShare.objects.create(account=account, recipient=recipient)
    login(client, recipient if access == "recipient" else unrelated)

    response = client.post(reverse("accounts:revoke", args=(account.pk, share.pk)))

    assert response.status_code == 404
    assert AccountShare.objects.filter(pk=share.pk).exists()


@pytest.mark.django_db
def test_state_changes_reject_unsupported_methods(
    client: Client, account: Account, owner: User, recipient: User
) -> None:
    share = AccountShare.objects.create(account=account, recipient=recipient)
    login(client, owner)

    share_response = client.get(reverse("accounts:share", args=(account.pk,)))
    revoke_response = client.get(reverse("accounts:revoke", args=(account.pk, share.pk)))
    list_post_response = client.post(reverse("accounts:list"))

    assert share_response.status_code == 405
    assert revoke_response.status_code == 405
    assert list_post_response.status_code == 405
    assert AccountShare.objects.filter(pk=share.pk).exists()


@pytest.mark.django_db
def test_mutations_enforce_csrf(account: Account, owner: User, recipient: User) -> None:
    csrf_client = Client(enforce_csrf_checks=True)
    login(csrf_client, owner)
    share = AccountShare.objects.create(account=account, recipient=recipient)
    urls = [
        reverse("accounts:create"),
        reverse("accounts:update", args=(account.pk,)),
        reverse("accounts:delete", args=(account.pk,)),
        reverse("accounts:share", args=(account.pk,)),
        reverse("accounts:revoke", args=(account.pk, share.pk)),
    ]

    responses = [csrf_client.post(url) for url in urls]

    assert [response.status_code for response in responses] == [403, 403, 403, 403, 403]
    assert Account.objects.filter(pk=account.pk).exists()
    assert AccountShare.objects.filter(pk=share.pk).exists()
