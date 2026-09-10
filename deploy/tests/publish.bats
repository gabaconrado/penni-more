#!/usr/bin/env bats

setup() {
  source_root="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
  test_root="$(mktemp -d)"
  repository="${test_root}/repository"
  mkdir -p "${repository}/deploy/scripts" "${repository}/deploy" "${test_root}/bin"
  cp "${source_root}/deploy/scripts/publish.sh" "${repository}/deploy/scripts/publish.sh"
  touch "${repository}/deploy/Containerfile"
  cat >"${repository}/penni-more.sh" <<'SCRIPT'
#!/usr/bin/env bash
printf 'check %s\n' "$*" >>"${CALL_LOG}"
if [[ "${VALIDATION_STATUS:-0}" -ne 0 ]]; then
  exit "${VALIDATION_STATUS}"
fi
if [[ "${DIRTY_AFTER_VALIDATION:-false}" == true ]]; then
  printf 'dirty\n' >>"${REPOSITORY}/tracked"
fi
if [[ "${BRANCH_AFTER_VALIDATION:-false}" == true ]]; then
  /usr/bin/git -C "${REPOSITORY}" switch -qc changed-after-validation
fi
SCRIPT
  chmod +x "${repository}/penni-more.sh" "${repository}/deploy/scripts/publish.sh"
  printf 'initial\n' >"${repository}/tracked"
  git -C "${repository}" init -q -b main
  git -C "${repository}" config user.name test
  git -C "${repository}" config user.email test@example.invalid
  git -C "${repository}" add .
  git -C "${repository}" commit -qm initial

  cat >"${test_root}/bin/git" <<'SCRIPT'
#!/usr/bin/env bash
if [[ "$*" == *" tag "* || "${1:-}" == tag ]]; then
  printf 'git %s\n' "$*" >>"${CALL_LOG}"
fi
exec /usr/bin/git "$@"
SCRIPT
  cat >"${test_root}/bin/podman" <<'SCRIPT'
#!/usr/bin/env bash
printf 'podman %s\n' "$*" >>"${CALL_LOG}"
if [[ "$*" == "login --get-login docker.io" ]]; then
  exit "${LOGIN_STATUS:-0}"
fi
if [[ "$*" == *"--target ${FAIL_BUILD_TARGET:-__none__}"* ]]; then
  exit 31
fi
if [[ "$*" == "push ${FAIL_PUSH_IMAGE:-__none__}" ]]; then
  exit 32
fi
SCRIPT
  chmod +x "${test_root}/bin/git" "${test_root}/bin/podman"
  export CALL_LOG="${test_root}/calls"
  export REPOSITORY="${repository}"
  export PATH="${test_root}/bin:${PATH}"
}

teardown() {
  rm -rf "${test_root}"
}

run_publish() {
  run "${repository}/deploy/scripts/publish.sh" "$@"
}

@test "publish accepts only one stable version before any operation" {
  versions=('' v1.2.3 1.2 01.2.3 1.02.3 1.2.03 1.2.3-rc.1 1.2.3+build)
  for version in "${versions[@]}"; do
    run_publish "${version}"
    [ "${status}" -eq 2 ]
  done
  run_publish 1.2.3 extra
  [ "${status}" -eq 2 ]
  [ ! -e "${CALL_LOG}" ]
}

@test "dirty tree and every non-main branch fail before validation" {
  printf 'dirty\n' >>"${repository}/tracked"
  run_publish 1.2.3
  [ "${status}" -eq 2 ]
  [ ! -e "${CALL_LOG}" ]

  /usr/bin/git -C "${repository}" restore tracked
  /usr/bin/git -C "${repository}" switch -qc feature
  run_publish 1.2.3
  [ "${status}" -eq 2 ]
  [ ! -e "${CALL_LOG}" ]
}

@test "missing registry authentication gives login guidance without attempting login" {
  LOGIN_STATUS=1 run_publish 1.2.3

  [ "${status}" -eq 2 ]
  [[ "${output}" == *"podman login docker.io"* ]]
  grep -Fxq 'podman login --get-login docker.io' "${CALL_LOG}"
  ! grep -Eq 'check|git |build|push' "${CALL_LOG}"
}

@test "missing required Podman tool fails before validation" {
  isolated_path="${test_root}/isolated-bin"
  mkdir -p "${isolated_path}"
  ln -s /bin/bash "${isolated_path}/bash"
  ln -s /usr/bin/dirname "${isolated_path}/dirname"
  ln -s "${test_root}/bin/git" "${isolated_path}/git"

  run env PATH="${isolated_path}" CALL_LOG="${CALL_LOG}" \
    "${repository}/deploy/scripts/publish.sh" 1.2.3

  [ "${status}" -eq 2 ]
  [[ "${output}" == *"required tool is unavailable: podman"* ]]
  [ ! -e "${CALL_LOG}" ]
}

