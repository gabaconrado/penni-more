#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly script_dir
readonly base_compose="${script_dir}/deploy/compose.yaml"
readonly local_compose="${script_dir}/deploy/compose.local.yaml"
readonly compose_project="penni-more-local"
readonly test_database_image="docker.io/library/postgres:17.6-bookworm"
readonly test_database_name="penni_more_test_runner"
readonly test_database_user="penni_more_test_runner"
readonly test_database_password="test-runner-only-password"
test_database_container_id=""
test_database_cid_file=""
test_database_temp_dir=""
test_database_port=""
integration_server_pid=""
integration_server_port=""
integration_port_lock=""

require_tools() {
  local tool
  for tool in "$@"; do
    if ! command -v "${tool}" >/dev/null 2>&1; then
      printf 'Required host tool is unavailable: %s\n' "${tool}" >&2
      return 2
    fi
  done
}

compose() {
  podman compose -p "${compose_project}" -f "${base_compose}" -f "${local_compose}" "$@"
}

check_docs() {
  "${script_dir}/.codex/lint.sh"
  uv run --project "${script_dir}/src/backend" python "${script_dir}/deploy/scripts/check_markdown_links.py"
  uv run --project "${script_dir}/src/backend" python "${script_dir}/deploy/scripts/validate_compose.py"
  bash -n "${script_dir}/penni-more.sh"
  find "${script_dir}/deploy/scripts" -type f -name '*.sh' -print0 | xargs -0 -r bash -n
  shellcheck "${script_dir}/penni-more.sh"
  find "${script_dir}/deploy/scripts" -type f -name '*.sh' -print0 | xargs -0 -r shellcheck
  bats "${script_dir}/deploy/tests"
}

check_backend() {
  uv run --project "${script_dir}/src/backend" ruff format --check "${script_dir}/src/backend"
  uv run --project "${script_dir}/src/backend" ruff check "${script_dir}/src/backend"
  uv run --project "${script_dir}/src/backend" mypy \
    --config-file "${script_dir}/src/backend/pyproject.toml" "${script_dir}/src/backend"
  POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-penni_more_local}" \
    uv run --project "${script_dir}/src/backend" python "${script_dir}/src/backend/manage.py" check
  POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-penni_more_local}" \
    uv run --project "${script_dir}/src/backend" python "${script_dir}/src/backend/manage.py" \
      makemigrations --check --dry-run
  DJANGO_SETTINGS_MODULE=penni_more.settings.production \
    DJANGO_SECRET_KEY=deployment-check-only-secret-key-000000000000000000000000 \
    PENNI_MORE_DOMAIN=example.invalid POSTGRES_PASSWORD=deployment-check-only \
    uv run --project "${script_dir}/src/backend" python "${script_dir}/src/backend/manage.py" check --deploy
}

test_backend() {
  POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-penni_more_local}" \
    uv run --project "${script_dir}/src/backend" pytest -c "${script_dir}/src/backend/pyproject.toml" \
    --cov --cov-report="xml:${script_dir}/src/backend/coverage.xml" \
    --junitxml="${script_dir}/src/backend/test-results.xml"
}

check_web() {
  npm --prefix "${script_dir}/src/web" run format:check
  npm --prefix "${script_dir}/src/web" run lint
  uv run --project "${script_dir}/src/backend" djlint "${script_dir}/src/web/templates" --check --lint
  npm --prefix "${script_dir}/src/web" run test
  npm --prefix "${script_dir}/src/web" run build
}

build_web_assets() {
  require_tools npm
  npm --prefix "${script_dir}/src/web" run build
}

cleanup_test_resources() {
  local exit_status="${1:-$?}"
  trap - EXIT INT TERM
  if [[ -n "${integration_server_pid}" ]]; then
    kill "${integration_server_pid}" 2>/dev/null || true
    wait "${integration_server_pid}" 2>/dev/null || true
    integration_server_pid=""
    integration_server_port=""
  fi
  if [[ -n "${integration_port_lock}" ]]; then
    rmdir -- "${integration_port_lock}" 2>/dev/null || true
    integration_port_lock=""
  fi
  capture_test_database_container_id || true
  if [[ -n "${test_database_container_id}" ]]; then
    if ! podman stop "${test_database_container_id}" >/dev/null 2>&1; then
      printf 'Warning: failed to stop test database container %s\n' \
        "${test_database_container_id}" >&2
    fi
    test_database_container_id=""
    test_database_port=""
  fi
  if [[ -n "${test_database_cid_file}" ]]; then
    if ! rm -f -- "${test_database_cid_file}"; then
      printf 'Warning: failed to remove test database CID file.\n' >&2
    fi
    test_database_cid_file=""
  fi
  if [[ -n "${test_database_temp_dir}" ]]; then
    rmdir -- "${test_database_temp_dir}" 2>/dev/null || true
    test_database_temp_dir=""
  fi
  return "${exit_status}"
}

