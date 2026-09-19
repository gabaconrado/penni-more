# Dashboard graphs report

## Outcome

The authenticated home page is now a financial dashboard with accessible, server-rendered income
versus expenses and expenses-by-category graphs. Shared date and account filters enforce an
inclusive UTC period and one currency, while category selection controls the category graph. The
implementation follows the approved [dashboard graphs plan](../plans/2026-09-19-dashboard-graphs.md)
without adding JavaScript, a chart dependency, schema changes, or an OpenAPI operation.

## Changes

- Added a user-scoped Django filter form with 30-days-ago-through-today defaults, accessible owned
  and shared account choices, all-category defaults, date ordering, and same-currency validation.
- Added exact `Decimal` aggregation for income, expenses, and selected expense categories. It uses
  inclusive transaction dates, excludes transfers, fills missing category totals with zero, and
  produces deterministic ordering and decorative bar percentages.
- Updated the authenticated home view to render results only for a valid nonempty account selection
  and to preserve safe bound form errors and deliberate empty states.
- Replaced the home hero with responsive, text-first graphs and labelled native filter controls.
  Exact two-decimal amounts and currency remain visible independently of bar size or color.
- Added backend request, validation, authorization, privacy, query-bound, escaping, and aggregation
  coverage, plus Web template and browser accessibility coverage.

## Review cycles

- The Web GUI review found one blocking missing state when the user had no accessible accounts. The
  Web implementation added a distinct **No accounts available** state; re-review found no remaining
  blocking issues.
- The backend review found three blocking test gaps covering request-level tampering, privacy, and
  shared-account cases; literal category filtering plus nontrivial percentage and query behavior;
  and rendered defaults, escaping, textual totals, and no-category behavior. The backend tests were
  expanded from 189 to 195 cases; re-review found no remaining blocking issues.
- The architect cross-scope review confirmed form, service, view, and template agreement, financial
  semantics, authorization and privacy behavior, and an unchanged health-only OpenAPI contract.
  No blocking or actionable findings remained.

## Verification

The following were observed passing:

- `.codex/lint.sh`;
- final `./penni-more.sh check all`;
- 195 backend tests, Ruff formatting and linting, mypy, Django system and deployment checks, and no
  pending migration changes;
- 23 Web unit tests, Prettier, ESLint, template linting, and the Tailwind build;
- 32 Playwright tests across the configured desktop and mobile Chromium projects; and
- OpenAPI contract validation, integration checks, deployment checks, and documentation checks.

The integration harness has no authenticated financial-data fixture. Authenticated dynamic graph
states, retained bound selections, 200% zoom, and forced-colors behavior were therefore not directly
browser-automated; Django response tests and Web template tests cover their underlying state and
markup. The template's account-availability branch performs a bounded queryset existence check; it
does not introduce per-account query growth and was accepted as a non-blocking implementation note.

## Deferred tasks

None.

## Commits

- `f41ae3d5559411202a7d4676b2bc6811461242f9` — `feat: add dashboard financial graphs`
