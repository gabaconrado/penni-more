"""Request tests for the server-rendered application shell."""

import pytest
from django.test import Client
from django.urls import reverse

from penni_more.users.models import User


def test_home_redirects_anonymous_user_to_login(client: Client) -> None:
    response = client.get("/")

    assert response.status_code == 302
    assert response.headers["Location"] == f"{reverse('login')}?next=/"


@pytest.mark.django_db
def test_home_renders_web_template_for_authenticated_user(client: Client) -> None:
    user = User.objects.create_user("person+<unsafe>@example.com", "test-password")
    client.force_login(user)

    response = client.get("/")

    assert response.status_code == 200
    assert b"<!doctype html>" in response.content.lower()
    assert b"Signed in as" in response.content
    assert b"person+&lt;unsafe&gt;@example.com" in response.content
    assert b"person+<unsafe>@example.com" not in response.content
    assert b'method="post"' in response.content
    assert b'action="/logout/"' in response.content
    assert b'name="csrfmiddlewaretoken"' in response.content


def test_anonymous_login_shell_hides_identity_and_logout(client: Client) -> None:
    response = client.get(reverse("login"))

    assert response.status_code == 200
    assert b"Signed in as" not in response.content
    assert b'action="/logout/"' not in response.content
