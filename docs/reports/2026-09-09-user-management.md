# User management and session authentication report

## Outcome

Penni More now uses a custom, email-only Django user identity with case-insensitive uniqueness.
Server-rendered session login protects user-facing pages by default, POST logout returns users to
login, and Django admin retains its standard staff and permission controls. Account creation is not
public. Operational health endpoints remain public and contract-compatible, with no authentication
API or OpenAPI change.

The completed work follows the [user management implementation plan](../plans/2026-09-09-user-management.md).

## Changes

- Added the custom user model, email normalization and database constraint, manager, admin forms,
  admin registration, initial migration, and authentication form.
- Enabled Django auth, admin, sessions, messages, standard password validation, and default login
  enforcement while explicitly exempting login and health views.
- Added named login, logout, and admin routes; authenticated the existing home page; and preserved
  safe return-target handling and generic invalid-credentials responses.
- Added an accessible, responsive login page and authenticated shell navigation with a
  CSRF-protected POST logout form. Core authentication behavior requires no JavaScript.
- Added backend, template, and browser coverage for identity, authorization, login/logout, health,
  responsive behavior, accessibility, and no-JavaScript use.

## Review cycles

- The initial Web GUI review found a blocking autofocus and skip-link focus-order conflict. The Web
  GUI coder removed autofocus, updated the checks, and the re-review reported no blocking findings.
- The initial backend review reported no blocking findings and identified optional test gaps. Those
  gaps were closed with additional coverage, and the backend re-review reported no blocking
  findings.
- The architect's contract and cross-scope review found no blocking or non-blocking findings.
  Backend routes, form context, templates, OpenAPI health behavior, and deployment boundaries agree
  with the plan.

## Verification

- `./penni-more.sh check all` exited 0. It observed 36 Bats tests, 49 pytest tests, 5 Vitest tests,
  and 12 Playwright tests passing.
- All repository formatting, linting, type checking, Django system and migration checks, Web asset
  build checks, and Spectral OpenAPI validation passed in the final run.
- Applying migrations to an isolated empty PostgreSQL database succeeded.
- The final migration consistency check reported `No changes detected`.

## Deferred tasks

None.

## Commits

- Implementation: `a9e0ac4fbb8bd71849b89d84b9a0b28563cc05ae`
- This report requires a separate local commit by the deployment agent if it is not amended through
  an authorized Git workflow; no report commit identifier exists yet.
