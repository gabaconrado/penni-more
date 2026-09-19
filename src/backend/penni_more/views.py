"""Minimal server-rendered and operational endpoints."""

from django.contrib.auth.decorators import login_not_required
from django.db import DatabaseError, connections
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from penni_more.dashboard.forms import DashboardFilterForm, dashboard_filter_initial
from penni_more.dashboard.services import build_dashboard_graphs


@require_http_methods(["GET", "POST"])
def home(request: HttpRequest) -> HttpResponse:
    """Render validated dashboard filters and their read-only graph results."""
    filters_submitted = request.method == "POST"
    if filters_submitted:
        dashboard_filter_form = DashboardFilterForm(request.POST, user=request.user)
    else:
        dashboard_filter_form = DashboardFilterForm(
            user=request.user, initial=dashboard_filter_initial()
        )

    graphs_available = False
    currency_code: str | None = None
    summary_bars: tuple[object, ...] = ()
    category_bars: tuple[object, ...] = ()
    if filters_submitted and dashboard_filter_form.is_valid():
        accounts = tuple(dashboard_filter_form.cleaned_data["accounts"])
        if accounts:
            categories = tuple(dashboard_filter_form.cleaned_data["categories"])
            graphs = build_dashboard_graphs(
                accounts=accounts,
                categories=categories,
                start=dashboard_filter_form.cleaned_data["start"],
                end=dashboard_filter_form.cleaned_data["end"],
            )
            graphs_available = True
            currency_code = accounts[0].currency.code
            summary_bars = graphs.summary_bars
            category_bars = graphs.category_bars

    return render(
        request,
        "home.html",
        {
            "dashboard_filter_form": dashboard_filter_form,
            "filters_submitted": filters_submitted,
            "graphs_available": graphs_available,
            "dashboard_currency_code": currency_code,
            "summary_bars": summary_bars,
            "category_bars": category_bars,
        },
    )


@require_http_methods(["GET"])
@login_not_required
def live(request: HttpRequest) -> JsonResponse:
    """Report process liveness without querying any dependency."""
    return JsonResponse({"status": "ok"})


@require_http_methods(["GET"])
@login_not_required
def ready(request: HttpRequest) -> JsonResponse:
    """Report database readiness without exposing diagnostic details."""
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1")
    except DatabaseError:
        return JsonResponse({"status": "unavailable"}, status=503)

    return JsonResponse({"status": "ok"})
