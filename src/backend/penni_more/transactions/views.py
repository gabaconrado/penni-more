"""Thin server-rendered views for transaction CRUD, filters, and CSV import."""

from __future__ import annotations

from calendar import monthrange
from datetime import date
from typing import Any, cast

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from penni_more.accounts.models import Account

from .forms import (
    CSVImportForm,
    ImportConfirmationForm,
    TransactionFilterForm,
    TransactionForm,
)
from .imports import confirm_import, load_preview, parse_csv_upload, store_preview
from .models import Transaction
from .services import (
    TransactionUnavailableError,
    TransactionWriteError,
    can_mutate,
    create_transaction,
    delete_transaction,
    filter_additional_data,
    present_transaction,
    update_transaction,
)

FILTER_SESSION_KEY = "transactions_filters"


def _base_queryset() -> Any:
    return Transaction.objects.select_related(
        "account",
        "account__owner",
        "account__currency",
        "target_account",
        "target_account__owner",
        "target_account__currency",
        "category",
        "created_by",
    )


def _accessible_transaction(request: HttpRequest, pk: int) -> Transaction:
    return cast(Transaction, get_object_or_404(_base_queryset().accessible_to(request.user), pk=pk))


def _owned_transaction(request: HttpRequest, pk: int) -> Transaction:
    return cast(
        Transaction,
        get_object_or_404(_base_queryset(), pk=pk, account__owner=request.user),
    )


def _accessible_ids(request: HttpRequest) -> set[int]:
    return set(Account.objects.accessible_to(request.user).values_list("pk", flat=True))


def _add_service_errors(form: TransactionForm, error: ValidationError) -> None:
    if hasattr(error, "error_dict"):
        for field, errors in error.error_dict.items():
            target = field if field in form.fields else None
            for item in errors:
                form.add_error(target, item)
    else:
        for item in error.error_list:
            form.add_error(None, item)


def _stored_filters(request: HttpRequest) -> dict[str, Any]:
    stored = request.session.get(FILTER_SESSION_KEY, {})
    if not isinstance(stored, dict):
        request.session.pop(FILTER_SESSION_KEY, None)
        request.session.modified = True
        return {}
    account_id = stored.get("account")
    if (
        account_id
        and not Account.objects.accessible_to(request.user).filter(pk=account_id).exists()
    ):
        stored.pop("account", None)
        request.session[FILTER_SESSION_KEY] = stored
        request.session.modified = True
    return stored


def _apply_filters(queryset: Any, stored: dict[str, Any]) -> Any:
    if stored.get("account"):
        queryset = queryset.filter(
            Q(account_id=stored["account"]) | Q(target_account_id=stored["account"])
        )
    if stored.get("month"):
        year, month = (int(part) for part in stored["month"].split("-"))
        queryset = queryset.filter(
            date__range=(date(year, month, 1), date(year, month, monthrange(year, month)[1]))
        )
    if stored.get("additional_key") and stored.get("additional_value"):
        queryset = filter_additional_data(
            queryset,
            key=stored["additional_key"],
            value=stored["additional_value"],
        )
    return queryset


def _presentation_page(request: HttpRequest, queryset: Any, page: Any) -> tuple[Any, list[Any]]:
    page_obj = Paginator(queryset.stable_order(), 50).get_page(page)
    accessible_ids = _accessible_ids(request)
    rows = [present_transaction(item, accessible_ids) for item in page_obj.object_list]
    page_obj.object_list = rows
    return page_obj, rows


@require_GET
def transaction_list(request: HttpRequest) -> HttpResponse:
    """List accessible transactions under validated session filters."""
    stored = _stored_filters(request)
    initial = {
        "account": stored.get("account", ""),
        "month": stored.get("month", ""),
        "additional_key": stored.get("additional_key", ""),
        "additional_value": stored.get("additional_value", ""),
    }
    form = TransactionFilterForm(initial=initial, user=request.user)
    queryset = _apply_filters(_base_queryset().accessible_to(request.user), stored)
    page_obj, rows = _presentation_page(request, queryset, request.GET.get("page"))
    return render(
        request,
        "transactions/transaction_list.html",
        {
            "page_obj": page_obj,
            "rows": rows,
            "filter_form": form,
            "filters_active": any(initial.values()),
        },
    )


@require_POST
def transaction_filters(request: HttpRequest) -> HttpResponse:
    """Validate and store private filter state, then redirect."""
    form = TransactionFilterForm(request.POST, user=request.user)
    if form.is_valid():
        account = form.cleaned_data["account"]
        request.session[FILTER_SESSION_KEY] = {
            "account": account.pk if account is not None else "",
            "month": form.cleaned_data["month"],
            "additional_key": form.cleaned_data["additional_key"],
            "additional_value": form.cleaned_data["additional_value"],
        }
        return redirect("transactions:list")
    stored = _stored_filters(request)
    queryset = _base_queryset().accessible_to(request.user)
    queryset = _apply_filters(queryset, stored) if any(stored.values()) else queryset.none()
    page_obj, rows = _presentation_page(request, queryset, 1)
    return render(
        request,
        "transactions/transaction_list.html",
        {
            "page_obj": page_obj,
            "rows": rows,
            "filter_form": form,
            "filters_active": any(stored.values()),
        },
    )


