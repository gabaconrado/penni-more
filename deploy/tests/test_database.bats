#!/usr/bin/env bats

setup() {
  repository_root="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
  fixture_root="$(mktemp -d)"
  fixture_repository="${fixture_root}/repository"
  fixture_bin="${fixture_root}/bin"
  mkdir -p "${fixture_repository}/.codex" "${fixture_repository}/deploy/scripts" \
    "${fixture_repository}/deploy/tests" "${fixture_repository}/src/backend" \
    "${fixture_repository}/src/contract" "${fixture_repository}/src/web" "${fixture_bin}"
  cp "${repository_root}/penni-more.sh" "${fixture_repository}/penni-more.sh"
  chmod +x "${fixture_repository}/penni-more.sh"
  printf '#!/usr/bin/env bash\nexit 0\n' >"${fixture_repository}/.codex/lint.sh"
  chmod +x "${fixture_repository}/.codex/lint.sh"

  call_log="${fixture_root}/calls"
  export CALL_LOG="${call_log}"
  export FAKE_CONTAINER_ID="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  export FAKE_CIDFILE_CONTENT="${FAKE_CONTAINER_ID}"
  export FAKE_RUN_STDOUT=""
  export FAKE_DATABASE_PORT="49153"
  export FAKE_INTEGRATION_PORT="49253"
  export FAKE_FIRST_INTEGRATION_PORT="49253"
  export FAKE_SECOND_INTEGRATION_PORT="49254"
  export FAKE_PODMAN_RUN_STATUS=0
  export FAKE_PODMAN_PORT_STATUS=0
  export FAKE_DATABASE_RUNNING=true
  export FAKE_DATABASE_READY=true
  export FAKE_UV_STATUS=0
  export FAKE_NPM_STATUS=0
  export FAKE_NPM_BROWSER_STATUS=0
  export FAKE_BLOCK_TEST=false
  export FAKE_BLOCK_START=false
  export FAKE_BLOCK_BROWSER=false
  export FAKE_START_MARKER=""
  export FAKE_BROWSER_MARKER=""
  export FAKE_OVERLAP_DIR=""
  export FAKE_SERVER_PID_FILE=""
  export FAKE_FIRST_SERVER_START_FAIL=false
  export FAKE_SERVER_ATTEMPT_FILE=""
  export FAKE_PORT_SELECTION_FILE=""

  make_fake_commands
}

teardown() {
  rm -rf "${fixture_root}"
}

make_fake_commands() {
  cat >"${fixture_bin}/podman" <<'SCRIPT'
#!/usr/bin/env bash
printf 'podman %s\n' "$*" >>"${CALL_LOG}"
case "${1:-}" in
  run)
    cid_file=""
    shift
    while (($# > 0)); do
      if [[ "$1" == --cidfile ]]; then
        cid_file="$2"
        shift 2
        continue
      fi
      shift
    done
    printf 'cidfile=%s\n' "${cid_file}" >>"${CALL_LOG}"
    printf '%s\n' "${FAKE_CIDFILE_CONTENT}" >"${cid_file}"
    if [[ "${FAKE_BLOCK_START}" == true ]]; then
      [[ -z "${FAKE_START_MARKER}" ]] || : >"${FAKE_START_MARKER}"
      /bin/sleep 1
    fi
    if ((FAKE_PODMAN_RUN_STATUS != 0)); then
      exit "${FAKE_PODMAN_RUN_STATUS}"
    fi
    printf '%s' "${FAKE_RUN_STDOUT}"
    ;;
  port)
    if ((FAKE_PODMAN_PORT_STATUS != 0)); then
      exit "${FAKE_PODMAN_PORT_STATUS}"
    fi
    printf '127.0.0.1:%s\n' "${FAKE_DATABASE_PORT}"
    ;;
  exec)
    [[ "${FAKE_DATABASE_READY}" == true ]]
    ;;
  inspect)
    printf '%s\n' "${FAKE_DATABASE_RUNNING}"
    ;;
  logs)
    printf 'bounded fake database log\n'
    ;;
  stop)
    ;;
  *)
    exit 64
    ;;
esac
SCRIPT
  cat >"${fixture_bin}/uv" <<'SCRIPT'
#!/usr/bin/env bash
printf 'uv db=%s user=%s password=%s host=%s port=%s %s\n' \
  "${POSTGRES_DB:-unset}" "${POSTGRES_USER:-unset}" "${POSTGRES_PASSWORD:-unset}" \
  "${POSTGRES_HOST:-unset}" "${POSTGRES_PORT:-unset}" "$*" >>"${CALL_LOG}"
