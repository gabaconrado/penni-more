# Ephemeral test database

## Summary

Make every database-dependent test path started through `penni-more.sh` provision its own fresh,
bare PostgreSQL container. The runner will publish PostgreSQL on a dynamically allocated loopback
port, pass that connection exclusively to the checks it owns, and remove the container on success,
failure, or interruption without touching the Compose-managed local development database.

## Goals

- Make `./penni-more.sh test`, database-dependent `check` scopes, aggregate `check`, and publication
  validation work without manually starting PostgreSQL.
- Start one `docker.io/library/postgres:17.6-bookworm` container per top-level command and share it
  across all database-dependent phases in that command.
- Give concurrent command invocations independent containers and dynamically assigned loopback
  ports, including when another service already owns host port 5432.
- Guarantee that a completed or interrupted invocation leaves no test database state, container,
  named volume, or Compose project behind.
- Preserve the original command or signal exit status while performing best-effort cleanup.
- Keep local development, production, and CI checks on PostgreSQL rather than introducing SQLite
  or another test-only database engine.

## Non-goals

- Changing `./penni-more.sh up`, `down`, `logs`, `shell`, `migrate`, or `reset` behavior.
- Restarting, reusing, stopping, or removing the Compose-managed local development database.
- Changing production database images, volumes, deployment, backup, migration, or recovery logic.
- Changing Django models, migrations, settings defaults, tests, Web GUI behavior, or OpenAPI.
- Supporting direct `pytest`, `npm`, or `manage.py` invocations outside `penni-more.sh`; callers of
  those lower-level commands remain responsible for their own environment.
- Adding a service manager, Compose file, Python package, or other dependency for test database
  lifecycle management.

## User-visible behavior

The following commands automatically start a fresh PostgreSQL test container before any
database-dependent phase and remove it when the top-level command finishes:

```text
./penni-more.sh test
./penni-more.sh check backend
./penni-more.sh check integration
./penni-more.sh check
./penni-more.sh check all
./penni-more.sh publish <version>
```

`publish` receives this behavior through its existing call to aggregate `check`; it must not start
a second database itself. Aggregate `check` uses one container for backend validation, pytest, and
browser integration rather than provisioning one per function.

Each invocation binds its container's PostgreSQL port to `127.0.0.1` on a runtime-assigned host
port. It therefore neither requires nor claims host port 5432. An already-running local Penni More
stack or unrelated PostgreSQL service continues running unchanged. Concurrent invocations use
different container IDs and host ports and may complete or clean up independently.

The runner prints concise lifecycle diagnostics sufficient to identify startup and readiness
failures. A missing Podman command fails before test work with the existing required-tool style.
Failure to create the container, discover a valid port, or reach readiness stops the requested test
path before Django or browser tests run.

## Decisions and assumptions

- Use a direct rootless-compatible `podman run`, not either repository Compose file. The container
  image is pinned to `docker.io/library/postgres:17.6-bookworm`, matching `deploy/compose.yaml`.
- Do not assign a fixed container name. Capture the container ID emitted by `podman run` and use
  only that exact ID for port discovery, readiness, diagnostics, stopping, and cleanup. This is the
  concurrency and cleanup boundary.
- Start the container with `--detach` and `--rm`, publish `5432/tcp` only as
  `127.0.0.1::<container-port>`, and use no host or named volume. Mount PostgreSQL's data directory
  as container-local temporary storage if needed to prevent the image's declared data volume from
  creating a retained anonymous volume. No state may survive container removal.
- Supply fixed, clearly test-only `POSTGRES_DB`, `POSTGRES_USER`, and `POSTGRES_PASSWORD` values to
  container initialization. Export the same values plus `POSTGRES_HOST=127.0.0.1` and the discovered
  host port only to the owned validation/test subprocesses. Caller-provided PostgreSQL variables
  must not redirect these paths to a local, production, or other external database.
- Parse the port reported by `podman port <container-id> 5432/tcp`, validate that it is numeric and
  in the valid TCP port range, and fail closed if the mapping is absent or malformed.
- Poll readiness with a bounded retry loop against the exact container, using `pg_isready` inside
  it so no host PostgreSQL client is required. Before retrying, detect an exited container; on
  terminal startup failure, emit bounded container logs without exposing credentials.
- Install one composed resource-cleanup trap for an invocation. It must account for both the test
  database container and the integration server process rather than allowing `check_integration`
  to overwrite the database trap. `EXIT`, `INT`, and `TERM` paths must clean only captured resources,
  disable recursive traps, tolerate an already-removed resource, and return the status that caused
  cleanup. Use conventional 130 and 143 statuses for `INT` and `TERM`.
- Stop the captured `--rm` container during cleanup and allow Podman to remove its writable state.
  Cleanup errors are diagnostic only and must not replace an earlier test failure or signal status.
