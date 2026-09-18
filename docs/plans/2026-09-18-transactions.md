# Transactions

## Summary

Add an authenticated, server-rendered Transactions feature backed by a mutable ledger. Expense,
income, and transfer rows are the sole source of account balances; no balance is stored on an
account. Current balances are aggregated from rows dated through the current UTC date and shown on
account list and detail pages.

The feature includes an admin-managed category catalog, structured additional data, transaction
CRUD with account-aware authorization, filtering and pagination, and an all-or-nothing CSV preview
and confirmation flow. It extends the existing account UI and protection rules without adding a
JSON API, JavaScript framework, dependency, balance cache, or OpenAPI operation.

## Goals

- Persist positive two-decimal transaction magnitudes and derive every balance effect from the
  transaction type and affected account type.
- Enforce the approved Bank/Card rules for expenses, income, and transfers at every manual and CSV
  write boundary.
- Calculate current Bank balances and Card amounts owed from ledger rows without persisting a
  balance or opening-balance field.
- Give users a private, accessible transaction list, detail, create, edit, delete, filter, and CSV
  import experience that works without JavaScript.
- Preserve ownership and sharing rules, including source-owner mutation authority for transfers
  and `Private account` masking for an inaccessible transfer counterpart.
- Protect account-type meaning and ledger history from account edits or deletion after an account
  participates in a transaction.
- Cover decimal, date, category, additional-data, authorization, privacy, atomicity, import,
  aggregation, migration, rendered-state, and accessibility behavior with PostgreSQL-backed tests.

## Non-goals

- Recurring or split transactions, attachments, exchange rates, or cross-currency transfers.
- CSV export, automatic duplicate detection, import idempotency, or content-based duplicate
  warnings.
- Immutable audit events, reversal entries, soft deletion, transaction version history, or a
  record of the replaced values after edit/delete.
- Stored opening balances, balance columns, balance caches, snapshots, statements, or background
  aggregation jobs.
- Credit limits, overdraft limits, available-credit calculations, or validation that prevents a
  negative balance.
- A currency snapshot on each transaction. Account currency remains editable and informational.
- JSON/REST transaction endpoints, OpenAPI expansion, or a JavaScript framework.
- User-managed categories, category CRUD outside Django admin, or category hierarchy.

## User-visible behavior

### Ledger and balances

- Every account starts at zero. Its current balance is calculated from the current transaction rows
  whose transaction date is on or before today's UTC date. A future-dated transaction appears in
  transaction views and month filters but has no balance effect until its date arrives.
- An Expense against a Bank account subtracts its amount. An Expense against a Card account adds
  its amount to the amount owed. Income is valid only against a Bank account and adds its amount.
- A Transfer has one Bank source and a distinct Bank or Card target. It subtracts from the source,
  adds to a Bank target, and subtracts from a Card target's amount owed. Both effects come from one
  row and are created, edited, or deleted atomically.
- Amount input is an unsigned positive magnitude with exactly two fractional digits. Bank balances
  may be negative, and a negative Card amount owed represents an overpayment.
- Account list and detail pages show the calculated current balance with the account's current
  currency code. Card pages label or explain it as an amount owed rather than available credit.
- Account detail shows the numeric primary key as **CSV account ID**. No account ID is added to the
  account list.

### Categories and transaction data

- Django admin is the only category-management interface. A category has a required display name
  and active/inactive state. Names are unique case-insensitively while preserving administrator
  capitalization.
- Every transaction requires a category. Inactive categories remain visible on history but cannot
  be selected for a new or edited transaction. Editing a transaction with an inactive category
  therefore requires choosing an active category. A referenced category cannot be deleted.
- A transaction also has a required nonblank name, optional description, date, amount, creator,
  UTC created/updated timestamps, and optional additional data. The creator and timestamps are
  system-managed and never accepted from a form or CSV.
- Additional data is entered manually as one `key = value` pair per line. Split each line on its
  first equals sign, trim both sides, allow equals signs in the value, and reject blank keys,
  blank values, malformed lines, or keys duplicated case-insensitively. An empty textarea means no
  additional data. Detail renders the pairs as a definition list or equivalent structure.
