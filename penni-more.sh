#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly script_dir
readonly base_compose="${script_dir}/deploy/compose.yaml"
readonly local_compose="${script_dir}/deploy/compose.local.yaml"
readonly compose_project="penni-more-local"
integration_server_pid=""

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

cleanup_integration() {
  local exit_status=$?
  trap - EXIT INT TERM
  if [[ -n "${integration_server_pid}" ]]; then
    kill "${integration_server_pid}" 2>/dev/null || true
    wait "${integration_server_pid}" 2>/dev/null || true
    integration_server_pid=""
  fi
  return "${exit_status}"
}

check_contract() {
  npm --prefix "${script_dir}/src/contract" run lint
}

check_integration() {
  local integration_port="${PENNI_MORE_INTEGRATION_PORT:-8010}"
  local status=0
  build_web_assets
  integration_server_pid=""
  trap cleanup_integration EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  DJANGO_SETTINGS_MODULE=penni_more.settings.local \
    POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-penni_more_local}" \
    uv run --project "${script_dir}/src/backend" python "${script_dir}/src/backend/manage.py" \
      runserver "127.0.0.1:${integration_port}" --noreload &
  integration_server_pid=$!
  for _ in {1..30}; do
    if curl --fail --silent "http://127.0.0.1:${integration_port}/health/live" >/dev/null; then
      break
    fi
    sleep 1
  done
  curl --fail --silent "http://127.0.0.1:${integration_port}/health/live" >/dev/null
  PLAYWRIGHT_BASE_URL="http://127.0.0.1:${integration_port}" \
    npm --prefix "${script_dir}/src/web" run test:browser || status=$?
  cleanup_integration
  return "${status}"
}

run_check() {
  local scope="${1:-all}"
  case "${scope}" in
    all) check_docs; check_backend; test_backend; check_web; check_contract; check_integration ;;
    docs) check_docs ;;
    backend) check_backend; test_backend ;;
    web) check_web ;;
    contract) check_contract ;;
    integration) check_integration ;;
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
    test) test_backend; npm --prefix "${script_dir}/src/web" run test ;;
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