@require_POST
def transaction_filters_clear(request: HttpRequest) -> HttpResponse:
    """Clear the session's transaction filters."""
    request.session.pop(FILTER_SESSION_KEY, None)
    return redirect("transactions:list")


@require_http_methods(["GET", "POST"])
def transaction_create(request: HttpRequest) -> HttpResponse:
    """Create a transaction against currently accessible accounts."""
    form = TransactionForm(request.POST or None, user=request.user, mode="create")
    if request.method == "POST" and form.is_valid():
        try:
            item = create_transaction(user=request.user, values=form.cleaned_data)
        except TransactionWriteError as error:
            _add_service_errors(form, error)
        else:
            messages.success(request, "Transaction created.")
            return redirect("transactions:detail", pk=item.pk)
    return render(request, "transactions/transaction_form.html", {"form": form, "mode": "create"})


@require_GET
def transaction_detail(request: HttpRequest, pk: int) -> HttpResponse:
    """Show one accessible transaction with private counterparts masked."""
    item = _accessible_transaction(request, pk)
    presentation = present_transaction(item, _accessible_ids(request))
    allowed = can_mutate(item, request.user)
    return render(
        request,
        "transactions/transaction_detail.html",
        {
            "transaction": presentation.transaction,
            "presentation": presentation,
            "source_account": presentation.source,
            "target_account": presentation.target,
            "additional_data_pairs": tuple(presentation.transaction.additional_data.items()),
            "can_edit": allowed,
            "can_delete": allowed,
            "is_future": item.date > timezone.now().date(),
            "amount_currency_code": presentation.transaction.amount_currency_code,
        },
    )


@require_http_methods(["GET", "POST"])
def transaction_update(request: HttpRequest, pk: int) -> HttpResponse:
    """Edit a transaction only as its current source owner."""
    item = _owned_transaction(request, pk)
    form = TransactionForm(
        request.POST or None,
        instance=item,
        user=request.user,
        mode="edit",
    )
    if request.method == "POST" and form.is_valid():
        try:
            saved = update_transaction(
                user=request.user,
                ledger_transaction=item,
                values=form.cleaned_data,
            )
        except TransactionUnavailableError as error:
            raise Http404 from error
        except TransactionWriteError as error:
            _add_service_errors(form, error)
        else:
            messages.success(request, "Transaction updated.")
            return redirect("transactions:detail", pk=saved.pk)
    return render(
        request,
        "transactions/transaction_form.html",
        {
            "form": form,
            "mode": "edit",
            "transaction": present_transaction(item, _accessible_ids(request)).transaction,
        },
    )


@require_http_methods(["GET", "POST"])
def transaction_delete(request: HttpRequest, pk: int) -> HttpResponse:
    """Confirm and delete a source-owner-controlled transaction."""
    item = _owned_transaction(request, pk)
    presentation = present_transaction(item, _accessible_ids(request))
    if request.method == "POST":
        try:
            delete_transaction(user=request.user, ledger_transaction=item)
        except TransactionWriteError as error:
            raise Http404 from error
        messages.success(request, "Transaction deleted.")
        return redirect("transactions:list")
    return render(
        request,
        "transactions/transaction_confirm_delete.html",
        {
            "transaction": presentation.transaction,
            "presentation": presentation,
            "source_account": presentation.source,
            "target_account": presentation.target,
            "amount_currency_code": presentation.transaction.amount_currency_code,
        },
    )


@require_http_methods(["GET", "POST"])
def transaction_import(request: HttpRequest) -> HttpResponse:
    """Validate an uploaded CSV and render a write-free preview."""
    form = CSVImportForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        preview = parse_csv_upload(form.cleaned_data["csv_file"], user=request.user)
        token = store_preview(request.session, preview.rows) if preview.is_valid else None
        return render(
            request,
            "transactions/transaction_import_preview.html",
            {
                "form": form,
                "preview_rows": preview.rows,
                "row_errors": preview.row_errors,
                "file_errors": preview.file_errors,
                "preview_token": token,
            },
        )
    return render(request, "transactions/transaction_import.html", {"form": form})


@require_POST
def transaction_import_confirm(request: HttpRequest) -> HttpResponse:
    """Revalidate and atomically import one stored preview."""
    form = ImportConfirmationForm(request.POST)
    rows = load_preview(request.session, str(request.POST.get("preview_token", "")))
    if not form.is_valid() or rows is None:
        form.add_error(None, "This import preview is unavailable or expired. Upload the CSV again.")
        return render(
            request,
            "transactions/transaction_import.html",
            {"form": CSVImportForm(), "confirmation_form": form},
        )
    try:
        count = confirm_import(user=request.user, rows=rows)
    except TransactionWriteError as error:
        return render(
            request,
            "transactions/transaction_import_preview.html",
            {
                "form": CSVImportForm(),
                "preview_rows": (),
                "row_errors": ({"source_line": None, "errors": error.messages},),
                "file_errors": (),
                "preview_token": None,
            },
        )
    messages.success(request, f"Imported {count} transactions.")
    return redirect("transactions:list")