- Limit additional data to 25 pairs, each key to 100 characters, and each value to 500 characters.
  These bounds apply equally to manual forms and CSV input. Store keys with their submitted display
  case, but compare keys and values using case-insensitive exact matching.
- Transaction names are limited to 255 characters and descriptions to 2,000 characters. The
  amount uses 18 total decimal digits and two decimal places, allowing values from `0.01` through
  `9999999999999999.99`.

### Navigation, list, and filters

- Authenticated navigation has a **Transactions** tab linking to `/transactions/`. The page shows
  every transaction for which the user can access at least one affected account.
- The default list is unfiltered and ordered by transaction date newest first, then creation time
  newest first, then primary key newest first. It displays 50 rows per page.
- Each row shows name, category, date, and account. A non-transfer shows its affected account. A
  transfer shows source and target. Any counterpart the viewer cannot access is shown only as
  `Private account`, with no account name, primary key, link, owner, or hidden identifier emitted.
- Filters combine with AND: one accessible account, one calendar month, and an optional
  additional-data key/value pair. The account filter matches either transfer side. Month uses the
  date-only transaction date. Additional-data key and value must both be blank or both supplied and
  match case-insensitively after trimming.
- Filter submissions use a CSRF-protected POST and store the validated filter state in the user's
  server-side session, then redirect to the list. This keeps arbitrary additional-data values out
  of URLs. Pagination URLs contain only `page` and reuse the session filter. A separate POST clears
  the state. Initial or cleared state shows all accessible transactions. Losing access to a stored
  account filter clears that filter without exposing whether the account still exists.
- The list has useful filtered and unfiltered empty states plus **Add transaction** and **Bulk
  import CSV** actions. Successful POST operations use redirects and Django messages.

### Create, detail, edit, and delete

- The add form exposes type, name, description, category, date, amount, affected/source account,
  optional transfer target, and additional data. Date defaults to today's UTC date and future dates
  are allowed. The form works without dynamic JavaScript: it may show all fields and explain when
  the target is required; authoritative validation is server-side.
- Expense allows an accessible Bank or Card account. Income allows an accessible Bank account.
  Transfer allows an accessible Bank source and a distinct accessible Bank or Card target. Source
  and target currencies must currently match. Changing either account's informational currency
  later neither rewrites nor invalidates historical transfers.
- Detail shows all transaction data, including amount, affected accounts, description fallback,
  additional-data pairs, creator identity, and created/last-updated timestamps displayed as UTC
  until a future user timezone preference exists. A date is date-only and is never timezone
  converted.
- A user may create a non-transfer against an account they own or receive through sharing. A
  transfer creator must be able to access both accounts. The account owner may edit/delete a
  non-transfer even when a recipient created it; only the source-account owner may edit/delete a
  transfer. Other direct mutation requests return 404.
- An edit may move a non-transfer or transfer source only to another account owned by the editor;
  this prevents an owner-authorized edit from assigning mutation authority to an account they only
  receive through sharing. A transfer target may be any account the editor can access.
- If a transfer's current target later becomes inaccessible to the source owner, edit identifies it
  only as `Private account` and offers a non-identifying **Keep private account** choice. The server
  retains the target without putting its ID or name in HTML, or the editor may select a different
  accessible target. All update invariants, including current currency compatibility, are still
  revalidated. Delete remains available to the source owner.
- Delete has a confirmation page and requires a CSRF-protected POST. Editing replaces the row's
  current ledger effect and deletion removes it; neither action creates an audit or reversal row.
- A transfer is visible when the viewer can access either side. Its non-account transaction data
  remains visible, but each inaccessible side is masked as `Private account`. An unrelated user
  receives 404 from detail and all mutation routes.

### CSV import

- Import is owner-controlled. Every non-transfer `account_id` and every transfer source must be
  owned by the importer. A transfer target may instead be owned or shared, but must be accessible.
- The upload accepts a UTF-8 CSV, optionally with a UTF-8 BOM, no larger than 1 MiB and containing
  at most 1,000 nonblank data rows. Reject invalid UTF-8, NUL bytes, malformed CSV, an empty or
  header-only file, and any file over either limit. Blank physical lines may be ignored while error
  messages retain the CSV source line number.
