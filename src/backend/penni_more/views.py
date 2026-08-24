"""Minimal server-rendered and operational endpoints."""

from django.db import DatabaseError, connections
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods


def home(request: HttpRequest) -> HttpResponse:
    """Render the shared Web GUI shell."""
    return render(request, "home.html")


@require_http_methods(["GET"])
def live(request: HttpRequest) -> JsonResponse:
    """Report process liveness without querying any dependency."""
    return JsonResponse({"status": "ok"})


@require_http_methods(["GET"])
def ready(request: HttpRequest) -> JsonResponse:
    """Report database readiness without exposing diagnostic details."""
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1")
    except DatabaseError:
        return JsonResponse({"status": "unavailable"}, status=503)

    return JsonResponse({"status": "ok"})
