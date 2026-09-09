"""Managers for the email-identified user model."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.contrib.auth.base_user import BaseUserManager

if TYPE_CHECKING:
    from .models import User


def normalize_email_address(email: str | None) -> str:
    """Return the canonical representation used for identity and persistence."""
    return email.strip().lower() if email else ""


class UserManager(BaseUserManager["User"]):
    """Create and find users whose sole login identifier is email."""

    use_in_migrations = True

    @classmethod
    def normalize_email(cls, email: str | None) -> str:
        """Normalize the entire address rather than only its domain."""
        return normalize_email_address(email)

    def get_by_natural_key(self, username: str | None) -> User:
        """Look up an email identifier without case sensitivity."""
        return self.get(**{f"{self.model.USERNAME_FIELD}__iexact": username})

    def create_user(self, email: str, password: str | None = None, **extra_fields: Any) -> User:
        """Create a regular active user with a required canonical email."""
        if not email or not email.strip():
            raise ValueError("The email address must be set.")
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        user = self.model(email=self.normalize_email(email), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(
        self, email: str, password: str | None = None, **extra_fields: Any
    ) -> User:
        """Create a superuser while preserving Django's flag invariants."""
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self.create_user(email, password, **extra_fields)
