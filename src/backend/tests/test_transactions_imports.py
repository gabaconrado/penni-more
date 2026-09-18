"""CSV parsing, preview-token, and atomic import tests."""

from typing import Any

import pytest
from django.contrib.sessions.backends.db import SessionStore
from django.core.files.uploadedfile import SimpleUploadedFile

from penni_more.accounts.models import Account, Currency
from penni_more.transactions.imports import (
    ImportPreview,
    confirm_import,
    load_preview,
    parse_csv_upload,
    store_preview,
)
from penni_more.transactions.models import Category, Transaction
from penni_more.transactions.services import TransactionWriteError
from penni_more.users.models import User

HEADER = "type,name,description,category,date,amount,account_id,target_account_id,additional_data\n"


@pytest.fixture
def import_data() -> tuple[User, Account, Category]:
    owner = User.objects.create_user("importer@example.com", "password")
    currency = Currency.objects.create(code="USD", name="US dollar", country="United States")
    account = Account.objects.create(
        name="Bank",
        description="",
        account_type=Account.Type.BANK,
        owner=owner,
        currency=currency,
    )
    return owner, account, Category.objects.create(name="Food")


def upload(content: bytes) -> SimpleUploadedFile:
    return SimpleUploadedFile("transactions.csv", content, content_type="text/csv")


@pytest.mark.django_db
def test_valid_preview_writes_nothing_and_confirmation_can_repeat(
    import_data: tuple[User, Account, Category],
) -> None:
    owner, account, _category = import_data
    content = (
        "\ufeff"
        + HEADER
        + f'expense,Lunch,,food,2026-09-18,12.50,{account.pk},,"{{""Statement"":""July""}}"\n'
    ).encode()
    preview = parse_csv_upload(upload(content), user=owner)
    assert preview.is_valid
    assert preview.rows[0]["category"] == "Food"
    assert preview.rows[0]["additional_data"] == {"Statement": "July"}
    assert not Transaction.objects.exists()

    assert confirm_import(user=owner, rows=list(preview.rows)) == 1
    assert confirm_import(user=owner, rows=list(preview.rows)) == 1
    assert Transaction.objects.filter(name="Lunch").count() == 2


@pytest.mark.django_db
@pytest.mark.parametrize(
    "content,error",
    [
        (b"\xff", "UTF-8"),
        (b"type\x00,name", "NUL"),
        (HEADER.encode(), "no data"),
        (b"wrong,headers\n", "headers"),
    ],
)
def test_file_level_rejections(
    import_data: tuple[User, Account, Category], content: bytes, error: str
) -> None:
    owner, _account, _category = import_data
    preview = parse_csv_upload(upload(content), user=owner)
    assert not preview.is_valid
    assert error.lower() in " ".join(preview.file_errors).lower()


@pytest.mark.django_db
def test_row_errors_report_source_lines_and_json_duplicates(
    import_data: tuple[User, Account, Category],
) -> None:
    owner, account, _category = import_data
    content = (
        HEADER
        + "\n"
        + f'expense,Lunch,,Food,2026-09-18,12.5,{account.pk},,"{{""A"":""1"",""a"":""2""}}"\n'
    ).encode()
    preview = parse_csv_upload(upload(content), user=owner)
    assert not preview.is_valid
    assert preview.row_errors[0]["source_line"] == 3
    assert "two decimal" in " ".join(preview.row_errors[0]["errors"])
    assert "unique" in " ".join(preview.row_errors[0]["errors"])


@pytest.mark.django_db
def test_preview_tokens_replace_expire_and_do_not_consume(
    import_data: tuple[User, Account, Category],
) -> None:
    _owner, _account, _category = import_data
    session = SessionStore()
    first = store_preview(session, [{"name": "first"}])
    assert load_preview(session, first) == [{"name": "first"}]
    assert load_preview(session, first) == [{"name": "first"}]
    second = store_preview(session, [{"name": "second"}])
    assert load_preview(session, first) is None
    assert load_preview(session, second) == [{"name": "second"}]
    session["transactions_import_preview"]["created_at"] -= 1801
    assert load_preview(session, second) is None
    assert "transactions_import_preview" not in session
    assert session.modified is True

    session["transactions_import_preview"] = {"token": second, "created_at": "broken"}
    session.modified = False
    assert load_preview(session, second) is None
    assert "transactions_import_preview" not in session
    assert session.modified is True


@pytest.mark.django_db
def test_csv_accepts_harmless_leading_zero_amount_and_ids(
    import_data: tuple[User, Account, Category],
) -> None:
    owner, account, _category = import_data
    content = (HEADER + f"expense,Lunch,,Food,2026-09-18,00012.50,00{account.pk},,\n").encode()
    preview = parse_csv_upload(upload(content), user=owner)
    assert preview.is_valid
    assert preview.rows[0]["amount"] == "12.50"
    assert preview.rows[0]["account_id"] == account.pk


