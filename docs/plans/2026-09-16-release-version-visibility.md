# Release version visibility and operator defaults

## Summary

Make release operations shorter and make the running application version visible without confusing
deployment state with registry state. The publication command will perform the interactive Docker
Hub login itself before validation and image work. Deployment will default to the established
`penni` SSH alias and `/home/penni/penni-more` directory while retaining environment overrides.

The repository README will show a dynamic Shields.io badge for the highest stable semantic version
published for the application image. Separately, every rendered application page will show `dev`
locally or the exact `vMAJOR.MINOR.PATCH` selected by the current production release metadata.

## Goals

- Make `./penni-more.sh publish VERSION` invoke interactive `podman login docker.io` before the
  expensive repository check, image builds, or pushes.
- Stop publication immediately when registry login fails, without accepting, printing, or storing
  credentials in repository-controlled arguments, files, metadata, or logs.
- Default deployment to `DEPLOY_SSH_TARGET=penni` and
  `DEPLOY_REMOTE_DIR=/home/penni/penni-more`, while allowing non-empty caller environment values to
  override either default independently.
- Add a README badge labeled `latest image` that dynamically reports the highest stable semantic
  version tag published for `gabaconrado/penni-more` and links to that repository's Docker Hub tags.
- Show an unobtrusive accessible version badge beside the Penni More brand on login and
  authenticated pages.
- Render `dev` under local/test settings and `v${PENNI_MORE_IMAGE_VERSION}` under production
  settings, using the version recorded in the active release's `release.env`.
- Preserve all release validation, tagging, build, push, dry-run, deployment, rollback, health,
  backup, and migration behavior not expressly changed here.

## Non-goals

- Querying Docker Hub, Shields.io, or another external service from Django or at application
  request time.
- Calling Docker Hub, logging in, building, publishing, deploying, or contacting production during
  implementation or tests.
- Claiming that the newest published image is the currently deployed version.
- Adding a tracked `CURRENT_VERSION` file or hard-coding `0.2.0` into application or deployment
  source. Version `0.2.0` is the stated current production intent; operational truth remains the
  active release's `PENNI_MORE_IMAGE_VERSION` value.
- Changing the stable `MAJOR.MINOR.PATCH` grammar, image names, Git-tag policy, release ID format,
  deployment host validation, or remote release process.
- Adding an OpenAPI operation, database model or migration, dependency, client-side JavaScript,
  financial behavior, or user-configurable version value.
- Showing the operational release ID, Git commit, branch, image digest, Nginx image version, or a
  live deployment status in the UI.

## User-visible behavior

### README image badge

Near the repository title/status, `README.md` displays a Shields.io Docker version badge whose
visible label is `latest image`. Its image URL is:

```text
https://img.shields.io/docker/v/gabaconrado/penni-more?sort=semver&label=latest%20image
```

The badge links to:

```text
https://hub.docker.com/r/gabaconrado/penni-more/tags
```

The badge describes the application image repository, not the separately published Nginx image and
not the live deployment. Shields.io and Docker Hub own refresh timing, so a newly pushed tag may not
appear immediately. The Markdown must use useful alternative text such as `Latest Docker image`.

### Publication

`./penni-more.sh publish 0.2.0` retains its current argument, required-tool, clean-worktree, and
exact-`main` validation. After those inexpensive local guards and before `./penni-more.sh check`,
tagging, building, or pushing, it runs exactly:

```text
podman login docker.io
```

Podman owns the interactive username, token/password, and credential-store flow through its normal
standard input/output. The script does not wrap credentials in arguments or environment variables
and does not echo them. A cancelled or failed login returns nonzero and performs no repository
check, tag mutation, build, or push. The obsolete `podman login --get-login docker.io` preflight and
its guidance to log in separately are removed. A successful login continues through the existing
full check, state recheck, local annotated tag, two builds, and ordered pushes.

### Deployment defaults

Both commands below use `penni:/home/penni/penni-more` when the variables are unset or empty:

```text
./penni-more.sh deploy 0.2.0 --dry-run
./penni-more.sh deploy 0.2.0
```

An operator can still override one or both values for another environment:

```text
DEPLOY_SSH_TARGET=other-host \
DEPLOY_REMOTE_DIR=/srv/penni-more \
  ./penni-more.sh deploy 0.2.0 --dry-run
```

