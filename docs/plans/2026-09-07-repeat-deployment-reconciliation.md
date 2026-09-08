# Repeat-deployment Compose reconciliation

## Summary

Make repeated production deployments reconcile the fixed Compose project from a clean container
state. After building and validating the new images, deployment will accept brief full-stack
downtime, run `podman compose down` without removing volumes, and then recreate database, server,
and Nginx in explicit dependency order.

This avoids `podman-compose` errors caused by replacing a service while dependent containers from
the previous release still exist. Named database, certificate, and challenge volumes remain intact.
Any failure after downtime begins invokes one best-effort previous-release code restart; database
migrations and data are never rolled back automatically.

## Goals

- Build the new server and Nginx images and run Django's production deployment check before stopping
  the working stack.
- Remove every container and network belonging to the existing fixed Compose project before
  recreating services.
- Preserve all named database and certificate volumes.
- Recreate PostgreSQL alone, wait for health, take the existing pre-migration backup, and then run
  migrations exactly once.
- Activate and validate the server before starting Nginx or the certificate bootstrap flow.
- Attempt a clean previous-release code restart after every failure occurring once stack shutdown
  has begun.
- Retain the existing successful-deployment release cleanup and non-blocking Podman prune.
- Add focused deterministic regression coverage for repeated reconciliation, ordering, volume
  preservation, and recovery.

## Non-goals

- Zero-downtime, rolling, blue-green, canary, or parallel Compose-project deployment.
- Database rollback, automatic backup restoration, or reverse migrations.
- Off-server backups or a deferred off-server-backup task.
- Changing database, certificate, or challenge volume names or contents.
- Changing backend, Web GUI, OpenAPI, HTTP, Compose service definitions, container images, or
  systemd units.
- Accessing or modifying production during implementation, review, checks, or commit.
- Changing the deployment lock supervisor or its descriptor-inheritance fix except where tests must
  continue to address the worker script.

## User-visible behavior

- Deployment performs all image builds and the production Django check while the current
  application remains available.
- Once those checks pass, the application has a short full-stack outage while deployment removes
  old project containers, restarts PostgreSQL, backs up and migrates it, and activates the new server
  and Nginx.
- `podman compose down` never receives `--volumes`, `-v`, or another explicit volume-removal option.
  Database and Let's Encrypt state therefore survive each repeated deployment.
- A failure before stack shutdown leaves the current production stack untouched and does not invoke
  recovery.
- A failure after shutdown begins reports the original deployment error, attempts to remove any
  partial new stack without volumes, repoints `current` to the validated previous release, and
  starts its database, server, and Nginx in dependency order.
- Recovery clearly reports that migrations and database state were not rolled back. A failed
  recovery is reported separately without masking the original deployment failure.
- On a failed first deployment with no valid previous release, recovery removes a `current` link
  only if it points to the failed release, reports that no prior code can be restarted, and performs
  no database restoration.

## Decisions and assumptions

- Simplicity and deterministic reconciliation take priority over uptime. One fixed Compose project
  remains authoritative, and no temporary parallel application project is introduced.
- The worker captures and validates the pre-deployment `current` release before downtime. A valid
  previous target remains a symlink under `releases/` whose target exists and contains both
  production Compose files.
- Pre-downtime work is limited to safe release setup, image builds, and
  `manage.py check --deploy --fail-level WARNING` with `--no-deps`. No running service is recreated,
  stopped, or migrated before these checks pass.
- Set a recovery-armed state immediately before invoking `podman compose down`. Even a partially
  failed `down` can leave the project unavailable, so every later nonzero exit triggers recovery.
- Normal reconciliation uses the new release's Compose files with the fixed `penni-more` project
  name. It invokes exactly `down` and does not include `--volumes`, `-v`, `system prune`, or manual
  volume removal at the downtime boundary.
- After shutdown, start only `database`, poll `pg_isready` with the existing bounded timeout, take
  the existing dump, retain the newest-backup policy, and run the new release's migration command
  once. Only then update `previous` and `current` and start `server`.
- Preserve the current bounded internal server-readiness check. Start Nginx directly when a
  certificate exists; otherwise run the existing HTTP-01 bootstrap. Preserve the bounded public
  HTTPS liveness check as the final activation gate.
- Implement recovery in one trap-safe function that is disabled before it performs recovery. It
  records the original status, never recursively invokes itself, and returns the original status
  after reporting recovery outcome.