- The first row must contain these exact headers in this exact order, with no missing, repeated, or
  extra columns:

  ```text
  type,name,description,category,date,amount,account_id,target_account_id,additional_data
  ```

- `type` uses exact lowercase `expense`, `income`, or `transfer`; date uses `YYYY-MM-DD`; amount has
  no sign or currency symbol and has exactly two fractional digits; account fields use positive
  integer IDs; category lookup is case-insensitive. `target_account_id` is required for transfers
  and blank otherwise. Optional blank `description` and `additional_data` cells are accepted.
- A nonblank `additional_data` cell is a JSON object whose keys and values must all be strings and
  obey the same trimming, blank, duplicate-case, count, and length rules as the manual form. The
  JSON parser must detect duplicate object keys before converting to a mapping, including keys that
  differ only by case. Arrays, scalars, nested objects, and non-string values are rejected.
- Upload performs validation only and renders a preview plus row-specific errors. Any error blocks
  confirmation; no transaction row is written. A valid preview displays normalized values and an
  explicit warning that importing identical data again creates duplicates.
- Store at most one active normalized preview in the authenticated user's database-backed Django
  session for 30 minutes. Address it with a cryptographically random token, bind it to that session,
  and send only the opaque token in the confirmation form. Do not place CSV contents in a URL,
  hidden field, cookie, browser storage, or log. A new preview replaces the previous one; expired or
  mismatched tokens fail safely and require another upload.
- Confirmation is a CSRF-protected POST. It revalidates every normalized row against current
  account access, account type/currency, active category, and all other invariants inside one
  database transaction before inserting anything. A drift failure creates no rows and returns
  row-specific errors. Success creates every row with the importer as creator.
- The preview token remains reusable until it expires or is replaced. Reconfirming it or importing
  the same file again intentionally creates duplicates; there is no idempotency key or automatic
  deduplication.

## Decisions and assumptions

- Add a cohesive `penni_more.transactions` Django application. A `Transaction` row is the current
  mutable ledger event, not an append-only event-sourcing record. Use stable lowercase
  `TextChoices` values `expense`, `income`, and `transfer`; the UI label is **Transfer**.
- Store the affected account or transfer source in required `account`, and the transfer target in
  nullable `target_account`. Both foreign keys use `PROTECT`, so an account that appears on either
  side cannot be deleted until those transactions are deleted. Require a target only for transfer,
  forbid it otherwise, and forbid equal source and target with named database constraints.
- Use `DecimalField(max_digits=18, decimal_places=2)` plus a positive database check. Custom form
  and CSV boundary fields enforce the exact two-digit input representation before converting to
  `Decimal`; code never uses binary floating point for money.
- Use `DateField` for the transaction date and timezone-aware `DateTimeField(auto_now_add=True)` /
  `DateTimeField(auto_now=True)` timestamps. The date default and balance cutoff are
  `django.utils.timezone.now().date()` under the project's UTC setting. Tests freeze or patch the
  clock at the boundary instead of depending on wall time.
- Store additional data as a PostgreSQL-backed Django `JSONField` containing only a flat JSON
  object. Add a database check that the JSON value is an object. The form/import parser enforces
  string values and case-insensitive key uniqueness. Filtering uses a parameterized PostgreSQL
  `jsonb_each_text` `EXISTS` expression comparing `lower(key)` and `lower(value)`; never interpolate
  user input into SQL. A balance cache or specialized normalized search index can be added only
  after measured need.
- `Category.name` is a trimmed `CharField(max_length=100)` with a nonblank database check and a
  PostgreSQL `UniqueConstraint` over `Lower("name")`. `Transaction.category` uses `PROTECT`.
  `Transaction.created_by` also uses `PROTECT` so required attribution is not silently erased.
- Add named checks for nonblank transaction/category names, positive amount, allowed type, transfer
  target shape, distinct accounts, and JSON-object shape. Cross-row account type, access, category
  activity, and currency equality remain service invariants and are repeated at every write
  boundary because database `CHECK` constraints cannot safely reference related rows.
- Add indexes supporting primary-account/date, target-account/date, and stable list ordering.
  Related foreign-key indexes remain available for category and creator filtering.
