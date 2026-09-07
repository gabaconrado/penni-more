# Deployment lock inheritance

## Outcome

Deployment locking now excludes concurrent releases without passing the lock descriptor to the
deployment worker or its descendants. The lock becomes available when the supervised worker exits,
even if a helper process remains alive.

Implementation commit:
`4cbd1c0b5c095f9833d25a7884d9aa57e958e5e2` (`fix: prevent deployment lock inheritance`).

## Changes

- `remote-release.sh` is now a validating lock supervisor. It invokes the adjacent internal worker
  through exclusive, non-waiting `flock --close` supervision.
- Lock contention retains status 3 and the existing diagnostic. Other worker and `flock` statuses
  are propagated unchanged.
- `remote-release-worker.sh` contains the prior release workflow without opening or referencing the
  deployment lock. Its argument and production-environment validation remain in place.
- Deterministic Bats fixtures exercise active contention, worker failure propagation, and lock
  release while a confirmed-alive helper process survives.

## Review

The architect review found no blocking issues. Release activation, backups, migrations, TLS,
health checks, retention, pruning, backend, Web GUI, OpenAPI, Compose, and systemd behavior were not
changed.

## Verification

The following checks passed:

- Bash syntax and ShellCheck for the supervisor and worker scripts.
- `bats deploy/tests/remote_release.bats`: 19 tests passed.
- `.codex/lint.sh`.
- `./penni-more.sh check docs`: 32 deployment tests passed.
- `./penni-more.sh check`: 23 backend tests, two Web tests, contract lint, and seven browser tests
  passed; one browser case was intentionally skipped by its configured project.
- `git diff --check` before the implementation commit.

The complete check used the repository's local Podman stack for PostgreSQL. That stack was stopped
after validation without removing its named volume.

`./penni-more.sh deploy` was not run. No SSH connection, production host, registry, cloud service,
or other operational external service was accessed or modified.

## Deferred work

None.
