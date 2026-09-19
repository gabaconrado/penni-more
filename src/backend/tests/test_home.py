"""Request tests for the server-rendered application shell."""

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.test import Client
from django.test.client import RequestFactory
from django.urls import reverse

from penni_more.accounts.models import Account, AccountShare, Currency
from penni_more.context_processors import release_version
from penni_more.transactions.models import Category, Transaction
from penni_more.users.models import User


def test_release_version_context_contains_only_public_label() -> None:
    context = release_version(RequestFactory().get("/"))

    assert context == {"penni_more_version": "dev"}


def test_home_redirects_anonymous_user_to_login(client: Client) -> None:
    response = client.get("/")

    assert response.status_code == 302
    assert response.headers["Location"] == f"{reverse('login')}?next=/"


@pytest.mark.django_db
def test_home_renders_web_template_for_authenticated_user(client: Client) -> None:
    user = User.objects.create_user("person+<unsafe>@example.com", "test-password")
    client.force_login(user)

    response = client.get("/")

    assert response.status_code == 200
    assert b"<!doctype html>" in response.content.lower()
    assert b"Signed in as" in response.content
    assert b"person+&lt;unsafe&gt;@example.com" in response.content
    assert b"person+<unsafe>@example.com" not in response.content
    assert b'method="post"' in response.content
    assert b'action="/logout/"' in response.content
    assert b'name="csrfmiddlewaretoken"' in response.content
    assert response.context["penni_more_version"] == "dev"
    assert b">dev<" in response.content
    assert response.context["filters_submitted"] is False
    assert response.context["graphs_available"] is False
    assert response.context["dashboard_currency_code"] is None
    assert response.context["summary_bars"] == ()
    assert response.context["category_bars"] == ()
    assert response.context["dashboard_filter_form"].initial["accounts"] == ()


@pytest.mark.django_db
def test_home_valid_post_exposes_graph_context(client: Client) -> None:
    user = User.objects.create_user("person@example.com", "test-password")
    currency = Currency.objects.create(code="USD", name="US dollar", country="United States")
    account = Account.objects.create(
        owner=user,
        currency=currency,
        name="Checking",
        account_type=Account.Type.BANK,
    )
    category = Category.objects.create(name="Food")
    Transaction.objects.create(
        created_by=user,
        account=account,
        category=category,
        transaction_type=Transaction.Type.EXPENSE,
        name="Groceries",
        amount=Decimal("12.34"),
        date=date(2026, 9, 19),
    )
    client.force_login(user)

    response = client.post(
        "/",
        {
            "start": "2026-09-19",
            "end": "2026-09-19",
            "accounts": [account.pk],
            "categories": [category.pk],
        },
    )

    assert response.status_code == 200
    assert response.context["filters_submitted"] is True
    assert response.context["graphs_available"] is True
    assert response.context["dashboard_currency_code"] == "USD"
    assert [(bar.label, bar.amount) for bar in response.context["summary_bars"]] == [
        ("Income", Decimal("0.00")),
        ("Expenses", Decimal("12.34")),
    ]
    assert [(bar.label, bar.amount) for bar in response.context["category_bars"]] == [
        ("Food", Decimal("12.34"))
    ]
    assert b"0.00 USD" in response.content
    assert b"12.34 USD" in response.content