Defaults pass through the existing character and safe-absolute-path validation. An explicitly
provided unsafe non-empty override still fails before transport. Dry-run remains read-only beyond
the existing remote preflight, and a normal deploy retains the existing mutation order.

### Application version badge

Every page extending `src/web/templates/base.html`, including the anonymous login page and all
authenticated pages, displays a small text badge beside the `Penni More` brand:

- local development and tests display exactly `dev`;
- production with `PENNI_MORE_IMAGE_VERSION=0.2.0` displays exactly `v0.2.0`.

The badge is visible text, readable by assistive technology, does not change the accessible name or
target of the home link, fits without horizontal overflow at supported mobile widths, and requires
no JavaScript. It exposes only the non-secret image version, not other release metadata.

## Decisions and assumptions

- The README badge uses the application repository because it represents the user-facing release.
  `sort=semver` selects the highest stable semantic-version tag rather than the most recently pushed
  arbitrary tag. The label explicitly says `latest image` to avoid a deployment claim.
- README rendering may contact Shields.io and Shields.io may contact Docker Hub. This happens only
  in the reader's repository host/browser; application runtime and tests make no such request.
- Local behavior is deterministic: the local settings module always exposes `dev`, even if a
  developer's shell happens to contain `PENNI_MORE_IMAGE_VERSION`.
- Production fails closed when `PENNI_MORE_IMAGE_VERSION` is absent, blank, or not a stable
  `MAJOR.MINOR.PATCH` value. Although deployment already validates release metadata, Django settings
  are a separate runtime boundary and validate it again.
- The production settings validator follows the existing release grammar: three dot-separated
  non-negative integers, with no leading zero except the single digit `0`; no leading `v`,
  prerelease, or build suffix. Whitespace is stripped before validation. The displayed `v` is added
  by settings and is never part of release metadata.
- The Django/template interface is one setting named `PENNI_MORE_VERSION_LABEL` and one template
  context variable named `penni_more_version`. Base/local settings set the label to `dev`.
  Production settings replace it with `v` plus the validated image version.
- A focused context processor at `penni_more.context_processors.release_version` returns only
  `{"penni_more_version": settings.PENNI_MORE_VERSION_LABEL}`. It is registered in the existing
  Django template configuration so inherited templates receive the same value without view
  duplication.
- The production Compose server environment explicitly maps
  `PENNI_MORE_IMAGE_VERSION: ${PENNI_MORE_IMAGE_VERSION:?PENNI_MORE_IMAGE_VERSION is required}`.
  The remote workflow already sources and exports the active target release's `release.env`, so no
  new metadata file or remote lookup is needed.
- The default SSH target relies on the operator's existing SSH configuration entry named `penni`.
  Establishing that SSH configuration or copying keys remains a host/operator prerequisite.
- Interactive login can refresh an existing Podman authentication. Publication deliberately asks
  Podman to log in on every invocation, as requested; it does not first inspect cached login state.

## Scope and ownership

### Deployment agent

The `deployment_agent` owns these operational, documentation, validation, and test changes:

- `README.md`: add the dynamic, linked `latest image` badge and remove or correct stale status text
  only as necessary to avoid contradicting the implemented repository state.
- `deploy/scripts/publish.sh`: replace the cached-login check with the interactive login call at the
  agreed point, preserving all later release behavior and failure status.
- `deploy/scripts/deploy.sh`: assign overridable defaults before existing validation and transport.
- `deploy/compose.production.yaml`: pass the required release image version explicitly into the
  Django server container.
- `deploy/scripts/validate_compose.py`: extend production policy validation to require that exact
  server environment mapping while preserving current image/build/port checks.
- `penni-more.sh`: provide a valid deployment-check-only image version to the production Django
  `check --deploy` invocation; do not set an image version for local/integration execution.
- `deploy/tests/publish.bats`: stub interactive `podman login docker.io` and verify its order,
  success, failure, and absence of the removed `--get-login` call.
- `deploy/tests/deploy.bats`: verify defaults, independent non-empty overrides, validation of unsafe
  overrides, and unchanged dry-run/normal behavior.
- `deploy/tests/commands.bats` and existing deployment validation tests only if needed to observe
  top-level routing or the Compose environment invariant; prefer the existing fixtures over a new
  harness.