- Before starting the integration server against the fresh base database, apply migrations with
  `manage.py migrate --noinput`. Pytest-django may continue creating and destroying its own test
  database within the same PostgreSQL container.
- Only command routes that run database-dependent checks provision PostgreSQL. `lint`, `check docs`,
  `check web`, and `check contract` retain their current behavior and do not start a database.
- Podman becomes an explicit host prerequisite for the affected test paths. The script reports a
  missing tool and never installs it or starts a Compose project as fallback.

## Scope and ownership

The `deployment_agent` exclusively owns implementation because all affected behavior is shell,
test orchestration, CI, and operator documentation:

- `penni-more.sh`: add the ephemeral PostgreSQL lifecycle, environment isolation, readiness wait,
  shared cleanup, signal handling, and affected command routing; reconcile integration-server
  cleanup with the single resource trap.
- `deploy/tests/commands.bats`: retain top-level dispatch coverage and update existing assertions or
  fixtures where the new prerequisite and routing behavior changes them.
- `deploy/tests/test_database.bats`: add focused deterministic lifecycle tests using a fake Podman
  executable and temporary files; do not mutate real local containers or volumes from Bats.
- `.github/workflows/ci.yml`: remove the backend and integration jobs' fixed PostgreSQL service
  containers and static connection variables so those jobs exercise the shared command behavior;
  verify Podman is present rather than installing a missing host tool at runtime.
- `README.md`: document that database-dependent top-level test commands require Podman but provision
  and clean their own isolated PostgreSQL container, independently from the local Compose stack.
- `deploy/README.md`: clarify that publication validation provisions the ephemeral test database,
  so an operator must have Podman but need not start the local database before publishing.
- `docs/reports/2026-09-10-ephemeral-test-database.md`: record the completed implementation,
  review iterations, observed checks, deferred work, and commit identifiers after implementation.

No backend, Web GUI, or contract coding assignment is required. All implementation paths are one
deployment-owned dependency chain and should not be edited concurrently by another agent. The plan
itself remains architect-owned.

## Contract impact

None. No HTTP operation, schema, Django/Web boundary, status code, or OpenAPI artifact changes.
There is no `contract_coder` assignment or contract review gate.

The shell command contract does change: the affected commands now require a working Podman runtime,
ignore ambient PostgreSQL connection overrides for their owned test phases, and own creation and
cleanup of a temporary database container.

## Implementation sequence

1. In `penni-more.sh`, introduce constants for the pinned PostgreSQL image and test-only database
   identity, plus state variables holding only the current invocation's container ID, discovered
   port, and integration-server PID.
2. Replace the integration-only trap with one cleanup function that snapshots `$?`, removes traps,
   terminates and waits for the exact integration PID when present, stops the exact test container
   when present, clears the state variables, and returns the original status. Add signal handlers
   that produce statuses 130 and 143 while still flowing through cleanup.
3. Add a database startup function that requires Podman, invokes the pinned bare container with
   `--detach`, `--rm`, loopback-only dynamic publication, no persistent storage, and test-only
   initialization values, then immediately records its returned container ID for cleanup.
4. Discover and validate the assigned host port. Poll `pg_isready` inside the captured container
   with a finite timeout and detect early container exit. On failure, print a concise error and
   bounded logs, allowing the shared trap to remove any remaining resource.
5. Add a wrapper that starts the database once, installs the shared traps, injects the owned
   PostgreSQL environment into its command body, and returns the body's exact status. Route `test`,
   `check backend`, `check integration`, `check all`, and default `check` through it. Keep all other
   top-level commands and check scopes outside it. Ensure `publish.sh` retains its single existing
   aggregate-check call and therefore creates exactly one database during validation.
6. Make integration setup migrate the fresh base database before starting Django. Keep the
   existing bounded liveness wait, Playwright status propagation, and exact child-PID cleanup, now
   coordinated by the shared trap.
7. Add fake-Podman Bats coverage for command selection, run arguments, dynamic port propagation,
   readiness ordering, migration ordering, and exact cleanup. Cover startup, port discovery,
   readiness, test, and integration failures as well as success, `INT`, and `TERM`; each must retain
   its original status and stop only its captured container. Assert no Compose command, fixed host
   port, named volume, ambient PostgreSQL endpoint, or second container is used.
8. Add a deterministic concurrency regression that starts two test-command fixtures in parallel,
   gives each a distinct fake container ID and port, and proves each child receives its own port and
   stops only its own ID. Avoid timing-only assertions by coordinating fixtures through explicit
   temporary markers or FIFOs and waiting for the spawned PIDs.
9. Update CI to remove its redundant PostgreSQL services and fixed port-5432 environments for the
   backend and integration jobs. Add an early read-only Podman version/info check so a runner image
   regression fails as a missing prerequisite before application tests. Retain current job
   separation, dependencies, artifacts, and check commands.
