# Release version visibility and operator defaults report

## Outcome

Release operations are shorter and version state is now visible without conflating registry and
deployment state. The repository README dynamically reports the latest stable application image,
while the application shows the exact active production image version or `dev` locally.

The completed work follows the
[release version visibility implementation plan](../plans/2026-09-16-release-version-visibility.md).

## Changes

- Added a linked README badge labeled `latest image` that selects the highest stable semantic
  version published for `gabaconrado/penni-more`.
- Changed `publish VERSION` to run interactive `podman login docker.io` after inexpensive local
  guards and before checks, tagging, builds, or pushes. Login failure stops all later work without
  passing or storing credentials.
- Defaulted deployments to the overridable SSH target `penni` and remote directory
  `/home/penni/penni-more`, preserving validation and dry-run behavior.
- Passed the active release's `PENNI_MORE_IMAGE_VERSION` into Django, validated it as a stable
  version, and displayed `vMAJOR.MINOR.PATCH` beside the Penni More brand. Local pages display
  `dev` deterministically.
- Added deployment, backend, template, and browser regression coverage. No OpenAPI, migration,
  dependency, lockfile, financial-domain, or request-time external-service change was required.

## Review cycles

- Backend and Web GUI reviewers reported no blocking findings. The backend reviewer noted that the
  production behavior is proven across settings, context, and rendering layers rather than one
  production request fixture. The Web reviewer noted that the browser harness has no authenticated
  fixture; backend rendered-response and template tests cover that path. Both gaps were nonblocking
  under the approved plan.
- The integrated architect review found the deployment ordering, failure safety, override behavior,
  runtime version chain, documentation semantics, and accessible shared UI consistent with the
  plan. OpenAPI remained unchanged, so no contract coder was required.
- No correction cycle was needed because all reviews completed without blocking findings.

## Verification

- `./penni-more.sh check` passed with 77 deployment and Bats tests, 110 backend tests, 13 Web unit
  tests, and 18 Playwright tests.
- Formatting, shell and Python linting, type checking, Django system and deployment checks,
  migration consistency, Compose and documentation validation, OpenAPI contract linting, Web asset
  building, and browser integration checks passed.
- `.codex/lint.sh` passed.
- A real Podman login, image build, push, SSH connection, deployment, production access, and live
  Docker Hub or registry verification were intentionally not run. These operational actions require
  separate immediate authorization and were not needed to validate the implementation.

## Deferred tasks

None.

## Commits

- Implementation: `807f8e5c08f0626bb5b2516a704000f5d4aa99ed`
- This report requires a separate local commit by the deployment agent. No remote Git operation was
  performed.
