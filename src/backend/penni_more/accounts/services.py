"""Account-sharing domain operations."""

from django.db import IntegrityError, transaction

from penni_more.users.models import User

from .models import Account, AccountShare


class DuplicateAccountShareError(Exception):
    """A recipient already has access to the account."""


class AccountOwnerShareError(Exception):
    """An owner cannot receive a redundant share of their own account."""


def share_account(account: Account, recipient: User) -> AccountShare:
    """Grant access while translating a concurrent duplicate into a domain error."""
    if account.owner_id == recipient.pk:
        raise AccountOwnerShareError
    try:
        with transaction.atomic():
            share, created = AccountShare.objects.get_or_create(
                account=account,
                recipient=recipient,
            )
    except IntegrityError as error:
        if AccountShare.objects.filter(account=account, recipient=recipient).exists():
            raise DuplicateAccountShareError from error
        raise
    if not created:
        raise DuplicateAccountShareError
    return share


def revoke_account_share(account: Account, share_id: int) -> None:
    """Remove a share only when it belongs to the nested account."""
    AccountShare.objects.filter(account=account, pk=share_id).delete()
