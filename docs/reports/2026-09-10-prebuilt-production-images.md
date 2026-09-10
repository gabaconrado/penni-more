# Pre-built production images report

## Outcome

Production releases now use two operator-published, version-only public Docker Hub images instead
of building application code on the server. The local publish command validates the repository,
creates an annotated local Git tag, builds both `linux/amd64` targets, and pushes them in the agreed
order. Versioned deployment verifies the matching local tag, transfers only deployment automation,
and pulls the selected images before any production mutation.

The completed work follows the
[pre-built production images implementation plan](../plans/2026-09-10-prebuilt-production-images.md).

## Changes

- Added `./penni-more.sh publish VERSION` for stable-version validation, clean-`main` enforcement,
  existing Podman authentication checks, complete local validation, forced annotated local tags,
  two-target builds, and ordered Docker Hub pushes.
- Changed production Compose to use
  `docker.io/gabaconrado/penni-more:VERSION` and
  `docker.io/gabaconrado/penni-more-nginx:VERSION` without a build fallback. Local Compose retains
  its application build.
- Changed `./penni-more.sh deploy VERSION` to require a clean `main` checkout and matching annotated
  `vVERSION` tag at `HEAD`. Deployment retains its timestamped operational release ID, records the
  separate image version with mode `0600`, and no longer transfers backend or Web source.
- Changed remote activation to pull both images and run the Django deployment check before shutdown
  or database mutation. Backup, migration, readiness, TLS, public health, locking, retention,
  cleanup, and recovery ordering remain intact.
- Preserved first-upgrade recovery for an older release without image-version metadata while making
  new metadata fail closed when the image-version field is present but empty or malformed.
- Kept CI validation/test-only and added deterministic mocked coverage for publish, deploy, image
  pull, metadata, failure ordering, and current, previous, and legacy recovery behavior.

## Review cycles

- The first architect review found that a release created before this feature had no image-version
  metadata, so recovery during the first upgraded deployment could fail to restart the prior local
  images. The deployment implementation added explicit legacy recovery behavior and a regression
  test.
- The next review found that an explicitly empty image-version field was indistinguishable from an
  absent legacy field. The implementation now tracks key presence separately: genuine absence
  alone selects legacy behavior, while present-empty and other malformed values fail before prior
  Compose evaluation.
- The final architect review confirmed release-specific image selection, version-leak prevention,
  strict current-release validation, recovery order and status preservation, and meaningful test
  coverage. No blocking findings remain.

## Verification

- Bash syntax checks and ShellCheck passed for the changed shell automation.
- The Compose schema and repository production-policy validator passed.
- `.codex/lint.sh`, `./penni-more.sh check docs`, and `git diff --check` passed.
- The final focused Bats run passed all 55 deployment tests.
- The final `./penni-more.sh check` passed, including 49 of 49 backend pytest tests, 5 of 5 Web unit
  tests, and 12 of 12 browser tests. Formatting, linting, type checking, Django system and migration
  checks, Web builds, OpenAPI contract validation, and integration checks also passed.
- The initial full check failed only because the already-configured local PostgreSQL service was not
  listening. After starting the already-present local Compose database, the same full check passed.
- No real image build, Docker Hub publish or push, deployment over SSH, or other operational
  external access was performed. Tests mocked those command boundaries.
- No release tag was created and no Git remote write was performed during implementation or
  verification.

## Deferred tasks

None.

## Commits

- Implementation: `5e5177dec93442d0b2aa5bdd80cd0b6aba6fcb57`
  (`feat: publish pre-built production images`).
- This report requires a separate local commit by the deployment agent; no report commit identifier
  exists yet.
