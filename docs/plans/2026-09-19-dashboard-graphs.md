# Dashboard graphs

## Summary

Turn the authenticated home page into a server-rendered financial dashboard with one income versus
expenses vertical bar graph and one expenses-by-category horizontal bar graph. A shared filter form
uses an inclusive UTC date range, accessible accounts of one currency, and categories. The page
uses Django, semantic HTML, and Tailwind CSS without JavaScript or a chart dependency.

## Goals

- Show exact income and expense totals for the selected period and accounts while excluding
  transfers.
- Show one expense bar for every selected category, including a zero-valued bar when that category
  has no matching expense.
- Apply one validated account and date dataset to both graphs, with a category filter applied only
  to the category graph.
- Permit owned and shared accounts under the existing account-access policy while preventing
  cross-currency aggregation and inaccessible-data disclosure.
- Keep exact values, currency, filter errors, and empty states understandable without relying on
  bar size, color, or JavaScript.

## Non-goals

- Currency conversion, exchange-rate data, or totals spanning currencies.
- Transfer totals, balance calculations, forecasts, comparisons with prior periods, or additional
  graph types.
- A JSON/reporting API, OpenAPI expansion, client-side framework, chart library, or custom
  JavaScript interaction.
- Persisted dashboard preferences, filter state in the session, exported graphs, or shareable
  filter URLs.
- Category management, schema changes, data migrations, background jobs, caches, or new indexes
  without measured evidence that the existing indexes are insufficient.

## User-visible behavior

The authenticated `/` page is the main dashboard. Its filter form has required start and end date
controls, a multiple account selector, a multiple category selector, and an **Apply filters**
button. The form submits a CSRF-protected POST to `/`; applying filters does not require JavaScript
and does not place financial filter selections in a URL or browser storage.

On an initial GET, start is the current application UTC date minus exactly 30 days and end is the
current application UTC date. The range is inclusive, so those defaults cover 31 calendar dates.
No account is selected. Every category is selected by default, including inactive categories.
Because no account is selected, both graph regions show a deliberate prompt to select at least one
account rather than totals or category bars.

An empty account selection remains valid and preserves that no-data state. One or more owned or
shared accounts may be selected, but all selected accounts must reference the same currency.
Selecting accounts with different currencies is invalid, retains the submitted controls, and shows
a field-associated correction message without calculating or displaying graphs.

For a valid nonempty account selection:

- the first graph has exactly two bars in stable order: **Income**, then **Expenses**;
- each bar is the exact sum of `Transaction.amount` for its matching transaction type, selected
  primary account, and inclusive `Transaction.date` range;
- transfers are excluded, including rows where a selected account is a transfer target;
- both bars remain present at zero when no matching transaction exists; and
- the selected accounts' common three-letter currency code appears with both textual two-decimal
  totals.

The second graph uses the same selected primary accounts and inclusive date range, considers only
expense rows, and then limits results to the selected categories. Every selected category gets one
bar, including a zero bar. Bars sort by total descending, then category name case-insensitively,
then original name and primary key for a fully deterministic tie-break. Inactive categories remain
selectable and visibly identified as inactive. Selecting no categories is valid and shows a clear
**No categories selected** state while leaving the income/expenses graph intact.

Each graph is a labelled `figure` or equivalent semantic region. Bar marks are decorative; the bar
label, exact amount, and currency are ordinary visible text so screen-reader and forced-colors users
receive the same information. Relative bar lengths use the largest value within that graph as 100%;
when every value is zero, all lengths are zero and the textual values remain present. The layout
stacks cleanly at small viewports, survives 200% zoom, has no chart-only horizontal page overflow,
and does not convey meaning by color alone.

Malformed dates, start dates after end dates, inaccessible or nonexistent accounts, nonexistent
categories, and forged selections render the bound form with generic usable errors. Account choice
validation is limited to `Account.objects.accessible_to(request.user)`, so an error does not reveal
whether an unselectable account exists. No aggregation runs for invalid input, and no prior or
partial result is displayed beside invalid filters.

## Decisions and assumptions

- `django.utils.timezone.now().date()` is the application UTC date because the project timezone is
  UTC. Tests patch the clock rather than depending on wall time.
- `Transaction.date`, not creation or update time, defines period membership. Both endpoints are
  included with `date__range` or equivalent `gte`/`lte` predicates.
- Dashboard totals sum stored positive two-decimal magnitudes. They do not reuse Bank/Card balance
  signs: an Expense is reported as positive spending and Income as positive income.
- Only the required `Transaction.account` is compared with selected accounts. Non-transfer rows
  have no target, and all transfer rows are excluded, so a transfer target never contributes.
