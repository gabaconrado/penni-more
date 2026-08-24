# Minimal runnable infrastructure

## Summary

Create the smallest runnable Django infrastructure slice on top of baseline commit
`a06e9e9fd45b77dfb49f0cbcf100b37b7dfa942a`. The result must provide a minimal home page,
health endpoints, a valid OpenAPI document, repeatable local Podman services, production-ready
container entry points, a guarded SSH deployment path, one top-level command interface, and CI
validation. It must not implement accounts, transactions, imports, reports, or other money-manager
features.

The implementation must prefer declared, locked dependencies and small configuration files over
custom frameworks. All checks must genuinely run; placeholder scripts that return success are not
acceptable.

## Goals

- Establish Django 5.2 LTS on Python 3.14.7 with uv-managed dependencies and a committed lock.
- Establish the server-rendered Tailwind and daisyUI build with minimal vanilla JavaScript.
- Provide a valid minimal OpenAPI contract and local Swagger UI.
- Run Django, PostgreSQL, and Swagger UI locally with rootless Podman Compose.
- Package production Django/Gunicorn, PostgreSQL, Nginx, and on-demand Certbot services.
- Provide a safe manual deployment to one Linux host through SSH and rsync.
- Expose one local command interface and make CI call the same scoped validations.
- Validate Markdown, Bash, Python, templates, Web GUI, OpenAPI, Compose configuration, browser
  behavior, and accessibility at the smallest useful level.

## Non-goals

- Accounts, authentication flows, financial models, transactions, CSV import, charts, or reports.
- A JavaScript framework, partial-page navigation framework, Redis, Celery, cache service, or worker.
- Public Swagger UI or an HTTP-served OpenAPI document in production.
- Staging, multiple production hosts, zero-downtime deployment, or continuous deployment.
- GitHub production credentials or any production access from GitHub Actions.
- Distribution-specific package installation, firewall mutation, SSH hardening, sysctl mutation, or
  privileged host setup.
- Off-host backups, more than one retained deployment backup, or automatic database restoration.
- A remote status, backup, restore, or rollback command in `penni-more.sh`.
- A hard coverage threshold. Coverage is reported until application behavior provides a meaningful
  baseline.
- HSTS preload or `includeSubDomains`.

## User-visible behavior

- `./penni-more.sh setup` synchronizes declared Python and Node dependencies. It reports any missing
  system prerequisite and never installs a missing system tool.
- `./penni-more.sh up` starts the local Django development server, persistent PostgreSQL database,
  and Swagger UI through Podman Compose. Django uses `runserver` with source reload; Swagger UI
  renders the repository contract.
- The local application shows a minimal responsive page that demonstrates the shared visual shell.
  No financial feature controls are implied to work.
- The local PostgreSQL port binds only to `127.0.0.1` at a configurable host port. Ordinary `down`
  preserves its named volume. An explicit local reset operation requires an unmistakable
  confirmation flag before removing that volume.
- `./penni-more.sh lint`, `test`, and `check` run real checks. `check` accepts `docs`, `backend`,
  `web`, `contract`, or `integration`; no scope runs all scopes.
- `./penni-more.sh logs`, `shell`, and `migrate` operate only on the local stack.
- `./penni-more.sh deploy --dry-run` validates both ends and prints the proposed release and actions
  without copying, backing up, migrating, changing symlinks, or restarting a service.
- `./penni-more.sh deploy` is the only top-level command that connects to production. It deploys a
  clean primary-branch commit, makes a database backup, applies migrations once, activates the new
  release, and waits for readiness. A failed application health check restores the previous code
  release while preserving the migrated database.
- Production redirects HTTP to HTTPS, serves collected static assets through Nginx, and proxies to
  one configurable Gunicorn worker with a small configurable thread pool.
- `GET /health/live` is public and returns only a generic healthy response without checking the
  database. The database-aware readiness endpoint is usable inside the Compose network but Nginx
  must not expose it.

## Decisions and assumptions

### Versions and dependency policy

- `.tool-versions` remains authoritative for Python 3.14.7 and Node.js 26.7.0. CI reads those values
  instead of duplicating them in workflow matrices.
