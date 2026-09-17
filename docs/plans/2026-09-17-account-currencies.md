# Account currencies

## Summary

Add a database-backed currency catalog managed through Django admin and require every account to
reference exactly one currency. Seed active CAD and BRL entries, including compact SVG flags stored
in the database, and migrate every existing account to CAD. Owners can select an active currency
when creating or editing an account; an account already using a retired currency may keep it or
move to an active currency.

Account pages show the currency's flag, code, and name. Flags are served as authenticated external
SVG image resources with restrictive response headers and are never inserted as inline markup.
This remains a server-rendered, no-JavaScript feature and adds no JSON API or OpenAPI operation.

## Goals

- Persist a minimal reusable currency catalog containing a unique uppercase three-letter code,
  display name, country, optional SVG flag content, and active/retired state.
- Require one non-null currency foreign key on every account and safely backfill existing accounts
  to CAD.
- Seed active Canadian dollar and Brazilian real rows, with database-resident initial SVG flags.
- Let appropriately permitted staff add, edit, retire, and, when unreferenced, delete currencies
  through the existing Django admin.
- Limit new account selections to active currencies while keeping an account's current retired
  currency available on that account's edit form.
- Show flag plus code and name on account create/edit, list, and detail pages, with a visible and
  accessible currency-code fallback when a flag is absent or cannot load.
- Validate uploaded SVGs and serve them with explicit security and caching behavior.
- Preserve account ownership, sharing authorization, bounded query behavior, CSRF protection, and
  operation without JavaScript.

## Non-goals

- Currency symbols, decimal precision, rounding, exchange rates, conversions, amounts, balances,
  transactions, or historical currency-change rules.
- A user-facing currency catalog page, catalog management outside Django admin, or a JSON API.
- Multiple currencies on one account, per-user currencies, locale-aware formatting, or automatic
  currency inference.
- Raster flag formats, remote flag URLs, media/object storage, data-URI images, or inline SVG.
- A general-purpose SVG sanitizer or arbitrary active SVG content.
- Deleting a currency that is referenced by an account, or automatically replacing references when
  a currency is retired.
- Account audit history or recording when and why its informational currency changes.

## User-visible behavior

- The account create form has a required **Currency** select listing active currencies only. Each
  option identifies the currency by code and display name; CAD and BRL are initially available.
- The account edit form normally lists active currencies. If the account currently uses a retired
  currency, that one retired value remains selectable and is labelled as retired, so an owner can
  save unrelated edits, keep it, or replace it with an active currency. No other retired currency
  can be submitted successfully.
- The account list adds a Currency column. The account detail adds a Currency definition. Both show
  a small flag when present and always show the code and display name as text.
- The adjacent textual code and name are the durable fallback when the image is absent or fails.
  Flag images are decorative with empty alternative text to avoid announcing the code twice.
- Existing accounts display CAD after migration. Currency remains editable because it is currently
  informational.
- Staff use Django's existing `/admin/` interface and normal model permissions to manage currencies.
  `is_active = false` means retired. Retired currencies remain attached to existing accounts.
- A referenced currency cannot be hard-deleted. Django admin may delete an unreferenced currency;
  retirement is the expected operation once a currency has been used.
- Admin flag upload is optional. A valid upload replaces stored flag content, an explicit clear
  control removes it, and leaving both untouched preserves the current flag. Invalid or oversized
  uploads produce a field error and do not change the row.

## Decisions and assumptions

### Currency model

- Add `Currency` to the existing `penni_more.accounts` application rather than creating another
  Django app. Currency currently exists only to classify accounts, so this is the smallest cohesive
  ownership boundary.
- Use these fields:
  - `code`: `CharField(max_length=3, unique=True)`;
  - `name`: required `CharField(max_length=100)`;
  - `country`: required `CharField(max_length=100)`;
  - `flag_svg`: blank-allowed `TextField` containing validated UTF-8 SVG text;
  - `is_active`: `BooleanField(default=True)`.
- Normalize `code` by stripping whitespace and uppercasing it before model validation/save. Add a
  named database check requiring exactly three ASCII uppercase letters. Add named non-blank checks
  for `name` and `country`, so direct ORM writes cannot create whitespace-only catalog metadata.
  The unique database constraint is the concurrency boundary for codes.
