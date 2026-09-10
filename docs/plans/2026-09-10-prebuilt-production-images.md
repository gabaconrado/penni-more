# Pre-built production images

## Summary

Move production deployment from server-side image builds to two operator-published, immutable
Docker Hub image tags. A local `publish VERSION` command validates the complete repository,
force-creates an annotated local Git tag, builds both `linux/amd64` image targets, and pushes them in
a defined order. A matching `deploy VERSION` command transfers only deployment automation and
activates those public images without building application code on the production host.

The semantic image version and timestamped operational deployment identifier remain separate. Each
release records both values so backup names, retention, locking, recovery, and Git traceability keep
their existing meanings.

## Goals

- Publish the application as `docker.io/gabaconrado/penni-more:VERSION` and the custom Nginx image
  as `docker.io/gabaconrado/penni-more-nginx:VERSION`.
- Accept only stable `MAJOR.MINOR.PATCH` versions for publishing and deployment.
- Require a clean `main` worktree and a successful complete local validation suite before any
  release tag, image build, or image push.
- Force-create an annotated local `vVERSION` Git tag after validation and before image building.
- Build both `linux/amd64` images successfully before pushing the application and then Nginx.
- Deploy a version only when local `HEAD` is the commit referenced by its annotated `vVERSION` tag.
- Pull and use the selected pre-built images on production without transferring application source
  or invoking a production image build.
- Preserve deployment dry runs, locking, pre-migration checks and backups, migration ordering,
  health checks, TLS handling, release retention, recovery, and safe cleanup.
- Keep CI limited to its existing validation and test responsibilities.

## Non-goals

- CI image builds, registry publication, release creation, or Git tagging.
- Git tag pushes or any other Git remote write.
- Docker Hub credential input, storage, login, or logout automation.
- Multi-architecture manifests or any target other than `linux/amd64`.
- `latest`, moving aliases, digest pinning, image signing, attestations, or SBOM publication.
- Prerelease versions, build metadata, or a leading `v` in command arguments or image tags.
- Removing the custom Nginx image or moving its static assets and runtime configuration elsewhere.
- Changing Django, Web GUI, OpenAPI, database, TLS, backup, or production host bootstrap behavior.
- Making publication of the two repositories atomic; Docker Hub does not provide that transaction.

## User-visible behavior

### Publishing

`./penni-more.sh publish 1.2.3` performs this exact release sequence:

1. Reject anything other than one stable `MAJOR.MINOR.PATCH` argument. In particular, reject
   `v1.2.3`, shortened versions, prereleases, build metadata, extra arguments, and options.
2. Require the release tools, a clean worktree, and branch exactly `main`. There is no branch
   escape hatch.
3. Require the operator to already be authenticated through Podman's normal Docker Hub auth store.
   The command accepts no usernames, passwords, or tokens and does not run an interactive login.
4. Run the same complete local validation as `./penni-more.sh check`. A failure stops the command
   before the local tag, builds, or pushes.
5. Recheck the clean `main` state after validation, then force-create annotated tag `v1.2.3` at the
   validated `HEAD`, with a release message. The tag remains local and overwrites an existing local
   tag of the same name.
6. Build the `application` and `nginx` targets from `deploy/Containerfile`, both explicitly for
   `linux/amd64`, with the exact versioned Docker Hub names. Both builds finish before either push.
7. Push `docker.io/gabaconrado/penni-more:1.2.3`, followed by
   `docker.io/gabaconrado/penni-more-nginx:1.2.3`.

The command exits nonzero at the first failure. A failure after tagging leaves the local annotated
tag in place; a failure during the pushes can leave only the application tag published. Rerunning
the same version repeats validation, force-reconciles the local tag, rebuilds both images, and
overwrites/reconciles both registry tags. No `latest` image or remote Git tag is created.

### Deployment

`./penni-more.sh deploy 1.2.3` requires one stable version, a clean worktree, branch exactly `main`,
an annotated local tag named `v1.2.3`, and that tag dereference to equal local `HEAD`. A lightweight
tag, missing tag, mismatched commit, dirty tree, wrong branch, malformed version, or former
`--allow-non-primary-branch` option fails before transport or remote state changes.

