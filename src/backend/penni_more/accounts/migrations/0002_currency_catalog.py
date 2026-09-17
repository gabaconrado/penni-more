from typing import Any

from django.db import migrations, models

CAD_FLAG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 3 2">'
    '<path fill="#fff" d="M0 0h3v2H0z"/>'
    '<path fill="#d80621" d="M0 0h.75v2H0zm2.25 0H3v2h-.75zM1.5.35l.15.3.3-.1'
    '-.15.35.2.1-.4.3.05.35h-.3l.05-.35L1 1l.2-.1-.15-.35.3.1z"/></svg>'
)
BRL_FLAG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 7">'
    '<path fill="#009b3a" d="M0 0h10v7H0z"/>'
    '<path fill="#fedf00" d="M5 .6 9.2 3.5 5 6.4.8 3.5z"/>'
    '<circle cx="5" cy="3.5" r="1.45" fill="#002776"/></svg>'
)


def seed_currencies(apps: Any, schema_editor: Any) -> None:
    Currency = apps.get_model("accounts", "Currency")
    seeds = (
        ("CAD", "Canadian dollar", "Canada", CAD_FLAG),
        ("BRL", "Brazilian real", "Brazil", BRL_FLAG),
    )
    for code, name, country, flag_svg in seeds:
        Currency.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "country": country,
                "flag_svg": flag_svg,
                "is_active": True,
            },
        )


def remove_seed_currencies(apps: Any, schema_editor: Any) -> None:
    Currency = apps.get_model("accounts", "Currency")
    Currency.objects.filter(code__in=("CAD", "BRL")).delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0001_initial")]

    operations = [
        migrations.CreateModel(
            name="Currency",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("code", models.CharField(max_length=3, unique=True)),
                ("name", models.CharField(max_length=100)),
                ("country", models.CharField(max_length=100)),
                ("flag_svg", models.TextField(blank=True)),
                ("is_active", models.BooleanField(default=True)),
            ],
            options={
                "ordering": ("code",),
                "verbose_name_plural": "currencies",
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("code__regex", "^[A-Z]{3}$")),
                        name="accounts_currency_code_uppercase_ascii",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("name__regex", "\\S")),
                        name="accounts_currency_name_not_blank",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("country__regex", "\\S")),
                        name="accounts_currency_country_not_blank",
                    ),
                ],
            },
        ),
        migrations.RunPython(seed_currencies, remove_seed_currencies),
    ]