if [[ "$*" == *"import socket"* ]]; then
  if [[ -n "${FAKE_PORT_SELECTION_FILE}" ]]; then
    selection=0
    [[ ! -e "${FAKE_PORT_SELECTION_FILE}" ]] || selection="$(<"${FAKE_PORT_SELECTION_FILE}")"
    printf '%s\n' "$((selection + 1))" >"${FAKE_PORT_SELECTION_FILE}"
    if ((selection == 0)); then
      printf '%s\n' "${FAKE_FIRST_INTEGRATION_PORT}"
    else
      printf '%s\n' "${FAKE_SECOND_INTEGRATION_PORT}"
    fi
  else
    printf '%s\n' "${FAKE_INTEGRATION_PORT}"
  fi
  exit 0
fi
if [[ "$*" == *"manage.py"*"runserver"* ]]; then
  if [[ "${FAKE_FIRST_SERVER_START_FAIL}" == true && \
    ! -e "${FAKE_SERVER_ATTEMPT_FILE}" ]]; then
    claimed_port="${FAKE_FIRST_INTEGRATION_PORT}"
    if ! exec 3<>"/dev/tcp/127.0.0.1/${claimed_port}"; then
      printf 'Expected fixture port %s to be claimed.\n' "${claimed_port}" >&2
      exit 97
    fi
    exec 3>&-
    : >"${FAKE_SERVER_ATTEMPT_FILE}"
    exit 98
  fi
  if [[ -n "${FAKE_SERVER_PID_FILE}" ]]; then
    printf '%s\n' "$$" >"${FAKE_SERVER_PID_FILE}"
  fi
  exec /bin/sleep 300
fi
if [[ "$*" == *"pytest -c"* && "${FAKE_BLOCK_TEST}" == true ]]; then
  /bin/sleep 1
fi
exit "${FAKE_UV_STATUS}"
SCRIPT
  cat >"${fixture_bin}/npm" <<'SCRIPT'
#!/usr/bin/env bash
printf 'npm base_url=%s %s\n' "${PLAYWRIGHT_BASE_URL:-unset}" "$*" >>"${CALL_LOG}"
if [[ "$*" == *"run test:browser"* ]]; then
  if [[ -n "${FAKE_OVERLAP_DIR}" ]]; then
    : >"${FAKE_OVERLAP_DIR}/${FAKE_CONTAINER_ID}"
    overlap_attempt=0
    while [[ "$(find "${FAKE_OVERLAP_DIR}" -type f | wc -l)" -lt 2 ]]; do
      overlap_attempt=$((overlap_attempt + 1))
      if ((overlap_attempt > 500)); then
        printf 'Timed out waiting for overlapping integration fixture.\n' >&2
        exit 70
      fi
      /bin/sleep 0.02
    done
  fi
  if [[ "${FAKE_BLOCK_BROWSER}" == true ]]; then
    [[ -z "${FAKE_BROWSER_MARKER}" ]] || : >"${FAKE_BROWSER_MARKER}"
    /bin/sleep 1
  fi
  exit "${FAKE_NPM_BROWSER_STATUS}"
fi
exit "${FAKE_NPM_STATUS}"
SCRIPT
  cat >"${fixture_bin}/curl" <<'SCRIPT'
#!/usr/bin/env bash
printf 'curl %s\n' "$*" >>"${CALL_LOG}"
exit 0
SCRIPT
  cat >"${fixture_bin}/sleep" <<'SCRIPT'
#!/usr/bin/env bash
exit 0
SCRIPT
  cat >"${fixture_bin}/shellcheck" <<'SCRIPT'
#!/usr/bin/env bash
exit 0
SCRIPT
  cat >"${fixture_bin}/bats" <<'SCRIPT'