10. Update operator documentation, then run focused and complete validation. Send the implementation
    to deployment-focused review; resolve every actionable finding before final validation and a
    justified local commit.

## Review and verification

The `deployment_agent` runs focused feedback throughout implementation:

```bash
bash -n penni-more.sh
shellcheck penni-more.sh
bats deploy/tests/commands.bats deploy/tests/test_database.bats
```

The focused Bats suite must prove:

- only database-dependent command routes start PostgreSQL;
- the pinned image, `--rm`, no persistent volume, and loopback-only dynamic port are used without
  Compose or host port 5432;
- readiness precedes Django/test work and integration migrations precede the server;
- aggregate checking uses one container across backend and integration phases;
- test subprocesses receive the generated endpoint instead of ambient PostgreSQL values;
- success and every covered failure/signal path stop the exact container and preserve status;
- two simultaneous invocations remain isolated by container ID and port;
- the local Compose project, named database volume, and unrelated Podman resources are never
  referenced by cleanup.

After focused tests pass, the deployment reviewer inspects the shell and CI diff against this plan,
with emphasis on trap composition, exit-status preservation, identifier validation, no-volume
semantics, concurrency, startup timeout behavior, credential-safe diagnostics, and the absence of
broad Podman cleanup. Because no dedicated deployment reviewer role exists, the architect performs
this cross-scope review and reports concrete blocking findings or explicitly reports none. Any
finding returns to the `deployment_agent`, followed by the same focused checks and another review.

Final validation by the `deployment_agent` must run:

```bash
.codex/lint.sh
./penni-more.sh check docs
./penni-more.sh test
./penni-more.sh check backend
./penni-more.sh check integration
./penni-more.sh check all
git diff --check
```

Observe the container list before and after at least one successful command and one deliberately
failing fake-backed lifecycle test. Confirm no test container or test database volume remains and
that any already-running local Compose database remains running with the same container ID. Run two
database-dependent commands concurrently and observe distinct assigned ports and successful exact
cleanup. No check may be reported as passed unless its exit result is observed.

The deployment agent then creates the justified local implementation commit. After the report is
written, the deployment agent commits that report separately if it was not included in the
implementation commit.

## Risks

- An `EXIT` trap installed by integration code can replace the database cleanup trap. A single
  resource-aware cleanup path and explicit regression coverage prevent orphaned containers.
- `set -e` can obscure the failing command or allow cleanup status to replace it. The wrapper and
  cleanup must capture status before any cleanup operation and test representative nonzero values.
- A mutable or ambiguous container name could make concurrent cleanup destructive. Container IDs
  returned by each `podman run` are the only permitted cleanup targets.
- Dynamic port output can vary or be malformed. Bind explicitly to IPv4 loopback, query the exact
  mapping, validate the extracted port, and fail closed.
- PostgreSQL may accept a container process before it accepts connections. A bounded `pg_isready`
  loop is required; a fixed sleep is insufficient.
- The official image declares database storage. The run arguments and verification must ensure its
  data is temporary and removed with the container, without creating a retained named or anonymous
  volume.
- Removing CI service containers makes the jobs depend on Podman availability in the runner image.
  The explicit prerequisite check makes that dependency visible; a missing host tool is reported
  rather than installed automatically.
- Pulling the pinned image may require network access when it is not cached. That is a normal
  declared container-image dependency; pull or registry failure must stop cleanly without a
  fallback to a developer database.

## Deferred work

None. Direct lower-level test commands and broader container-cache management are explicitly
outside this feature rather than deferred defects.

## Completion criteria

- Every agreed database-dependent `penni-more.sh` path starts one fresh bare PostgreSQL
  `17.6-bookworm` container and needs no manually running database.
- Each invocation uses its own validated loopback-only dynamic port; simultaneous invocations and
  an occupied host port 5432 do not conflict.
- Aggregate checks share one container across their backend and integration work, and publication
  continues to invoke exactly one aggregate validation path.
- Test connection variables cannot point owned tests at the local development or another ambient
  database; Compose files and persistent volumes are not used.
- Cleanup runs on success, failure, `INT`, and `TERM`, stops only captured resources, preserves the
  original status, and leaves no test container or database state.
- The local development database and all unrelated Podman state remain unchanged.
- CI backend and integration jobs exercise the same self-provisioning commands without fixed
  PostgreSQL service containers.
- Focused Bats regressions, Bash syntax, ShellCheck, Markdown lint, scoped checks, the complete
  repository check, and whitespace validation pass with observed results.
- Architect review reports no unresolved blocking findings, the deployment agent creates the local
  commit or commits, and the cycle report records the delivered behavior and verification.