- Recovery first performs a best-effort `podman compose down` against the partial fixed project,
  again without volume flags. When a valid previous release exists, it restores the `current`
  symlink and uses that release's Compose files and release ID to start `database`, wait for database
  health, start `server`, wait for internal readiness, then start `nginx`. It does not run backup,
  migration, Certbot issuance, release retention, or prune.
- If the prior certificate is missing or previous services fail health during recovery, report that
  recovery could not be verified. Do not request a new certificate or mutate database state in the
  recovery path.
- Release-directory cleanup and `podman system prune --force` run only after the new public liveness
  check succeeds and recovery has been disarmed. Prune remains non-blocking and still excludes
  `--all` and `--volumes`.
- The deployment is manually initiated from the user's machine after the local commit. Repository
  agents do not contact the VPS.

## Scope and ownership

### Deployment agent

The deployment agent exclusively owns implementation, tests, final checks, local Git operations,
and the cycle report:

- `deploy/scripts/remote-release-worker.sh`: implement pre-downtime validation, full-project
  reconciliation, ordered startup, and the guarded previous-release recovery path.
- `deploy/tests/remote_release.bats`: update existing expectations and add focused behavioral tests
  for repeated-project reconciliation, volume preservation, phase ordering, and recovery.
- `deploy/scripts/remote-release.sh` only if a minimal supervisor integration adjustment is proven
  necessary; the lock design and external interface must otherwise remain unchanged.
- `docs/reports/2026-09-07-repeat-deployment-reconciliation.md`: concise observed cycle report after
  review, checks, and the implementation commit.

The deployment agent is not alone in the worktree. It must preserve unrelated changes and the
completed lock-inheritance fix, and must not edit backend, Web GUI, OpenAPI, Compose, systemd, or
unassigned documentation paths. Only the deployment agent may stage or commit.

### Architect and coordinator

- `docs/plans/2026-09-07-repeat-deployment-reconciliation.md`: this plan.
- Review the completed diff for phase ordering, failure recovery, data preservation, lock-worker
  consistency, and the absence of cross-scope changes.
- No backend, Web GUI, or contract reviewer is required because those scopes are unchanged.

Implementation and tests both depend on the deployment workflow and belong to one deployment agent;
there is no safe parallel ownership split.

## Contract impact

There is no OpenAPI, application, HTTP, database-schema, or Web GUI contract change. Deployment
continues to use the existing internal readiness and public liveness endpoints without changing
their inputs or responses. The remote supervisor still invokes the worker with the same remote
directory and release ID.

## Implementation sequence

1. Refactor the worker into small functions for Compose invocation, bounded database readiness,
   bounded server readiness, previous-target validation, normal activation, and recovery. Keep
   quoted/braced expansions, arrays for Compose arguments, and the short top-level flow required by
   the Bash standards.
2. Before downtime, link the shared directory into the new release, capture a valid previous target,
   build server and Nginx images, and run the production deployment check with no dependencies.
   Assert through tests that any failure here exits without `down`, backup, migration, symlink
   activation, or recovery startup.
3. Arm the recovery handler immediately before the new-release Compose command invokes `down`.
   Ensure this command contains neither `--volumes` nor `-v`. Do not delete or recreate named
   volumes directly.
4. Start PostgreSQL alone and wait for health. Take the release-specific custom-format dump before
   migration and retain the existing one-backup policy. Run the migration once. A database startup,
   health, backup, or migration failure must enter recovery.
5. After migration succeeds, update `previous` only for the validated old current target, point
   `current` at the new release, start `server`, and wait for internal readiness. Then start Nginx or
   use the existing certificate bootstrap flow and require public HTTPS liveness.
6. On successful public health, disarm recovery. Preserve release retention and the best-effort
   `podman system prune --force` in their current post-health order.
7. For any failure after recovery is armed, preserve the original status and diagnostic. Disable
   recursive recovery; perform a best-effort partial-project `down` without volumes; then:
   - with a valid previous target, restore `current`, set the previous release ID, and recreate
     database, server, and Nginx sequentially with bounded database/server verification;
   - without a previous target, remove only a `current` symlink that resolves to the failed new
     release and report that no previous code is available;
   - always state that migrations and the database were not rolled back;
   - report restart or verification failure separately, then return the original deployment status.