- Centralize visibility, type/account compatibility, amount/date/additional-data normalization,
  balance aggregation, and writes in queryset/service helpers. Views remain thin. Avoid one query
  per account, category, transaction, creator, or transfer side by using related-object loading and
  set-based balance annotations/aggregations.
- Current balance effects are derived with explicit conditional `Decimal` expressions. A Bank
  primary Expense is negative, Bank Income positive, any Transfer source negative, Card primary
  Expense positive, Bank transfer target positive, and Card transfer target negative. Invalid
  combinations must never be silently assigned a sign.
- Account currency is deliberately not snapshotted. Amounts and calculated balances use the
  account's current currency label. A later currency edit may leave the two accounts on an old
  transfer with different labels; this is accepted informational behavior. Creating or updating a
  transfer still requires the two current currency IDs to match.
- Preserve 404 non-disclosure for inaccessible records. Authorization is enforced by object
  querysets/services, never only by hidden template controls. User content remains autoescaped and
  financial values are not logged.
- All writes use Django forms or explicit CSV validation, CSRF protection, `transaction.atomic()`,
  and post/redirect/get after success. No new Python or npm package is needed.

### Concurrency and locking

- Transaction create/update/import services lock every participating `Account` row with
  `select_for_update()` in ascending primary-key order, then lock referenced categories in
  ascending primary-key order, and recheck access, type, currency, and activity under the lock.
  Update/delete also lock the transaction row before changing it. Imports acquire each distinct
  account/category lock once and insert only after every row passes revalidation.
- Account update and delete services lock the account row before rechecking transaction
  participation. Account type changes are rejected once any transaction references the account as
  primary/source or target. Name, description, and currency remain editable. Account model
  validation/save guards the type rule for direct ORM/admin-style writes, while locked services
  serialize Web writes with transaction creation.
- Account deletion rechecks participation while holding the account lock and returns a useful
  non-destructive error instead of leaking `ProtectedError`. The foreign-key `PROTECT` constraints
  remain the final race-safe guard. Share revocation is unaffected and may make a transfer
  counterpart private without changing its ledger effects.
- A category deactivation concurrent with a transaction write serializes on the category row. A
  transaction committed before deactivation becomes valid history; a write that observes the
  inactive category is rejected.

## Scope and ownership

### Backend coder

The `backend_coder` exclusively owns these new backend paths:

- `src/backend/penni_more/transactions/__init__.py`
- `src/backend/penni_more/transactions/apps.py`
- `src/backend/penni_more/transactions/admin.py`
- `src/backend/penni_more/transactions/models.py`
- `src/backend/penni_more/transactions/forms.py`
- `src/backend/penni_more/transactions/services.py`
- `src/backend/penni_more/transactions/imports.py`
- `src/backend/penni_more/transactions/urls.py`
- `src/backend/penni_more/transactions/views.py`
- `src/backend/penni_more/transactions/migrations/__init__.py`
- `src/backend/penni_more/transactions/migrations/0001_initial.py`
- `src/backend/tests/test_transactions_models.py`
- `src/backend/tests/test_transactions_views.py`
- `src/backend/tests/test_transactions_imports.py`
- `src/backend/tests/test_transactions_admin.py`
- `src/backend/tests/test_transactions_migrations.py`

The backend coder also exclusively owns focused updates to:

- `src/backend/penni_more/settings/base.py` to install the transactions application;
- `src/backend/penni_more/urls.py` to include its namespaced routes;
- `src/backend/penni_more/accounts/models.py`, `forms.py`, `services.py`, and `views.py` for
  transaction participation checks, type locking, protected deletion, set-based balances, and the
  account contexts consumed below;
- `src/backend/tests/test_accounts_models.py`, `test_accounts_views.py`, and
  `test_accounts_admin.py` where transaction history changes existing account behavior.

Generate the initial migration with Django. Do not hand-edit generated structure except when a
reviewed PostgreSQL-specific JSON constraint cannot be expressed accurately by the generator; any
such migration operation must retain reversible state operations. No seed category or existing-data
backfill is required because the new transaction table starts empty. Existing accounts remain valid
and start with a calculated zero balance.

The backend coder owns the domain models, querysets, aggregation, form boundaries, import parser and
session preview, locking services, routes, views, category admin, contexts, and backend tests. The
backend coder must not edit templates, OpenAPI, deployment files, or dependency manifests.

