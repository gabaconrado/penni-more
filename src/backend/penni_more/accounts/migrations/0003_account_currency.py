from typing import Any

import django.db.models.deletion
from django.db import migrations, models


def assign_cad(apps: Any, schema_editor: Any) -> None:
    Account = apps.get_model("accounts", "Account")
    Currency = apps.get_model("accounts", "Currency")
    try:
        cad = Currency.objects.get(code="CAD")
    except Currency.DoesNotExist as error:
        raise RuntimeError("Cannot backfill account currencies because CAD is missing.") from error
    Account.objects.update(currency_id=cad.pk)


class Migration(migrations.Migration):
    dependencies = [("accounts", "0002_currency_catalog")]

    operations = [
        migrations.AddField(
            model_name="account",
            name="currency",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="accounts",
                to="accounts.currency",
            ),
        ),
        migrations.RunPython(assign_cad, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="account",
            name="currency",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="accounts",
                to="accounts.currency",
            ),
        ),
    ]
