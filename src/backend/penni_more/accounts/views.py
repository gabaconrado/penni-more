"""Thin server-rendered views for account CRUD, currencies, and sharing."""

import hashlib
from typing import Any, cast

from django.contrib import messages
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .forms import AccountForm, AccountShareForm
from .models import Account, AccountShare, Currency
from .services import DuplicateAccountShareError, revoke_account_share, share_account


def _save_account_with_locked_currency(
    form: AccountForm, *, owner: Any | None = None
) -> Account | None:
    """Recheck currency eligibility while locking it through the account write."""
    selected_currency = form.cleaned_data["currency"]
    with transaction.atomic():
        current_currency_id = None
        if form.instance.pk is not None:
            persisted_account = (
                Account.objects.select_for_update()
                .only("currency_id")
                .filter(pk=form.instance.pk)
                .first()
            )
            if persisted_account is None:
                form.add_error(None, "This account no longer exists.")
                return None
            current_currency_id = persisted_account.currency_id

        locked_currency = (
            Currency.objects.select_for_update().filter(pk=selected_currency.pk).first()
        )
        if locked_currency is None or (
            not locked_currency.is_active and locked_currency.pk != current_currency_id
        ):
            form.add_error("currency", "Select a valid currency.")
            return None

        form.instance.currency = locked_currency
        if owner is not None:
            form.instance.owner = owner
        return cast(Account, form.save())


def _owned_account(request: HttpRequest, pk: int) -> Account:
    return get_object_or_404(
        Account.objects.select_related("owner", "currency"), pk=pk, owner=request.user
    )


def _detail_context(account: Account, *, is_owner: bool) -> dict[str, object]:
    context: dict[str, object] = {"account": account, "is_owner": is_owner}
    if is_owner:
        context["share_form"] = AccountShareForm(account=account)
        context["shares"] = account.shares.select_related("recipient").order_by(
            "recipient__email", "pk"
        )
    return context


@require_GET
def account_list(request: HttpRequest) -> HttpResponse:
    """List each account accessible to the current user."""
    accounts = Account.objects.accessible_to(request.user).select_related("owner", "currency")
    return render(request, "accounts/account_list.html", {"accounts": accounts})


@require_http_methods(["GET", "POST"])
def account_create(request: HttpRequest) -> HttpResponse:
    """Create an account owned by the current user."""
    form = AccountForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        account = _save_account_with_locked_currency(form, owner=request.user)
        if account is not None:
            messages.success(request, "Account created.")
            return redirect("accounts:detail", pk=account.pk)
    return render(request, "accounts/account_form.html", {"form": form, "mode": "create"})


@require_GET
def account_detail(request: HttpRequest, pk: int) -> HttpResponse:
    """Show an account to its owner or a share recipient."""
    account = get_object_or_404(
        Account.objects.accessible_to(request.user).select_related("owner", "currency"), pk=pk
    )
    return render(
        request,
        "accounts/account_detail.html",
        _detail_context(account, is_owner=account.owner_id == request.user.pk),
    )


@require_http_methods(["GET", "POST"])
def account_update(request: HttpRequest, pk: int) -> HttpResponse:
    """Edit owner-controlled account information."""
    account = _owned_account(request, pk)
    form = AccountForm(request.POST or None, instance=account)
    if request.method == "POST" and form.is_valid():
        saved_account = _save_account_with_locked_currency(form)
        if saved_account is not None:
            messages.success(request, "Account updated.")
            return redirect("accounts:detail", pk=saved_account.pk)
    return render(
        request,
        "accounts/account_form.html",
        {"account": account, "form": form, "mode": "edit"},
    )


@require_http_methods(["GET", "POST"])
def account_delete(request: HttpRequest, pk: int) -> HttpResponse:
    """Confirm and permanently delete an owned account."""
    account = _owned_account(request, pk)
    if request.method == "POST":
        account.delete()
        messages.success(request, "Account deleted.")
        return redirect("accounts:list")
    return render(request, "accounts/account_confirm_delete.html", {"account": account})


@require_POST
def account_share(request: HttpRequest, pk: int) -> HttpResponse:
    """Grant an existing user read access to an owned account."""
    account = _owned_account(request, pk)
    form = AccountShareForm(request.POST, account=account)
    if form.is_valid() and form.recipient is not None:
        try:
            share_account(account, form.recipient)
        except DuplicateAccountShareError:
            form.add_error("email", "This user already has access.")
        else:
            messages.success(request, "Account access shared.")
            return redirect("accounts:detail", pk=account.pk)

    context = _detail_context(account, is_owner=True)
    context["share_form"] = form
    return render(request, "accounts/account_detail.html", context)


@require_POST
def account_share_revoke(request: HttpRequest, pk: int, share_id: int) -> HttpResponse:
    """Revoke one recipient's access to an owned account."""
    account = _owned_account(request, pk)
    get_object_or_404(AccountShare, account=account, pk=share_id)
    revoke_account_share(account, share_id)
    messages.success(request, "Shared access revoked.")
    return redirect("accounts:detail", pk=account.pk)


@require_GET
def currency_flag(request: HttpRequest, pk: int) -> HttpResponse:
    """Return a stored flag as a contained, same-origin SVG image."""
    currency = get_object_or_404(Currency, pk=pk)
    if not currency.flag_svg:
        return HttpResponse(status=404)

    body = currency.flag_svg.encode("utf-8")
    response = HttpResponse(body, content_type="image/svg+xml; charset=utf-8")
    response.headers["Content-Disposition"] = f'inline; filename="{currency.code}-flag.svg"'
    response.headers["Content-Security-Policy"] = "default-src 'none'; sandbox"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    response.headers["Cache-Control"] = "private, max-age=300"
    response.headers["ETag"] = f'"{hashlib.sha256(body).hexdigest()}"'
    return response