- `deploy/README.md`: document that publish performs login and that the standard deploy commands use
  defaults, plus concise override examples and the distinction between latest published and running
  versions.
- Final repository validation, selective staging, and justified local commits. Git mutations in
  tests remain confined to temporary fixture repositories.

The deployment agent also stages and commits the final report after the architect writes
`docs/reports/2026-09-16-release-version-visibility.md`.

### Backend coder

The `backend_coder` exclusively owns Django implementation under `src/backend`:

- `src/backend/penni_more/settings/base.py`: define the local/default `dev` label and register the
  focused context processor.
- `src/backend/penni_more/settings/production.py`: require, trim, validate, and format
  `PENNI_MORE_IMAGE_VERSION` as the production label.
- `src/backend/penni_more/context_processors.py`: expose the stable context interface without
  request-time external I/O.
- `src/backend/tests/test_settings.py`: cover required and malformed production versions, exact
  formatted production output, and deterministic local output.
- `src/backend/tests/test_home.py` and/or `src/backend/tests/test_auth.py`: cover context/rendering
  on authenticated and anonymous base-template responses, including exact escaped text.

No model, migration, form, view-specific version logic, health response, or dependency change is
allowed. If a listed test file needs no textual change because the same observable behavior is
covered in another owned backend test, record that in the final report.

### Web GUI coder

The `web_gui_coder` exclusively owns Web GUI implementation under `src/web`:

- `src/web/templates/base.html`: render the version badge beside, but not inside the accessible
  name of, the Penni More home link using existing Tailwind/daisyUI tokens.
- `src/web/tests/unit/shell.test.js`: assert the shared template uses the agreed context variable,
  displays it on both sides of the authentication conditional, retains navigation semantics, and
  adds no script.
- `src/web/tests/browser/login.spec.js`: assert `dev` is visibly and accessibly rendered on the
  anonymous local login page, retains keyboard behavior, has no horizontal overflow, and produces
  no automated accessibility regression.
- Update another existing browser test only if needed to cover the authenticated shell with the
  current integration fixtures; backend request coverage must in all cases prove the authenticated
  rendering path.

No new JavaScript, package, arbitrary visual token, page-specific duplicate badge, or external
request is allowed.

### Architect and reviewers

- The `backend_reviewer` reviews backend settings, validation, context exposure, and request tests.
- The `web_gui_reviewer` reviews shared-template semantics, responsive/accessibility behavior, and
  Web tests.
- The architect reviews the deployment diff, the cross-scope setting/context/Compose interface,
  and confirms OpenAPI remains unchanged. The architect writes the final report after all blocking
  findings are resolved.
- Every actionable review finding returns to its owning coder or deployment agent, followed by
  another review cycle. Style-only preferences already enforced by automation do not block.

The three implementation assignments have disjoint file ownership and may run concurrently because
their interface names and values are fixed above. Web rendering depends logically on the backend
context contract, and production rendering depends logically on Compose propagation, so integrated
verification begins only after all three assignments finish.

Any additional changed path must be assigned to its repository owner and justified against this
plan before editing. All agents preserve unrelated user changes.

## Contract impact

There is no OpenAPI change. No route, request, response, schema, authentication rule, or HTTP health
payload changes, so `src/contract/openapi.yaml` and contract-generated artifacts remain untouched.

The new internal runtime interface is:

```text
release.env PENNI_MORE_IMAGE_VERSION=MAJOR.MINOR.PATCH
  -> production Compose server environment PENNI_MORE_IMAGE_VERSION
  -> production setting PENNI_MORE_VERSION_LABEL=vMAJOR.MINOR.PATCH
  -> template context penni_more_version
  -> visible base-template badge vMAJOR.MINOR.PATCH
```

The local interface terminates at `PENNI_MORE_VERSION_LABEL=dev`; local Compose does not need an
image-version variable. The README badge is independent of this chain and reports registry state.

The changed command-line contracts are:

- `publish VERSION` now always invokes interactive Docker Hub login after local preflight and
  before full validation/build/push;
- `deploy VERSION [--dry-run]` now supplies the agreed SSH target and remote directory defaults,
  while non-empty environment overrides remain supported.

## Implementation sequence

1. The deployment agent updates deterministic Bats fixtures first. Replace the Podman login stub's
   `--get-login` branch with an interactive-login branch and add call-order/failure assertions. Add
   default and override deployment cases without contacting SSH or production.
