# Repeat-deployment reconciliation

## Outcome

Repeated production deployments now reconcile the fixed Compose project from a clean container
state while preserving named volumes. Builds and Django's production check complete before
downtime, and post-shutdown failures attempt a guarded previous-release code restart without
rolling back database state.

Implementation commit:
`2bf2aa97b7e74b207ac8ff66379834e792e572ee`
(`fix: reconcile repeated production deployments`).

## Changes

- The deployment worker captures a validated prior release, builds both new images, and runs the
  production deployment check before stopping the active project.
- Reconciliation uses a full-project `podman compose down` without volume-removal options, then
  starts and verifies PostgreSQL, takes the pre-migration backup, runs one migration, activates the
  server, and starts Nginx only after server and certificate checks.
- An armed EXIT recovery preserves the original failure status, removes a partial project without
  removing volumes, and restarts validated prior database, server, and Nginx services in order.
  Recovery never restores a backup or reverses migrations and reports that limitation explicitly.
- Focused Bats fixtures model existing dependent containers, command ordering, volume-option
  rejection, failures before and after activation, failed recovery, and first-deployment behavior.
- Successful deployment still performs release retention and best-effort safe Podman pruning only
  after public health succeeds.

## Review

The architect review found no blocking issues. The lock supervisor, backend, Web GUI, OpenAPI,
Compose definitions, container images, and systemd units were unchanged.

## Verification

The following checks passed:

- Bash syntax and ShellCheck for the deployment supervisor and worker.
- `bats deploy/tests/remote_release.bats`: 23 tests passed.
- `.codex/lint.sh`.
- `./penni-more.sh check docs`: 36 deployment tests passed.
- `./penni-more.sh check`: 23 backend tests, two Web tests, contract lint, and seven browser tests
  passed; one browser case was intentionally skipped by its configured project.
- `git diff --check` before the implementation commit.

The complete check used the repository's local Podman stack for PostgreSQL. The stack was stopped
after validation without removing its named volume.

`./penni-more.sh deploy` was not run. No SSH connection, production host, registry, cloud service,
Let's Encrypt service, or other operational external service was accessed or modified.

## Deferred work

None. No off-server backup task was created because it was explicitly outside this cycle.
