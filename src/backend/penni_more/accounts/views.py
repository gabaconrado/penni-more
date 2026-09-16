"""Thin server-rendered views for account CRUD and sharing."""

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .forms import AccountForm, AccountShareForm
from .models import Account, AccountShare
from .services import DuplicateAccountShareError, revoke_account_share, share_account


def _owned_account(request: HttpRequest, pk: int) -> Account:
    return get_object_or_404(Account.objects.select_related("owner"), pk=pk, owner=request.user)


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
    accounts = Account.objects.accessible_to(request.user).select_related("owner")
    return render(request, "accounts/account_list.html", {"accounts": accounts})


@require_http_methods(["GET", "POST"])
def account_create(request: HttpRequest) -> HttpResponse:
    """Create an account owned by the current user."""
    form = AccountForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        account = form.save(commit=False)
        account.owner = request.user
        account.save()
        messages.success(request, "Account created.")
        return redirect("accounts:detail", pk=account.pk)
    return render(request, "accounts/account_form.html", {"form": form, "mode": "create"})


@require_GET
def account_detail(request: HttpRequest, pk: int) -> HttpResponse:
    """Show an account to its owner or a share recipient."""
    account = get_object_or_404(
        Account.objects.accessible_to(request.user).select_related("owner"), pk=pk
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
        account = form.save()
        messages.success(request, "Account updated.")
        return redirect("accounts:detail", pk=account.pk)
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
