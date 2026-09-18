# Transactions report

## Outcome

Penni More now has a server-rendered transaction ledger with calculated account balances,
account-aware authorization, private transfer-counterpart masking, filtering, pagination, and
atomic CSV preview and import. Expense, income, and transfer effects are validated against account
types and current currencies; balances remain derived from ledger rows rather than stored on
accounts.

The completed work follows the
[transactions implementation plan](../plans/2026-09-18-transactions.md). It adds no dependency,
deployment, or OpenAPI change.

## Changes

- Added transaction and admin-managed category persistence, database constraints, UTC audit fields,
  positive two-decimal amounts, structured additional data, and protected account relationships.
- Added centralized validation and single-statement PostgreSQL balance aggregation for the complete
  bank and card sign matrix, including future-date exclusion and integrity checks.
- Added authenticated transaction list, filter, detail, create, edit, delete, and CSV import routes
  with owner and shared-account policies, deterministic pagination, and private-counterpart masking.
- Added all-or-nothing CSV validation, server-side preview storage, explicit confirmation,
  confirmation-time revalidation, bounded file and row handling, and row-specific errors.
- Added calculated balances and transaction-history protections to account pages. Account details
  expose the CSV account ID; transaction selectors use that accessible ID to disambiguate otherwise
  identical accounts, while the account list remains ID-free.
- Added responsive, accessible templates and backend, Web unit, migration, and browser coverage.

## Review cycles

- The first review cycle found races between share revocation and transaction writes, stale or
  expired import-preview handling, privacy risks after confirmation-time access drift, unsafe
  concurrent transaction disappearance, incomplete currency presentation, and authorization and
  request-level coverage gaps. The owning coders added consistent account locking and revalidation,
  privacy-safe failed confirmation, preview cleanup, private 404 handling, accessible-side currency
  labels, and focused PostgreSQL and rendered-response tests.
- The second cycle confirmed those corrections and found that balance aggregation used multiple SQL
  statements, which could mix snapshots under PostgreSQL `READ COMMITTED`. It also identified
  unclear invalid-filter results and incomplete messaging and regression coverage. Balance
  calculation was replaced with one parameterized SQL statement, and the filter states, copy, and
  tests now distinguish retained prior filters from an unapplied invalid submission.
- The final cycle verified the single-snapshot sign and integrity semantics, import atomicity,
  locking, cross-scope contexts, privacy masking, and test coverage. Account selectors were then
  made unambiguous with the already user-visible CSV account ID, including identical-account cases,
  without exposing inaccessible counterparts or adding IDs to the account list. Backend, Web GUI,
  and architect reviewers reported no remaining blocking findings.

## Verification

- `./penni-more.sh check all` passed.
- `.codex/lint.sh` passed.
- Backend formatting, Ruff, mypy, Django system and deployment checks, and all 181 PostgreSQL pytest
  tests passed.
- Web formatting, ESLint, template checks, asset compilation, all 21 Vitest tests, and all 28
  Playwright tests passed.
- Migration drift detection passed. The transaction migration applied on a fresh database and was
  successfully reversed on isolated test data.
- Spectral reported no contract warnings, and the health-only OpenAPI contract remained unchanged.

## Deferred tasks

None.

## Commits

- Implementation: `014457e9ab269ea4e7e6f4bf0a1d450b75937d3d`
  (`feat: add transaction ledger`).
- This report requires a separate local commit by the deployment agent. No remote operation was
  performed.
