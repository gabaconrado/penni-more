#!/usr/bin/env bats

setup() {
  repository_root="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
}

@test "unknown top-level command fails" {
  run "${repository_root}/penni-more.sh" unknown
  [ "${status}" -eq 2 ]
  [[ "${output}" == *"Usage:"* ]]
}

@test "unknown check scope fails" {
  run "${repository_root}/penni-more.sh" check unknown
  [ "${status}" -eq 2 ]
  [[ "${output}" == *"Unknown check scope"* ]]
}

@test "publish command routes its version to the publication script" {
  test_root="$(mktemp -d)"
  mkdir -p "${test_root}/deploy/scripts"
  cp "${repository_root}/penni-more.sh" "${test_root}/penni-more.sh"
  cat >"${test_root}/deploy/scripts/publish.sh" <<'SCRIPT'
#!/usr/bin/env bash
printf '%s\n' "$*"
SCRIPT
  chmod +x "${test_root}/deploy/scripts/publish.sh"

  run "${test_root}/penni-more.sh" publish 1.2.3

  [ "${status}" -eq 0 ]
  [ "${output}" = "1.2.3" ]
  rm -rf "${test_root}"
}

@test "local reset requires exact confirmation" {
  run "${repository_root}/penni-more.sh" reset
  [ "${status}" -eq 2 ]
  [[ "${output}" == *"--confirm-local-data-loss"* ]]
}

@test "setup builds ignored web assets after clean dependency installation" {
  test_root="$(mktemp -d)"
  mkdir -p "${test_root}/bin"
  cat >"${test_root}/bin/uv" <<'SCRIPT'
#!/usr/bin/env bash
printf 'uv %s\n' "$*" >>"${CALL_LOG}"
SCRIPT
  cat >"${test_root}/bin/npm" <<'SCRIPT'
#!/usr/bin/env bash
printf 'npm %s\n' "$*" >>"${CALL_LOG}"
SCRIPT
  chmod +x "${test_root}/bin/uv" "${test_root}/bin/npm"
  export CALL_LOG="${test_root}/calls"

  run env PATH="${test_root}/bin:${PATH}" "${repository_root}/penni-more.sh" setup

  [ "${status}" -eq 0 ]
  grep -Fq "npm --prefix ${repository_root}/src/web ci" "${CALL_LOG}"
  grep -Fq "npm --prefix ${repository_root}/src/web run build" "${CALL_LOG}"
  ci_line="$(grep -nF "npm --prefix ${repository_root}/src/web ci" "${CALL_LOG}" | cut -d: -f1)"
  build_line="$(grep -nF "npm --prefix ${repository_root}/src/web run build" "${CALL_LOG}" | cut -d: -f1)"
  [ "${ci_line}" -lt "${build_line}" ]
  rm -rf "${test_root}"
}

@test "local up builds web assets before Compose startup" {
  test_root="$(mktemp -d)"
  mkdir -p "${test_root}/bin"
  cat >"${test_root}/bin/npm" <<'SCRIPT'
#!/usr/bin/env bash
printf 'npm %s\n' "$*" >>"${CALL_LOG}"
SCRIPT
  cat >"${test_root}/bin/podman" <<'SCRIPT'
#!/usr/bin/env bash
printf 'podman %s\n' "$*" >>"${CALL_LOG}"
SCRIPT
  chmod +x "${test_root}/bin/npm" "${test_root}/bin/podman"
  export CALL_LOG="${test_root}/calls"

  run env PATH="${test_root}/bin:${PATH}" "${repository_root}/penni-more.sh" up

  [ "${status}" -eq 0 ]
  [ "$(sed -n '1p' "${CALL_LOG}")" = "npm --prefix ${repository_root}/src/web run build" ]
  grep -Fq 'podman compose ' "${CALL_LOG}"
  rm -rf "${test_root}"
}

@test "integration startup failure preserves status and safely cleans the spawned server" {
  test_root="$(mktemp -d)"
  mkdir -p "${test_root}/bin"
  cat >"${test_root}/bin/npm" <<'SCRIPT'
#!/usr/bin/env bash
exit 0
SCRIPT
  cat >"${test_root}/bin/uv" <<'SCRIPT'
#!/usr/bin/env bash
printf '%s\n' "$$" >"${SERVER_PID_LOG}"
exec /bin/sleep 60
SCRIPT
  cat >"${test_root}/bin/curl" <<'SCRIPT'
#!/usr/bin/env bash
exit 23
SCRIPT
  cat >"${test_root}/bin/sleep" <<'SCRIPT'
#!/usr/bin/env bash
exit 0
SCRIPT
  chmod +x "${test_root}/bin/npm" "${test_root}/bin/uv" "${test_root}/bin/curl" \
    "${test_root}/bin/sleep"
  export SERVER_PID_LOG="${test_root}/server-pid"

  run env PATH="${test_root}/bin:${PATH}" "${repository_root}/penni-more.sh" check integration

  [ "${status}" -eq 23 ]
  [[ "${output}" != *"unbound variable"* ]]
  server_pid="$(<"${SERVER_PID_LOG}")"
  ! kill -0 "${server_pid}" 2>/dev/null
  rm -rf "${test_root}"
}

@test "Compose validation rejects a schema-invalid fixture" {
  run "${repository_root}/src/backend/.venv/bin/python" \
    "${repository_root}/deploy/scripts/validate_compose.py" --schema-only \
    "${repository_root}/deploy/tests/fixtures/compose.invalid.yaml"

  [ "${status}" -ne 0 ]
  [[ "${output}" == *"definitely-not-a-compose-property"* ]]
}