8. Extend Bats with deterministic fake Compose state and command logs. Cover:
   - image builds and production checks occur before the first `down`;
   - pre-downtime check failure never stops the existing project or invokes recovery;
   - a simulated existing dependent-container state rejects service replacement until `down`, and
     the new workflow succeeds because `down` clears that state;
   - every normal and recovery `down` omits `--volumes` and `-v` and no explicit volume-removal
     command occurs;
   - normal order is `down`, database-only start, database health, dump, migration, symlink
     activation, server start/readiness, then Nginx/certificate and public health;
   - representative failures before activation and after activation both attempt the validated
     previous release in database/server/Nginx order without `pg_restore` or a second migration;
   - recovery failure preserves the original status and emits both the no-database-rollback warning
     and a distinct recovery-failure diagnostic;
   - no-previous first-deployment failure does not fabricate a rollback target;
   - success still performs release retention and safe, non-blocking prune only after public health.
9. Run focused checks and architect review. Return all actionable defects to the deployment agent and
   repeat until no blocking findings remain.
10. Run final repository validation, inspect the complete diff, and create a coherent local
    Conventional Commit. Write the cycle report with the observed checks and commit ID. Do not run
    or access production; hand the committed fix to the user for manual deployment.

## Review and verification

Run focused syntax, static analysis, and deployment tests during implementation:

```bash
bash -n deploy/scripts/remote-release.sh
bash -n deploy/scripts/remote-release-worker.sh
shellcheck deploy/scripts/remote-release.sh
shellcheck deploy/scripts/remote-release-worker.sh
bats deploy/tests/remote_release.bats
```

Behavioral tests must use only temporary directories and deterministic fake `podman`, `curl`, and
readiness commands. They must model an already-running fixed project so a service-level replacement
would fail until a logged project-wide `down` occurs. Tests must inspect complete argument arrays,
not accept a substring that could hide `--volumes` or `-v`.

Before architect review and again before commit, run:

```bash
.codex/lint.sh
./penni-more.sh check docs
git diff --check
```

Final validation must run the complete repository baseline:

```bash
./penni-more.sh check
```

No validation may run `./penni-more.sh deploy`, connect over SSH, contact Let's Encrypt, or mutate
real production Podman state. The report must name these intentionally omitted operational checks
and identify the Bats cases that cover their behavior locally.

## Risks

- A volume-removing `down` would destroy database or certificate state. Use only `down`, reject
  `--volumes` and `-v` in tests, and never add explicit volume cleanup.
- Arming recovery after `down` returns would miss partial shutdown failures. Arm it immediately
  before the command.
- Using service-level recreation before removing old dependent containers repeats the reported
  `podman-compose` failure. Require full-project `down` before the first post-check `up`.
- Running migrations before backup or more than once risks data integrity. Preserve one successful
  dump before the sole migration invocation.
- An EXIT/ERR trap can mask the original failure or recurse when recovery fails. Disable it inside
  recovery, capture the incoming status, make recovery commands explicitly best-effort, and return
  the captured status.
- Previous code may be incompatible with an applied migration. Recovery is code-only and cannot
  guarantee application health; state this explicitly and verify the restarted server where
  possible.
- Starting Nginx before server readiness or before certificates exist can recreate observed startup
  failures. Preserve dependency ordering and the existing certificate bootstrap gate.
- A failed first deployment has no code release to restore. Clean only the failed activation link,
  preserve all volumes and backups, and report the limitation.
- Full-stack downtime lasts through database health, backup, migration, and health checks. This is
  explicitly accepted for the two-user system in exchange for a simpler reliable deployment.

## Deferred work

None. Off-server backups are explicitly outside this cycle and must not receive a follow-up task.

## Completion criteria

- New images build and the production Django check passes before the running Compose project is
  stopped.
- The worker performs one full-project `podman compose down` before service recreation, without
  `--volumes`, `-v`, or explicit volume removal.
- Named database, certificate, and challenge volumes remain preserved across reconciliation.
- Normal activation follows database start and health, pre-migration backup, one migration, server
  start and readiness, then Nginx/certificate handling and public liveness.
- Existing dependent containers cannot cause service-replacement errors because reconciliation
  removes the old project containers first.
- Every failure after shutdown begins attempts the guarded previous-release code restart; recovery
  performs no database restore or migration rollback and clearly reports that limitation.
- Pre-downtime failures leave the existing stack untouched. First-deployment failure never creates
  a false previous target.
- Successful deployment retains current release cleanup and best-effort safe Podman pruning after
  public health.
- Focused regression tests, Bash syntax, ShellCheck, `.codex/lint.sh`, docs checks, the complete
  repository check, and `git diff --check` pass with observed results.
- Changes remain within deployment-owned scripts/tests, this plan, and the cycle report. No
  production access, off-server-backup task, application change, contract change, or Git remote
  mutation occurs.
- Architect review reports no blocking findings, the deployment agent creates the local commit, and
  the concise report records checks and the commit ID.
