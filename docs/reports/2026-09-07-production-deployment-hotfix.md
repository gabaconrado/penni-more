# Production deployment hotfix

## Outcome

The production deployment workflow now prepares the complete Let's Encrypt path for unprivileged
Nginx access, avoids invalid rollback targets on a first deployment, and performs conservative
Podman cleanup only after a healthy release.

Implementation commit:
`4bc8532b34a71f2123ade8fcbaff9ea42626beca` (`fix: harden production deployment recovery`).

## Changes

- Certificate bootstrap and renewal assign group 101 to the Let's Encrypt root, `live/`, and
  `archive/` paths. Required directories use mode `0750`, and archive files use mode `0640`.
- Rollback is eligible only when `current` is a symlink to a release under `releases/` containing
  both production Compose files. A first deployment no longer records an invalid prior release.
- A healthy deployment runs exactly `podman system prune --force` after release retention. Cleanup
  failure emits a warning without failing the deployment; `--all` and `--volumes` are not used.
- Deterministic Bats fixtures cover certificate ordering, first-deployment failure, valid rollback,
  cleanup ordering, safe arguments, and non-blocking cleanup failure.

## Review

The architect review found no blocking issues. Backend, Web GUI, OpenAPI, Compose definitions,
application behavior, and database behavior were unchanged.

## Verification

The following checks passed:

- Bash syntax checks for all three changed scripts.
- ShellCheck for all three changed scripts.
- `bats deploy/tests/remote_release.bats`: 16 tests passed.
- `.codex/lint.sh`.
- `./penni-more.sh check docs`: 29 deployment tests passed.
- `./penni-more.sh check`: 23 backend tests, two Web tests, contract lint, and seven browser tests
  passed; one browser case was intentionally skipped by its configured project.
- `git diff --check` before the implementation commit.

The first complete-check attempt found that the local PostgreSQL service was not running. The
repository's local stack was started, the complete check passed, and the stack was stopped again
without removing its named volume.

`./penni-more.sh deploy` was not run because the user retained control of the production
redeployment. No production host, registry, or other operational external service was accessed.

## Deferred work

None.