### Web GUI coder

The `web_gui_coder` exclusively owns these new Web GUI paths:

- `src/web/templates/transactions/transaction_list.html`
- `src/web/templates/transactions/transaction_detail.html`
- `src/web/templates/transactions/transaction_form.html`
- `src/web/templates/transactions/transaction_confirm_delete.html`
- `src/web/templates/transactions/transaction_import.html`
- `src/web/templates/transactions/transaction_import_preview.html`
- `src/web/tests/unit/transactions.test.js`
- `src/web/tests/browser/transactions.spec.js`

The Web GUI coder also exclusively owns focused updates to:

- `src/web/templates/base.html` for the authenticated Transactions navigation tab;
- `src/web/templates/accounts/account_list.html` and `account_detail.html` for current balance and
  the detail-only CSV account ID;
- `src/web/templates/accounts/account_form.html` and `account_confirm_delete.html` for type-lock and
  transaction-history deletion messages/states;
- `src/web/tests/unit/accounts.test.js`, `shell.test.js`, and existing browser tests where the
  integrated account or navigation behavior changes.

Templates use existing Tailwind/DaisyUI patterns, semantic tables/definition lists, responsive
horizontal containment, visible labels, field-linked errors, clear focus, useful empty/error/success
states, and real CSRF-protected forms. Core CRUD, filter, clear, upload, preview, confirmation, and
pagination behavior must work with JavaScript disabled. No JavaScript or dependency is planned.

Backend domain implementation and template construction may proceed concurrently after accepting
the fixed route, form, and context interfaces below. Backend rendered-response tests depend on the
templates before their final run. The Web coder may read backend interfaces but must not implement
or alter them.

### Review, contract, documentation, and deployment

- `backend_reviewer` reviews all backend changes, including migrations, database constraints,
  service boundaries, authorization/privacy, Decimal behavior, SQL parameterization, query growth,
  row locking, rollback behavior, session preview safety, admin behavior, and tests without editing
  them.
- `web_gui_reviewer` reviews templates and Web tests for information disclosure, semantically and
  accessibly named controls, responsive tables, error association, keyboard flow, no-JavaScript
  operation, filter persistence, preview clarity, and account integration without editing them.
- The `architect` reviews integrated cross-scope behavior and confirms the OpenAPI artifact remains
  unchanged. No `contract_coder` assignment is required unless implementation discovers a real JSON
  API requirement, which must return to planning rather than being added silently.
- The architect writes the final concise cycle report under
  `docs/reports/2026-09-18-transactions.md` after reviews and observed checks are complete. Any
  legitimate non-blocking deferral requires a focused architect-owned file under `docs/tasks` and
  explicit user/plan approval; agreed transaction behavior cannot be silently deferred.
- `deployment_agent` owns final repository validation and every local Git mutation/commit,
  including committing the report if separate. No `deploy/**`, shell script, dependency manifest,
  or lockfile change is planned.

## Contract impact

There is no OpenAPI impact. `src/contract/openapi.yaml` currently describes only public/internal
JSON health operations. Transactions, category admin, filter state, account balances, and CSV import
are authenticated server-rendered HTML/session interfaces, so documenting them as JSON operations
would inaccurately expand the API surface.

The internal HTML route interface is:

| Method | Path | Route name | Authorization and result |
| --- | --- | --- | --- |
| GET | `/transactions/` | `transactions:list` | Authenticated; accessible rows, active session filters, 50/page |
| POST | `/transactions/filters/` | `transactions:filters` | Authenticated; validate/store filters, then redirect |
| POST | `/transactions/filters/clear/` | `transactions:filters-clear` | Authenticated; clear filters, then redirect |
| GET, POST | `/transactions/new/` | `transactions:create` | Authenticated; create against approved accessible accounts |
| GET | `/transactions/<int:pk>/` | `transactions:detail` | Access to either affected account; otherwise 404 |
| GET, POST | `/transactions/<int:pk>/edit/` | `transactions:update` | Affected owner/source owner only; otherwise 404 |
| GET, POST | `/transactions/<int:pk>/delete/` | `transactions:delete` | Affected owner/source owner only; GET confirms, POST deletes |
| GET, POST | `/transactions/import/` | `transactions:import` | Authenticated; GET upload, POST validate and preview only |
| POST | `/transactions/import/confirm/` | `transactions:import-confirm` | Authenticated; revalidate token payload and atomically import |