@pytest.mark.django_db
def test_confirmation_revalidates_drift_without_partial_insert(
    import_data: tuple[User, Account, Category],
) -> None:
    owner, account, category = import_data
    later_category = Category.objects.create(name="Later")
    content = (
        HEADER
        + f"expense,One,,Food,2026-09-18,1.00,{account.pk},,\n"
        + f"expense,Two,,Later,2026-09-18,2.00,{account.pk},,\n"
    ).encode()
    preview = parse_csv_upload(upload(content), user=owner)
    assert preview.is_valid
    later_category.is_active = False
    later_category.save()
    with pytest.raises(TransactionWriteError):
        confirm_import(user=owner, rows=list(preview.rows))
    assert not Transaction.objects.exists()


@pytest.mark.django_db
def test_csv_enforces_byte_row_and_source_authorization_bounds(
    import_data: tuple[User, Account, Category],
) -> None:
    owner, account, _category = import_data
    oversized = parse_csv_upload(upload(b"x" * (1024 * 1024 + 1)), user=owner)
    assert "1 MiB" in oversized.file_errors[0]

    data_rows = "".join(
        f"expense,Row {index},,Food,2026-09-18,1.00,{account.pk},,\n" for index in range(1001)
    )
    too_many = parse_csv_upload(upload((HEADER + data_rows).encode()), user=owner)
    assert "1000" in too_many.file_errors[0]

    other = User.objects.create_user("other-importer@example.com", "password")
    forbidden = parse_csv_upload(
        upload((HEADER + f"expense,Private,,Food,2026-09-18,1.00,{account.pk},,\n").encode()),
        user=other,
    )
    assert not forbidden.is_valid
    assert "you own" in " ".join(forbidden.row_errors[0]["errors"])


@pytest.mark.django_db
def test_csv_type_account_currency_matrix_and_malformed_bounds(
    import_data: tuple[User, Account, Category],
) -> None:
    owner, bank, _category = import_data
    card = Account.objects.create(
        name="Card",
        description="",
        account_type=Account.Type.CARD,
        owner=owner,
        currency=bank.currency,
    )
    euro = Currency.objects.create(code="EUR", name="Euro", country="European Union")
    euro_bank = Account.objects.create(
        name="Euro bank",
        description="",
        account_type=Account.Type.BANK,
        owner=owner,
        currency=euro,
    )

    def result(row: str) -> ImportPreview:
        return parse_csv_upload(upload((HEADER + row + "\n").encode()), user=owner)

    assert result(f"transfer,Valid,,Food,2026-09-18,1.00,{bank.pk},{card.pk},").is_valid
    assert not result(f"income,Bad,,Food,2026-09-18,1.00,{card.pk},,").is_valid
    assert not result(f"transfer,Bad,,Food,2026-09-18,1.00,{card.pk},{bank.pk},").is_valid
    assert not result(f"transfer,Bad,,Food,2026-09-18,1.00,{bank.pk},{euro_bank.pk},").is_valid
    assert not result(f"expense,Bad,,Food,2026-09-18,1.00,{bank.pk},{card.pk},").is_valid

    malformed = parse_csv_upload(upload((HEADER + 'expense,"unterminated').encode()), user=owner)
    assert "malformed" in malformed.file_errors[0].lower()
    too_long_name = result(f"expense,{'x' * 256},,Food,2026-09-18,1.00,{bank.pk},,")
    assert "255" in " ".join(too_long_name.row_errors[0]["errors"])
    too_long_description = result(f"expense,Name,{'x' * 2001},Food,2026-09-18,1.00,{bank.pk},,")
    assert "2000" in " ".join(too_long_description.row_errors[0]["errors"])


@pytest.mark.django_db
def test_worst_case_confirmation_has_bounded_queries(
    import_data: tuple[User, Account, Category], django_assert_max_num_queries: Any
) -> None:
    owner, account, category = import_data
    rows: list[dict[str, Any]] = [
        {
            "source_line": index + 2,
            "transaction_type": "expense",
            "name": f"Row {index}",
            "description": "",
            "category_name": category.name,
            "category_id": category.pk,
            "category": category.name,
            "date": "2026-09-18",
            "amount": "1.00",
            "account_id": account.pk,
            "account": account.name,
            "target_account_id": None,
            "target_account": None,
            "additional_data": {},
        }
        for index in range(1000)
    ]
    with django_assert_max_num_queries(7):
        assert confirm_import(user=owner, rows=rows) == 1000
    assert Transaction.objects.count() == 1000
