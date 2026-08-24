---
name: django-standards
description: Apply Penni More Python and Django backend implementation and review standards.
---

# Django standards

Apply these rules to Python and Django code under `src/backend`.

## Project tooling

- Use uv for Python versions, the virtual environment, dependencies, locking, and project commands.
- Declare project metadata and dependencies in `pyproject.toml`, and commit `uv.lock` for
  reproducible application builds.
- Run Python and Django commands through `uv run`. Do not invoke an unmanaged environment or edit
  installed packages directly.

## Design

- Keep financial domain rules separate from views, forms, serializers, and persistence details.
- Represent money with `Decimal` and database decimal columns. Define currency, precision,
  rounding, sign, and date semantics explicitly; never use binary floating-point values for money.
- Keep views thin and use focused domain services for multi-step financial operations.
- Prefer Django facilities over additional dependencies when they meet the requirement clearly.
- Keep synchronous code unless measured behavior and the deployment model justify async handling.

## Validation and security

- Validate untrusted input with Django forms, serializers, or explicit boundary validation.
- Preserve CSRF protection, template autoescaping, secure session behavior, and Django's standard
  security middleware. Never mark financial or user-provided content as safe HTML.
- Return documented OpenAPI errors without exposing credentials, personal financial data, queries,
  or internal exceptions.
- Keep secrets in runtime configuration and fail clearly when required configuration is absent.

## Persistence and API

- Implement the OpenAPI contract exactly, including validation, status codes, and content types.
- Use database constraints for durable invariants and `transaction.atomic()` for operations that
  must succeed or fail together, especially transfers and imports.
- Treat schema and data migrations as reviewed application changes. Ensure migrations are safe for
  existing data and reversible when practical.
- Avoid hidden query growth. Review list and aggregation paths for pagination, appropriate indexes,
  and deliberate use of related-object loading.

## Tests and checks

- Test observable behavior at domain, request, and persistence boundaries.
- Test decimal arithmetic, rounding, currency rules, dates, authorization, duplicate imports,
  transaction rollback, and database constraints where relevant.
- Use Django's transaction-aware test facilities when commit or rollback behavior matters.
- Run the project-provided formatting, linting, type, migration, system, and test checks. Do not
  weaken a check without a narrow documented rationale.