`./penni-more.sh deploy 1.2.3 --dry-run` retains the existing read-only remote preflight and performs
no copy or remote mutation. A real deployment creates a separate identifier in the existing
`YYYYMMDDTHHMMSSZ-<short-commit>` form. Its private `release.env` records at least the operational
release ID, image version, commit, and branch. Only deployment files and this metadata are needed on
the server; backend and Web source trees are no longer copied.

The remote worker explicitly pulls the selected application and Nginx tags before the production
Django deployment check or any database/project mutation. It never runs `podman compose build`.
Image-pull or deployment-check failure leaves the running project and database untouched. Normal
activation otherwise preserves the existing shutdown, database health, backup, migration, server
readiness, certificate/Nginx, public-health, retention, and prune order.

Recovery restarts the prior release with the image version recorded in that prior release's own
metadata, not the failed release's version. Existing messaging that migrations and data are not
rolled back remains unchanged.

## Decisions and assumptions

- The version grammar is exactly three dot-separated non-negative decimal integers. Use one shared
  validation policy across publish and deploy; do not accept SemVer prerelease or `+build` syntax.
  Leading-zero handling must be consistent and tested; use the conventional SemVer rule that only
  the single digit `0` may begin a component.
- Git tag names have a `v` prefix, while image tags and command arguments do not.
- Before deployment, verify that `refs/tags/vVERSION` is an annotated tag object and compare
  `vVERSION^{commit}` with `HEAD`; do not compare the tag-object ID with the commit ID.
- Publication authentication is satisfied by Podman's existing auth state for `docker.io`. A clear
  preflight failure should tell the operator to run `podman login docker.io`, without prompting for
  or forwarding credentials.
- `deploy/Containerfile` remains the single multi-stage source for both images. The custom Nginx
  target remains necessary because it contains collected Django/Tailwind static files, Nginx
  configuration, and the rootless entrypoint.
- Local Compose retains its build-based developer flow. Move build declarations into the local
  override if necessary so the merged production model contains no `build` key for application or
  Nginx. Production image selection comes only from the recorded image version.
- Production image references use the fully qualified `docker.io` names. Do not rely on registry
  search aliases or mutable local-only names.
- Public production pulls need no credential handling. The publish command is the only path that
  uses the operator's existing authenticated Docker Hub session.
- A release directory continues to hold operational automation and immutable metadata even though
  it no longer contains application source. Timestamped IDs continue to name backups and release
  directories.
- Compose helpers must select `PENNI_MORE_IMAGE_VERSION` from the metadata belonging to the target
  release on every normal or recovery call. A process-global value from the failed release is not
  sufficient for recovery.
- The existing unqualified `podman system prune --force` occurs only after a healthy deployment and
  does not remove tagged release images. Do not broaden it with `--all` or `--volumes`.
- Docker Hub repositories are public and already exist or will be created by the operator. The
  scripts do not call Docker Hub APIs to create or change repository visibility.

## Scope and ownership

### Deployment agent

The `deployment_agent` exclusively owns all implementation and test changes:

- Update `penni-more.sh` to expose `publish VERSION`, update usage, and route publication through a
  focused deployment script while retaining existing validation behavior.
- Add `deploy/scripts/publish.sh` for version, tool, Git, authentication, validation, annotated-tag,
  two-target build, and ordered-push orchestration. Keep its top-level flow short, commands in
  arrays where appropriate, errors on standard error, and no credential arguments or Git remote
  commands.
- Update `deploy/scripts/deploy.sh` for the required version argument, strict clean-`main` and
  annotated-tag/`HEAD` checks, removal of the branch override, version-aware metadata, and reduced
  transfer set.
- Update `deploy/compose.yaml`, `deploy/compose.local.yaml`, and
  `deploy/compose.production.yaml` as a coordinated set so local development still builds the
  application while the merged production definition contains exact public versioned images and
  no application/Nginx build declarations.
- Update `deploy/scripts/validate_compose.py` to enforce the production image repository and version
  interpolation policy and to reject production `build` keys for the server and Nginx services,
  while retaining the existing network, port, and API-documentation checks.
- Update `deploy/scripts/remote-release-worker.sh` to pull both selected images before the Django
  deployment check, remove server-side builds, and make all Compose invocations—including prior
  release recovery—use the target release's recorded image version.
