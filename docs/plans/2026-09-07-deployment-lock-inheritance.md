# Deployment lock inheritance

## Summary

Prevent long-lived Podman networking helpers from inheriting the deployment lock. The lock must
exclude concurrent deployments for the complete lifetime of the deployment process, then become
available as soon as that process exits, even if a helper such as `aardvark-dns` remains alive.

The current `remote-release.sh` opens descriptor 9 and locks it in the deploying shell. Every
subsequent command inherits that descriptor unless it is explicitly closed, so a daemonized Podman
descendant can keep the open file description and advisory lock alive after the shell exits. The fix
will separate lock supervision from deployment work: an external `flock --close` supervisor retains
the lock while it waits, and the worker plus all descendants start without the lock descriptor.

## Goals

- Preserve non-waiting mutual exclusion throughout every state-changing deployment.
- Ensure the deployment worker and all of its descendants lack the lock descriptor.
- Release the lock when the deployment process finishes, regardless of surviving Podman helpers.
- Preserve the deployment worker's success or failure status and the existing contention status and
  diagnostic.
- Add deterministic regression coverage for both concurrent exclusion and post-exit release.
- Provide a safe user-operated procedure for rotating the already-confirmed stale lock after the
  fixed local commit exists.

## Non-goals

- Stopping, restarting, or reconfiguring `aardvark-dns`, Podman networking, running containers, or
  the production host.
- Accessing production during implementation, review, validation, or commit.
- Changing release activation, backups, migrations, TLS, health checks, pruning, or retention.
- Changing backend, Web GUI, OpenAPI, Compose, container-image, or systemd behavior.
- Replacing advisory file locking with a persistent lock directory, PID-file protocol, database
  lock, or remote coordination service.
- Removing the renamed stale lock inode while a known helper may still hold it.

## User-visible behavior

- While one deployment is active, a second deployment exits immediately with status 3 and reports
  `Another deployment is already running.`
- Once the deployment process exits, another deployment can acquire the same lock path immediately.
  This remains true when a helper spawned during the first deployment is still running.
- Successful and failed deployments continue to return the deployment worker's original exit
  status; only lock contention is translated to the established status 3 and diagnostic.
- The normal local `./penni-more.sh deploy` interface and remote directory layout do not change.
- After the fix is committed, the user receives an explicit recovery procedure to rotate the stale
  `deployment.lock` inode without stopping healthy application containers.

## Decisions and assumptions

- Use util-linux `flock`, which is already required by remote preflight and the production host
  contract. Do not add a host or project dependency.
- Keep `remote-release.sh` as the remotely invoked entry point and lock supervisor. Move the
  state-changing deployment body into a deployment-owned worker script. This avoids an internal
  re-entry flag that could accidentally bypass locking.
- The supervisor opens and holds the lock, invokes the worker through `flock --close`, and waits for
  it. `--close` must ensure the worker is invoked without the lock descriptor while the supervisor
  still owns the lock until the worker terminates. Do not combine `--close` with a no-fork mode.
- Use a dedicated internal conflict exit code from `flock`, distinct from expected worker failures.
  Translate only that code to the public status 3 and contention diagnostic; propagate every other
  status unchanged.
- Validate `remote_dir` and `release_id` before constructing either the lock path or worker command.
  Resolve the worker path relative to the entry-point script, never the caller's current directory.
- The worker is not a public deployment entry point. It relies on the supervisor for exclusion but
  retains the current argument and environment validation that protects deployment operations.
- Tests use temporary directories and fake commands only. A deliberately long-lived fake helper
  must redirect inherited output streams so the test harness does not block on its lifetime.
- The stale production lock has already been diagnosed as descriptor inheritance, but rotating its
  pathname while a genuine deployment is active would split mutual exclusion across two inodes.
  Recovery must first establish that no deployment worker is active.

## Scope and ownership

### Deployment agent

The deployment agent exclusively owns implementation, tests, final checks, the local commit, and
the cycle report:

- `deploy/scripts/remote-release.sh`: retain argument validation and become the lock supervisor.
- `deploy/scripts/remote-release-worker.sh`: new internal worker containing the state-changing
  release sequence currently in `remote-release.sh`, without opening or owning the deployment lock.
- `deploy/tests/remote_release.bats`: adapt existing deployment tests to the split and add focused
  behavioral lock-lifetime regression coverage.
- `deploy/scripts/deploy.sh` only if transport validation must explicitly include the new worker;
  the existing recursive synchronization of `deploy/` should otherwise remain unchanged.
- `docs/reports/2026-09-07-deployment-lock-inheritance.md`: concise report after implementation,
  review, validation, and commit.

The deployment agent is not alone in the worktree. It must preserve unrelated changes, especially
the preceding production hotfix, and must not edit any backend, Web GUI, OpenAPI, or unassigned
documentation path. Only the deployment agent may stage or commit.

### Architect and coordinator

- `docs/plans/2026-09-07-deployment-lock-inheritance.md`: this plan.
- Review the completed deployment diff for lock lifetime, exit-status propagation, path safety, and
  cross-scope consistency.
- No backend, Web GUI, or contract reviewer is required because those scopes are unchanged.

The supervisor and worker changes are dependent and must be implemented by one deployment agent;
there is no safe parallel implementation split.

## Contract impact

There is no OpenAPI, HTTP, application, database, or Compose contract change. The only affected
interface is deployment-process coordination on the remote host. `deploy.sh` continues to invoke
`remote-release.sh` with the same two positional arguments and observe the same public exit codes.

## Implementation sequence

1. Preserve safe validation of the absolute remote directory and release identifier in
   `remote-release.sh`. Resolve the adjacent worker path, derive `deployment.lock`, and verify that
   required lock and worker capabilities exist before attempting deployment.
2. Make `remote-release.sh` invoke the worker under an external, exclusive, non-waiting
   `flock --close` supervisor. Assign a unique internal contention code. Return success when the
   worker succeeds, translate only lock contention to status 3 plus the existing diagnostic, and
   propagate all other worker or `flock` errors without masking them.
3. Move the current release workflow to `remote-release-worker.sh`. Preserve `set -euo pipefail`,
   validated positional inputs, production environment validation, and all existing ordering and
   failure behavior. Remove descriptor-9 creation and locking from the worker. Keep its top-level
   flow unchanged beyond what the extraction requires.
4. Update existing Bats references so tests that inspect or execute deployment behavior target the
   worker where appropriate while entry-point and coordination tests target the supervisor. Do not
   weaken the existing backup, migration, rollback, certificate, health, retention, or prune
   assertions during the split.
5. Add two behavioral concurrency tests:
   - Start a supervised fake deployment worker that blocks on a deterministic fixture signal. Wait
     until it has acquired the lock, invoke a second supervisor against the same remote directory,
     and assert immediate status 3 with the contention diagnostic. Release and reap the first
     process in cleanup.
   - Have the fake worker spawn a long-lived helper, record its PID, and exit. Confirm the supervisor
     exits while the helper remains alive, then confirm another supervisor or direct non-waiting
     `flock` acquisition succeeds on the same lock path. Explicitly terminate and reap the fake
     helper during test cleanup.
6. Run the focused checks and inspect the diff. Return every actionable finding to the deployment
   agent and repeat review until no blocking findings remain.
7. Run final validation and create one coherent local Conventional Commit without any remote Git
   mutation. Write the cycle report with observed checks and commit ID; have the deployment agent
   commit the report if separate.
8. Only after the fixed commit exists, provide the user the operational recovery handoff below. The
   agent must not execute it or contact production. The user will rotate the stale lock and manually
   redeploy.

## Operational recovery handoff

The handoff must tell the user to connect as the unprivileged `penni` account and perform these
guards before changing the lock pathname:

1. Confirm the locally fixed commit is complete and is the commit selected for the next deployment.
2. Confirm no `remote-release.sh` or `remote-release-worker.sh` process is active. If one is active,
   do not rotate the lock; let the deployment finish or diagnose that process first.