exit_after_signal() {
  local exit_status="$1"
  cleanup_test_resources "${exit_status}" || true
  exit "${exit_status}"
}

show_test_database_failure() {
  printf 'Test database failed to become ready. Recent container logs follow.\n' >&2
  podman logs --tail 50 "${test_database_container_id}" >&2 || true
}

capture_test_database_container_id() {
  local captured_id=""
  [[ -z "${test_database_container_id}" && -n "${test_database_cid_file}" && \
    -r "${test_database_cid_file}" ]] || return 0
  captured_id="$(<"${test_database_cid_file}")"
  if [[ "${captured_id}" =~ ^[0-9a-f]{64}$ ]]; then
    test_database_container_id="${captured_id}"
    return 0
  fi
  [[ -z "${captured_id}" ]] || printf 'Test database CID file contained an invalid ID.\n' >&2
  return 1
}

start_test_database() {
  local port_mapping=""
  local status=0
  printf 'Starting isolated PostgreSQL test database.\n' >&2
  test_database_temp_dir="$(mktemp -d "${TMPDIR:-/tmp}/penni-more-test-database.XXXXXX")"
  test_database_cid_file="${test_database_temp_dir}/container.cid"
  podman run --detach --rm --cidfile "${test_database_cid_file}" \
    --publish 127.0.0.1::5432/tcp \
    --tmpfs /var/lib/postgresql/data:rw,noexec,nosuid,nodev \
    --env "POSTGRES_DB=${test_database_name}" \
    --env "POSTGRES_USER=${test_database_user}" \
    --env "POSTGRES_PASSWORD=${test_database_password}" \
    "${test_database_image}" >/dev/null || {
    status=$?
    capture_test_database_container_id || true
    printf 'Could not create the isolated test database container.\n' >&2
    return "${status}"
  }
  if ! capture_test_database_container_id || [[ -z "${test_database_container_id}" ]]; then
    printf 'Test database did not return a valid container ID.\n' >&2
    return 1
  fi

  port_mapping="$(podman port "${test_database_container_id}" 5432/tcp)" || {
    status=$?
    printf 'Could not discover the test database port.\n' >&2
    return "${status}"
  }
  if [[ ! "${port_mapping}" =~ ^127\.0\.0\.1:([0-9]+)$ ]]; then
    printf 'Test database returned an invalid loopback port mapping.\n' >&2
    return 1
  fi
  test_database_port="${BASH_REMATCH[1]}"
  if ((10#${test_database_port} < 1 || 10#${test_database_port} > 65535)); then
    printf 'Test database returned an out-of-range host port.\n' >&2
    return 1
  fi

  local attempt
  local running=""
  for ((attempt = 1; attempt <= 30; attempt++)); do
    if podman exec "${test_database_container_id}" pg_isready \
      -U "${test_database_user}" -d "${test_database_name}" >/dev/null 2>&1; then
      printf 'Isolated PostgreSQL test database is ready on 127.0.0.1:%s.\n' \
        "${test_database_port}" >&2
      return 0
    fi
    if ! running="$(podman inspect --format '{{.State.Running}}' \
      "${test_database_container_id}" 2>/dev/null)" || [[ "${running}" != "true" ]]; then
      show_test_database_failure
      return 1
    fi
    if ((attempt < 30)); then
      sleep 1
    fi
  done
  show_test_database_failure
  return 1
}

with_test_database() {
  require_tools podman
  trap 'cleanup_test_resources "$?"' EXIT
  trap 'exit_after_signal 130' INT
  trap 'exit_after_signal 143' TERM
  start_test_database
  export POSTGRES_DB="${test_database_name}"
  export POSTGRES_USER="${test_database_user}"
  export POSTGRES_PASSWORD="${test_database_password}"
  export POSTGRES_HOST="127.0.0.1"
  export POSTGRES_PORT="${test_database_port}"
  "$@"
  cleanup_test_resources 0
}

check_contract() {
  npm --prefix "${script_dir}/src/contract" run lint
}

find_integration_port() {
  local port=""
  port="$(uv run --project "${script_dir}/src/backend" python -c \
    'import socket; sock = socket.socket(); sock.bind(("127.0.0.1", 0)); print(sock.getsockname()[1]); sock.close()')"
  if [[ ! "${port}" =~ ^[0-9]+$ ]] || ((10#${port} < 1 || 10#${port} > 65535)); then
    printf 'Could not allocate a valid integration server port.\n' >&2
    return 1
  fi
  printf '%s\n' "${port}"
}

integration_server_is_running() {
  local running_pid=""
  kill -0 "${integration_server_pid}" 2>/dev/null || return 1
  while IFS= read -r running_pid; do
    [[ "${running_pid}" == "${integration_server_pid}" ]] && return 0
  done < <(jobs -pr)
  return 1
}

start_integration_server() {
  local attempt
  local integration_port=""
  local probe_status=1
  for ((attempt = 1; attempt <= 5; attempt++)); do
    integration_port="$(find_integration_port)"
    integration_port_lock="${TMPDIR:-/tmp}/penni-more-integration-port-${integration_port}.lock"
    if ! mkdir -- "${integration_port_lock}" 2>/dev/null; then
      integration_port_lock=""
      continue
    fi

    DJANGO_SETTINGS_MODULE=penni_more.settings.local \
      uv run --project "${script_dir}/src/backend" python "${script_dir}/src/backend/manage.py" \
        runserver "127.0.0.1:${integration_port}" --noreload &
    integration_server_pid=$!
    local readiness_attempt
    for ((readiness_attempt = 1; readiness_attempt <= 30; readiness_attempt++)); do
      if ! integration_server_is_running; then
        wait "${integration_server_pid}" 2>/dev/null || true
        integration_server_pid=""
        break
      fi
      if curl --fail --silent "http://127.0.0.1:${integration_port}/health/live" \
        >/dev/null; then
        sleep 0.1
        if integration_server_is_running && \
          curl --fail --silent "http://127.0.0.1:${integration_port}/health/live" \
            >/dev/null; then
          integration_server_port="${integration_port}"
          printf 'Isolated integration server is ready on 127.0.0.1:%s.\n' \
            "${integration_server_port}" >&2
          return 0
        fi
      else
        probe_status=$?
      fi
      sleep 1
    done

    if [[ -n "${integration_server_pid}" ]]; then
      kill "${integration_server_pid}" 2>/dev/null || true
      wait "${integration_server_pid}" 2>/dev/null || true
      integration_server_pid=""
    fi
    rmdir -- "${integration_port_lock}" 2>/dev/null || true
    integration_port_lock=""
    printf 'Integration server did not retain port %s; retrying.\n' \
      "${integration_port}" >&2
  done
  printf 'Could not start an isolated integration server.\n' >&2
  return "${probe_status}"
}

check_integration() {
  local integration_port=""
  local status=0
  build_web_assets
  integration_server_pid=""
  DJANGO_SETTINGS_MODULE=penni_more.settings.local \
    uv run --project "${script_dir}/src/backend" python "${script_dir}/src/backend/manage.py" \
      migrate --noinput
  start_integration_server
  integration_port="${integration_server_port}"
  PLAYWRIGHT_BASE_URL="http://127.0.0.1:${integration_port}" \
    npm --prefix "${script_dir}/src/web" run test:browser || status=$?
  return "${status}"
}

check_all() {
  check_docs
  check_backend
  test_backend
  check_web
  check_contract
  check_integration
}

check_backend_scope() {
  check_backend
  test_backend
}

test_all() {
  test_backend
  npm --prefix "${script_dir}/src/web" run test
}

run_check() {
  local scope="${1:-all}"
  case "${scope}" in
    all) with_test_database check_all ;;
    docs) check_docs ;;
    backend) with_test_database check_backend_scope ;;
    web) check_web ;;
    contract) check_contract ;;
    integration) with_test_database check_integration ;;
    *) printf 'Unknown check scope: %s\n' "${scope}" >&2; return 2 ;;
  esac
}