- A valid selected account set establishes one display currency from its common `currency_id` and
  current currency code. No monetary rounding beyond the stored two-decimal values is introduced.
- Categories are the global admin-managed catalog. Initial selection includes every current row,
  not only active or historically used rows. A later GET picks up catalog additions; submitted
  selections are otherwise literal, including an empty selection.
- The requirement that no selected account yields a no-data state takes precedence over zero-bar
  filling. Zero category bars are produced after at least one valid account is selected; the
  dashboard does not imply that zero was aggregated when no currency dataset exists.
- Valid POSTs render the result directly with status 200. There is no state-changing domain action,
  no session persistence, and no redirect needed. Refresh may repeat the read-only aggregation.
- The backend calculates bounded numeric percentages from exact `Decimal` totals. Templates receive
  only normalized values between 0 and 100 for inline CSS dimensions; they never interpolate raw
  user input into CSS.
- No new dependency is needed. Existing account, category, transaction, date, amount, and index
  structures are sufficient for the first implementation.

## Scope and ownership

### Backend coder

The `backend_coder` exclusively owns these new paths:

- `src/backend/penni_more/dashboard/__init__.py`
- `src/backend/penni_more/dashboard/forms.py`
- `src/backend/penni_more/dashboard/services.py`
- `src/backend/tests/test_dashboard.py`

The backend coder also exclusively owns focused updates to:

- `src/backend/penni_more/views.py` to bind the dashboard form, invoke aggregation only for a valid
  nonempty account selection, and provide the fixed template context below; and
- `src/backend/tests/test_home.py` for authentication and integrated home-response expectations.

`DashboardFilterForm` owns the HTML trust boundary. It receives the request user; its account field
is a `ModelMultipleChoiceField` backed only by accessible owned/shared accounts with currency data
available for labels and validation. Its category field is a `ModelMultipleChoiceField` over all
categories. It validates required dates, inclusive ordering, and one shared `currency_id` across a
nonempty account selection. The initial factory derives both dates from one captured UTC `today`
value and selects all category primary keys while leaving accounts empty.

`services.py` owns immutable graph result objects and set-based aggregation. Given already validated
accounts, categories, and dates, it restricts transactions to selected primary account IDs and the
inclusive date range. One conditional aggregate query calculates the income and expense totals;
one grouped expense query calculates totals for selected categories. Missing groups are filled with
exact `Decimal("0.00")` values in memory. Category results are sorted by negative total, Unicode
casefolded name, original name, and primary key. Percentage scaling is deterministic, bounded to
0–100, derived without binary floating point, and independently normalized for each graph.

The backend/template context interface is fixed as:

- `dashboard_filter_form`: unbound with defaults on GET and bound to submitted data on POST;
- `filters_submitted`: whether the request is POST;
- `graphs_available`: true only for a valid submitted form with at least one account;
- `dashboard_currency_code`: the common selected currency code when graphs are available, otherwise
  `None`;
- `summary_bars`: an ordered two-item tuple of immutable objects exposing `label`, exact `amount`,
  and normalized `percentage` when graphs are available, otherwise empty; and
- `category_bars`: immutable objects exposing category identity, display label, exact `amount`, and
  normalized `percentage`; empty when graphs are unavailable or no category is selected.

The view may add a simple explicit flag for the no-category state if it keeps template branching
clear, but it must not move validation or aggregation policy into the template. Service code must
not accept arbitrary unvalidated IDs, and tests must confirm the view never invokes it for an
invalid form.

### Web GUI coder

The `web_gui_coder` exclusively owns focused updates to:

- `src/web/templates/home.html` for the filter form, accessible graph regions, exact values, and
  default, no-account, no-category, invalid, and result states;
- `src/web/tests/unit/shell.test.js` for changed home-template expectations;
- `src/web/tests/browser/home.spec.js` for reachable responsive, keyboard, and accessibility checks.

No `src/web/tailwind.css`, JavaScript, package manifest, or lockfile change is planned. Use existing
Tailwind/DaisyUI utilities, native date and multiple-select controls, visible labels and help text,
field-associated errors, an error summary where useful, and CSRF metadata. Render bar dimensions
from the backend's normalized numeric percentages only. Do not use SVG or ARIA graphics roles as a
substitute for visible text; keep decorative bar shapes hidden from assistive technology.

Backend service/form implementation and Web template implementation may proceed concurrently after
accepting the context interface above. Backend rendered-response tests depend on the updated
template before their final run. Each coder may read the other scope but must not edit it.

### Review, contract, documentation, and deployment

