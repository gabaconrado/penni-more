"""Admin registration and category policy tests."""

import pytest
from django.contrib import admin
from django.db.models.deletion import ProtectedError
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from penni_more.accounts.models import Account, Currency
from penni_more.transactions.admin import CategoryAdmin
from penni_more.transactions.models import Category, Transaction
from penni_more.users.models import User


def test_category_is_registered_with_catalog_controls() -> None:
    registered = admin.site._registry[Category]
    assert isinstance(registered, CategoryAdmin)
    assert registered.list_display == ("name", "is_active")
    assert registered.list_filter == ("is_active",)


@pytest.mark.django_db
def test_referenced_category_delete_is_protected_with_useful_admin_response(
    client: Client,
) -> None:
    owner = User.objects.create_superuser("category-owner@example.com", "password")
    currency = Currency.objects.create(code="USD", name="US dollar", country="United States")
    account = Account.objects.create(
        name="Bank",
        description="",
        account_type=Account.Type.BANK,
        owner=owner,
        currency=currency,
    )
    category = Category.objects.create(name="Referenced")
    Transaction.objects.create(
        transaction_type=Transaction.Type.EXPENSE,
        name="Expense",
        description="",
        category=category,
        date=timezone.now().date(),
        amount="1.00",
        account=account,
        additional_data={},
        created_by=owner,
    )
    client.force_login(owner)
    response = client.get(reverse("admin:transactions_category_delete", args=(category.pk,)))
    assert response.status_code == 200
    assert b"Expense" in response.content
    assert Category.objects.filter(pk=category.pk).exists()

    with pytest.raises(ProtectedError):
        category.delete()