- Order currencies by code. Use a stable human-readable label of `CODE — Name`, adding
  `(retired)` when inactive. Country remains visible in admin but is not repeated on account pages.
- Store SVG text directly rather than Base64. It remains database-resident content, avoids Base64
  expansion and decode failure modes, and can be returned as the original validated UTF-8 bytes.
  Templates receive only the flag URL, never the stored markup.
- Add `Account.currency` as a non-null foreign key with `on_delete=PROTECT` and
  `related_name="accounts"`. This enforces exactly one currency and prevents deletion of a referenced
  catalog row at the persistence boundary. There is no model default after migration; all new
  account creation must choose a currency explicitly.

### Flag validation, storage, and response

- Put reusable upload validation in the backend accounts app and use only the Python standard
  library and Django; add no dependency. Limit decoded uploads to 64 KiB, require an `.svg` filename,
  reject an explicitly supplied content type other than `image/svg+xml`, require valid UTF-8, reject
  NUL bytes and case-insensitive `DOCTYPE` or `ENTITY` declarations, parse the XML, and require an
  SVG root element in the SVG namespace. A missing browser content type is not by itself a failure
  because content is validated independently.
- Treat the SVG as untrusted stored content even after structural validation. Do not call
  `mark_safe`, place it in a template, transform it into a data URI, or reuse it in an HTML response.
  The purpose of XML validation is to reject malformed/non-SVG uploads and parser hazards; browser
  containment comes from the separate image response and its headers.
- Add the authenticated, GET-only route
  `/accounts/currencies/<int:pk>/flag.svg`, named `accounts:currency-flag`. Return 404 for an unknown
  currency or empty flag, and `image/svg+xml; charset=utf-8` for a stored flag. IDs and currency
  metadata are not secret, but keeping the route under the normal login middleware matches all
  account pages and avoids introducing another public surface.
- Set `Content-Security-Policy: default-src 'none'; sandbox`,
  `X-Content-Type-Options: nosniff`, `Cross-Origin-Resource-Policy: same-origin`, and a safe inline
  filename through `Content-Disposition`. Set `Cache-Control: private, max-age=300` and an ETag
  derived from the stored bytes. A five-minute private cache bounds stale images after an admin
  replacement; tests need not require conditional-GET support unless it is deliberately added.
- Admin uses a custom model form with an upload-only `FileField` and a separate clear checkbox;
  `flag_svg` itself stays excluded from editable fields so raw SVG is never rendered into an admin
  textarea. The model admin lists code, name, country, active state, and whether a flag is present;
  it supports code/name/country search and active filtering. Any preview must use the external flag
  route and must not render stored SVG inline.

### Selection and rendering rules

- Extend `AccountForm` with `currency`. On create, its queryset is active currencies ordered by
  code. On edit, it is active currencies plus the instance's current currency, de-duplicated and
  ordered by code. The bound form queryset is the authorization boundary for crafted submissions:
  another retired currency is an invalid choice.
- Do not force a retired current value to change and do not reactivate it as a side effect. If the
  row is retired between form display and POST, Django must reject it unless it is still the
  account's current currency.
- Extend account list, accessible detail, and owner-only lookup querysets with
  `select_related("currency")`. Rendering several flags produces browser image requests but no
  per-account database query in the HTML response.
- Templates always render escaped `currency.code` and `currency.name`. When `flag_svg` is present,
  render a small `<img>` whose `src` reverses `accounts:currency-flag`; use fixed width/height,
  `loading="lazy"` on list rows, and `alt=""` because the adjacent visible code is the fallback and
  accessible name. Do not add JavaScript for image errors.

### Migration and seed behavior

- Use two migrations after the existing accounts `0001_initial` migration:
  1. `0002_currency_catalog` creates `Currency`, then runs a data migration that upserts CAD and BRL
     by code with active status, approved names/countries, and compact self-contained SVG text.
  2. `0003_account_currency` adds the account foreign key as nullable, assigns the CAD row to every
     account in one set-based update, and alters the field to non-null with `PROTECT`.
