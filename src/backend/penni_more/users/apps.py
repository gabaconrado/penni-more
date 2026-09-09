"""Application configuration for users."""

from django.apps import AppConfig


class UsersConfig(AppConfig):
    """Configure the custom user application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "penni_more.users"