`TransactionForm` submits `transaction_type`, `name`, `description`, `category`, `date`, `amount`,
`account`, `target_account`, and `additional_data`. It receives the request user and create/edit
mode so account/category choices cannot be widened by a forged value. `TransactionFilterForm`
submits `account`, `month`, `additional_key`, and `additional_value`. Import submits `csv_file`;
confirmation submits only `preview_token`. Creator, timestamps, signs, and balance effects are never
submitted fields.

The list context provides a Django `Page` as `page_obj`, bound `filter_form`, `filters_active`, and
presentation rows whose account references are already masked/linked for the current viewer. Detail
provides `transaction`, presentation-safe source/target values, structured additional-data pairs,
`can_edit`, and `can_delete`. Form pages provide `form`, `mode`, and optional `transaction`; delete
provides the transaction presentation. Import preview provides normalized presentation rows,
row/file errors, and `preview_token` only when confirmation is allowed.

Account list context adds a set-based calculated balance per account. Account detail adds one
calculated balance, `csv_account_id`, `has_transactions`, `account_type_locked`, and
`can_delete_account` or equivalent explicit presentation values. Do not make templates issue
per-row balance queries or infer delete/type policy themselves.

Successful create/update redirects to transaction detail; delete redirects to transaction list;
filter/clear redirects to transaction list; import confirmation redirects to transaction list with
the imported row count. Invalid normal forms and upload preview render status 200 with bound errors.
Inaccessible objects return 404. Expired/mismatched preview tokens render a non-disclosing form
error and require a fresh upload. Unsupported methods return 405 and never mutate state.

## Implementation sequence

1. The backend coder creates the transactions app and implements `Category`, `Transaction`, choices,
   constraints, indexes, normalization, visibility querysets, and the initial migration. Add focused
   migration/model tests before building views.
2. The backend coder implements pure validation/effect helpers and set-based balance aggregation.
   Cover every valid and invalid Bank/Card/type/role combination, positive two-place magnitude
   bounds, future cutoff, negative totals, card overpayment, transfer double effect, currency rules,
   JSON shape, case-insensitive additional-data matching, and stable ordering.
3. The backend coder implements locked create/update/delete services and integrates transaction
   participation with account update/delete. Cover source/target/category locks, atomic rollback,
   concurrency-relevant rechecks, type immutability, editable currency, `PROTECT`, creator
   attribution, and mutation authority.
4. The backend coder adds category admin and tests case-insensitive concurrent uniqueness, trimming,
   active state, ordinary Django model permissions, inactive-category history, and a useful
   protected-delete response.
5. The backend coder implements transaction/filter forms, namespaced routes, thin views, pagination,
   privacy-safe presentation, and account balance contexts. Test anonymous redirects, CSRF/methods,
   every owner/recipient/unrelated matrix, 404 non-disclosure, private counterpart masking in both
   context and HTML, session filter behavior, query bounds, escaped content, and redirects/messages.
6. In parallel after the fixed interfaces are accepted, the Web GUI coder builds transaction pages,
   navigation, and account-page updates. Include unfiltered/filtered empty states, 50-row
   pagination, preserved filter controls, private-account text, structured details, inactive
   history labels, bound form errors, delete confirmation, upload constraints, preview errors, and
   duplicate warning.
7. The backend coder implements the bounded CSV parser and session preview, then confirmation-time
   locked revalidation/insertion. Test encoding/BOM, headers/order, quoting, blank files/lines,
   row/byte limits, all field errors, JSON duplicate detection, authorization, validation drift,
   expiry/replacement/token mismatch, all-or-nothing rollback, repeat confirmation duplicates, and
   bounded queries for 1,000 rows.
8. Both coders run `.codex/lint.sh` and their scoped checks. The backend and Web GUI reviewers
   inspect their owned scopes. Every actionable finding returns to its owning coder; checks and
   review repeat until both reviewers explicitly report no blocking findings.
