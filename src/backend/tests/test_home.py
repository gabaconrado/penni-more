"""Request tests for the server-rendered application shell."""

import pytest
from django.test import Client
from django.test.client import RequestFactory
from django.urls import reverse

from penni_more.context_processors import release_version
from penni_more.users.models import User


def test_release_version_context_contains_only_public_label() -> None:
    context = release_version(RequestFactory().get("/"))

    assert context == {"penni_more_version": "dev"}


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
    assert response.context["penni_more_version"] == "dev"
    assert b">dev<" in response.content


def test_anonymous_login_shell_hides_identity_and_logout(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PENNI_MORE_IMAGE_VERSION", "9.8.7")

    response = client.get(reverse("login"))

    assert response.status_code == 200
    assert b"Signed in as" not in response.content
    assert b'action="/logout/"' not in response.content
    assert response.context["penni_more_version"] == "dev"
    assert b">dev<" in response.content