@test "validation failure leaves no tag build or push" {
  VALIDATION_STATUS=23 run_publish 1.2.3

  [ "${status}" -eq 23 ]
  grep -Fxq 'check check' "${CALL_LOG}"
  ! grep -Eq '^git |podman build|podman push' "${CALL_LOG}"
  ! /usr/bin/git -C "${repository}" rev-parse -q --verify refs/tags/v1.2.3
}

@test "git state is rechecked after validation" {
  DIRTY_AFTER_VALIDATION=true run_publish 1.2.3
  [ "${status}" -eq 2 ]
  ! grep -Eq '^git |podman build|podman push' "${CALL_LOG}"

  /usr/bin/git -C "${repository}" restore tracked
  : >"${CALL_LOG}"
  BRANCH_AFTER_VALIDATION=true run_publish 1.2.3
  [ "${status}" -eq 2 ]
  ! grep -Eq '^git |podman build|podman push' "${CALL_LOG}"
}

@test "publish force-annotates HEAD then builds both targets before ordered pushes" {
  old_commit="$(/usr/bin/git -C "${repository}" rev-parse HEAD)"
  printf 'second\n' >"${repository}/tracked"
  /usr/bin/git -C "${repository}" add tracked
  /usr/bin/git -C "${repository}" commit -qm second
  /usr/bin/git -C "${repository}" tag -a v1.2.3 -m old "${old_commit}"

  run_publish 1.2.3

  [ "${status}" -eq 0 ]
  [ "$(/usr/bin/git -C "${repository}" cat-file -t refs/tags/v1.2.3)" = tag ]
  [ "$(/usr/bin/git -C "${repository}" rev-parse 'v1.2.3^{commit}')" = \
    "$(/usr/bin/git -C "${repository}" rev-parse HEAD)" ]
  check_line="$(grep -n '^check check$' "${CALL_LOG}" | cut -d: -f1)"
  tag_line="$(grep -n '^git .*tag .*--force.*--annotate v1.2.3' "${CALL_LOG}" | cut -d: -f1)"
  app_build_line="$(grep -n 'podman build .*--platform linux/amd64 .*--target application .*docker.io/gabaconrado/penni-more:1.2.3' "${CALL_LOG}" | cut -d: -f1)"
  nginx_build_line="$(grep -n 'podman build .*--platform linux/amd64 .*--target nginx .*docker.io/gabaconrado/penni-more-nginx:1.2.3' "${CALL_LOG}" | cut -d: -f1)"
  app_push_line="$(grep -n '^podman push docker.io/gabaconrado/penni-more:1.2.3$' "${CALL_LOG}" | cut -d: -f1)"
  nginx_push_line="$(grep -n '^podman push docker.io/gabaconrado/penni-more-nginx:1.2.3$' "${CALL_LOG}" | cut -d: -f1)"
  [ "${check_line}" -lt "${tag_line}" ]
  [ "${tag_line}" -lt "${app_build_line}" ]
  [ "${app_build_line}" -lt "${nginx_build_line}" ]
  [ "${nginx_build_line}" -lt "${app_push_line}" ]
  [ "${app_push_line}" -lt "${nginx_push_line}" ]
  ! grep -Eq '(:latest|git .*push)' "${CALL_LOG}"
}

@test "a failed build or push stops all later forbidden operations" {
  FAIL_BUILD_TARGET=application run_publish 1.2.3
  [ "${status}" -eq 31 ]
  ! grep -Eq -- '--target nginx|podman push' "${CALL_LOG}"

  : >"${CALL_LOG}"
  FAIL_BUILD_TARGET=nginx run_publish 1.2.3
  [ "${status}" -eq 31 ]
  ! grep -q '^podman push' "${CALL_LOG}"

  : >"${CALL_LOG}"
  FAIL_PUSH_IMAGE=docker.io/gabaconrado/penni-more:1.2.3 run_publish 1.2.3
  [ "${status}" -eq 32 ]
  ! grep -q '^podman push docker.io/gabaconrado/penni-more-nginx' "${CALL_LOG}"
}

@test "rerunning a partially published version repeats reconciliation" {
  FAIL_PUSH_IMAGE=docker.io/gabaconrado/penni-more-nginx:1.2.3 run_publish 1.2.3
  [ "${status}" -eq 32 ]
  : >"${CALL_LOG}"

  run_publish 1.2.3

  [ "${status}" -eq 0 ]
  [ "$(grep -c '^podman build' "${CALL_LOG}")" -eq 2 ]
  [ "$(grep -c '^podman push' "${CALL_LOG}")" -eq 2 ]
}