- Update `deploy/scripts/start-production.sh` only as needed to require and propagate the recorded
  image version during systemd-managed starts and stops.
- Update `deploy/README.md` with the publish/login prerequisites, exact image names, stable-version
  examples, tag behavior, partial-push retry semantics, versioned deploy/dry-run commands, public
  pull model, and the distinction between image version and operational release ID.
- Add `deploy/tests/publish.bats` for the isolated publication workflow. Update
  `deploy/tests/commands.bats`, `deploy/tests/deploy.bats`, and `deploy/tests/remote_release.bats` for
  command routing, deployment guards and metadata, pre-built image activation, and recovery.
- Update existing deployment tests and fixtures rather than adding parallel test harnesses when a
  current helper already expresses the behavior.
- Run final repository validation, stage only feature-owned files, and create the justified local
  implementation commit or commits. Git mutation during tests must occur only inside temporary
  fixture repositories.

If implementation shows that one listed path needs no textual change, record that in the report.
Any additional changed path must be assigned to the deployment agent and justified against this
plan before editing.

### Architect and other scopes

- The architect reviews the deployment diff for this plan's version/tag/image contracts and
  cross-release recovery semantics. The architect writes the final concise report at
  `docs/reports/2026-09-10-prebuilt-production-images.md`; the deployment agent commits it.
- No `backend_coder`, `web_gui_coder`, `contract_coder`, backend reviewer, or Web GUI reviewer
  assignment is required. Application behavior and the OpenAPI contract do not change.
- `.github/workflows/ci.yml` is intentionally unchanged. Review must confirm it still contains only
  validation/test jobs and gains no image build, registry login, publish, or release stage.
- `src/contract/openapi.yaml`, backend code, Web GUI code, dependency manifests, and lockfiles are
  outside scope.

All implementation paths belong to one owner and should be changed sequentially as one deployment
assignment. There is no independent coding scope to parallelize.

## Contract impact

There is no OpenAPI impact. HTTP routes, schemas, authentication, health responses, and server/Web
integration remain unchanged.

The changed operator and deployment interfaces are:

- `./penni-more.sh publish VERSION`, where `VERSION` is stable `MAJOR.MINOR.PATCH`;
- local annotated tag `vVERSION`, force-updated at the validated `HEAD` and never pushed;
- `docker.io/gabaconrado/penni-more:VERSION` for the `application` target;
- `docker.io/gabaconrado/penni-more-nginx:VERSION` for the `nginx` target;
- `./penni-more.sh deploy VERSION [--dry-run]`, with no branch override;
- `PENNI_MORE_IMAGE_VERSION=VERSION` in each release's generated `release.env`, distinct from
  `PENNI_MORE_RELEASE_ID`.

The release metadata file remains operator-generated and mode `0600`. Its image version is a
validated non-secret identifier and must be consumed from the metadata for the specific current or
previous release. No registry credentials enter source, environment examples, release metadata,
logs, SSH arguments, or tests.

## Implementation sequence

1. The deployment agent adds deterministic Bats coverage for the publish command and updates deploy
   fixtures to represent distinct operational IDs and image versions. All Git mutation occurs in
   temporary test repositories, and Podman, SSH, rsync, validation, build, pull, and push boundaries
   are mocked where exercising them would alter external or production state.
2. Implement `deploy/scripts/publish.sh` and top-level routing. Validate arguments and local state
   before work, run the complete check, revalidate the Git state, force-create the annotated local
   tag, build both exact `linux/amd64` targets, then push in the agreed order. Preserve every failure
   status and do not add cleanup that deletes a successfully built or published release artifact.
3. Separate local build configuration from production image selection across the three Compose
   documents. Extend repository Compose validation so the fully merged local configuration still
   has the application build while the fully merged production configuration has exact versioned
   public server/Nginx images and no build definitions.
4. Change `deploy.sh` to consume `VERSION`, remove the emergency branch behavior, verify the
   annotated tag and commit relationship, retain the timestamped release ID, write the image
   version to release metadata, and transfer only `deploy/**`. Keep remote preflight and `--dry-run`
   read-only behavior before any copy or mutation.
