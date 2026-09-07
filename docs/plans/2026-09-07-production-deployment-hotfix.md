# Production deployment hotfix

## Summary

Correct the two failures observed during the first production deployment and add conservative
post-deployment Podman cleanup. The deployment must make Let's Encrypt state readable by the
unprivileged Nginx process, distinguish the absence of a prior release from a valid rollback target,
and run non-blocking `podman system prune --force` only after the deployed application passes its
public health check.

The deployment agent owns all implementation and validation. This cycle does not contact the
production VPS; after the fixes are committed locally, the user will manually run the next
deployment.

## Goals

- Make initial certificate issuance and every renewal leave all required Let's Encrypt paths
  traversable by Nginx group 101 and archive certificate/key files readable by that group.
- Prevent a missing `current` path during the first deployment from becoming a previous release or
  a self-referential rollback link.
- Cover both production regressions with focused deterministic Bats tests.
- Reclaim safe, unused rootless Podman resources after a fully healthy deployment with
  `podman system prune --force`.
- Preserve deployment success when pruning fails while emitting a visible warning.

## Non-goals

- Publishing or pulling application images through Docker Hub or another registry.
- Changing backend, Web GUI, OpenAPI, Compose service definitions, container images, application
  behavior, or database behavior.
- Changing the existing release and backup retention policy.
- Adding `--all` or `--volumes` to Podman pruning, or removing named volumes explicitly.
- Accessing, modifying, validating, or redeploying the production VPS during this cycle.
- Expanding the tests beyond focused coverage of the corrected deployment behavior.

## User-visible behavior

- A first deployment with no `current` link activates the new release without recording a bogus
  previous target. If health later fails and no valid prior release exists, the script reports the
  failure without attempting to start Compose files through a nonexistent or self-referential path.
- Certificate bootstrap and renewal set permissions that allow the Nginx process running as
  UID/GID 101 to traverse `/etc/letsencrypt`, `live/`, and `archive/`, follow the `live/` symlinks,
  and read the corresponding certificate and private-key files under `archive/`.
- After internal readiness and public HTTPS liveness succeed, deployment runs exactly
  `podman system prune --force`. It does not pass `--all` or `--volumes`.
- A prune failure prints a warning to standard error but does not turn an otherwise healthy
  deployment into a failure.

## Decisions and assumptions

- The production Nginx container continues to run as UID/GID 101. Certbot's one-off container will
  set group 101 on the Let's Encrypt root and relevant `live/` and `archive/` trees.
- Directories required to reach certificates use mode `0750`. Regular files in `archive/` use mode
  `0640`. The `live/` entries remain Certbot-managed symlinks; the scripts must not replace or copy
  them.
- Permission normalization runs after successful initial issuance and after each renewal, before
  starting or reloading Nginx. A permission failure remains blocking because Nginx could not safely
  consume the certificate.
- A rollback target exists only when the pre-activation `current` entry is an existing symlink that
  resolves to a real release directory with the required production Compose files. An absent or
  dangling `current` entry means there is no rollback target and must not create `previous`.
- Pruning is intentionally best-effort. Its position after the public health gate ensures failed or
  partially activated deployments never trigger cleanup. Ordinary prune preserves volumes because
  `--volumes` is absent and preserves tagged rollback images because `--all` is absent.
- The current production database, certificates, release directories, and running containers are
  outside this implementation scope and must not be used as test fixtures.

## Scope and ownership

### Deployment agent

The deployment agent exclusively owns implementation, tests, final validation, and local Git
operations for this cycle:

- `deploy/scripts/bootstrap-certificates.sh`: normalize the complete certificate path permissions
  after initial issuance and before Nginx startup.
- `deploy/scripts/renew-certificates.sh`: apply the same normalization after renewal and before the
  Nginx reload.
- `deploy/scripts/remote-release.sh`: validate prior-release detection and add best-effort pruning
  after successful public health and release retention.
- `deploy/tests/remote_release.bats`: minimally extend existing Bats coverage for certificate path
  permissions, first-deployment rollback detection, and safe/non-blocking post-success pruning.
- Any other `deploy/tests/*.bats` file only if required to keep an existing fixture focused; no new
  test framework is permitted.
- `docs/reports/2026-09-07-production-deployment-hotfix.md`: concise observed cycle report after
  implementation and validation.

The deployment agent is not alone in the worktree. It must preserve unrelated changes and must not
edit backend, Web GUI, contract, or other agents' documentation paths. Only the deployment agent may
stage and commit the completed cycle.

### Architect and coordinator

- `docs/plans/2026-09-07-production-deployment-hotfix.md`: this implementation plan.
- Review the implementation diff for compliance with the incident requirements and confirm that no
  backend, Web GUI, or OpenAPI contract behavior changed.
- No backend reviewer, Web GUI reviewer, or contract review is required because their ownership
  scopes are unchanged.

## Contract impact

There is no OpenAPI or application interface change. The existing public liveness endpoint remains
the deployment success criterion, and the existing internal readiness endpoint remains the
pre-ingress health criterion. No contract artifact or consumer may be edited.

## Implementation sequence