#!/usr/bin/env bash
exit 0
SCRIPT
  chmod +x "${fixture_bin}"/*
}

run_fixture() {
  run env \
    PATH="${fixture_bin}:${PATH}" \
    POSTGRES_DB=ambient_database \
    POSTGRES_USER=ambient_user \
    POSTGRES_PASSWORD=ambient_password \
    POSTGRES_HOST=192.0.2.20 \
    POSTGRES_PORT=5432 \
    PENNI_MORE_INTEGRATION_PORT=8010 \
    "${fixture_repository}/penni-more.sh" "$@"
}

assert_one_container_stopped() {
  [ "$(grep -c '^podman run ' "${call_log}")" -eq 1 ]
  [ "$(grep -c "^podman stop ${FAKE_CONTAINER_ID}$" "${call_log}")" -eq 1 ]
}

assert_cid_file_removed() {
  cid_file="$(grep '^cidfile=' "${call_log}" | cut -d= -f2-)"
  [ -n "${cid_file}" ]
  [ ! -e "${cid_file}" ]
  [ ! -d "$(dirname "${cid_file}")" ]
}

@test "test starts an isolated temporary database and overrides ambient connection values" {
  run_fixture test

  [ "${status}" -eq 0 ]
  assert_one_container_stopped
  assert_cid_file_removed
  grep -Fq \
    'podman run --detach --rm --cidfile ' \
    "${call_log}"
  grep -Fq -- \
    '--publish 127.0.0.1::5432/tcp --tmpfs /var/lib/postgresql/data:rw,noexec,nosuid,nodev' \
    "${call_log}"
  grep -Fq 'docker.io/library/postgres:17.6-bookworm' "${call_log}"
  grep -Fq \
    'uv db=penni_more_test_runner user=penni_more_test_runner password=test-runner-only-password host=127.0.0.1 port=49153' \
    "${call_log}"
  ready_line="$(grep -n "podman exec ${FAKE_CONTAINER_ID} pg_isready" "${call_log}" | cut -d: -f1)"
  test_line="$(grep -n 'pytest -c' "${call_log}" | cut -d: -f1)"
  [ "${ready_line}" -lt "${test_line}" ]
  ! grep -Eq 'podman compose|5432:5432|penni-more-database|volume' "${call_log}"
}

@test "non-database check scopes do not start Podman" {
  local scope
  for scope in docs web contract; do
    : >"${call_log}"
    run_fixture check "${scope}"
    [ "${status}" -eq 0 ]
    ! grep -q '^podman ' "${call_log}"
  done
}

@test "backend and integration scopes each provision and remove one database" {
  run_fixture check backend
  [ "${status}" -eq 0 ]
  assert_one_container_stopped

  : >"${call_log}"
  run_fixture check integration
  [ "${status}" -eq 0 ]
  assert_one_container_stopped
  migrate_line="$(grep -n 'manage.py migrate --noinput' "${call_log}" | cut -d: -f1)"
  server_line="$(grep -n 'manage.py runserver' "${call_log}" | cut -d: -f1)"
  [ "${migrate_line}" -lt "${server_line}" ]
  grep -Fq 'manage.py runserver 127.0.0.1:49253 --noreload' "${call_log}"
  grep -Fq 'curl --fail --silent http://127.0.0.1:49253/health/live' "${call_log}"
  grep -Fq 'npm base_url=http://127.0.0.1:49253' "${call_log}"
}

@test "integration retries when the first selected port is lost before bind" {
  claimant_port_file="${fixture_root}/claimed-port"
  /usr/bin/python3 -c \
    'import socket, sys, time
s = socket.socket()
s.bind(("127.0.0.1", 0))
s.listen()
open(sys.argv[1], "w", encoding="ascii").write(str(s.getsockname()[1]))
connection, _ = s.accept()
connection.close()
time.sleep(5)' "${claimant_port_file}" &
  claimant_pid=$!
  while [[ ! -s "${claimant_port_file}" ]]; do
    /bin/sleep 0.01
  done
  export FAKE_FIRST_SERVER_START_FAIL=true
  export FAKE_FIRST_INTEGRATION_PORT="$(<"${claimant_port_file}")"
  export FAKE_SECOND_INTEGRATION_PORT="$((FAKE_FIRST_INTEGRATION_PORT == 65535 ? \
    FAKE_FIRST_INTEGRATION_PORT - 1 : FAKE_FIRST_INTEGRATION_PORT + 1))"
  export FAKE_SERVER_ATTEMPT_FILE="${fixture_root}/server-attempt"
  export FAKE_PORT_SELECTION_FILE="${fixture_root}/port-selection"

  run_fixture check integration
  kill "${claimant_pid}" 2>/dev/null || true
  wait "${claimant_pid}" 2>/dev/null || true

  [ "${status}" -eq 0 ]
  [ "$(grep -c 'manage.py runserver' "${call_log}")" -eq 2 ]
  grep -Fq "manage.py runserver 127.0.0.1:${FAKE_FIRST_INTEGRATION_PORT} --noreload" \
    "${call_log}"
  grep -Fq "manage.py runserver 127.0.0.1:${FAKE_SECOND_INTEGRATION_PORT} --noreload" \
    "${call_log}"
  grep -Fq "npm base_url=http://127.0.0.1:${FAKE_SECOND_INTEGRATION_PORT}" "${call_log}"
  assert_one_container_stopped
}

@test "aggregate check shares one database across backend and integration" {
  run_fixture check all

  [ "${status}" -eq 0 ]
  assert_one_container_stopped
  [ "$(grep -c 'manage.py migrate --noinput' "${call_log}")" -eq 1 ]
  [ "$(grep -c 'pytest -c' "${call_log}")" -eq 1 ]
}

@test "port discovery failure stops only the captured container and preserves status" {
  export FAKE_PODMAN_PORT_STATUS=37

  run_fixture test

  [ "${status}" -eq 37 ]
  assert_one_container_stopped
}

@test "container creation failure recovers and cleans the CID file target" {
  export FAKE_PODMAN_RUN_STATUS=41

  run_fixture test

  [ "${status}" -eq 41 ]
  [[ "${output}" == *"Could not create"* ]]
  grep -Fq "podman stop ${FAKE_CONTAINER_ID}" "${call_log}"
  assert_cid_file_removed
}

@test "malformed run output is ignored in favor of the private CID file" {
  export FAKE_RUN_STDOUT='not-a-container-id'

  run_fixture test

  [ "${status}" -eq 0 ]
  assert_one_container_stopped
}

@test "malformed CID file fails closed without an unsafe stop target" {
  export FAKE_CIDFILE_CONTENT='../../unrelated-container'

  run_fixture test

  [ "${status}" -eq 1 ]
  [[ "${output}" == *"invalid ID"* ]]
  ! grep -q '^podman stop ' "${call_log}"
  assert_cid_file_removed
}

@test "signal during container startup recovers the exact ID from the CID file" {
  export FAKE_BLOCK_START=true
  export FAKE_START_MARKER="${fixture_root}/startup-blocked"

  env PATH="${fixture_bin}:${PATH}" "${fixture_repository}/penni-more.sh" test \
    >"${fixture_root}/startup-output" 2>&1 &
  script_pid=$!
  while [[ ! -e "${FAKE_START_MARKER}" ]]; do
    /bin/sleep 0.01
  done
  kill -TERM "${script_pid}"
  actual_status=0
  wait "${script_pid}" || actual_status=$?

  [ "${actual_status}" -eq 143 ]
  assert_one_container_stopped
  assert_cid_file_removed
}

@test "readiness failure emits bounded logs and stops the captured container" {
  export FAKE_DATABASE_READY=false
  export FAKE_DATABASE_RUNNING=false

  run_fixture test

  [ "${status}" -eq 1 ]
  [[ "${output}" == *"Recent container logs follow"* ]]
  grep -Fq "podman logs --tail 50 ${FAKE_CONTAINER_ID}" "${call_log}"
  assert_one_container_stopped
  ! grep -Eq '^uv |^npm ' "${call_log}"
}

@test "backend test failure is returned after exact database cleanup" {
  export FAKE_UV_STATUS=29

  run_fixture test

  [ "${status}" -eq 29 ]
  assert_one_container_stopped
}

@test "browser test failure cleans the server and database and preserves status" {
  export FAKE_NPM_BROWSER_STATUS=31

  run_fixture check integration

  [ "${status}" -eq 31 ]
  assert_one_container_stopped
}

@test "TERM and INT clean the exact database and use conventional statuses" {
  local signal
  local expected_status
  export FAKE_BLOCK_TEST=true
  for signal in TERM INT; do
    : >"${call_log}"
    if [[ "${signal}" == TERM ]]; then
      expected_status=143
    else
      expected_status=130
    fi
    run timeout --foreground --preserve-status --signal="${signal}" 0.1 \
      env PATH="${fixture_bin}:${PATH}" "${fixture_repository}/penni-more.sh" test
    [ "${status}" -eq "${expected_status}" ]
    assert_one_container_stopped
  done
}

@test "signal during integration kills the exact server PID and test database" {
  export FAKE_BLOCK_BROWSER=true
  export FAKE_SERVER_PID_FILE="${fixture_root}/integration-server-pid"
  export FAKE_BROWSER_MARKER="${fixture_root}/browser-blocked"

  env PATH="${fixture_bin}:${PATH}" "${fixture_repository}/penni-more.sh" check integration \
    >"${fixture_root}/integration-output" 2>&1 &
  script_pid=$!
  while [[ ! -e "${FAKE_BROWSER_MARKER}" ]]; do
    /bin/sleep 0.01
  done
  kill -TERM "${script_pid}"
  actual_status=0
  wait "${script_pid}" || actual_status=$?

  [ "${actual_status}" -eq 143 ]
  assert_one_container_stopped
  server_pid="$(<"${FAKE_SERVER_PID_FILE}")"
  ! kill -0 "${server_pid}" 2>/dev/null
}

@test "invalid dynamic ports fail closed and clean up" {
  export FAKE_DATABASE_PORT=70000

  run_fixture test

  [ "${status}" -eq 1 ]
  [[ "${output}" == *"out-of-range host port"* ]]
  assert_one_container_stopped
}

@test "overlapping integration commands isolate their database, port, and server" {
  local first_log="${fixture_root}/first-calls"
  local second_log="${fixture_root}/second-calls"
  local first_id="1111111111111111111111111111111111111111111111111111111111111111"
  local second_id="2222222222222222222222222222222222222222222222222222222222222222"
  local overlap_dir="${fixture_root}/overlap"
  local first_server_pid_file="${fixture_root}/first-server-pid"
  local second_server_pid_file="${fixture_root}/second-server-pid"
  mkdir "${overlap_dir}"

  env PATH="${fixture_bin}:${PATH}" CALL_LOG="${first_log}" FAKE_CONTAINER_ID="${first_id}" \
    FAKE_CIDFILE_CONTENT="${first_id}" FAKE_RUN_STDOUT='' \
    FAKE_DATABASE_PORT=49161 FAKE_PODMAN_RUN_STATUS=0 FAKE_PODMAN_PORT_STATUS=0 \
    FAKE_DATABASE_RUNNING=true FAKE_DATABASE_READY=true FAKE_UV_STATUS=0 FAKE_NPM_STATUS=0 \
    FAKE_NPM_BROWSER_STATUS=0 FAKE_BLOCK_TEST=false FAKE_BLOCK_START=false \
    FAKE_BLOCK_BROWSER=false FAKE_OVERLAP_DIR="${overlap_dir}" FAKE_INTEGRATION_PORT=49261 \
    FAKE_SERVER_PID_FILE="${first_server_pid_file}" FAKE_FIRST_SERVER_START_FAIL=false \
    FAKE_SERVER_ATTEMPT_FILE='' FAKE_PORT_SELECTION_FILE='' \
    "${fixture_repository}/penni-more.sh" check integration >"${fixture_root}/first-output" 2>&1 &
  first_pid=$!
  env PATH="${fixture_bin}:${PATH}" CALL_LOG="${second_log}" FAKE_CONTAINER_ID="${second_id}" \
    FAKE_CIDFILE_CONTENT="${second_id}" FAKE_RUN_STDOUT='' \
    FAKE_DATABASE_PORT=49162 FAKE_PODMAN_RUN_STATUS=0 FAKE_PODMAN_PORT_STATUS=0 \
    FAKE_DATABASE_RUNNING=true FAKE_DATABASE_READY=true FAKE_UV_STATUS=0 FAKE_NPM_STATUS=0 \
    FAKE_NPM_BROWSER_STATUS=0 FAKE_BLOCK_TEST=false FAKE_BLOCK_START=false \
    FAKE_BLOCK_BROWSER=false FAKE_OVERLAP_DIR="${overlap_dir}" FAKE_INTEGRATION_PORT=49262 \
    FAKE_SERVER_PID_FILE="${second_server_pid_file}" FAKE_FIRST_SERVER_START_FAIL=false \
    FAKE_SERVER_ATTEMPT_FILE='' FAKE_PORT_SELECTION_FILE='' \
    "${fixture_repository}/penni-more.sh" check integration >"${fixture_root}/second-output" 2>&1 &
  second_pid=$!

  wait "${first_pid}"
  wait "${second_pid}"
  grep -Fq 'port=49161' "${first_log}"
  grep -Fq 'manage.py runserver 127.0.0.1:49261 --noreload' "${first_log}"
  grep -Fq 'npm base_url=http://127.0.0.1:49261' "${first_log}"
  grep -Fq "podman stop ${first_id}" "${first_log}"
  ! grep -Fq "${second_id}" "${first_log}"
  grep -Fq 'port=49162' "${second_log}"
  grep -Fq 'manage.py runserver 127.0.0.1:49262 --noreload' "${second_log}"
  grep -Fq 'npm base_url=http://127.0.0.1:49262' "${second_log}"
  grep -Fq "podman stop ${second_id}" "${second_log}"
  ! grep -Fq "${first_id}" "${second_log}"
  ! kill -0 "$(<"${first_server_pid_file}")" 2>/dev/null
  ! kill -0 "$(<"${second_server_pid_file}")" 2>/dev/null
}