2. In parallel, the backend coder adds failing settings/context/request tests and the Web GUI coder
   adds failing shared-template/unit/browser assertions for the exact `dev` presentation.
3. The deployment agent changes publish login orchestration and deploy default assignment. Keep
   argument/tool/Git preflight before login, login before `penni-more.sh check`, and all existing
   post-check state/tag/build/push ordering. Preserve deploy validation and dry-run semantics.
4. The deployment agent passes `PENNI_MORE_IMAGE_VERSION` through production Compose, makes the
   Compose policy validator assert the exact required interpolation, and updates the production
   `check --deploy` environment with a valid synthetic value such as `0.0.0`.
5. The backend coder adds the deterministic base label, validates production metadata with the
   existing stable-version grammar, registers the context processor, and exposes only the formatted
   label. Do not read Docker Hub or release files in a request.
6. The Web GUI coder adds the compact visible badge beside the brand in `base.html`, using the
   agreed context variable and existing responsive styles. Confirm it is outside the authentication
   branch so login and authenticated pages share it.
7. The deployment agent updates `README.md` and `deploy/README.md`. Documentation must distinguish
   the dynamic latest-published-image badge from the running-version UI and must not claim that a
   publish succeeded or that `0.2.0` is verifiably live.
8. Each coder runs scope checks before review. Matching reviewers inspect completed diffs. The
   architect performs cross-scope review after all components are present. Findings are fixed and
   rereviewed until no blocking finding remains.
9. The deployment agent runs the complete repository checks, inspects all diffs, stages only this
   feature, and creates one or more justified local commits. Nothing is pushed, published, or
   deployed.
10. The architect writes the concise cycle report, including observed checks and intentionally
    omitted live operations. The deployment agent validates and commits the report if separate.

## Review and verification

### Publication and deployment tests

`deploy/tests/publish.bats` must prove with a stubbed Podman executable that:

- malformed versions, missing tools, dirty worktrees, and non-`main` branches fail before login;
- a valid invocation executes exactly `podman login docker.io`, never `login --get-login`, and does
  not pass username, password, token, or password-stdin arguments;
- login occurs before `check`, tag, either build, or either push;
- login failure preserves a nonzero result and prevents check, tag, builds, and pushes;
- successful login retains the existing full-check/state-recheck/tag/build/push ordering;
- all existing build/push failure and partial-publication rerun tests still pass.

`deploy/tests/deploy.bats` must prove with stubbed SSH/rsync that:

- with both variables unset, dry-run targets exactly `penni:/home/penni/penni-more`;
- a non-empty `DEPLOY_SSH_TARGET` override and a non-empty `DEPLOY_REMOTE_DIR` override each work
  independently, and overriding both retains existing behavior;
- empty variables select defaults, while unsafe non-empty target/path overrides still fail before
  transport;
- dry-run still performs only remote preflight and a real test fixture still writes exact release
  metadata and follows the existing transfer/remote-worker flow.

Compose validation must prove the merged production server environment contains the exact required
`PENNI_MORE_IMAGE_VERSION` interpolation. Existing production image, no-build, network, port, and
API-documentation rules continue to pass.

### Backend and Web tests

Backend tests must prove:

- local settings and rendered local pages show exactly `dev`, unaffected by an ambient image
  version;
- production settings require `PENNI_MORE_IMAGE_VERSION` in addition to existing secrets/domain/
  database configuration;
- `0.2.0` produces `PENNI_MORE_VERSION_LABEL == "v0.2.0"`;
- blank, shortened, leading-zero, `v`-prefixed, prerelease, build-metadata, and otherwise malformed
  values raise `ImproperlyConfigured` with a non-secret diagnostic;
- the context processor returns only the public formatted label;
- anonymous login and authenticated home responses render the exact badge text with normal Django
  escaping and without changing authentication controls.

Web unit/browser tests must prove:

- `base.html` renders `penni_more_version` beside the home brand outside the authentication branch;
- the local login page visibly exposes `dev` to assistive-technology selectors;
- the badge adds no script and core behavior still works without JavaScript;
- navigation, keyboard focus order, mobile horizontal-overflow, and automated accessibility checks
  remain passing.

### Commands and review gates

During implementation, run and observe at minimum:

```text
bash -n penni-more.sh deploy/scripts/*.sh
shellcheck penni-more.sh deploy/scripts/*.sh
bats deploy/tests/commands.bats deploy/tests/publish.bats deploy/tests/deploy.bats
uv run --project src/backend python deploy/scripts/validate_compose.py
./penni-more.sh check backend
./penni-more.sh check web
./penni-more.sh check integration
npm --prefix src/contract run lint
.codex/lint.sh
uv run --project src/backend python deploy/scripts/check_markdown_links.py
git diff --check
```

After all review findings are resolved and before commit, the deployment agent runs and observes:

```text
./penni-more.sh check
```

Tests must use command stubs and local fixtures. They must not execute a real Podman login, build,
push, deploy, SSH connection, registry lookup, Shields request, or production access. A live
publish/deploy and confirmation that Docker Hub currently reports `0.2.0` are intentionally not
verified in this cycle because those operations require separate immediate authorization and are
not necessary to validate the code.

Reviewers must confirm:

- the README says latest image while the UI says running version through release metadata;
- production version validation fails closed and local output remains deterministic;
- no credentials or sensitive metadata can reach source, rendered HTML, command logs, or fixtures;
- publish login and deploy defaults do not weaken existing release safety checks;
- login and authenticated layouts remain accessible and responsive;
- the OpenAPI artifact, database schema, dependencies, and remote Git state remain unchanged.

## Risks

- The latest registry tag can be newer than production after publishing or older during cache lag.
  Keep the README label scoped to `latest image`; derive the UI label only from active release
  metadata.
- Shields.io or Docker Hub can be unavailable, rate-limited, or change caching behavior. This may
  leave a broken or stale README badge but must never affect application startup or requests.
- Interactive login may block awaiting operator input or fail in a non-interactive environment.
  That is intentional for the manual publish command; fail before the expensive check and document
  that unattended publication is outside scope.
- Moving login later than builds would waste work or risk partial local release state. Tests enforce
  login before full validation, tagging, building, and pushing.
- Defaults could accidentally target production when an operator expected a required-variable
  failure. The agreed values are intentionally convenient; preserve the existing dry-run command,
  print the resolved target before mutations, and document overrides.
- A Compose interpolation used only for selecting the image is not automatically present inside
  the container. Explicit server environment mapping plus validator coverage prevents an
  unversioned production UI.
- Trusting malformed release metadata could display misleading text or prevent safe startup. Apply
  the same stable-version grammar in Django settings and rely on normal template escaping.
- Adding the badge inside the brand link could change its accessible name to include `dev` or a
  version. Render it as a sibling and cover the link name and badge separately.
- The existing production `check --deploy` command will fail after the new required setting unless
  its isolated check environment supplies a valid synthetic value. Update only that check context;
  do not make production fall back to `dev`.

## Deferred work

None. Deployment-history pages, image digests, signed images, registry/deployment drift detection,
automated publication, and a live production status badge are explicit non-goals rather than
unfinished work.

## Completion criteria

- The README contains a linked dynamic `latest image` badge for the highest stable semantic version
  of `gabaconrado/penni-more`, with no claim that it is deployed.
- `publish VERSION` performs exact interactive `podman login docker.io` after local guards and
  before full check/tag/build/push; failure stops safely; no credentials enter code or tests; all
  prior publication guarantees remain passing.
- `deploy VERSION [--dry-run]` uses `penni` and `/home/penni/penni-more` by default, accepts safe
  non-empty environment overrides, retains validation, prints the resolved target, and preserves
  dry-run and deployment behavior.
- Local/test pages show `dev`; production accepts only stable image metadata and shows the exact
  `vMAJOR.MINOR.PATCH` active image version on both login and authenticated pages.
- Production Compose explicitly supplies the active release image version to Django, and repository
  validation fails if that mapping disappears or changes.
- The UI badge is visible, accessible, responsive, server-rendered, and introduces no JavaScript,
  external request, dependency, OpenAPI change, or database migration.
- Focused and full checks pass with observed results; backend and Web reviewers and the architect
  report no unresolved blocking findings; the deployment agent creates justified local commits;
  and `docs/reports/2026-09-16-release-version-visibility.md` records the cycle and omitted live
  operations. No remote Git write, real registry login/publish, or production deployment occurs.