5. Change the remote worker to resolve the target release image version, explicitly pull server and
   Nginx before the production Django check, and remove all build commands. Ensure each Compose call
   receives the target release's ID and image version; recovery must resolve both from the previous
   release metadata. Preserve the recovery trap's original-status behavior and every data-safety
   ordering invariant.
6. Update systemd start/stop compatibility and deployment documentation. Remove obsolete source
   transfer/build and branch-override guidance; document tag residue and non-atomic push recovery.
7. Run deployment-focused checks, then give the complete diff to the architect for plan and
   cross-scope review. Return every blocking finding to the deployment agent and repeat until the
   architect reports no blocking findings.
8. The deployment agent runs the full final validation, inspects the diff, creates the local
   implementation commit or commits, and later commits the architect's report if written
   separately. No tag or commit is pushed.

## Review and verification

### Publication tests

`deploy/tests/publish.bats` and top-level command tests must prove with temporary repositories and
mocked command boundaries that:

- missing, extra, `v`-prefixed, shortened, leading-zero, prerelease, and build-metadata versions fail
  before validation, Git mutation, build, or push;
- a dirty worktree and every branch other than exact `main` fail before validation/tag/build/push,
  and no escape-hatch option is accepted;
- missing required tools and missing Podman Docker Hub authentication fail clearly without an
  interactive login or credential handling;
- validation completes before tag creation, and validation failure performs no tag, build, or push;
- local state is rechecked after validation and a newly dirty/wrong-branch state performs no tag,
  build, or push;
- `vVERSION` is force-created as an annotated tag at the validated `HEAD`, including when that local
  tag already exists at another commit, and no Git remote command occurs;
- both builds use `deploy/Containerfile`, the exact `application`/`nginx` targets, exact Docker Hub
  version tags, and explicit `linux/amd64`; neither uses `latest`;
- both builds precede the first push, application precedes Nginx during push, and every failed build
  or push returns nonzero with no later forbidden operation;
- a rerun of the same version repeats the safe reconciliation sequence after partial publication.

### Deployment and recovery tests

Update the existing deployment Bats coverage to prove that:

- deploy applies the same stable-version grammar, requires clean exact `main`, requires an annotated
  `vVERSION`, and rejects a tag whose dereferenced commit differs from `HEAD`;
- dry-run performs remote preflight but no mkdir, rsync, metadata write, remote worker call, pull,
  build, or production mutation;
- real deployment retains the timestamped release ID, records the exact image version and Git
  commit, transfers `deploy/**`, and does not transfer `src/backend` or `src/web`;
- the remote worker pulls both selected image tags before the Django production check and before
  `down`, database startup, backup, or migration, and contains no Compose build operation;
- either image-pull failure and a failed Django deployment check leave the running project and
  database untouched;
- normal deployment retains the existing database, backup, migration, activation, health, TLS,
  retention, and safe-prune order without `--volumes`, `-v`, or `--all`;
- recovery after activation uses the previous release ID and previous release image version,
  restarts database/server/Nginx in the established order, never restores the database, and
  preserves the original failure status;
- first-deployment failure, recovery failure, lock contention, certificate bootstrap/renewal, and
  healthy cleanup retain their existing tested behavior.

Extend `deploy/scripts/validate_compose.py` tests or Bats assertions to observe the merged models:

- local server has a build definition suitable for `./penni-more.sh up`;
- production server and Nginx have the exact public repository plus required version interpolation;
- production server and Nginx have no merged `build` key;
- existing production port and API-documentation restrictions still hold.

### Commands and review gates

During implementation, run and observe at minimum:

```text
bash -n penni-more.sh deploy/scripts/*.sh
shellcheck penni-more.sh deploy/scripts/*.sh
bats deploy/tests/commands.bats deploy/tests/publish.bats deploy/tests/deploy.bats \
  deploy/tests/remote_release.bats
uv run --project src/backend python deploy/scripts/validate_compose.py
.codex/lint.sh
./penni-more.sh check docs
git diff --check
```

After review findings are resolved and before committing, run the complete repository baseline:

```text
./penni-more.sh check
```

