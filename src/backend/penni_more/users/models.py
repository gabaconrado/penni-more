"""Custom email-identified user model."""

from typing import Any, ClassVar

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.functions import Lower

from .managers import UserManager, normalize_email_address


class User(AbstractUser):
    """Application user authenticated by a canonical email address."""

    username = None  # type: ignore[assignment]
    email = models.EmailField("email address", unique=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: ClassVar[list[str]] = []

    objects: ClassVar[UserManager] = UserManager()  # type: ignore[assignment]

    class Meta:
        constraints = [
            models.UniqueConstraint(
                Lower("email"),
                name="users_user_email_ci_unique",
                violation_error_message="A user with that email address already exists.",
            )
        ]

    def clean(self) -> None:
        """Normalize email during model validation."""
        super().clean()
        self.email = normalize_email_address(self.email)

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Persist only the canonical email representation."""
        self.email = normalize_email_address(self.email)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.email