3. Attempt a non-waiting `flock` acquisition on
   `${HOME}/penni-more/deployment.lock`. If it succeeds, the lock is already free and no rotation is
   needed.
4. Only when the acquisition still fails and no deployment process exists, atomically rename the
   lock path to a timestamped name in the same directory, such as
   `deployment.lock.stale-<UTC timestamp>`. Do not delete it and do not stop the healthy application
   containers. The inherited descriptor remains attached to the renamed inode, while the fixed
   deployment creates and supervises a new `deployment.lock` inode.
5. Run the fixed deployment manually from the local machine. Confirm it completes and that a
   subsequent non-waiting lock probe succeeds. Retain the renamed stale file until the old helper no
   longer exists or the VPS has rebooted; later removal is a separate explicit cleanup decision.

The final user-facing handoff should provide copyable commands with quoted, braced Bash expansions
and an abort-on-active-deployment guard. It must not ask the user to kill `aardvark-dns`, delete a
live lock inode, use `sudo`, or remove Podman state.

## Review and verification

Run focused syntax and static checks for every changed deployment script:

```bash
bash -n deploy/scripts/remote-release.sh
bash -n deploy/scripts/remote-release-worker.sh
shellcheck deploy/scripts/remote-release.sh
shellcheck deploy/scripts/remote-release-worker.sh
bats deploy/tests/remote_release.bats
```

The focused tests must observe real advisory-lock behavior on temporary files, not merely grep for
`flock` arguments. They must use bounded polling or fixture signals rather than timing-only sleeps,
and cleanup traps must terminate every helper even after assertion failure. The regression is
covered only if the helper is confirmed alive before the second post-exit acquisition succeeds.

Before review handoff and again before commit, run:

```bash
.codex/lint.sh
./penni-more.sh check docs
git diff --check
```

Final validation must include the complete shared repository check:

```bash
./penni-more.sh check
```

No validation may invoke `./penni-more.sh deploy`, SSH, a production service, or real Podman state.
Record those operational checks as intentionally not run and identify the Bats regression that
covers the lock lifecycle locally.

## Risks

- Closing the descriptor in both supervisor and worker would release the lock before deployment
  finishes. The external `flock` process must retain ownership while only its command-side copy is
  closed.
- Allowing the worker or any intermediate shell to receive the descriptor repeats the production
  defect. The behavioral long-lived-helper test must prove descriptor isolation rather than infer it
  from source text.
- Confusing the conflict code with a worker failure could falsely report an active deployment or
  mask the real failure. Use a dedicated internal code and assert propagation of a representative
  worker failure.
- Splitting the script could omit a validation or reorder state changes. Compare the worker with the
  pre-change workflow and retain all existing tests.
- Rotating a genuinely active lock would allow two deployments to mutate the same release state.
  The operational handoff requires both process inspection and a failed lock probe before rename.
- Deleting the stale inode is unnecessary and makes recovery less inspectable. Rename it in place
  and leave cleanup until the holding helper has exited.

## Deferred work

None. General Podman network-helper lifecycle changes are outside this defect and are not required
for completion.

## Completion criteria

- One active deployment excludes a second for its entire state-changing lifetime with immediate
  status 3 and the established diagnostic.
- The deployment lock becomes available immediately after the supervised worker exits, even while
  a verified fake long-lived descendant remains alive.
- The supervisor propagates worker success and non-contention failure statuses without masking
  diagnostics.
- No deployment worker or Podman descendant inherits the lock descriptor.
- All pre-existing deployment behavior and tests remain intact after the supervisor/worker split.
- Focused behavioral tests, Bash syntax, ShellCheck, `.codex/lint.sh`, docs checks, the complete
  shared check, and `git diff --check` pass with observed results.
- Changes remain limited to deployment-owned scripts, tests, this plan, and the cycle report; no
  production access or Git remote mutation occurs.
- A local implementation commit and concise cycle report exist.
- The user receives the guarded stale-lock rotation and manual redeployment instructions only after
  the fixed commit is ready.
