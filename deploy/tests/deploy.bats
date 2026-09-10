#!/usr/bin/env bats

setup() {
  source_root="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
  test_root="$(mktemp -d)"
  repository="${test_root}/repository"
  mkdir -p "${repository}/deploy/scripts" "${test_root}/bin"
  cp "${source_root}/deploy/scripts/deploy.sh" "${repository}/deploy/scripts/deploy.sh"
  cp "${source_root}/deploy/scripts/preflight.sh" "${repository}/deploy/scripts/preflight.sh"
  git -C "${repository}" init -q -b main
  git -C "${repository}" config user.name test
  git -C "${repository}" config user.email test@example.invalid
  git -C "${repository}" add deploy/scripts/deploy.sh deploy/scripts/preflight.sh
  git -C "${repository}" commit -qm initial
  git -C "${repository}" tag -a v1.2.3 -m 'Release 1.2.3'
  cat >"${test_root}/bin/ssh" <<'SCRIPT'
#!/usr/bin/env bash
printf 'ssh %s\n' "$*" >>"${CALL_LOG}"
if [[ "$*" == *"cat >"* ]]; then
  cat >"${METADATA_LOG}"
fi
exit "${SSH_STATUS:-0}"
SCRIPT
  cat >"${test_root}/bin/rsync" <<'SCRIPT'
#!/usr/bin/env bash
printf 'rsync %s\n' "$*" >>"${CALL_LOG}"
SCRIPT
  chmod +x "${test_root}/bin/ssh" "${test_root}/bin/rsync"
  export CALL_LOG="${test_root}/calls"
  export METADATA_LOG="${test_root}/metadata"
  export DEPLOY_SSH_TARGET="test-host"
  export DEPLOY_REMOTE_DIR="/srv/penni-more"
  export PATH="${test_root}/bin:${PATH}"
}

teardown() {
  rm -rf "${test_root}"
}

@test "missing deployment variables fail before transport" {
  unset DEPLOY_SSH_TARGET
  run "${repository}/deploy/scripts/deploy.sh" 1.2.3 --dry-run
  [ "${status}" -ne 0 ]
  [ ! -e "${CALL_LOG}" ]
}

@test "unsafe remote directory fails before transport" {
  DEPLOY_REMOTE_DIR=/ run "${repository}/deploy/scripts/deploy.sh" 1.2.3 --dry-run
  [ "${status}" -eq 2 ]
  [ ! -e "${CALL_LOG}" ]
}

@test "dirty tree fails before transport" {
  printf 'dirty\n' >>"${repository}/deploy/scripts/deploy.sh"
  run "${repository}/deploy/scripts/deploy.sh" 1.2.3 --dry-run
  [ "${status}" -eq 2 ]
  [ ! -e "${CALL_LOG}" ]
}

@test "wrong branch and the former escape hatch fail" {
  git -C "${repository}" switch -qc emergency
  run "${repository}/deploy/scripts/deploy.sh" 1.2.3 --dry-run
  [ "${status}" -eq 2 ]
  [ ! -e "${CALL_LOG}" ]

  run "${repository}/deploy/scripts/deploy.sh" 1.2.3 --allow-non-primary-branch
  [ "${status}" -eq 2 ]
  [ ! -e "${CALL_LOG}" ]
}

@test "dry run performs read-only preflight without rsync" {
  run "${repository}/deploy/scripts/deploy.sh" 1.2.3 --dry-run
  [ "${status}" -eq 0 ]
  [[ "${output}" == *"Dry run complete"* ]]
  grep -q '^ssh ' "${CALL_LOG}"
  ! grep -q '^rsync ' "${CALL_LOG}"
  ! grep -q 'mkdir\|remote-release\|cat >' "${CALL_LOG}"
}

@test "real deploy records image version and transfers only deployment files" {
  run "${repository}/deploy/scripts/deploy.sh" 1.2.3
  [ "${status}" -eq 0 ]
  grep -Fxq 'PENNI_MORE_IMAGE_VERSION=1.2.3' "${METADATA_LOG}"
  grep -Fxq 'PENNI_MORE_GIT_BRANCH=main' "${METADATA_LOG}"
  grep -Fq 'chmod 0600' "${CALL_LOG}"
  [ "$(grep -c '^rsync ' "${CALL_LOG}")" -eq 1 ]
  grep -Fq "${repository}/deploy/" "${CALL_LOG}"
  ! grep -Eq '/src/(backend|web)' "${CALL_LOG}"
}

@test "deploy accepts only stable versions" {
  for version in '' v1.2.3 1.2 01.2.3 1.02.3 1.2.03 1.2.3-rc.1 1.2.3+build; do
    run "${repository}/deploy/scripts/deploy.sh" "${version}" --dry-run
    [ "${status}" -eq 2 ]
  done
  [ ! -e "${CALL_LOG}" ]
}

@test "deploy requires an annotated tag at HEAD" {
  git -C "${repository}" tag -d v1.2.3 >/dev/null
  run "${repository}/deploy/scripts/deploy.sh" 1.2.3 --dry-run
  [ "${status}" -eq 2 ]
  [[ "${output}" == *"must exist and be annotated"* ]]

  git -C "${repository}" tag v1.2.3
  run "${repository}/deploy/scripts/deploy.sh" 1.2.3 --dry-run
  [ "${status}" -eq 2 ]
  [[ "${output}" == *"must exist and be annotated"* ]]
}

@test "deploy rejects an annotated tag that does not reference HEAD" {
  git -C "${repository}" tag -d v1.2.3 >/dev/null
  old_commit="$(git -C "${repository}" rev-parse HEAD)"
  printf 'next\n' >"${repository}/tracked"
  git -C "${repository}" add tracked
  git -C "${repository}" commit -qm next
  git -C "${repository}" tag -a v1.2.3 -m release "${old_commit}"

  run "${repository}/deploy/scripts/deploy.sh" 1.2.3 --dry-run

  [ "${status}" -eq 2 ]
  [[ "${output}" == *"must reference HEAD"* ]]
  [ ! -e "${CALL_LOG}" ]
}
