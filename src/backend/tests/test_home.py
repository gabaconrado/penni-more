"""Request tests for the server-rendered application shell."""

from django.test import Client


def test_home_renders_web_template(client: Client) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert b"<!doctype html>" in response.content.lower()
