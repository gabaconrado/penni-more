"""Historical migration coverage for the initial transaction ledger schema."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.django_db(transaction=True)
def test_initial_transaction_migration_is_reversible() -> None:
    executor = MigrationExecutor(connection)
    latest = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate([("transactions", None)])
        old_apps = executor.loader.project_state([("accounts", "0003_account_currency")]).apps
        with pytest.raises(LookupError):
            old_apps.get_model("transactions", "Transaction")

        executor = MigrationExecutor(connection)
        executor.migrate([("transactions", "0001_initial")])
        apps = executor.loader.project_state([("transactions", "0001_initial")]).apps
        Category = apps.get_model("transactions", "Category")
        assert Category.objects.create(name="Migration category").pk is not None

        MigrationExecutor(connection).migrate([("transactions", None)])
    finally:
        MigrationExecutor(connection).migrate(latest)