usage() {
  printf '%s\n' \
    'Usage: ./penni-more.sh {setup|lint|test|check [scope]|up|down|logs|shell|migrate|reset --confirm-local-data-loss|publish VERSION|deploy VERSION [--dry-run]}'
}

main() {
  local command="${1:-}"
  [[ -n "${command}" ]] || { usage >&2; return 2; }
  shift
  case "${command}" in
    setup)
      require_tools uv npm
      uv sync --project "${script_dir}/src/backend" --frozen
      npm --prefix "${script_dir}/src/web" ci
      npm --prefix "${script_dir}/src/contract" ci
      build_web_assets
      ;;
    lint) check_docs; check_backend; check_web; check_contract ;;
    test) with_test_database test_all ;;
    check) run_check "${1:-all}" ;;
    up) require_tools podman; build_web_assets; compose up -d --build --force-recreate ;;
    down) require_tools podman; compose down ;;
    logs) require_tools podman; compose logs "$@" ;;
    shell) require_tools podman; compose exec server /bin/sh ;;
    migrate) require_tools podman; compose exec server python manage.py migrate ;;
    reset)
      local database_volume="${PENNI_MORE_DATABASE_VOLUME:-penni-more-database}"
      [[ "${1:-}" == "--confirm-local-data-loss" ]] || {
        printf 'Refusing reset. Pass --confirm-local-data-loss to remove only the local database volume.\n' >&2
        return 2
      }
      [[ "${database_volume}" =~ ^[A-Za-z0-9_.-]+$ ]] || {
        printf 'Refusing unsafe local database volume name: %s\n' "${database_volume}" >&2
        return 2
      }
      require_tools podman
      compose down
      podman volume rm "${database_volume}"
      ;;
    publish) "${script_dir}/deploy/scripts/publish.sh" "$@" ;;
    deploy) "${script_dir}/deploy/scripts/deploy.sh" "$@" ;;
    *) usage >&2; return 2 ;;
  esac
}

main "$@"
