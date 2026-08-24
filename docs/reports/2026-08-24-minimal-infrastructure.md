# Minimal runnable infrastructure report

## Outcome

Implemented and locally committed the [minimal runnable infrastructure plan](../plans/2026-08-24-minimal-infrastructure.md).
Penni More now has a minimal Django home page, contracted liveness and readiness endpoints,
Tailwind and daisyUI assets, local and production Podman Compose stacks, guarded deployment and TLS
helpers, shared validation commands, and a five-job CI workflow.

## Changes

- Added the locked Django, Web GUI, and OpenAPI projects with focused unit, contract, browser, and
  accessibility coverage.
- Added local Django, PostgreSQL, and Swagger UI services plus production Gunicorn, Nginx,
  PostgreSQL, and on-demand Certbot packaging.
- Added the top-level setup, validation, local operations, reset, and guarded SSH deployment
  interface.
- Added offline Compose-spec validation, deployment safety tests, production recovery guidance,
  accessibility release checks, and pinned CI actions with dependency caching.

## Review cycles

Backend, Web GUI, and architect reviews identified production probe headers, real-environment
deployment checks, clean stylesheet generation, integration cleanup, GET-only contract alignment,
and full Compose-schema validation as blocking issues. The owning agents corrected each issue and
the matching reviewers then reported no blocking findings.

Final runtime validation found one Podman Compose health-check portability issue. The deployment
owner corrected the probe and repeated lint, schema, shell, merged-configuration, and runtime
checks successfully.

## Verification

- `.codex/lint.sh`, every scoped `./penni-more.sh check <scope>`, the aggregate
  `./penni-more.sh check`, and `git diff --check` passed.
- Backend validation passed with 23 tests, Ruff, mypy, Django system and deployment checks, and the
  missing-migration check.
- Web validation passed with Prettier, ESLint, djLint, Vitest, a clean Tailwind build, and seven
  Chromium and Axe checks; one project-specific browser case was intentionally skipped.
- Spectral contract validation, offline Compose-spec validation, merged Podman Compose validation,
  and all 23 Bats deployment tests passed.
- The local home page, stylesheet, liveness, readiness, Swagger UI, healthy Django/PostgreSQL
  containers, and loopback-only PostgreSQL publication were observed. Ordinary shutdown preserved
  the named database volume.
- Production application and Nginx images built successfully. `collectstatic`, `nginx -t`, and the
  production image deployment check passed.
- No production deployment, destructive reset, or operational external-service access was run.
  Manual keyboard and screen-reader checks remain documented as release activities.

## Deferred tasks

None.

## Commits

- `1daa57ecc155a579ac715f85e4051d3ccc8615f6` — `feat: establish minimal application infrastructure`