- `backend_reviewer` reviews the backend changes without editing them, focusing on authorization,
  exact Decimal sums, date boundaries, transfer exclusion, currency validation, tampered input,
  deterministic ordering, empty states, and bounded queries.
- `web_gui_reviewer` reviews the Web changes without editing them, focusing on semantics, visible
  exact values, field/error association, keyboard operation, zoom and responsive behavior,
  no-JavaScript use, and non-color communication.
- The `architect` reviews cross-scope consistency and confirms the OpenAPI artifact remains
  unchanged. No `contract_coder` assignment is required. Any discovered need for a JSON API must
  return to planning before contract or implementation work begins.
- Every actionable review finding returns to its owning coder. Review and focused verification
  repeat until both reviewers explicitly report no blocking findings. An issue may be deferred only
  with user or plan approval and a focused architect-owned `docs/tasks` artifact.
- After implementation and review, the architect writes the concise cycle report at
  `docs/reports/2026-09-19-dashboard-graphs.md`. The `deployment_agent` owns final validation, all
  local Git mutations and justified commits, and coordination of committing the report if needed.
  No `deploy/**` change is planned.

## Contract impact

There is no OpenAPI change. `src/contract/openapi.yaml` describes JSON health operations only; this
feature is an authenticated server-rendered HTML form and page. Adding a reporting operation would
create an unnecessary API surface and is outside the approved behavior.

The existing HTML route changes to this internal interface:

| Method | Path | Route name | Result |
| --- | --- | --- | --- |
| GET | `/` | `home` | Authenticated dashboard with unbound default filters and no graphs |
| POST | `/` | `home` | Authenticated validated filters and graphs, or bound validation errors |

Both methods retain the existing authentication requirement. POST requires CSRF protection.
Unsupported methods return 405 and never perform aggregation. The health JSON routes and all other
HTML routes are unchanged.

## Implementation sequence

1. The backend coder adds dashboard form tests, then implements UTC defaults, accessible
   owned/shared account choices, all-category initial choices, empty selections, date ordering, and
   common-currency validation in `dashboard/forms.py`.
2. The backend coder adds service tests and implements exact set-based summary and category
   aggregation, zero filling, stable sorting, and Decimal percentage scaling in
   `dashboard/services.py`.
3. In parallel once the context interface is accepted, the Web GUI coder replaces the home hero
   with the labelled dashboard filter and graph regions, including all empty/error states and
   visible exact amounts. The coder updates template and browser tests without adding JavaScript.
4. The backend coder updates the home view and request tests for GET defaults, POST results,
   authentication, CSRF, unsupported methods, invalid/tampered input, output escaping, and the
   agreed context. Run rendered-response tests after the Web template lands.
5. Both coders run `.codex/lint.sh` plus their scoped checks. The backend and Web GUI reviewers
   inspect the result. Coders resolve every actionable finding and rerun affected checks until both
   reviewers report no blocking findings.
6. The architect confirms context/template agreement, account visibility, financial semantics,
   graph scaling, no API/schema/dependency/deployment diff, and writes the cycle report after final
   results are known.
7. The deployment agent runs final validation, checks for unrelated or generated-artifact drift,
   creates justified local commit(s), and commits the report separately if sequencing requires it.

## Review and verification

### Backend review

Backend tests and review must demonstrate:

- one captured UTC date produces the exact 31-date default range, including month/year boundaries;
- GET selects every active and inactive category, selects no account, and performs no transaction
  aggregation;
- owned and shared accounts are available once, unrelated accounts are absent, and forged,
  nonexistent, or newly inaccessible IDs yield generic form errors and no result data;
- zero, one, or many same-currency accounts validate while a mixed-currency selection fails visibly;
- malformed/missing dates and `start > end` fail, while both endpoint dates are included exactly;
- summary totals include only selected primary accounts and the `income`/`expense` types, exclude all
  transfers and unselected accounts, preserve exact two-decimal arithmetic, and render two zero
  values for a valid dataset with no matches;
- category totals include expenses only, respect selected categories, include zero-valued selected
  categories, exclude unselected categories, and sort by the approved deterministic keys;
- no categories leaves the summary intact and produces no category bars; no accounts produces
  neither graph and never implies a currency or zero total;
- user/category names are escaped in rendered output, inactive categories are identified, and
  values and currency appear as text independently of CSS;
- summary aggregation is one query and category aggregation is one grouped query, with no per-row
  or per-category query growth for larger selections; and
- anonymous requests redirect to login, POST is CSRF protected, invalid POST returns usable status
  200 errors, and unsupported methods return 405.

Run and observe at minimum:

```text
.codex/lint.sh
./penni-more.sh check backend
uv run --project src/backend python src/backend/manage.py makemigrations --check --dry-run
```