Tests must not run the real `publish` flow against Docker Hub, push either image, invoke an
interactive registry login, mutate tags in the working repository, deploy over SSH, contact Let's
Encrypt, or alter production Podman state. Mock external commands and use temporary local Git
repositories. A real authenticated Docker Hub publish is intentionally unverified during
implementation because it requires explicit approval immediately before access; record that
omission in the report rather than weakening or bypassing the boundary.

The architect's review must compare the diff with this plan and confirm:

- no CI publishing/build stage or Git remote write was introduced;
- no backend, Web, or OpenAPI behavior changed;
- release metadata unambiguously separates image version from deployment ID;
- production and recovery select the intended release-specific images without a build fallback;
- publish ordering and deployment safety failures are covered by deterministic tests.

## Risks

- Docker Hub cannot atomically update two repositories. Application push may succeed before Nginx
  fails. Preserve nonzero status and make a same-version rerun rebuild and overwrite both tags.
- The annotated tag is deliberately created before building. Failed builds or pushes therefore
  leave a local tag that does not prove publication succeeded. Documentation must describe this,
  and reruns must force-reconcile the tag instead of treating its existence as success.
- Force-moving a previously used version can change the code associated with a public mutable
  registry tag. This behavior is explicitly requested for operator control; deploy's tag/`HEAD`
  equality prevents a local script/image mismatch but cannot prove remote image contents.
- A malformed or unbound image version could make Compose select an unintended tag. Validate at
  both local command boundaries, require the metadata field, and make Compose interpolation fail
  closed.
- Leaving a base `build` declaration in the merged production Compose model can cause an accidental
  server build when an image is missing. Validate the merged configuration contains no production
  application/Nginx build key and explicitly pull before mutation.
- Pull failure, unavailable public images, registry outage, or architecture mismatch must stop
  before shutdown. Explicit `linux/amd64` builds and pre-mutation pulls limit this failure surface.
- Recovery can silently select the failed version if it inherits process-global image metadata.
  Resolve the prior release's image version from its own `release.env` for every recovery Compose
  call and cover that difference in tests.
- Pruning images too broadly could remove the prior image needed for recovery or later systemd
  startup. Keep the existing post-health prune without `--all` or explicit image removal.
- Removing source transfer changes release contents. Systemd, certificate helpers, manual restore
  instructions, and recovery need deployment files plus release metadata only; tests and review
  must confirm none still depends on transferred source.
- Validation can generate ignored artifacts or, unexpectedly, modify tracked files. Rechecking a
  clean exact-`main` state after the suite prevents tagging a tree other than the one validated.
- Logged commands or metadata could expose registry credentials if authentication is reimplemented.
  Use only Podman's auth store and never accept, print, transfer, or persist credentials.

## Deferred work

None. Image signing, attestations, SBOM publication, immutable digest deployment, and atomic
multi-repository release coordination are explicit non-goals, not unfinished work for this cycle.

## Completion criteria

- `./penni-more.sh publish VERSION` accepts only stable versions; requires clean exact `main` and
  existing Podman Docker Hub authentication; runs the complete check before tagging; force-creates
  annotated local `vVERSION`; builds both exact `linux/amd64` targets before any push; pushes
  application then Nginx; and creates no `latest` or remote Git tag.
- Every validation, build, and push failure exits nonzero at the required boundary, and a
  same-version rerun safely reconciles local and registry tags after partial failure.
- `./penni-more.sh deploy VERSION` requires clean exact `main` and annotated `vVERSION^{commit}` at
  `HEAD`, retains read-only dry-run behavior, and writes separate release ID and image version
  metadata.
- Production receives no backend/Web source, has no application/Nginx build definition, pulls both
  public versioned images before any project/database mutation, and never builds them remotely.
- Normal deployment and prior-release recovery use the image version recorded for their respective
  release while preserving locking, checks, backup, migration, health, TLS, retention, cleanup, and
  original-failure semantics.
- CI remains validation/test-only, OpenAPI/backend/Web behavior remains unchanged, and no
  credentials or Git remote writes are introduced.
- All focused checks and `./penni-more.sh check` pass with observed results; the architect reports
  no blocking findings; the deployment agent creates the justified local commit or commits; and
  `docs/reports/2026-09-10-prebuilt-production-images.md` records the completed cycle and the
  intentionally omitted live publish/deploy checks.
