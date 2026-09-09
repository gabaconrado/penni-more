"""Request tests for email/password session authentication and admin access."""

from typing import Any

import pytest
from django.contrib.auth import SESSION_KEY
from django.contrib.auth.models import Permission
from django.test import Client
from django.urls import reverse

from penni_more.users.forms import (
    AdminUserChangeForm,
    AdminUserCreationForm,
    EmailAuthenticationForm,
)
from penni_more.users.models import User

pytestmark = pytest.mark.django_db

PASSWORD = "authentication-test-password"


def form_errors(response: Any) -> list[str]:
    """Return rendered non-field authentication errors as plain strings."""
    form = response.context["form"]
    return [str(error) for error in form.non_field_errors()]


def test_login_form_is_email_and_password_only(client: Client) -> None:
    response = client.get(reverse("login"))

    assert response.status_code == 200
    form = response.context["form"]
    assert isinstance(form, EmailAuthenticationForm)
    assert list(form.fields) == ["username", "password"]
    assert form.fields["username"].label == "Email"
    assert form.fields["username"].widget.input_type == "email"
    assert form.fields["username"].widget.attrs["autocomplete"] == "email"
    assert form.fields["password"].widget.attrs["autocomplete"] == "current-password"


def test_login_accepts_any_email_case_and_defaults_to_home(client: Client) -> None:
    user = User.objects.create_user("person@example.com", PASSWORD)

    response = client.post(
        reverse("login"), {"username": "PERSON@EXAMPLE.COM", "password": PASSWORD}
    )

    assert response.status_code == 302
    assert response.headers["Location"] == reverse("home")
    assert client.session[SESSION_KEY] == str(user.pk)


@pytest.mark.parametrize(
    ("email", "password", "is_active"),
    [
        ("unknown@example.com", PASSWORD, True),
        ("person@example.com", "wrong-password", True),
        ("person@example.com", PASSWORD, False),
    ],
)
def test_credential_failures_share_one_generic_error(
    client: Client, email: str, password: str, is_active: bool
) -> None:
    User.objects.create_user("person@example.com", PASSWORD, is_active=is_active)

    response = client.post(reverse("login"), {"username": email, "password": password})

    assert response.status_code == 200
    assert form_errors(response) == ["Please enter a correct email address and password."]
    assert SESSION_KEY not in client.session


def test_login_does_not_follow_external_next_target(client: Client) -> None:
    User.objects.create_user("person@example.com", PASSWORD)

    response = client.post(
        reverse("login"),
        {
            "username": "person@example.com",
            "password": PASSWORD,
            "next": "https://example.invalid/steal-session",
        },
    )

    assert response.status_code == 302
    assert response.headers["Location"] == reverse("home")


def test_login_follows_safe_local_next_target(client: Client) -> None:
    User.objects.create_user("person@example.com", PASSWORD)
    local_target = reverse("health-live")

    response = client.post(
        reverse("login"),
        {
            "username": "person@example.com",
            "password": PASSWORD,
            "next": local_target,
        },
    )

    assert response.status_code == 302
    assert response.headers["Location"] == local_target


def test_login_post_requires_csrf_token() -> None:
    User.objects.create_user("person@example.com", PASSWORD)
    csrf_client = Client(enforce_csrf_checks=True)

    rejected = csrf_client.post(
        reverse("login"), {"username": "person@example.com", "password": PASSWORD}
    )
    csrf_client.get(reverse("login"))
    accepted = csrf_client.post(
        reverse("login"),
        {"username": "person@example.com", "password": PASSWORD},
        headers={"X-CSRFToken": csrf_client.cookies["csrftoken"].value},
    )

    assert rejected.status_code == 403
    assert accepted.status_code == 302


def test_logout_is_post_only_and_clears_session(client: Client) -> None:
    user = User.objects.create_user("person@example.com", PASSWORD)
    client.force_login(user)

    get_response = client.get(reverse("logout"))
    assert get_response.status_code == 405
    assert SESSION_KEY in client.session

    post_response = client.post(reverse("logout"))
    assert post_response.status_code == 302
    assert post_response.headers["Location"] == reverse("login")
    assert SESSION_KEY not in client.session


def test_non_staff_user_cannot_enter_admin(client: Client) -> None:
    user = User.objects.create_user("person@example.com", PASSWORD)
    client.force_login(user)

    response = client.get(reverse("admin:index"))

    assert response.status_code == 302
    assert response.headers["Location"] == (
        f"{reverse('admin:login')}?next={reverse('admin:index')}"
    )


def test_staff_and_superuser_can_enter_admin(client: Client) -> None:
    staff = User.objects.create_user("staff@example.com", PASSWORD, is_staff=True)
    client.force_login(staff)
    assert client.get(reverse("admin:index")).status_code == 200

    superuser = User.objects.create_superuser("admin@example.com", PASSWORD)
    client.force_login(superuser)
    assert client.get(reverse("admin:index")).status_code == 200


def test_admin_add_view_uses_tailored_form_and_reports_duplicate_email(client: Client) -> None:
    staff = User.objects.create_user("staff@example.com", PASSWORD, is_staff=True)
    staff.user_permissions.add(
        *Permission.objects.filter(
            content_type__app_label="users", codename__in=("add_user", "change_user")
        )
    )
    User.objects.create_user("person@example.com", PASSWORD)
    client.force_login(staff)

    add_url = reverse("admin:users_user_add")
    get_response = client.get(add_url)
    assert get_response.status_code == 200
    assert isinstance(get_response.context["adminform"].form, AdminUserCreationForm)
    assert "username" not in get_response.context["adminform"].form.fields

    post_response = client.post(
        add_url,
        {
            "email": "PERSON@EXAMPLE.COM",
            "password1": "another-test-password",
            "password2": "another-test-password",
            "is_active": "on",
        },
    )
    assert post_response.status_code == 200
    assert post_response.context["adminform"].form.errors["email"] == [
        "A user with that email address already exists."
    ]
    assert User.objects.filter(email__iexact="person@example.com").count() == 1


def test_admin_staff_permissions_are_scoped_to_add_and_change_views(client: Client) -> None:
    target = User.objects.create_user("person@example.com", PASSWORD)
    add_only_staff = User.objects.create_user("adder@example.com", PASSWORD, is_staff=True)
    add_only_staff.user_permissions.add(
        Permission.objects.get(content_type__app_label="users", codename="add_user")
    )
    client.force_login(add_only_staff)

    denied_add_without_change = client.get(reverse("admin:users_user_add"))
    denied_change = client.get(reverse("admin:users_user_change", args=[target.pk]))
    assert denied_add_without_change.status_code == 403
    assert denied_change.status_code == 403

    change_staff = User.objects.create_user("changer@example.com", PASSWORD, is_staff=True)
    change_staff.user_permissions.add(
        Permission.objects.get(content_type__app_label="users", codename="change_user")
    )
    client.force_login(change_staff)

    denied_add = client.get(reverse("admin:users_user_add"))
    change_response = client.get(reverse("admin:users_user_change", args=[target.pk]))
    assert denied_add.status_code == 403
    assert change_response.status_code == 200
    assert isinstance(change_response.context["adminform"].form, AdminUserChangeForm)
    assert "username" not in change_response.context["adminform"].form.fields


def test_no_public_account_creation_or_recovery_routes(client: Client) -> None:
    assert client.get("/register/").status_code == 404
    assert client.get("/password-reset/").status_code == 404
