# Account currencies report

## Outcome

Accounts now have one required, informational currency selected from a database-backed catalog.
CAD and BRL are seeded with database-resident SVG flags, existing accounts migrate to CAD, and
staff can manage or retire currencies through Django admin. Account forms, lists, and details show
the currency with a textual fallback, while flags are served through an authenticated, sandboxed
SVG endpoint.

The completed work follows the
[account currencies implementation plan](../plans/2026-09-17-account-currencies.md). It adds no
OpenAPI, dependency, or deployment change.

## Changes

- Added the Currency catalog, CAD and BRL seed migration, non-null protected Account relationship,
  and CAD backfill for existing accounts.
- Added Django admin catalog management with retirement semantics and optional validated SVG upload,
  replacement, preservation, and clearing.
- Limited account creation to active currencies. Editing additionally permits the account's current
  retired currency, with persisted rows locked and re-read before validating updates.
- Added the Currency control and flag, code, and name presentation to account forms, lists, and
  details, with accessible text fallback and no inline SVG or JavaScript.
- Added an authenticated flag endpoint with restrictive content, origin, caching, and disposition
  headers, plus backend, migration, template, and browser regression coverage.

## Review cycles

- The Web GUI reviewer reported no blocking findings.
- The first backend review found create and update retirement time-of-check/time-of-use races. The
  first correction still relied on the ModelForm-mutated Account instance during updates. The
  second correction locked and re-read the persisted Account and Currency rows; final backend
  review reported no blocking findings.
- The architect's integrated review reported no blocking findings. The persistence, selection,
  rendering, flag-serving, and retirement behavior matched the plan, and the health-only OpenAPI
  contract remained unchanged.

## Verification

- `.codex/lint.sh` passed.
- `./penni-more.sh check all` passed after an unchanged elevated retry when sandboxed Podman setup
  could not change permissions.
- The all-scope check passed 77 deployment tests, Ruff, mypy, Django checks, migration consistency
  with no generated changes, 139 PostgreSQL backend tests including two migration executor tests,
  13 Web unit tests, Spectral contract validation, and 18 Playwright tests.
- A clean migration applied `accounts.0002_currency_catalog` and
  `accounts.0003_account_currency`; repository diff checks passed.

## Deferred tasks

None.

## Commits

- Implementation: `42e21c4fb82dcd1475faf38f5bd5d08c184ffc6d` (`feat: add account currencies`)
- This report requires a separate local commit by the deployment agent. No remote push was
  performed.