- Seed exactly `CAD / Canadian dollar / Canada` and `BRL / Brazilian real / Brazil`. Initial flag
  SVG strings live inside the historical migration so applying it never depends on runtime static
  files, package data, the network, or the current validator implementation. They must satisfy the
  same size, UTF-8, XML-root, and declaration restrictions as future uploads.
- The seed forward function uses `update_or_create(code=...)` for deterministic reruns in migration
  tests. Its reverse function removes only the two seeded codes. Reversing `0003` first removes the
  account foreign key, so reversing `0002` can remove the seed rows and table without violating
  references. The account backfill reverse function is a no-op because the field is removed while
  reversing that migration.
- Fail migration application clearly if CAD is unexpectedly absent before backfill; never leave
  existing accounts null or silently choose another currency. Migration tests must start from
  `0001_initial`, create an account through historical models, migrate forward, and prove the seed,
  flags, CAD backfill, and non-null relationship. Also exercise reverse migration on isolated test
  state.

## Scope and ownership

### Backend coder

The `backend_coder` exclusively owns these backend additions and updates:

- `src/backend/penni_more/accounts/models.py`
- `src/backend/penni_more/accounts/forms.py`
- `src/backend/penni_more/accounts/admin.py`
- `src/backend/penni_more/accounts/validators.py`
- `src/backend/penni_more/accounts/urls.py`
- `src/backend/penni_more/accounts/views.py`
- `src/backend/penni_more/accounts/migrations/0002_currency_catalog.py`
- `src/backend/penni_more/accounts/migrations/0003_account_currency.py`
- `src/backend/tests/test_accounts_models.py`
- `src/backend/tests/test_accounts_views.py`
- `src/backend/tests/test_accounts_admin.py`
- `src/backend/tests/test_accounts_migrations.py`

No change to `services.py`, settings, dependencies, or deployment files is planned. The backend
coder owns the persistence model, migration sequencing, seed SVG strings, admin registration and
upload form, validation, protected deletion, form choice policy, flag response, queryset loading,
and backend tests. The backend coder must update every account fixture/factory/direct creation and
form POST in its owned tests to supply a currency rather than weakening the non-null invariant.

### Web GUI coder

The `web_gui_coder` exclusively owns these Web GUI updates:

- `src/web/templates/accounts/account_form.html`
- `src/web/templates/accounts/account_list.html`
- `src/web/templates/accounts/account_detail.html`
- `src/web/tests/unit/accounts.test.js`
- `src/web/tests/browser/accounts.spec.js` only if existing reachable browser states need an
  assertion; do not add provisioning infrastructure solely to reach authenticated currency pages.

The Web GUI coder owns the select markup, field-linked errors, flag/code/name presentation,
responsive list column, textual fallback, and template tests. No JavaScript, stylesheet dependency,
or admin template override is planned.

Backend and Web GUI implementation may proceed concurrently after accepting the fixed interfaces
in this plan: form field `currency`, related object `account.currency`, optional
`currency.flag_svg`, and route name `accounts:currency-flag` taking the currency primary key.
Backend rendered-response tests require the updated templates before their final run.

### Review, contract, and deployment

- `backend_reviewer` reviews all backend paths above, including migration safety, admin permission
  behavior, upload validation, SVG response headers, form tamper resistance, deletion protection,
  query counts, and tests. The reviewer does not edit files.
- `web_gui_reviewer` reviews the three templates and Web tests for accessibility, responsive
  behavior, reliable textual fallback, semantic form/table structure, escaping, and no-JavaScript
  operation. The reviewer does not edit files.
- The `architect` performs the integrated cross-scope review and confirms the implemented internal
  route/form/template interfaces match this plan and the OpenAPI document remains unchanged.
- `contract_coder` is unnecessary. `src/contract/openapi.yaml` describes the health JSON API only;
  the account forms, Django admin, and authenticated SVG resource do not create a JSON contract
  consumed by a separate client.
- `deployment_agent` owns final repository validation, migration smoke checks, all local Git
  staging/commits, and the later report commit. No `deploy/**` change is expected.

## Contract impact

There is no OpenAPI change. The catalog is managed by Django admin, account changes use existing
HTML forms, and flags are authenticated image resources for server-rendered pages. Existing health
paths and schemas remain untouched.