@pytest.mark.django_db
def test_home_get_renders_exact_clock_defaults_and_selects_active_and_inactive_categories(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = User.objects.create_user("person@example.com", "test-password")
    active = Category.objects.create(name="Active")
    inactive = Category.objects.create(name="Historical", is_active=False)
    monkeypatch.setattr(
        "penni_more.dashboard.forms.timezone.now",
        lambda: datetime(2026, 9, 19, 23, 45, tzinfo=UTC),
    )
    client.force_login(user)

    response = client.get("/")
    content = response.content.decode()

    assert response.status_code == 200
    assert 'value="2026-08-20"' in content
    assert 'value="2026-09-19"' in content
    assert f'<option value="{active.pk}" selected>' in content
    assert f'<option value="{inactive.pk}" selected>' in content
    assert "Historical (inactive)" in content


@pytest.mark.django_db
def test_home_escapes_hostile_account_and_category_labels_in_filters_and_graphs(
    client: Client,
) -> None:
    user = User.objects.create_user("person@example.com", "test-password")
    currency = Currency.objects.create(code="USD", name="US dollar", country="United States")
    account = Account.objects.create(
        owner=user,
        currency=currency,
        name="Cash <script>alert(1)</script>",
        account_type=Account.Type.BANK,
    )
    category = Category.objects.create(name='Food <img src="x" onerror="alert(2)">')
    Transaction.objects.create(
        created_by=user,
        account=account,
        category=category,
        transaction_type=Transaction.Type.EXPENSE,
        name="Expense",
        amount=Decimal("1.23"),
        date=date(2026, 9, 19),
    )
    client.force_login(user)

    response = client.post(
        "/",
        {
            "start": "2026-09-19",
            "end": "2026-09-19",
            "accounts": [account.pk],
            "categories": [category.pk],
        },
    )

    assert response.status_code == 200
    assert b"<script>alert(1)</script>" not in response.content
    assert b"&lt;script&gt;alert(1)&lt;/script&gt;" in response.content
    assert b'<img src="x" onerror="alert(2)">' not in response.content
    assert b"Food &lt;img src=&quot;x&quot; onerror=&quot;alert(2)&quot;&gt;" in response.content


@pytest.mark.django_db
def test_home_valid_empty_categories_keeps_summary_and_renders_no_category_state(
    client: Client,
) -> None:
    user = User.objects.create_user("person@example.com", "test-password")
    currency = Currency.objects.create(code="USD", name="US dollar", country="United States")
    account = Account.objects.create(
        owner=user,
        currency=currency,
        name="Checking",
        account_type=Account.Type.BANK,
    )
    category = Category.objects.create(name="Food")
    Transaction.objects.create(
        created_by=user,
        account=account,
        category=category,
        transaction_type=Transaction.Type.EXPENSE,
        name="Expense",
        amount=Decimal("5.67"),
        date=date(2026, 9, 19),
    )
    client.force_login(user)

    response = client.post(
        "/",
        {
            "start": "2026-09-19",
            "end": "2026-09-19",
            "accounts": [account.pk],
            "categories": [],
        },
    )

    assert response.status_code == 200
    assert response.context["graphs_available"] is True
    assert [(bar.label, bar.amount) for bar in response.context["summary_bars"]] == [
        ("Income", Decimal("0.00")),
        ("Expenses", Decimal("5.67")),
    ]
    assert response.context["category_bars"] == ()
    assert b"5.67 USD" in response.content
    assert b"No categories selected." in response.content


@pytest.mark.django_db
def test_home_does_not_aggregate_invalid_or_empty_account_post(client: Client) -> None:
    user = User.objects.create_user("person@example.com", "test-password")
    client.force_login(user)

    with patch("penni_more.views.build_dashboard_graphs") as aggregate:
        invalid = client.post("/", {"start": "not-a-date", "end": "2026-09-19", "accounts": []})
        empty = client.post("/", {"start": "2026-09-01", "end": "2026-09-19", "accounts": []})

    aggregate.assert_not_called()
    assert invalid.status_code == 200
    assert invalid.context["dashboard_filter_form"].errors
    assert invalid.context["graphs_available"] is False
    assert empty.status_code == 200
    assert empty.context["dashboard_filter_form"].is_valid()
    assert empty.context["graphs_available"] is False


@pytest.mark.django_db
def test_home_rejects_tampered_inaccessible_and_mixed_currency_posts_without_aggregation(
    client: Client,
) -> None:
    viewer = User.objects.create_user("viewer@example.com", "test-password")
    owner = User.objects.create_user("owner@example.com", "test-password")
    usd = Currency.objects.create(code="USD", name="US dollar", country="United States")
    eur = Currency.objects.create(code="EUR", name="Euro", country="European Union")
    owned_usd = Account.objects.create(
        owner=viewer, currency=usd, name="Owned USD", account_type=Account.Type.BANK
    )
    owned_eur = Account.objects.create(
        owner=viewer, currency=eur, name="Owned EUR", account_type=Account.Type.BANK
    )
    hidden = Account.objects.create(
        owner=owner,
        currency=usd,
        name="Secret hidden account",
        account_type=Account.Type.BANK,
    )
    revoked = Account.objects.create(
        owner=owner,
        currency=usd,
        name="Previously shared secret",
        account_type=Account.Type.BANK,
    )
    revoked_share = AccountShare.objects.create(account=revoked, recipient=viewer)
    revoked_share.delete()
    category = Category.objects.create(name="Food")
    client.force_login(viewer)

    payload = {"start": "2026-09-01", "end": "2026-09-19", "categories": [category.pk]}
    with patch("penni_more.views.build_dashboard_graphs") as aggregate:
        responses = (
            client.post("/", {**payload, "accounts": [hidden.pk]}),
            client.post("/", {**payload, "accounts": [987654321]}),
            client.post("/", {**payload, "accounts": [revoked.pk]}),
            client.post("/", {**payload, "accounts": [owned_usd.pk], "categories": [987654321]}),
            client.post("/", {**payload, "accounts": [owned_usd.pk, owned_eur.pk]}),
        )

    aggregate.assert_not_called()
    for response in responses:
        assert response.status_code == 200
        assert response.context["graphs_available"] is False
        assert response.context["dashboard_currency_code"] is None
        assert response.context["summary_bars"] == ()
        assert response.context["category_bars"] == ()

    for response in responses[:3]:
        assert (
            "Select a valid account."
            in response.context["dashboard_filter_form"].errors["accounts"]
        )
    assert (
        "Select a valid category."
        in responses[3].context["dashboard_filter_form"].errors["categories"]
    )
    assert (
        "Selected accounts must use the same currency."
        in responses[4].context["dashboard_filter_form"].errors["accounts"]
    )
    assert b"Secret hidden account" not in responses[0].content
    assert b"Previously shared secret" not in responses[2].content
    assert b"987654321" not in responses[1].content


@pytest.mark.django_db
def test_home_accepts_owned_and_shared_same_currency_accounts(client: Client) -> None:
    viewer = User.objects.create_user("viewer@example.com", "test-password")
    owner = User.objects.create_user("owner@example.com", "test-password")
    usd = Currency.objects.create(code="USD", name="US dollar", country="United States")
    owned = Account.objects.create(
        owner=viewer, currency=usd, name="Owned", account_type=Account.Type.BANK
    )
    shared = Account.objects.create(
        owner=owner, currency=usd, name="Shared", account_type=Account.Type.BANK
    )
    AccountShare.objects.create(account=shared, recipient=viewer)
    category = Category.objects.create(name="Food")
    for account, amount in ((owned, "1.00"), (shared, "2.00")):
        Transaction.objects.create(
            created_by=account.owner,
            account=account,
            category=category,
            transaction_type=Transaction.Type.EXPENSE,
            name="Expense",
            amount=Decimal(amount),
            date=date(2026, 9, 19),
        )
    client.force_login(viewer)

    response = client.post(
        "/",
        {
            "start": "2026-09-19",
            "end": "2026-09-19",
            "accounts": [owned.pk, shared.pk],
            "categories": [category.pk],
        },
    )

    assert response.status_code == 200
    assert response.context["dashboard_filter_form"].is_valid()
    assert response.context["graphs_available"] is True
    assert response.context["dashboard_currency_code"] == "USD"
    assert response.context["summary_bars"][1].amount == Decimal("3.00")


@pytest.mark.django_db
def test_home_post_requires_csrf_and_unsupported_methods_return_405() -> None:
    user = User.objects.create_user("person@example.com", "test-password")
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(user)

    response = csrf_client.post("/", {"start": "2026-09-01", "end": "2026-09-19", "accounts": []})
    method_client = Client()
    method_client.force_login(user)
    unsupported = method_client.put("/")

    assert response.status_code == 403
    assert unsupported.status_code == 405


def test_anonymous_login_shell_hides_identity_and_logout(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PENNI_MORE_IMAGE_VERSION", "9.8.7")

    response = client.get(reverse("login"))

    assert response.status_code == 200
    assert b"Signed in as" not in response.content
    assert b'action="/logout/"' not in response.content
    assert response.context["penni_more_version"] == "dev"
    assert b">dev<" in response.content
