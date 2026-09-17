"""Historical migration coverage for the currency catalog and account backfill."""

from xml.etree import ElementTree

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.django_db(transaction=True)
def test_currency_migrations_seed_backfill_and_reverse() -> None:
    executor = MigrationExecutor(connection)
    latest = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate([("accounts", "0001_initial")])
        old_apps = executor.loader.project_state([("accounts", "0001_initial")]).apps
        User = old_apps.get_model("users", "User")
        Account = old_apps.get_model("accounts", "Account")
        owner = User.objects.create(email="migration-owner@example.com", password="unused")
        account = Account.objects.create(
            name="Before currencies",
            description="",
            account_type="bank",
            owner_id=owner.pk,
        )

        executor = MigrationExecutor(connection)
        executor.migrate([("accounts", "0003_account_currency")])
        new_apps = executor.loader.project_state([("accounts", "0003_account_currency")]).apps
        Currency = new_apps.get_model("accounts", "Currency")
        MigratedAccount = new_apps.get_model("accounts", "Account")

        currencies = {currency.code: currency for currency in Currency.objects.all()}
        assert set(currencies) == {"BRL", "CAD"}
        assert (currencies["CAD"].name, currencies["CAD"].country) == (
            "Canadian dollar",
            "Canada",
        )
        assert (currencies["BRL"].name, currencies["BRL"].country) == (
            "Brazilian real",
            "Brazil",
        )
        for currency in currencies.values():
            assert currency.is_active is True
            assert currency.flag_svg
            root = ElementTree.fromstring(currency.flag_svg)
            assert root.tag == "{http://www.w3.org/2000/svg}svg"
            assert "<!doctype" not in currency.flag_svg.lower()
            assert "<!entity" not in currency.flag_svg.lower()
            assert len(currency.flag_svg.encode()) <= 64 * 1024
        assert MigratedAccount.objects.get(pk=account.pk).currency_id == currencies["CAD"].pk
        assert MigratedAccount._meta.get_field("currency").null is False

        executor = MigrationExecutor(connection)
        executor.migrate([("accounts", "0001_initial")])
        reversed_apps = executor.loader.project_state([("accounts", "0001_initial")]).apps
        with pytest.raises(LookupError):
            reversed_apps.get_model("accounts", "Currency")
        assert reversed_apps.get_model("accounts", "Account").objects.filter(pk=account.pk).exists()
    finally:
        MigrationExecutor(connection).migrate(latest)


@pytest.mark.django_db(transaction=True)
def test_account_currency_backfill_fails_clearly_without_cad() -> None:
    executor = MigrationExecutor(connection)
    latest = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate([("accounts", "0002_currency_catalog")])
        apps = executor.loader.project_state([("accounts", "0002_currency_catalog")]).apps
        apps.get_model("accounts", "Currency").objects.filter(code="CAD").delete()

        with pytest.raises(RuntimeError, match="CAD is missing"):
            MigrationExecutor(connection).migrate([("accounts", "0003_account_currency")])
    finally:
        MigrationExecutor(connection).migrate([("accounts", "0002_currency_catalog")])
        apps = (
            MigrationExecutor(connection)
            .loader.project_state([("accounts", "0002_currency_catalog")])
            .apps
        )
        Currency = apps.get_model("accounts", "Currency")
        if not Currency.objects.filter(code="CAD").exists():
            Currency.objects.create(
                code="CAD",
                name="Canadian dollar",
                country="Canada",
                flag_svg='<svg xmlns="http://www.w3.org/2000/svg"/>',
                is_active=True,
            )
        MigrationExecutor(connection).migrate(latest)