- Use Django `>=5.2.8,<5.3`: 5.2 is the selected LTS, and 5.2.8 is the first release in that line
  with Python 3.14 compatibility. uv resolves the latest compatible secured patch and records it in
  `src/backend/uv.lock`.
- Runtime Python dependencies are limited initially to Django, Gunicorn, and the PostgreSQL driver.
  Development groups contain only the agreed format, lint, type, test, coverage, template, and
  static Compose-schema validation tools.
- Frontend dependencies are Tailwind CSS, daisyUI, the minimum Tailwind build CLI, ESLint,
  Prettier, Vitest, Playwright, and Axe integration. Do not add Chart.js until a chart exists.
- Contract dependencies are isolated under `src/contract` and include a pinned Spectral CLI. Do not
  make the Web GUI package own contract tooling.
- Commit uv and npm lockfiles. Never commit `.venv`, `node_modules`, Playwright browsers, generated
  coverage, traces, screenshots, or built static output.

### Django and HTTP

- Use synchronous WSGI through Gunicorn. Django's development `runserver` is local-only.
- Keep environment-specific settings explicit. Production uses `DEBUG=False`, a required secret
  key, exact allowed hosts and CSRF trusted origins derived from the configured domain, secure
  session and CSRF cookies, proxy-aware HTTPS detection, and an HSTS duration configurable from an
  initial 300 seconds. HSTS subdomains and preload stay false.
- Run `manage.py check --deploy` against production settings during validation and deployment
  preflight. Never silence a deployment warning without an approved, narrow reason.
- Build frontend assets and run `collectstatic` during the immutable image build. Nginx serves the
  collected result; Gunicorn never serves production static files.
- The WSGI service listens only on the internal Compose network. Nginx is the only production HTTP
  ingress. PostgreSQL never publishes a production host port.
- The live response has a stable status code and minimal body described by OpenAPI. Readiness uses a
  cheap database connection check, returns no diagnostic internals, and is excluded explicitly in
  Nginx configuration.

These choices follow Django's current primary guidance to deploy WSGI behind a production server,
run the deployment checklist, enforce site-wide HTTPS, and collect static files for a separate web
server:

- [Django 5.2 release notes](https://docs.djangoproject.com/en/5.2/releases/5.2/)
- [Django deployment checklist](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/)
- [Django with Gunicorn](https://docs.djangoproject.com/en/5.2/howto/deployment/wsgi/gunicorn/)
- [Deploying static files](https://docs.djangoproject.com/en/5.2/howto/static-files/deployment/)

### Compose and container images

- Use a portable Compose-spec base plus explicit local and production override files. Avoid Podman
  extensions in Compose YAML so another spec validator can inspect it in CI.
- The base defines the application and PostgreSQL interfaces, health checks, network, and named
  database volume. The local override adds source mounts, `runserver`, the loopback database port,
  and Swagger UI. The production override adds Gunicorn, Nginx, certificates, journald logging, and
  production hardening.
- Use one multi-stage `deploy/Containerfile`: a Node stage builds Web assets; a uv stage installs the
  locked Python environment; a collection stage runs `collectstatic`; a slim Python target runs the
  non-root application without Node or build tools; and an Nginx target receives only Nginx
  configuration and collected static assets.
- Pin image versions to explicit version identifiers or immutable digests. Do not use `latest`.
- Run containers with a non-root user, dropped capabilities, read-only root filesystems where the
  service supports it, and explicit temporary filesystems. Writable persistent mounts are limited
  to PostgreSQL data and Let's Encrypt state; ephemeral runtime paths may use `tmpfs`.
- Application and Nginx logs go to stdout/stderr. Production selects Podman's journald driver; host
  journal retention is a documented bootstrap responsibility.

### Production host contract

The deployment target is distribution-neutral only within this explicit capability contract:

- Linux with systemd user services and timers, journald, rootless Podman 4.9 or newer, and a Compose
  provider.
- Bash, OpenSSH, rsync, Git metadata in the local source tree, DNS lookup tools, and PostgreSQL dump
  support through the database container.
- A dedicated unprivileged deployment account with systemd lingering already enabled.
- Rootless binding to ports 80 and 443 already allowed by host policy.
- Firewall and SSH already hardened so only SSH, HTTP, and HTTPS are exposed as applicable.
- At least 1 vCPU and 2 GB RAM. The default production Gunicorn setting is one worker and a small
  thread pool, both configurable through the remote environment.

The repository documents those requirements and read-only preflight probes. Deployment aborts if a
probe would require `sudo`; it never changes the host to make a probe pass.

### TLS lifecycle

- The remote production environment requires the public domain, expected public IP, and Let's
  Encrypt contact email in addition to Django and database secrets.
- Certificate bootstrap uses a one-off Certbot container and the HTTP-01 webroot challenge. Nginx
  first serves only the challenge and redirect-safe bootstrap configuration; after successful
  issuance it switches to the HTTPS configuration.
- A systemd user timer runs renewal. Nginx reloads only through a successful Certbot deploy hook.
  Certbot is not a continuously running service.
- Deployment resolves the domain and checks that it includes the provisioned expected public IP.
  It verifies ports 80 and 443 are bindable or already owned by this fixed Compose project, rather
  than incorrectly rejecting an ordinary redeployment.

### Release and recovery model

- Local environment variables provide `DEPLOY_SSH_TARGET` and `DEPLOY_REMOTE_DIR`; neither value is
  hardcoded. OpenSSH config and existing keys provide authentication. Scripts never create or copy
  keys or accept passwords.
- The remote layout is `releases/<UTC timestamp>-<short commit>/`, `current` and `previous`
  symlinks, `shared/.env`, `shared/backups/`, shared certificate state, and deployment lock state.
- Rsync copies a release allowlist and excludes `.git`, local environments, dependencies, secrets,
  reports, caches, and generated artifacts. A manifest records the full Git commit and release ID.
- A remote advisory lock covers the whole state-changing deployment. Contention aborts without
  waiting indefinitely.
- Deployment requires a clean working tree and the primary branch. A deliberately named emergency
  override flag may permit another branch and is recorded in release metadata and output.
- Use a fixed Compose project name and a release-specific application image identifier so switching
  source directories does not fork persistent resources or accidentally reuse an image.
- Build images on the remote server. Start or confirm PostgreSQL health, then produce a timestamped
  `pg_dump` before any migration. Failure aborts. On the first release this still means starting the
  empty database and dumping it before built-in migrations.
- Delete the older backup only after the new dump succeeds, leaving exactly the newest deployment
  backup. No off-host copy is made.
- Run migrations as a one-off command, never an entrypoint. Activate the release, recreate changed
  services, and poll internal readiness and public liveness with bounded timeouts.
- If activation health fails, repoint `current` to `previous` and recreate the previous release's
  application and Nginx services. Do not reverse migrations or restore PostgreSQL automatically.
- Retain only `current` and `previous` releases after success. A manual, confirmation-gated database
  restoration helper may exist on the remote release, but it is not exposed by `penni-more.sh` and
  is never invoked automatically.

### Validation and CI

- `docs`: rumdl plus repository-local Markdown target and anchor checks; external URLs are not
  probed in ordinary CI. Bash uses `bash -n`, ShellCheck, and Bats tests for dispatch, validation,
  dry-run, locking, failure, and destructive confirmation paths.
- `backend`: Ruff formatting and lint, mypy with `django-stubs`, Django system checks, production
  deployment checks, missing-migration detection, pytest/pytest-django against PostgreSQL, and
  coverage reports without a minimum threshold.
- `web`: djLint for Django templates, ESLint for JavaScript, Prettier for JavaScript and CSS, Vitest,
  and a clean production Tailwind build.
- `contract`: Spectral validates both OpenAPI schema correctness and project style. Minimal consumer
  tests assert the health operation's status and response shape so a syntactically valid contract
  cannot silently diverge from Django.
- `integration`: Playwright exercises the real temporary Django application at desktop and phone
  viewports. Axe scans representative rendered pages. Browser diagnostics are retained on failure;
  manual keyboard and screen-reader checks remain a release checklist.
- Local backend and integration checks use PostgreSQL, not SQLite. Fast format, lint, type, and unit
  checks run through host uv/npm; PostgreSQL-backed and full-stack validation may use the local
  Podman services.
- GitHub Actions uses parallel `docs-shell`, `backend`, `web`, `contract`, and `integration` jobs.
  It triggers for pull requests, primary-branch pushes, and manual dispatch. Every job is required.
- GitHub's integration job declares PostgreSQL as a service container, runs Django directly with
  uv, and starts a bounded temporary server process for Playwright. No CI step invokes Docker,
  Podman, or Compose.
- Compose files receive static schema validation in CI without a container engine. Runtime Compose
  validation remains part of local/final Podman checks.
- Actions are pinned to full commit SHAs with release-tag comments. CI caches uv and npm downloads,
  not environments or `node_modules`. Reports and coverage upload even on failure; Playwright
  traces/screenshots upload only on browser failure.

## Scope and ownership

Each path below has one implementation owner. An owner must not edit another owner's path; required
changes cross the parent coordinator as findings or follow-up assignments.

### Backend coder

- `src/backend/pyproject.toml` and `src/backend/uv.lock`: Python metadata, runtime dependencies,
  validation dependencies, and uv lock.
- `src/backend/manage.py` and `src/backend/penni_more/**`: minimal Django project, environment-driven
  settings, URL configuration, WSGI entry point, live/readiness views, and static/template paths.
- `src/backend/tests/**`: health, settings, PostgreSQL, and contract-consistency tests.

Keeping uv metadata inside `src/backend` avoids granting backend ownership of a root implementation
file. All commands use `uv run --project src/backend ...`.

### Web GUI coder

- `src/web/package.json` and `src/web/package-lock.json`: frontend and browser-test dependencies and
  scripts.
- `src/web/tailwind.css`, `src/web/static/**`, and `src/web/templates/**`: the minimal responsive
  server-rendered shell and source assets.
- `src/web/eslint.config.*`, `src/web/prettier.config.*`, `src/web/vitest.config.*`,
  `src/web/playwright.config.*`, and `src/web/tests/**`: Web GUI validation and critical smoke tests.

The backend only points Django at these directories. It does not edit templates or assets.

### Contract coder

- `src/contract/openapi.yaml`: minimal OpenAPI contract for liveness and internal readiness.
- `src/contract/package.json`, `src/contract/package-lock.json`, and
  `src/contract/.spectral.yaml`: isolated contract validation tooling and rules.

The contract must mark readiness as internal in its description and tags; production exposure is
still enforced by Nginx rather than assumed from documentation.

### Deployment agent

- `penni-more.sh`: top-level local command dispatcher and sole remote `deploy` entry point.
- `deploy/**`: Containerfile, portable base/local/production Compose files, Nginx configurations,
  environment examples, systemd user units/timer, deployment helpers, bootstrap documentation,
  accessibility release checklist, and Bats tests.
- `.github/workflows/ci.yml`: validation-only GitHub Actions workflow.
- `.codex/lint.sh`: integrate only repository-wide Markdown and Bash checks that belong in the
  automatic lint hook; keep heavy tests in scoped commands.
- `.gitignore`: ignore newly generated local, test, release, and secret artifacts while preserving
  example environment files.

The deployment agent may read the other scopes and call their declared commands but must not repair
their implementation. It also owns final validation and all staging and commits.

### Architect and cycle coordinator

- `docs/plans/2026-08-24-minimal-infrastructure.md`: this approved plan.
- `docs/tasks/2026-08-24-<topic>.md`: only genuinely deferrable issues approved during review.
- `docs/reports/2026-08-24-minimal-infrastructure.md`: final observed cycle report, written by the
  cycle coordinator and staged by the deployment agent.
- Architect reviews `src/contract/**`, cross-scope route/build/settings consistency, and any plan
  interpretation. It does not edit implementation or contract artifacts during review.

## Contract impact

Create OpenAPI 3.1 source at `src/contract/openapi.yaml` with only the two health operations needed
by this scaffold:

- `GET /health/live` has a stable `operationId`, returns HTTP 200 JSON with a required enum-like
  generic status, requires no authentication, and exposes no dependency or version detail.
- `GET /health/ready` has a stable `operationId`, documents HTTP 200 and 503 generic responses, and
  states that it is internal-only. It exposes no database error text.
- Both operations reuse one small health response schema and one generic unavailable schema where
  distinct status semantics require it.
- The contract declares no financial schemas, authentication model, or speculative API versioning.

The backend implements those exact paths, statuses, content types, and bodies. The Web GUI does not
consume either operation in browser code. Swagger UI loads this file only through the local Compose
service. Nginx proxies liveness but returns a non-revealing 404 for readiness and any attempted
OpenAPI or documentation location.

This is an additive initial contract with no compatibility migration. Architect review must compare
the contract against Django tests, Compose health checks, Nginx locations, and deployment polling.

## Implementation sequence

### 1. Establish scope-owned dependency manifests

Run the backend, Web GUI, and contract assignments in parallel because their paths do not overlap:

1. Backend coder creates the uv project, locks compatible Django 5.2 LTS and validation tooling,
   and verifies a minimal Django import and settings load.
2. Web GUI coder creates the locked npm project, minimal Tailwind/daisyUI source, template shell,
   and tool configurations without waiting for backend views.
3. Contract coder creates and validates the two-operation OpenAPI document and its isolated locked
   validator package.

Dependency manifests must expose stable script/command names documented to the deployment agent.
No agent may add a substitute package merely because an agreed tool is inconvenient.

### 2. Implement the thin server-rendered slice

After the Web GUI establishes template/static paths and the contract establishes response shapes:

1. Backend coder configures Django to find `src/web/templates` and source static assets, renders the
   minimal home page, implements both health operations, and adds production-safe settings.
2. Backend tests use PostgreSQL configuration and verify the contract-visible behavior, database
   readiness success/failure, and absence of sensitive details.
3. Web GUI coder completes Vitest, Playwright desktop/mobile smoke coverage, Axe checks, and the
   manual accessibility checklist content under its assigned deployment documentation path only by
   sending the required checklist text to the deployment agent. It must not edit `deploy/**`.

The backend and Web GUI reviewers may start only after their respective linters and focused tests
have run successfully.

### 3. Assemble local and production containers

After the dependency locks, build scripts, Django commands, contract filename, and health contracts
are stable, deployment agent implements:

1. Multi-stage Containerfile targets and explicit build contexts.
2. Base Compose plus local and production overrides, named volumes, health checks, loopback-only
   local database port, local source mounts, and local Swagger UI.
3. Production Gunicorn command, Nginx static/proxy/TLS configuration, Certbot one-off profile, fixed
   project identity, journald logging, resource configuration, and least-privilege settings.
4. Environment examples with safe placeholders and validation definitions. Examples contain no
   realistic secrets.

The deployment agent gives backend/Web owners any observed interface mismatch instead of editing
their files.

### 4. Implement the command and deployment interfaces

Deployment agent implements `penni-more.sh` and focused helpers under `deploy/scripts`:

1. Local prerequisite/version validation and `setup`, `lint`, `test`, scoped `check`, `up`, `down`,
   `logs`, `shell`, and `migrate` dispatch.
2. A confirmation-gated local data reset. If exposed as `reset`, it is the only additional command
   beyond the agreed basic list and must clearly state that only the local PostgreSQL volume is
   targeted.
3. Deploy argument validation, clean-tree/branch guards, environment validation, dry-run behavior,
   SSH/rsync transport, safe release allowlist, and remote lock.
4. Remote release build, first-deploy database startup, mandatory dump, explicit migration,
   activation, bounded health polling, code-only automatic rollback, pruning to two releases and one
   backup, and release metadata.
5. Certificate bootstrap and renewal helper plus systemd user service/timer definitions. A failed
   renewal must leave the working certificate and Nginx process unchanged.
6. Bootstrap and operations documentation for host capabilities, remote `.env` placement and mode,
   systemd installation, journal retention, initial TLS, HSTS ramp-up, manual database restore, and
   explicit recovery limitations.

All mutating remote helpers implement dry-run separation structurally: the dry-run path must return
before any rsync write or remote state-changing command is constructed or executed.

### 5. Build shared validation and CI

After all scopes expose stable commands, deployment agent:

1. Makes each `penni-more.sh check <scope>` call only the owner-provided commands for that scope.
2. Adds Bats coverage using temporary directories, fake command binaries, and inert SSH/rsync
   fixtures; tests must never contact a real host or mutate real Podman state.
3. Adds offline/local Markdown link checks and static Compose schema validation.
4. Adds the five parallel CI jobs. The integration job uses a PostgreSQL service, uv-managed Django
   process, Playwright, and cleanup traps; no container-engine command appears in the workflow.
5. Pins every action to a verified full commit SHA and annotates the intended release tag.
6. Uploads reports with `if: always()` and browser diagnostics with `if: failure()` as agreed.

### 6. Review, correction, final validation, and commit

1. Backend reviewer reviews `src/backend/**` against this plan, Django standards, the contract, and
   observed PostgreSQL tests.
2. Web GUI reviewer reviews `src/web/**` for server-rendered behavior, accessibility, responsive
   layouts, dependency restraint, and tests.
3. Architect reviews `src/contract/**` and every cross-scope use of URLs, status shapes, static
   paths, commands, settings, and health semantics.
4. Deployment agent self-reviews `deploy/**`, root scripts, and CI against Bash and Git standards;
   the cycle coordinator additionally inspects deployment behavior for plan compliance because no
   separate deployment reviewer exists.
5. Every actionable finding returns to its exclusive owner. Repeat the relevant review until each
   reviewer explicitly reports no blocking findings. Do not silently defer any finding.
6. Deployment agent runs the full final matrix, inspects the complete diff, stages only this cycle,
   and creates one or more coherent local Conventional Commits with the required co-author trailer.
7. Cycle coordinator writes the concise report with observed commands, review iterations, deferred
   tasks, and commit IDs; deployment agent commits it if it is a separate final commit.

## Review and verification

The exact wrapper implementation may add pass-through flags, but these public commands and outcomes
are required:

```bash
./penni-more.sh setup
./penni-more.sh lint
./penni-more.sh test
./penni-more.sh check docs
./penni-more.sh check backend
./penni-more.sh check web
./penni-more.sh check contract
./penni-more.sh check integration
./penni-more.sh check
```

Focused owner checks must include the equivalent of:

```bash
uv run --project src/backend ruff format --check .
uv run --project src/backend ruff check .
uv run --project src/backend mypy .
uv run --project src/backend python manage.py check
uv run --project src/backend python manage.py makemigrations --check --dry-run
uv run --project src/backend pytest --cov --cov-report=xml --junitxml=<report-path>
npm --prefix src/web run format:check
npm --prefix src/web run lint
npm --prefix src/web run test
npm --prefix src/web run build
npm --prefix src/contract run lint
bash -n penni-more.sh deploy/scripts/*.sh
shellcheck penni-more.sh deploy/scripts/*.sh
bats deploy/tests
```

Use a safe file enumeration rather than a literal unmatched glob when scripts may be absent. Django
deployment validation must load production-like non-secret test values:

```bash
uv run --project src/backend python manage.py check --deploy
```

Local runtime observations:

```bash
./penni-more.sh up
podman compose -f deploy/compose.yaml -f deploy/compose.local.yaml config
./penni-more.sh check integration
./penni-more.sh down
```

The observer must confirm the home page and local Swagger UI load, PostgreSQL publishes only on
loopback, `down` retains data, the public health response is generic, and the local Compose health
states settle. Destructive reset is tested only against a uniquely named test project/volume and
requires its exact confirmation flag.

Production validation must not contact a real host during ordinary implementation. Bats fakes must
prove:

- missing variables, tools, versions, unsafe paths, production environment mode, DNS mismatch,
  occupied foreign ports, dirty Git state, and wrong branch abort before mutation;
- emergency branch override is explicit and recorded;
- dry-run performs no rsync write and invokes no remote mutator;
- concurrent lock acquisition fails safely;
- backup failure prevents migration;
- migration executes once and never from a container entrypoint;
- health failure selects the previous code release but never invokes database restore;
- pruning preserves current and previous releases and the newest successful backup;
- certificate renewal reloads Nginx only after success.

Before review handoff and before commit, run `.codex/lint.sh`. Final validation also includes
`git diff --check`, static Compose schema validation, production image builds, container health,
Nginx configuration validation, `collectstatic`, and the complete wrapper `check`. Any command not
run because it would require real production access must be named in the report with the inert test
that covers it.

## Risks

- Python 3.14 is supported by Django 5.2 only from 5.2.8; an overly broad lower bound could resolve
  an incompatible patch. The uv constraint and lock prevent that.
- Some Python, Node, browser, or native driver dependencies may lag Node 26 or Python 3.14. Resolve
  compatible current versions in locks; do not silently downgrade `.tool-versions` or replace an
  agreed tool. A real incompatibility is blocking and returns to the user.
- Rootless ports, systemd user services, journald, Compose providers, and networking differ across
  Linux hosts. The capability contract and read-only preflight reduce ambiguity but do not make the
  deployment universally portable.
- TLS bootstrap has a temporary HTTP-only phase. Explicit bootstrap configuration and bounded
  transition prevent Nginx from referencing absent certificates.
- Code rollback cannot undo a breaking migration. Initial migrations are simple, and future plans
  must require forward/backward-compatible schema transitions across the retained releases.
- Retaining one on-host backup protects only against the most recent migration failure. Disk or
  host loss remains explicitly unprotected.
- Remote builds can pressure a 2 GB host. Multi-stage images, one application worker, bounded build
  concurrency, and documented free-space preflight reduce but do not eliminate this risk.
- Dry-run safety can be undermined if helpers mix validation and mutation. Tests must prove no
  mutator is reachable from the dry-run branch.
- GitHub service-container health and temporary server startup can race browser tests. Use explicit
  bounded readiness polling and always-run process cleanup rather than sleeps.
- Automated Axe checks do not establish full accessibility. Manual keyboard and screen-reader
  review remains documented release work.

## Deferred work

The following are accepted non-goals and do not require task files in this cycle: off-host backups,
staging, continuous deployment, HSTS preload/subdomains, monitoring services, cache/workers, and a
coverage threshold. Create a focused task only when later evidence or a feature makes one concrete.

## Completion criteria

- All paths are owned as specified, and no agent edited outside its assignment.
- uv and npm locks reproduce the declared Python, Web GUI, and contract environments.
- The minimal Django page and both health operations behave as contracted against PostgreSQL.
- Local Podman starts Django, persistent PostgreSQL, and Swagger UI; local reset is separately and
  explicitly confirmation-gated.
- Production images build with Gunicorn, collected static assets, Nginx, private PostgreSQL, and
  one-off Certbot behavior; production exposes neither readiness nor OpenAPI documentation.
- Production settings pass Django's deployment check, HTTPS/cookie/HSTS behavior matches the plan,
  and container privileges and writable paths are minimized.
- Dry-run, release locking, clean-tree/branch gates, backups, explicit migrations, health polling,
  code-only rollback, retention, TLS renewal, and remote environment preservation have deterministic
  Bats coverage.
- The top-level command set works, and only `deploy` can contact the remote host.
- All five GitHub Actions jobs call the shared validation interfaces, use PostgreSQL as a service,
  never invoke a container engine, pin actions by SHA, and publish agreed artifacts.
- Backend reviewer, Web GUI reviewer, and architect report no blocking findings after any correction
  cycles.
- `.codex/lint.sh`, every scoped check, full `check`, static and runtime Compose validation,
  production image validation, and `git diff --check` pass with observed results.
- No agreed feature behavior remains hidden in a deferral, and the final cycle report records
  verification and local commit identifiers.