9. The architect compares models, services, routes, forms, contexts, templates, privacy masking,
   aggregation signs, import behavior, and account changes with this plan. Confirm there is no
   contract/dependency/deployment diff and no cross-scope rule was reinterpreted.
10. The deployment agent runs final checks against the isolated PostgreSQL workflow, verifies clean
    migration state and migration from both an empty database and the current pre-feature schema,
    creates justified local commit(s), and commits the final report if it is written separately.

## Review and verification

### Backend review

Tests and review must demonstrate:

- Database constraints reject blank names, nonpositive/out-of-range amounts, unknown types,
  malformed target shape, same-account transfers, non-object additional data, and duplicate
  case-insensitive category names. Related deletion protection and migration reversibility behave as
  documented.
- Every valid type/account combination produces exactly the approved sign on each affected account;
  invalid Income/Card, transfer source/Card, same-account, and current cross-currency combinations
  are rejected consistently by manual and CSV writes.
- Balance aggregation includes edits, excludes deleted and future-dated rows, includes today's UTC
  rows, gives one atomic row two transfer effects, starts at exact Decimal zero, permits negatives,
  and performs a bounded number of queries for many accounts.
- Account type changes and account deletion are refused after participation on either transfer side,
  including race-safe service rechecks. Currency updates remain allowed and do not rewrite history.
- Visibility includes either accessible transfer side once. Private counterpart name, ID, owner,
  link, and form value never reach an unauthorized response. Owner/recipient/unrelated view, create,
  edit, delete, import, and direct-request permissions exactly match this plan.
- Category selection is active-only on create/edit/import, category matching is case-insensitive,
  historical inactive labels still render, and protected deletion is handled without a server error.
- Additional-data parsing trims values, detects malformed/blank/over-limit/duplicate-case input,
  permits equals signs in manual values, and performs parameterized case-insensitive exact
  filtering.
- Date defaults and cutoff are UTC-stable; future dates remain listable; created/updated/creator are
  server-managed; update preserves creator and created timestamp while advancing updated timestamp.
- Filtering combines all predicates, transfer account matching covers either side, filter state does
  not enter URLs, stale access is handled privately, ordering is deterministic, and pagination is
  50 rows with no skipped/duplicated rows for stable data.
- CSV preview writes nothing and reports source row numbers. Confirmation revalidates and inserts
  all rows or none, forged/expired/replaced tokens fail, preview content stays server-side, repeated
  valid confirmation creates duplicates, and worst-case allowed input has bounded memory/query
  behavior.
- State changes are CSRF-protected POSTs, successful operations use PRG/messages, invalid operations
  preserve safe values and errors, unsupported methods do not mutate, and user content is escaped.

Run and observe at minimum:

```text
.codex/lint.sh
./penni-more.sh check backend
```

Also run focused tests while iterating through the isolated project test environment, and observe:

```text
uv run --project src/backend python src/backend/manage.py makemigrations --check --dry-run
```

reports no missing model changes. Do not claim a concurrency behavior solely from mocks; use
PostgreSQL transaction-aware tests for rollback/locking-sensitive cases where deterministic
orchestration is practical.

### Web GUI review

Tests and reviewer observation must demonstrate:

- authenticated primary navigation contains one Transactions link without regressing Accounts,
  identity, logout, narrow viewport behavior, or keyboard focus;
- transaction list, empty, filtered-empty, detail, create, edit, delete, upload, invalid preview,
  and valid preview states have unique titles, one clear primary heading, landmarks, logical focus,
  and meaningful status/error content;
- tables have programmatic headers and narrow-screen containment; pagination identifies current
  position and exposes keyboard-operable previous/next links only when available;
- all fields have visible labels and field-linked errors, preserve safe submitted values, explain
  type-dependent requirements, and do not rely on color or JavaScript;
- private counterparts render only `Private account`, never an identifier-bearing link/value, while
  accessible account names are clear; edit/delete controls exist only in authorized markup;
- details use semantic structures for all fields and additional data, timestamps state UTC, future
  dates are not misleadingly presented as already affecting current balance, and Card balance copy
  says amount owed;
- filter and clear, delete, import confirmation, and every mutation are real POST forms with CSRF
  metadata and explicit button labels; CSV upload has the correct multipart encoding;
