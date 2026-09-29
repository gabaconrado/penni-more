# Statement transaction mapping

## Row boundary

Every detected posted statement transaction produces exactly one CSV row with the same settled
value. Never split, merge, synthesize, or exclude a posted transaction. Explicit fee and interest
lines are their own rows. Separately show opening/closing balances, totals, pending items, and
informational lines as exclusions with reasons.

Use the positive absolute settled amount in the statement account currency, formatted with exactly
two decimals. Preserve the signed source amount in the finalization envelope: debits are negative
and credits are positive. Prefer the transaction/purchase date; when only the posting date exists,
use it and include a short `additional_data` pair saying that the posting date was used.

For foreign-currency transactions, use the final settled account-currency value. Include original
amount/currency, exchange details, or an embedded fee in `additional_data` only when explicitly
available and useful. Do not copy the original statement descriptor merely for traceability.

## Types and account direction

- `expense`: negative statement effect; the configured owned statement account is `account_id`.
- `income`: positive statement effect; the configured owned statement account is a bank account and
  is `account_id`.
- outgoing `transfer`: negative effect; statement account is `account_id` and the other configured
  account is `target_account_id`.
- incoming `transfer`: positive effect; the other configured owned bank account is `account_id` and
  the statement account is `target_account_id`.

Use `transfer` only when both sides are configured. External movements remain `expense` or `income`.
Transfer source and target differ, use the same currency, and the source is a bank account. A
non-transfer source must be owned; any transfer target may be owned or accessible.

## CSV and final envelope

The UTF-8 CSV header is exactly:

```text
type,name,description,category,date,amount,account_id,target_account_id,additional_data
```

Rows require a configured category, ISO `YYYY-MM-DD` date, amount `0.01` through
`9999999999999999.99`, name at most 255 characters, and description at most 2,000 characters.
`additional_data` is blank or a compact JSON object with at most 25 nonblank string pairs; keys are
unique without case and at most 100 characters, values at most 500.

Pipe the approved envelope below to `finalize`. Values shown here are conspicuously fictional:

```json
{
  "source_account": "fictional-main",
  "output_basename": "fictional-statement.csv",
  "expected_config_hash": "current hash",
  "expected_patterns_hash": "current hash",
  "expected": {"count": 1, "debit_total": "12.34", "credit_total": "0.00"},
  "entries": [
    {
      "ordinal": 1,
      "signed_amount": "-12.34",
      "row": {
        "type": "expense",
        "name": "Fictional Service",
        "description": "Fictional purpose",
        "category": "Fictional category",
        "date": "2042-01-02",
        "amount": "12.34",
        "account_id": 101,
        "target_account_id": null,
        "additional_data": {}
      }
    }
  ],
  "proposed_patterns": {"schema_version": 1, "rules": []}
}
```

Ordinals must be consecutive from one. The helper checks each amount and direction, row count, and
debit/credit totals before staging either file. The basename must end in `.csv`, contain only safe
ASCII filename characters, and must not already exist.
