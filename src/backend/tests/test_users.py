"""Persistence and form tests for email-identified users."""

import pytest
from django.core.exceptions import FieldDoesNotExist, ValidationError
from django.db import IntegrityError, transaction

from penni_more.users.forms import AdminUserChangeForm, AdminUserCreationForm
from penni_more.users.models import User

pytestmark = pytest.mark.django_db


def test_create_user_requires_email_and_sets_regular_user_defaults() -> None:
    with pytest.raises(ValueError, match="email address must be set"):
        User.objects.create_user("", "test-password")

    user = User.objects.create_user("  Owner@Example.COM  ", "test-password")

    assert user.email == "owner@example.com"
    assert user.check_password("test-password")
    assert user.is_active
    assert not user.is_staff
    assert not user.is_superuser


@pytest.mark.parametrize(
    "flags",
    [
        {"is_staff": False},
        {"is_superuser": False},
    ],
)
def test_create_superuser_rejects_contradictory_flags(flags: dict[str, bool]) -> None:
    with pytest.raises(ValueError, match="Superuser must have"):
        User.objects.create_superuser("admin@example.com", "test-password", **flags)


def test_create_superuser_sets_required_flags() -> None:
    user = User.objects.create_superuser("ADMIN@Example.COM", "test-password")

    assert user.email == "admin@example.com"
    assert user.is_staff
    assert user.is_superuser


def test_model_shape_uses_email_without_username() -> None:
    removed_field = "username"
    with pytest.raises(FieldDoesNotExist):
        User._meta.get_field(removed_field)

    assert User.USERNAME_FIELD == "email"
    assert User.REQUIRED_FIELDS == []
    for field_name in (
        "first_name",
        "last_name",
        "groups",
        "user_permissions",
        "is_staff",
        "is_active",
        "is_superuser",
        "last_login",
        "date_joined",
        "password",
    ):
        assert User._meta.get_field(field_name)


def test_model_validation_normalizes_email_and_rejects_case_variant() -> None:
    User.objects.create_user("person@example.com", "test-password")
    duplicate = User(email="PERSON@EXAMPLE.COM")

    with pytest.raises(ValidationError):
        duplicate.full_clean()

    assert duplicate.email == "person@example.com"


def test_admin_creation_form_reports_case_variant_duplicate() -> None:
    User.objects.create_user("person@example.com", "test-password")
    form = AdminUserCreationForm(
        data={
            "email": "PERSON@EXAMPLE.COM",
            "password1": "different-test-password",
            "password2": "different-test-password",
        }
    )

    assert not form.is_valid()
    assert form.errors["email"] == ["A user with that email address already exists."]


def test_admin_change_form_reports_case_variant_duplicate() -> None:
    User.objects.create_user("existing@example.com", "test-password")
    target = User.objects.create_user("target@example.com", "test-password")
    form = AdminUserChangeForm(
        instance=target,
        data={
            "email": "EXISTING@EXAMPLE.COM",
            "first_name": target.first_name,
            "last_name": target.last_name,
            "is_active": "on",
            "date_joined": target.date_joined,
        },
    )

    assert not form.is_valid()
    assert form.errors["email"] == ["A user with that email address already exists."]


def test_database_constraint_rejects_case_variant_when_validation_is_bypassed() -> None:
    existing = User.objects.create_user("person@example.com", "test-password")
    User.objects.filter(pk=existing.pk).update(email="PERSON@EXAMPLE.COM")

    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.create(email="person@example.com")


def test_natural_key_lookup_is_case_insensitive() -> None:
    user = User.objects.create_user("person@example.com", "test-password")

    assert User.objects.get_by_natural_key("PERSON@EXAMPLE.COM") == user
