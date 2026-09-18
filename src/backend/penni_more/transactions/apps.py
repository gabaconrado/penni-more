"""Application configuration for the transaction ledger."""

from django.apps import AppConfig


class TransactionsConfig(AppConfig):
    """Configure the transaction ledger application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "penni_more.transactions"
