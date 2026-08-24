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
  run "${repository}/deploy/scripts/deploy.sh" --dry-run
  [ "${status}" -ne 0 ]
  [ ! -e "${CALL_LOG}" ]
}

@test "unsafe remote directory fails before transport" {
  DEPLOY_REMOTE_DIR=/ run "${repository}/deploy/scripts/deploy.sh" --dry-run
  [ "${status}" -eq 2 ]
  [ ! -e "${CALL_LOG}" ]
}

@test "dirty tree fails before transport" {
  printf 'dirty\n' >>"${repository}/deploy/scripts/deploy.sh"
  run "${repository}/deploy/scripts/deploy.sh" --dry-run
  [ "${status}" -eq 2 ]
  [ ! -e "${CALL_LOG}" ]
}

@test "wrong branch requires emergency override" {
  git -C "${repository}" switch -qc emergency
  run "${repository}/deploy/scripts/deploy.sh" --dry-run
  [ "${status}" -eq 2 ]
  [ ! -e "${CALL_LOG}" ]
}

@test "dry run performs read-only preflight without rsync" {
  run "${repository}/deploy/scripts/deploy.sh" --dry-run
  [ "${status}" -eq 0 ]
  [[ "${output}" == *"Dry run complete"* ]]
  grep -q '^ssh ' "${CALL_LOG}"
  ! grep -q '^rsync ' "${CALL_LOG}"
  ! grep -q 'mkdir\|remote-release\|cat >' "${CALL_LOG}"
}

@test "emergency branch override is recorded" {
  git -C "${repository}" switch -qc emergency
  mkdir -p "${repository}/deploy" "${repository}/src/backend" "${repository}/src/web"
  run "${repository}/deploy/scripts/deploy.sh" --allow-non-primary-branch
  [ "${status}" -eq 0 ]
  [[ "${output}" == *"Emergency branch override: enabled"* ]]
  grep -Fxq 'PENNI_MORE_GIT_BRANCH=emergency' "${METADATA_LOG}"
  grep -Fxq 'PENNI_MORE_EMERGENCY_BRANCH_OVERRIDE=true' "${METADATA_LOG}"
}