Run focused dashboard tests while iterating through the repository's isolated PostgreSQL test
workflow. Do not claim a check or query bound without observing it.

### Web GUI review

Web tests and reviewer observation must demonstrate:

- the dashboard has a unique page title, one clear level-one heading, labelled filter and graph
  regions, logical source order, and no regression to navigation, identity, logout, or skip links;
- native date and multiple-select controls have visible labels, instructions, keyboard operation,
  retained bound values, and programmatically associated errors;
- the Apply form uses POST and CSRF, works with JavaScript disabled, and has an explicit submit
  label;
- default/no-account, invalid, no-category, all-zero, and ordinary result states are understandable
  without relying on color, bar length, or hidden content;
- both summary bars and every selected category bar expose label, exact two-decimal value, and
  currency as visible text, while bar shapes are decorative;
- long category/account labels, many category rows, phone and desktop viewports, 200% zoom, forced
  colors, and reduced motion remain usable without chart-induced page overflow;
- keyboard-only operation has visible focus and sensible order, and automated axe checks report no
  violations on reachable states; and
- no script, chart package, sensitive URL state, client storage, or unsafe rendered HTML is added.

Run and observe at minimum:

```text
.codex/lint.sh
./penni-more.sh check web
./penni-more.sh check integration
```

The existing integration harness has no authenticated financial-data fixture endpoint. Do not add a
test-only public endpoint. Keep dynamic authorization and aggregation assertions in Django response
tests, template semantics in Web unit tests, and browser automation to safely reachable states.
Record manual accessibility observations accurately without presenting an unrun scenario as an
automated pass.

### Contract and final validation

The architect verifies that `src/contract/openapi.yaml` has no diff and still accurately describes
the health-only JSON surface. If it changes, stop integration and route the change through
`contract_coder` and architect review under `api-standards`.

The deployment agent runs and observes:

```text
./penni-more.sh check all
```

Final inspection also confirms no model migration, dependency, generated lockfile, OpenAPI,
deployment, or unrelated change. Never report a check as passed unless its result was observed.

## Risks

- Accidentally reusing account-balance signs would invert expenses for Bank accounts or treat Card
  expenses differently. Dashboard aggregation must sum positive transaction magnitudes by type and
  remain separate from balance services.
- A transfer can involve a selected account in either role. An explicit type restriction before
  aggregation prevents either side from entering dashboard totals.
- Accepting arbitrary account IDs in a service or widening the form queryset could disclose private
  data. User-scoped model choices, generic invalid-choice errors, and view tests against forged and
  revoked access protect the boundary.
- Multiple currencies make a numeric total meaningless. Validate currency IDs before every query
  and derive the displayed code only from the validated nonempty selection.
- Filling absent categories after aggregation can drift from the submitted selection or become an
  N+1 path. Materialize the validated selection once, fetch grouped totals once, and fill by primary
  key in memory.
- Percentage calculations can lose money precision or emit unsafe CSS. Keep money as `Decimal`,
  normalize separately from displayed amounts, clamp the presentation percentage, and expose only
  controlled numeric output.
- A large category catalog can create a long page. A simple linear list is correct for the requested
  first version; pagination, category grouping, and virtualization would harm comparison or require
  new interaction and should be considered only after measured use.

## Completion criteria

- The authenticated home page exposes the approved default filters and two accessible,
  server-rendered graph areas with explicit Apply behavior and full no-JavaScript operation.
- Valid same-currency selections produce exact inclusive-date income, expense, and selected-category
  totals; transfers and unselected or inaccessible data never contribute.
- Summary output has exactly two ordered bars for a valid nonempty account dataset. Category output
  has exactly one deterministically ordered bar per selected category, including zero values; empty
  account and category selections have the approved distinct states.
- Currency and two-decimal totals are visible as text, and responsive, keyboard, zoom, forced-color,
  and screen-reader behavior meets the documented review conditions.
- Invalid dates, mixed currencies, and tampered account/category values retain safe input, show
  useful errors, run no aggregation, and disclose no inaccessible financial data.
- Backend and Web GUI reviewers report no unresolved blocking findings after all actionable findings
  are returned to and fixed by the owning coder.
- The architect reports cross-scope agreement and no OpenAPI/schema/dependency/deployment impact;
  any approved deferral has a focused task file and does not invalidate this feature.
- `.codex/lint.sh`, backend, Web, integration, migration-drift, and final `check all` commands pass
  with observed results.
- The deployment agent creates the justified local commit(s), and
  `docs/reports/2026-09-19-dashboard-graphs.md` records the outcome, review cycles, observed checks,
  deferred tasks, and commit identifiers.