The internal server-rendered interface changes are:

- `AccountForm` submits required `name`, optional `description`, required `account_type`, and
  required `currency`. Create accepts only an active currency. Edit accepts active currencies plus
  that account's current currency.
- Account list context still provides `accounts`; each account has its `currency` already loaded.
  Detail and edit context still provide `account`, with `account.currency` loaded.
- `GET /accounts/currencies/<currency-pk>/flag.svg` returns 200 SVG content with the headers defined
  above or 404 when the row/flag does not exist. Other methods return 405. Anonymous requests follow
  the existing login redirect behavior.
- Existing account create/update redirect, authorization, and error-rendering behavior is
  unchanged. A submitted inactive non-current currency returns status 200 with a bound field error
  and no persistence change.

## Implementation sequence

1. The backend coder adds `Currency`, constraints, normalization/display behavior, and
   `Account.currency`, then creates the two migrations exactly in the sequence above. Add focused
   migration tests before relying on current-model tests.
2. The backend coder adds currency model tests covering code normalization and uniqueness,
   database checks, blank metadata, active/retired labels, the required account relation, and
   `PROTECT` for referenced rows while allowing unreferenced deletion.
3. The backend coder implements SVG validation and the custom currency admin form/registration.
   Test add, replace, preserve, clear, malformed XML, non-SVG root, unsafe declaration, invalid
   UTF-8, wrong extension/content type, over-limit upload, active filtering, ordinary Django model
   permissions, and the protected deletion response. Superuser tests may cover the full happy path;
   a staff user with only the relevant currency permissions must remain scoped by Django admin.
4. The backend coder extends `AccountForm` and account query loading. Test active-only create,
   active edit, retained current retired currency, replacement with active currency, rejection of a
   different retired currency, and the retirement race between GET and POST.
5. The backend coder adds the flag route and response. Test authentication, GET-only behavior, 404
   cases, exact content type/body, content disposition, CSP, nosniff, same-origin resource policy,
   private cache policy, deterministic ETag, and absence of raw SVG from HTML responses.
6. In parallel with steps 1-5, the Web GUI coder adds the required select and currency presentation
   to the account form, list, and detail templates. Keep code/name visible regardless of the flag,
   use decorative external images only, and preserve existing labels, errors, focus treatment, and
   responsive wrappers.
7. Both coders update their owned regression tests and run the scoped checks. Backend tests retain
   bounded list/detail query assertions after adding currency. Web unit tests assert five list
   column headers, the currency field's error association/value preservation, external reversed
   image URLs, visible code/name fallback, empty `alt`, and no inline SVG or script.
8. Dispatch `backend_reviewer` and `web_gui_reviewer`. Return every actionable finding to the owning
   coder, rerun affected checks, and repeat review until both report no blocking findings.
9. The architect checks the integrated model/form/route/template interfaces, retired-currency
   behavior, cross-scope accessibility fallback, and unchanged OpenAPI surface.
10. The deployment agent runs final checks, applies migrations on a clean isolated database and a
    migration test state containing an account, inspects the diff for unrelated changes, and creates
    one or more justified local commits. Afterward, the workflow writes the concise feature report
    under `docs/reports`, which the deployment agent commits if separate.

## Review and verification

### Backend review

Tests and inspection must demonstrate:

- CAD and BRL are active, uniquely coded, correctly named/countried, and have valid non-empty SVG
  content after migration; an account created before the migrations becomes CAD-backed.
- Every current account has one currency, new ORM rows cannot omit it, and referenced currency
  deletion raises Django's protected-deletion behavior without changing data.
- Admin is available only through existing staff status plus normal add/change/delete/view model
  permissions. Upload errors are bound to the upload field and never persist partial updates.
- Retiring a currency preserves its accounts. Create and edit tampering cannot select disallowed
  retired currencies, while an edit that retains its own retired value succeeds.
- HTML list/detail queries remain bounded as account count grows and use `select_related` for both
  owner and currency. Flag retrieval is one intentional request per distinct image URL and does not
  add database queries to template rendering.