- account list/detail show exact calculated values and currency labels, the CSV ID appears only on
  detail, and transaction history produces clear disabled/error states for type change/deletion;
- duplicate-import warning and all-or-nothing behavior are understandable before confirmation; and
- axe reports no violations on reachable states, keyboard-only flows work, and disabled JavaScript
  leaves every core task operable.

Run and observe at minimum:

```text
.codex/lint.sh
./penni-more.sh check web
./penni-more.sh check integration
```

Do not add a public or test-only data-provisioning endpoint for browser tests. Where authenticated
financial states are unreachable in the existing Playwright harness, backend rendered-response
tests own dynamic policy/privacy behavior and Web unit tests own template semantics. Record manual
review observations without claiming an unrun automated scenario.

### Contract and final validation

The architect verifies `src/contract/openapi.yaml` has no diff and remains an accurate health-only
JSON contract. If it changes unexpectedly, stop integration and route it through `contract_coder`
plus architect review under `api-standards` before proceeding.

The deployment agent runs and observes:

```text
./penni-more.sh check all
```

Final validation also confirms the migration applies from the current account-currency schema and
from an empty database, reverses on isolated test data where practical, leaves
`makemigrations --check --dry-run` clean, and introduces no dependency, OpenAPI, deployment, or
unrelated diff. Never report a check as passed unless its output was observed.

## Risks

- Balance sign logic spans transaction type and both account roles. Centralized effect expressions
  plus a complete truth-table test matrix prevent list/detail/account calculations from drifting.
- Cross-model invariants cannot be fully represented by database checks. Row locks, repeated service
  validation, final foreign-key constraints, and PostgreSQL transaction tests limit race windows.
- Mutable currency can make an old transfer's current account labels differ. This is intentional
  because currency is informational; no exchange-rate or snapshot semantics should be inferred.
- JSONB case-insensitive pair search cannot use a simple key lookup or ordinary GIN index. Keep SQL
  parameterized and query plans bounded; defer a normalized search table/cache until measurements
  justify the added model.
- A shared recipient can create an effect that only the owner can later mutate. Creator attribution,
  explicit detail copy, and the confirmed owner policy make that authority visible.
- Revoked sharing can hide a transfer target from its source owner while leaving mutation authority.
  The non-identifying keep sentinel must be resolved server-side and never leak the private key.
- CSV parsing and preview can amplify memory, query, and session storage. Enforce
  byte/row/field/pair bounds before persistence, replace rather than accumulate previews, use opaque
  tokens, and batch lookup/locking instead of per-row queries.
- Repeat confirmation intentionally creates duplicates. Clear warning and PRG reduce accidents, but
  the behavior must not be disguised as idempotent.
- Pagination over mutable rows can shift during concurrent edits/inserts. Stable ordering prevents
  ambiguity for a fixed dataset; cursor pagination is unnecessary at this scale and out of scope.

## Completion criteria

- The approved models, migration, constraints, account protections, UTC fields, Decimal rules,
  aggregation, category admin, forms, routes, views, templates, filter state, pagination, and CSV
  preview/confirmation behavior are implemented in their owned scopes.
- Every approved authorization and privacy case works through direct requests as well as rendered
  controls, including either-side transfer visibility and complete inaccessible-counterpart masking.
- Current balances are derived only from ledger rows through today's UTC date, match the full sign
  matrix, and appear with current currency labels on both account list and detail without hidden
  per-row query growth or persisted balance state.
- Manual and CSV writes share the same domain invariants; transfers and imports are atomic;
  confirmation-time drift produces zero partial rows; repeated valid imports may duplicate.
- Account type and deletion are protected after any transaction participation, while currency edits,
  negative balances, future dates, and removal of unrelated shares remain supported.
- Backend and Web GUI reviewers report no unresolved blocking findings after all actionable findings
  are returned to and fixed by the owning coder.
- The architect reports cross-scope agreement and no OpenAPI change; any approved deferral has its
  own task file and does not invalidate this feature.
- `.codex/lint.sh`, scoped backend/Web/integration checks, clean migration detection, and
  `./penni-more.sh check all` pass with observed results.
- The deployment agent creates the justified local commit(s), and the final report records the plan,
  implementation, review iterations, observed verification, deferred tasks, and commit identifiers.