1. In both certificate lifecycle scripts, replace the archive-only permission adjustment with the
   same explicit normalization operation. Set group 101 and mode `0750` on
   `/etc/letsencrypt`; recursively set group 101 on `live/` and `archive/`; set directories under
   those trees to `0750`; and set regular archive files to `0640`. Run it only after Certbot
   succeeds and before Nginx is started or reloaded.
2. In `remote-release.sh`, initialize the previous target as empty. Populate it only when the
   pre-existing `current` entry is a symlink resolving to an existing release with both
   `deploy/compose.yaml` and `deploy/compose.production.yaml`. Only then update `previous` and make
   rollback eligible. Preserve the existing behavior that database migrations and backups are not
   reversed.
3. After the public HTTPS liveness loop has established a healthy release and after filesystem
   retention completes, invoke `podman system prune --force`. Guard it so failure prints a concise
   warning to standard error and the script still returns success. Do not include `--all`,
   `--volumes`, `sudo`, or a separate volume/image removal command.
4. Extend the existing Bats fixtures with deterministic fake commands and temporary release trees:
   - verify both initial issuance and renewal apply group/mode changes to the Let's Encrypt root,
     `live/`, and `archive/`, and do so before Nginx start/reload;
   - verify an absent `current` path produces no `previous` link and a simulated failed first
     deployment never invokes Compose using `current` or another invalid prior path;
   - verify a valid existing current release remains eligible for the existing code-only rollback;
   - verify prune runs only following a successful public health result and uses exactly
     `system prune --force` without `--all` or `--volumes`;
   - verify a fake prune failure emits a warning while the healthy deployment exits successfully.
5. Inspect the resulting diff for scope, shell safety, and preservation of existing deployment
   semantics. Fix every actionable finding in the deployment-owned files and repeat focused checks
   until no blocking findings remain.
6. Run final validation, create a coherent local Conventional Commit, and write the concise cycle
   report with observed results and the commit identifier. Do not run the production deploy command;
   hand the committed fix back to the user for manual redeployment.

## Review and verification

Run focused syntax, static analysis, and deployment tests during implementation:

```bash
bash -n deploy/scripts/bootstrap-certificates.sh
bash -n deploy/scripts/renew-certificates.sh
bash -n deploy/scripts/remote-release.sh
shellcheck deploy/scripts/bootstrap-certificates.sh
shellcheck deploy/scripts/renew-certificates.sh
shellcheck deploy/scripts/remote-release.sh
bats deploy/tests/remote_release.bats
```

The Bats results must demonstrate the observable ordering and failure behavior described above
without invoking a real SSH connection, operational host, public certificate authority, or Podman
state. Assertions based only on the presence of an unrelated string are insufficient when a small
fake-command behavior test can exercise the branch.

Before review handoff and again before the local commit, run:

```bash
.codex/lint.sh
./penni-more.sh check docs
git diff --check
```

Final repository validation must also run the complete shared check because deployment shell tests
are part of the repository-wide baseline:

```bash
./penni-more.sh check
```

If a validation command fails, the deployment agent fixes only its owned files and reruns the
affected command. The final report must identify any command not run and its exact reason. In
particular, `./penni-more.sh deploy` must be recorded as not run because the user retained manual
production deployment control.

## Risks

- Overly permissive certificate modes could expose the private key to unrelated container users.
  Restrict access to owner and group 101 with `0750` directories and `0640` archive files; do not
  use world-readable modes.
- Correcting only archive file modes repeats the observed failure because Nginx must traverse the
  Let's Encrypt root, `live/`, and per-domain directories before following symlinks.
- Treating any canonicalized `current` string as valid can recreate the first-deployment
  self-reference. Validate the symlink and target artifacts before recording it.
- Cleanup before public health could remove diagnostic build state after a failed deployment. Keep
  prune strictly after success and make its failure non-blocking.
- Adding `--all` could remove tagged images retained for rollback, and adding `--volumes` could
  remove persistent application state when containers are absent. Tests must reject both flags.
- No test can prove the production host's current filesystem ownership without accessing it. The
  local tests validate the generated operations; the user's manual redeploy provides the eventual
  operational observation.

## Deferred work

None. Docker Hub publishing is intentionally not recorded as deferred work in this cycle.

## Completion criteria

- Initial issuance and renewal both normalize the entire Let's Encrypt traversal path for Nginx
  group 101 while keeping private-key files unavailable to other users.
- An absent `current` path is never recorded as `previous`, and first-deployment failure does not
  attempt rollback through nonexistent Compose files or create a self-referential symlink.
- Existing valid prior-release rollback remains code-only and does not restore the database.
- A healthy deployment invokes exactly `podman system prune --force` only after public liveness and
  release retention; no `--all` or `--volumes` option is present.
- Prune failure produces a warning but leaves the deployment exit status successful.
- Focused Bats regression tests, Bash syntax checks, ShellCheck, `.codex/lint.sh`, the docs scope,
  the complete repository check, and `git diff --check` all pass with observed results.
- No backend, Web GUI, OpenAPI, production service, or Docker Hub tracking artifact is changed.
- The deployment agent creates the local implementation commit, the cycle report records the
  observed checks and commit, and no Git remote mutation occurs.
- The user receives a clear handoff that the committed fix is ready for their manual redeployment.
