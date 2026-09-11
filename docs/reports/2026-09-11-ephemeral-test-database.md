# Ephemeral test database report

## Outcome

Database-dependent `penni-more.sh` commands now create one isolated PostgreSQL 17.6 container per
top-level invocation, use runtime-assigned loopback ports, and remove the container and temporary
data on success, failure, or interruption. Aggregate checks share that container across backend and
browser phases. Local Compose state is neither required nor modified, and simultaneous test runs
remain isolated.

The completed work follows the
[ephemeral test database implementation plan](../plans/2026-09-10-ephemeral-test-database.md).

## Changes

- Added direct Podman lifecycle management using a pinned PostgreSQL image, `--rm`, temporary data
  storage, a private CID file, bounded readiness checks, and exact-container cleanup.
- Overrode ambient database connection values only within owned test commands. `test`, backend and
  integration checks, aggregate checks, and publication validation now provision their database;
  non-database scopes do not.
- Added dynamic integration-server ports with cross-process locking, bind-loss detection, bounded
  retry, exact child-process cleanup, and endpoint propagation to Playwright.
- Replaced the backend and integration CI service databases with the shared command lifecycle and
  documented the self-contained local and publication behavior.
- Added deterministic Bats coverage for startup and readiness failures, malformed IDs and ports,
  signal status preservation, exact resource cleanup, port retry, and overlapping invocations.

## Review cycles

- The first architect review found that malformed startup output or an early signal could leave a
  created container without a cleanup target, and that the fixed integration port prevented
  concurrent checks. The implementation added private CID-file recovery, dynamic integration
  ports, exact PID cleanup, and stronger signal and overlap tests.
- The second review found a selection-to-bind race because the integration port reservation closed
  before Django bound it. The implementation added cross-process port locks, exact job ownership,
  readiness confirmation, retry after a lost bind, a forced-claim regression, and bounded overlap
  synchronization.
- The final review confirmed the container and server ownership, cleanup and status preservation,
  concurrent endpoint isolation, CI changes, documentation, and plan compliance. No blocking or
  actionable findings remain.

## Verification

- Bash syntax checks, ShellCheck, `.codex/lint.sh`, and `git diff --check` passed.
- Focused lifecycle Bats tests passed 25 of 25. `./penni-more.sh check docs` passed all 72 deployment
  tests, and the fake readiness-failure lifecycle check passed.
- `./penni-more.sh test` passed 49 pytest and five Vitest tests using ephemeral database port 33867.
- `./penni-more.sh check backend` passed formatting, Ruff, mypy, Django system, deployment and
  migration checks, and 49 pytest tests using database port 33099.
- `./penni-more.sh check integration` applied migrations and passed 12 Playwright tests using
  database port 42151.
- The final `./penni-more.sh check all` passed 72 deployment tests, all backend checks and 49 pytest
  tests, five Vitest tests, contract lint, and 12 Playwright tests. It used database port 35659 and
  integration port 60493.
- Two concurrent real integration checks both passed with database ports 39957 and 36897 and
  integration ports 57451 and 46677.
- Podman inspection before and after successful, failing, and concurrent runs found no remaining
  containers and an unchanged volume list. The existing `penni-more-database` volume remained
  present. No local Compose database container was running, so a running-container ID comparison
  was not applicable.

## Deferred tasks

None.

## Commits

- Implementation: `4cdf961b5e5d652d70658d8ec548612f89597979`
  (`feat: isolate test database lifecycle`).
- This report requires a separate local commit by the deployment agent; no report commit identifier
  exists yet.