- Stored SVG text never appears inline or in form fields. The flag endpoint returns only validated
  content with all security/cache headers, and missing/cleared flags return 404.
- Existing owner/recipient/unrelated-user authorization, sharing, delete, CSRF, redirect, message,
  and escaping tests continue to pass with currency present.

Run and observe at minimum:

```text
.codex/lint.sh
./penni-more.sh check backend
uv run --project src/backend python src/backend/manage.py makemigrations --check --dry-run
```

The backend scoped check already runs formatting, lint, type checks, Django checks, missing-migration
checks, deploy checks, and the PostgreSQL-backed test suite. Do not claim migration reversibility
without observing the migration executor test.

### Web GUI review

Tests and reviewer observation must demonstrate:

- the required Currency control has a visible label, preserves its selected value, and associates
  validation errors programmatically;
- list and detail show code and name even with no flag, a missing response, or a broken image;
- flags use external URLs, fixed dimensions, empty alternative text, and never inline SVG/data URIs;
- the added list column remains understandable in the existing narrow-screen scroll region and has
  a programmatic header;
- pages retain unique titles, clear headings, keyboard focus visibility, escaped data, and complete
  operation with JavaScript disabled.

Run and observe at minimum:

```text
.codex/lint.sh
./penni-more.sh check web
./penni-more.sh check integration
```

Where the browser harness cannot provision authenticated account data, backend rendered-response
tests own dynamic selection/authorization behavior and Web unit tests own template semantics. Do
not add a public or test-only provisioning route for this feature.

### Contract and final validation

The architect or deployment agent runs the existing contract check to prove the unchanged document
still validates:

```text
./penni-more.sh check contract
```

The deployment agent then runs and observes:

```text
./penni-more.sh check all
```

Final inspection confirms there is no dependency, OpenAPI, deployment, or unexpected generated-file
diff and that the clean-database migration path contains the two seed rows and a non-null account
foreign key.

## Risks

- SVG is an active document format. XML structure checks alone are not a sanitizer, so safety relies
  on never embedding stored content and on the sandboxed, no-source CSP image response. A later use
  outside this exact response boundary requires a new security review.
- A 64 KiB database text field is small per currency but still operator-controlled. Enforce the
  limit before decoding/storing and cover it with a regression test.
- Retirement and edit policy can be bypassed by careless future forms or services. Keep the policy
  centralized in `AccountForm` for the current HTML boundary and test crafted POSTs.
- Migration seed names or SVGs become historical data. Future catalog corrections belong in a new
  migration or an explicit admin change; do not edit an already-applied migration after release.
- Adding a required foreign key affects every account fixture and direct ORM creation. Tests must
  supply explicit currency data rather than introduce an implicit runtime default.
- Adding a list column and flag may crowd small screens. Retain the existing horizontally scrollable
  table region and review at representative narrow widths.

## Deferred work

No follow-up task is required for the agreed scope. Symbols, precision, amount formatting, exchange
rates, transaction semantics, audit history, and a user-facing currency catalog remain intentionally
outside this feature and should be designed with the future money/transaction domain rather than
preemptively added now.

## Completion criteria

- Migrations seed active CAD and BRL with valid initial flags, migrate all existing accounts to CAD,
  and leave `Account.currency` non-null and protected.
- Django admin can add/change/retire currencies and safely upload, preserve, replace, or clear SVG
  content; referenced deletion is blocked and unreferenced deletion is allowed.
- Create accepts active currencies only. Edit additionally accepts only its own current retired
  currency, and currency changes persist without altering ownership or sharing behavior.
- Account form, list, and detail meet the agreed currency display and accessible fallback behavior
  with no JavaScript and no inline SVG.
- The authenticated flag route implements validation assumptions, 404/method behavior, exact media
  response, security headers, private caching, and ETag behavior.
- Backend and Web GUI reviewers report no blocking findings after any required repair cycles; the
  architect confirms cross-scope consistency and no OpenAPI impact.
- `.codex/lint.sh`, backend, Web, integration, contract, and final all-scope checks pass with observed
  results; migration forward/reverse coverage passes.
- The deployment agent creates the justified local commit or commits, and the completed cycle report
  is written under `docs/reports` and committed.
