#!/usr/bin/env bats

setup() {
  repository_root="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
  supervisor="${repository_root}/deploy/scripts/remote-release.sh"
  worker="${repository_root}/deploy/scripts/remote-release-worker.sh"
  script="${worker}"
}

teardown() {
  if [[ -n "${supervisor_pid:-}" ]]; then
    if [[ -n "${lock_release:-}" ]]; then
      touch "${lock_release}"
      for _ in {1..100}; do
        if ! kill -0 "${supervisor_pid}" 2>/dev/null; then
          break
        fi
        /bin/sleep 0.01
      done
    fi
    kill "${supervisor_pid}" 2>/dev/null || true
    wait "${supervisor_pid}" 2>/dev/null || true
  fi
  if [[ -n "${helper_pid:-}" ]]; then
    kill "${helper_pid}" 2>/dev/null || true
    for _ in {1..100}; do
      if ! kill -0 "${helper_pid}" 2>/dev/null; then
        break
      fi
      /bin/sleep 0.01
    done
  fi
  if [[ -n "${fixture_root:-}" ]]; then
    rm -rf "${fixture_root}"
  fi
}

create_lock_fixture() {
  fixture_root="$(mktemp -d)"
  fixture_remote="${fixture_root}/remote"
  fixture_scripts="${fixture_root}/deploy/scripts"
  mkdir -p "${fixture_remote}" "${fixture_scripts}"
  cp "${supervisor}" "${fixture_scripts}/remote-release.sh"
  chmod +x "${fixture_scripts}/remote-release.sh"
}

create_remote_fixture() {
  fixture_root="$(mktemp -d)"
  fixture_remote="${fixture_root}/remote"
  fixture_calls="${fixture_root}/calls"
  mkdir -p \
    "${fixture_remote}/shared" \
    "${fixture_remote}/releases/release-1/deploy" \
    "${fixture_root}/bin"
  touch \
    "${fixture_remote}/releases/release-1/deploy/compose.yaml" \
    "${fixture_remote}/releases/release-1/deploy/compose.production.yaml"
  cat >"${fixture_remote}/shared/.env" <<'ENV'
PENNI_MORE_ENVIRONMENT=production
PENNI_MORE_DOMAIN=money.example.test
POSTGRES_USER=penni_more
POSTGRES_DB=penni_more
ENV
  cat >"${fixture_remote}/releases/release-1/release.env" <<'ENV'
PENNI_MORE_RELEASE_ID=release-1
ENV
  cat >"${fixture_root}/bin/podman" <<'SCRIPT'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"${CALL_LOG}"
for argument in "$@"; do
  if [[ "${argument}" == --volumes || "${argument}" == -v ]]; then
    : >"${FORBIDDEN_VOLUME_LOG}"
    exit 90
  fi
done
if [[ -n "${RECONCILIATION_STATE:-}" && "$*" == *" down" ]]; then
  rm -f "${RECONCILIATION_STATE}"
fi
if [[ -n "${RECONCILIATION_STATE:-}" \
  && -e "${RECONCILIATION_STATE}" \
  && "$*" == *"up -d database"* ]]; then
  exit 88
fi
if [[ "${FAIL_NEW_DATABASE:-false}" == true \
  && "$*" == *"/releases/release-1/"* \
  && "$*" == *"up -d database"* ]]; then
  exit 41
fi
if [[ "${FAIL_READY:-false}" == true \
  && "$*" == *"/releases/release-1/"* \
  && "$*" == *"/health/ready"* ]]; then
  exit 1
fi
if [[ "${FAIL_RECOVERY:-false}" == true \
  && "$*" == *"/releases/release-0/"* \
  && "$*" == *"up -d server"* ]]; then
  exit 42
fi
if [[ "${FAIL_PRUNE:-false}" == true && "$*" == "system prune --force" ]]; then
  exit 1
fi
SCRIPT
  cat >"${fixture_root}/bin/curl" <<'SCRIPT'
#!/usr/bin/env bash
printf 'curl %s\n' "$*" >>"${CALL_LOG}"
if [[ "${PUBLIC_HEALTHY:-false}" == true ]]; then
  printf '{"status": "ok"}'
else
  exit 1
fi
SCRIPT
  cat >"${fixture_root}/bin/sleep" <<'SCRIPT'
#!/usr/bin/env bash
exit 0
SCRIPT
  cat >"${fixture_root}/bin/find" <<'SCRIPT'
#!/usr/bin/env bash
printf 'find %s\n' "$*" >>"${CALL_LOG}"
exec /usr/bin/find "$@"
SCRIPT
  cat >"${fixture_root}/bin/ln" <<'SCRIPT'
#!/usr/bin/env bash
printf 'ln %s\n' "$*" >>"${CALL_LOG}"
exec /bin/ln "$@"
SCRIPT
  chmod +x \
    "${fixture_root}/bin/podman" \
    "${fixture_root}/bin/curl" \
    "${fixture_root}/bin/sleep" \
    "${fixture_root}/bin/find" \
    "${fixture_root}/bin/ln"
}

run_remote_fixture() {
  run env \
    PATH="${fixture_root}/bin:${PATH}" \
    CALL_LOG="${fixture_calls}" \
    FAIL_READY="${FAIL_READY:-false}" \
    FAIL_NEW_DATABASE="${FAIL_NEW_DATABASE:-false}" \
    FAIL_RECOVERY="${FAIL_RECOVERY:-false}" \
    FAIL_PRUNE="${FAIL_PRUNE:-false}" \
    PUBLIC_HEALTHY="${PUBLIC_HEALTHY:-false}" \
    RECONCILIATION_STATE="${RECONCILIATION_STATE:-}" \
    FORBIDDEN_VOLUME_LOG="${fixture_root}/forbidden-volume-option" \
    "${script}" "${fixture_remote}" release-1
}

add_previous_release() {
  mkdir -p "${fixture_remote}/releases/release-0/deploy"
  touch \
    "${fixture_remote}/releases/release-0/deploy/compose.yaml" \
    "${fixture_remote}/releases/release-0/deploy/compose.production.yaml"
  ln -s "${fixture_remote}/releases/release-0" "${fixture_remote}/current"
}

create_certificate_fixture() {
  fixture_root="$(mktemp -d)"
  fixture_calls="${fixture_root}/calls"
  mkdir -p \
    "${fixture_root}/deploy/scripts" \
    "${fixture_root}/deploy/nginx" \
    "${fixture_root}/shared" \
    "${fixture_root}/bin"
  cp \
    "${repository_root}/deploy/scripts/bootstrap-certificates.sh" \
    "${repository_root}/deploy/scripts/renew-certificates.sh" \
    "${fixture_root}/deploy/scripts/"
  cat >"${fixture_root}/shared/.env" <<'ENV'
PENNI_MORE_DOMAIN=money.example.test
LETSENCRYPT_EMAIL=operator@example.test
ENV
  cat >"${fixture_root}/release.env" <<'ENV'
PENNI_MORE_RELEASE_ID=release-1
ENV
  cat >"${fixture_root}/bin/podman" <<'SCRIPT'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"${CALL_LOG}"
SCRIPT
  chmod +x "${fixture_root}/bin/podman"
}

@test "remote deployment supervises the worker with a closed non-waiting lock" {
  grep -Fq 'flock --exclusive --nonblock --close' "${supervisor}"
  ! grep -Fq 'deployment.lock' "${worker}"
}

@test "active supervised deployment excludes a concurrent deployment" {
  create_lock_fixture
  lock_started="${fixture_root}/lock-started"
  lock_release="${fixture_root}/lock-release"
  cat >"${fixture_scripts}/remote-release-worker.sh" <<'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail
touch "${LOCK_STARTED}"
while [[ ! -e "${LOCK_RELEASE}" ]]; do
  /bin/sleep 0.01
done
SCRIPT
  chmod +x "${fixture_scripts}/remote-release-worker.sh"

  env LOCK_STARTED="${lock_started}" LOCK_RELEASE="${lock_release}" \
    "${fixture_scripts}/remote-release.sh" "${fixture_remote}" release-1 \
    >"${fixture_root}/first-output" 2>&1 &
  supervisor_pid=$!
  for _ in {1..100}; do
    [[ -e "${lock_started}" ]] && break
    /bin/sleep 0.01
  done
  [ -e "${lock_started}" ]

  run "${fixture_scripts}/remote-release.sh" "${fixture_remote}" release-2

  [ "${status}" -eq 3 ]
  [[ "${output}" == *"Another deployment is already running."* ]]
  touch "${lock_release}"
  wait "${supervisor_pid}"
  supervisor_pid=''
}

@test "surviving worker helper does not retain the deployment lock" {
  create_lock_fixture
  helper_pid_file="${fixture_root}/helper-pid"
  cat >"${fixture_scripts}/remote-release-worker.sh" <<'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail
(
  trap 'exit 0' TERM
  while :; do
    /bin/sleep 1
  done
) </dev/null >/dev/null 2>&1 &
printf '%s\n' "$!" >"${HELPER_PID_FILE}"
SCRIPT
  chmod +x "${fixture_scripts}/remote-release-worker.sh"

  run env HELPER_PID_FILE="${helper_pid_file}" \
    "${fixture_scripts}/remote-release.sh" "${fixture_remote}" release-1

  [ "${status}" -eq 0 ]
  for _ in {1..100}; do
    [[ -s "${helper_pid_file}" ]] && break
    /bin/sleep 0.01
  done
  [ -s "${helper_pid_file}" ]
  helper_pid="$(cat "${helper_pid_file}")"
  kill -0 "${helper_pid}"

  run flock --exclusive --nonblock "${fixture_remote}/deployment.lock" true

  [ "${status}" -eq 0 ]
  kill "${helper_pid}"
  for _ in {1..100}; do
    if ! kill -0 "${helper_pid}" 2>/dev/null; then
      break
    fi
    /bin/sleep 0.01
  done
  ! kill -0 "${helper_pid}" 2>/dev/null
  helper_pid=''
}

@test "supervisor propagates a non-contention worker failure" {
  create_lock_fixture
  cat >"${fixture_scripts}/remote-release-worker.sh" <<'SCRIPT'
#!/usr/bin/env bash
exit 42
SCRIPT
  chmod +x "${fixture_scripts}/remote-release-worker.sh"

  run "${fixture_scripts}/remote-release.sh" "${fixture_remote}" release-1

  [ "${status}" -eq 42 ]
  [[ "${output}" != *"Another deployment is already running."* ]]
}

@test "backup precedes the single explicit migration" {
  backup_line="$(grep -n 'pg_dump' "${script}" | cut -d: -f1)"
  migration_line="$(grep -n 'manage.py migrate' "${script}" | cut -d: -f1)"
  [ "${backup_line}" -lt "${migration_line}" ]
  [ "$(grep -c 'manage.py migrate' "${script}")" -eq 1 ]
}

@test "production deployment check precedes every database mutation" {
  create_remote_fixture
  PUBLIC_HEALTHY=true

  run_remote_fixture

  [ "${status}" -eq 0 ]
  deploy_check_line="$(grep -n 'check --deploy --fail-level WARNING' "${fixture_calls}" | cut -d: -f1)"
  down_line="$(grep -n ' down$' "${fixture_calls}" | head -n 1 | cut -d: -f1)"
  database_start_line="$(grep -n 'up -d database$' "${fixture_calls}" | head -n 1 | cut -d: -f1)"
  backup_line="$(grep -n 'pg_dump' "${fixture_calls}" | cut -d: -f1)"
  migration_line="$(grep -n 'manage.py migrate' "${fixture_calls}" | cut -d: -f1)"
  [ "${deploy_check_line}" -lt "${down_line}" ]
  [ "${down_line}" -lt "${database_start_line}" ]
  [ "${database_start_line}" -lt "${backup_line}" ]
  [ "${backup_line}" -lt "${migration_line}" ]
}

@test "full-project down reconciles dependent containers without removing volumes" {
  create_remote_fixture
  RECONCILIATION_STATE="${fixture_root}/dependent-containers"
  : >"${RECONCILIATION_STATE}"

  run env \
    PATH="${fixture_root}/bin:${PATH}" \
    CALL_LOG="${fixture_calls}" \
    RECONCILIATION_STATE="${RECONCILIATION_STATE}" \
    FORBIDDEN_VOLUME_LOG="${fixture_root}/forbidden-volume-option" \
    podman compose -p penni-more up -d database

  [ "${status}" -eq 88 ]
  PUBLIC_HEALTHY=true
  run_remote_fixture
  [ "${status}" -eq 0 ]
  [ ! -e "${RECONCILIATION_STATE}" ]
  [ ! -e "${fixture_root}/forbidden-volume-option" ]
  [ "$(grep -c ' down$' "${fixture_calls}")" -eq 1 ]
  ! grep -Eq ' down .+|volume rm' "${fixture_calls}"
}

@test "normal activation follows the required database server and ingress order" {
  create_remote_fixture
  PUBLIC_HEALTHY=true

  run_remote_fixture

  [ "${status}" -eq 0 ]
  down_line="$(grep -n ' down$' "${fixture_calls}" | cut -d: -f1)"
  database_line="$(grep -n 'up -d database$' "${fixture_calls}" | head -n 1 | cut -d: -f1)"
  database_health_line="$(grep -n 'pg_isready' "${fixture_calls}" | head -n 1 | cut -d: -f1)"
  backup_line="$(grep -n 'pg_dump' "${fixture_calls}" | cut -d: -f1)"
  migration_line="$(grep -n 'manage.py migrate' "${fixture_calls}" | cut -d: -f1)"
  activation_line="$(grep -nF "ln -sfn ${fixture_remote}/releases/release-1 ${fixture_remote}/current" "${fixture_calls}" | cut -d: -f1)"
  server_line="$(grep -n 'up -d server$' "${fixture_calls}" | head -n 1 | cut -d: -f1)"
  server_health_line="$(grep -n '/health/ready' "${fixture_calls}" | head -n 1 | cut -d: -f1)"
  nginx_line="$(grep -n 'up -d nginx$' "${fixture_calls}" | head -n 1 | cut -d: -f1)"
  public_health_line="$(grep -n '^curl .*health/live$' "${fixture_calls}" | cut -d: -f1)"
  [ "${down_line}" -lt "${database_line}" ]
  [ "${database_line}" -lt "${database_health_line}" ]
  [ "${database_health_line}" -lt "${backup_line}" ]
  [ "${backup_line}" -lt "${migration_line}" ]
  [ "${migration_line}" -lt "${activation_line}" ]
  [ "${activation_line}" -lt "${server_line}" ]
  [ "${server_line}" -lt "${server_health_line}" ]
  [ "${server_health_line}" -lt "${nginx_line}" ]
  [ "${nginx_line}" -lt "${public_health_line}" ]
  [ "$(grep -c 'manage.py migrate' "${fixture_calls}")" -eq 1 ]
}

@test "post-shutdown database failure restarts prior code and preserves original status" {
  create_remote_fixture
  add_previous_release
  FAIL_NEW_DATABASE=true

  run_remote_fixture

  [ "${status}" -eq 41 ]
  prior_prefix="-f ${fixture_remote}/releases/release-0/deploy/compose.yaml -f ${fixture_remote}/releases/release-0/deploy/compose.production.yaml"
  database_line="$(grep -nF -- "${prior_prefix} up -d database" "${fixture_calls}" | cut -d: -f1)"
  server_line="$(grep -nF -- "${prior_prefix} up -d server" "${fixture_calls}" | cut -d: -f1)"
  nginx_line="$(grep -nF -- "${prior_prefix} up -d nginx" "${fixture_calls}" | cut -d: -f1)"
  [ "${database_line}" -lt "${server_line}" ]
  [ "${server_line}" -lt "${nginx_line}" ]
  ! grep -q 'manage.py migrate' "${fixture_calls}"
  [[ "${output}" == *"Database migrations and data were not rolled back."* ]]
}

@test "recovery failure preserves original status and reports both limitations" {
  create_remote_fixture
  add_previous_release
  FAIL_NEW_DATABASE=true
  FAIL_RECOVERY=true

  run_remote_fixture

  [ "${status}" -eq 41 ]
  [[ "${output}" == *"Database migrations and data were not rolled back."* ]]
  [[ "${output}" == *"Previous-release recovery could not be verified."* ]]
  [ "$(grep -c ' down$' "${fixture_calls}")" -eq 2 ]
  ! grep -Eq ' down .+|volume rm|pg_restore|restore-backup' "${fixture_calls}"
  [ ! -e "${fixture_root}/forbidden-volume-option" ]
}

@test "failed production deployment check prevents database startup and mutation" {
  test_root="$(mktemp -d)"
  remote="${test_root}/remote"
  mkdir -p "${remote}/shared" "${remote}/releases/release-1" "${test_root}/bin"
  cat >"${remote}/shared/.env" <<'ENV'
PENNI_MORE_ENVIRONMENT=production
PENNI_MORE_DOMAIN=money.example.test
POSTGRES_USER=penni_more
POSTGRES_DB=penni_more
ENV
  cat >"${remote}/releases/release-1/release.env" <<'ENV'
PENNI_MORE_RELEASE_ID=release-1
ENV
  cat >"${test_root}/bin/podman" <<'SCRIPT'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"${CALL_LOG}"
[[ "$*" != *"check --deploy --fail-level WARNING"* ]]
SCRIPT
  chmod +x "${test_root}/bin/podman"
  export CALL_LOG="${test_root}/calls"

  run env PATH="${test_root}/bin:${PATH}" "${script}" "${remote}" release-1

  [ "${status}" -ne 0 ]
  grep -q 'check --deploy --fail-level WARNING' "${CALL_LOG}"
  ! grep -q ' down$\|up -d database\|pg_dump\|manage.py migrate' "${CALL_LOG}"
  rm -rf "${test_root}"
}

@test "production probes send the configured host and trusted HTTPS proxy header" {
  grep -Fq "os.environ['PENNI_MORE_DOMAIN']" "${script}"
  grep -Fq "'X-Forwarded-Proto': 'https'" "${script}"
  grep -Fq "os.environ['PENNI_MORE_DOMAIN']" "${repository_root}/deploy/compose.yaml"
  grep -Fq "'X-Forwarded-Proto': 'https'" "${repository_root}/deploy/compose.yaml"
}

@test "probe headers pass production host and HTTPS enforcement" {
  run env PYTHONPATH="${repository_root}/src/backend" \
    DJANGO_SETTINGS_MODULE=penni_more.settings.production \
    DJANGO_SECRET_KEY=probe-test-only-secret-key-000000000000000000000000 \
    POSTGRES_PASSWORD=probe-test-only PENNI_MORE_DOMAIN=money.example.test \
    "${repository_root}/src/backend/.venv/bin/python" - <<'PYTHON'
import django
from django.test import Client

django.setup()
client = Client()
assert client.get(
    "/health/live",
    headers={"host": "money.example.test", "x-forwarded-proto": "https"},
).status_code == 200
assert client.get(
    "/health/live",
    headers={"host": "money.example.test"},
).status_code == 301
assert client.get(
    "/health/live",
    headers={"host": "wrong.example.test", "x-forwarded-proto": "https"},
).status_code == 400
PYTHON

  [ "${status}" -eq 0 ]
}

@test "backup failure prevents migration" {
  test_root="$(mktemp -d)"
  remote="${test_root}/remote"
  mkdir -p "${remote}/shared/backups" "${remote}/releases/release-1" "${test_root}/bin"
  cat >"${remote}/shared/.env" <<'ENV'
PENNI_MORE_ENVIRONMENT=production
POSTGRES_USER=penni_more
POSTGRES_DB=penni_more
ENV
  cat >"${remote}/releases/release-1/release.env" <<'ENV'
PENNI_MORE_RELEASE_ID=release-1
ENV
  cat >"${test_root}/bin/podman" <<'SCRIPT'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"${CALL_LOG}"
[[ "$*" != *"pg_dump"* ]]
SCRIPT
  chmod +x "${test_root}/bin/podman"
  export CALL_LOG="${test_root}/calls"
  run env PATH="${test_root}/bin:${PATH}" "${script}" "${remote}" release-1
  [ "${status}" -ne 0 ]
  grep -q 'pg_dump' "${CALL_LOG}"
  ! grep -q 'manage.py migrate' "${CALL_LOG}"
  rm -rf "${test_root}"
}

@test "health rollback never restores the database" {
  grep -Fq 'Database migrations and data were not rolled back.' "${script}"
  ! grep -Eq 'pg_restore|restore-backup' "${script}"
}

@test "retention preserves current and previous releases" {
  grep -Fq 'readlink -f "${remote_dir}/current"' "${script}"
  grep -Fq 'readlink -f "${remote_dir}/previous"' "${script}"
  grep -Fq '! -path "${backup}" -delete' "${script}"
}

@test "certificate reload follows successful renewal" {
  renewal="${repository_root}/deploy/scripts/renew-certificates.sh"
  renew_line="$(grep -n 'certbot renew' "${renewal}" | cut -d: -f1)"
  reload_line="$(grep -n 'nginx -s reload' "${renewal}" | cut -d: -f1)"
  [ "${renew_line}" -lt "${reload_line}" ]
}

@test "certificate bootstrap normalizes every path before starting nginx" {
  create_certificate_fixture

  run env PATH="${fixture_root}/bin:${PATH}" CALL_LOG="${fixture_calls}" \
    "${fixture_root}/deploy/scripts/bootstrap-certificates.sh"

  [ "${status}" -eq 0 ]
  grep -Fq 'chgrp 101 /etc/letsencrypt && chmod 0750 /etc/letsencrypt' "${fixture_calls}"
  grep -Fq 'chgrp -R 101 /etc/letsencrypt/live /etc/letsencrypt/archive' "${fixture_calls}"
  grep -Fq 'find /etc/letsencrypt/live /etc/letsencrypt/archive -type d -exec chmod 0750 {} +' "${fixture_calls}"
  grep -Fq 'find /etc/letsencrypt/archive -type f -exec chmod 0640 {} +' "${fixture_calls}"
  permission_line="$(grep -n 'chgrp 101 /etc/letsencrypt' "${fixture_calls}" | cut -d: -f1)"
  nginx_line="$(grep -n 'up -d nginx' "${fixture_calls}" | cut -d: -f1)"
  [ "${permission_line}" -lt "${nginx_line}" ]
}

@test "certificate renewal normalizes every path before reloading nginx" {
  create_certificate_fixture

  run env PATH="${fixture_root}/bin:${PATH}" CALL_LOG="${fixture_calls}" \
    "${fixture_root}/deploy/scripts/renew-certificates.sh"

  [ "${status}" -eq 0 ]
  grep -Fq 'chgrp 101 /etc/letsencrypt && chmod 0750 /etc/letsencrypt' "${fixture_calls}"
  grep -Fq 'chgrp -R 101 /etc/letsencrypt/live /etc/letsencrypt/archive' "${fixture_calls}"
  grep -Fq 'find /etc/letsencrypt/live /etc/letsencrypt/archive -type d -exec chmod 0750 {} +' "${fixture_calls}"
  grep -Fq 'find /etc/letsencrypt/archive -type f -exec chmod 0640 {} +' "${fixture_calls}"
  permission_line="$(grep -n 'chgrp 101 /etc/letsencrypt' "${fixture_calls}" | cut -d: -f1)"
  reload_line="$(grep -n 'exec -T nginx nginx -s reload' "${fixture_calls}" | cut -d: -f1)"
  [ "${permission_line}" -lt "${reload_line}" ]
}

@test "failed first deployment does not create or invoke an invalid rollback target" {
  create_remote_fixture
  FAIL_READY=true

  run_remote_fixture

  [ "${status}" -ne 0 ]
  [ ! -e "${fixture_remote}/previous" ]
  [ ! -L "${fixture_remote}/previous" ]
  [ ! -e "${fixture_remote}/current" ]
  [ ! -L "${fixture_remote}/current" ]
  ! grep -Fq "${fixture_remote}/current/deploy/compose.yaml" "${fixture_calls}"
  [[ "${output}" == *"No previous release code is available to restart."* ]]
}

@test "failed deployment restores a valid prior release" {
  create_remote_fixture
  mkdir -p "${fixture_remote}/releases/release-0/deploy"
  touch \
    "${fixture_remote}/releases/release-0/deploy/compose.yaml" \
    "${fixture_remote}/releases/release-0/deploy/compose.production.yaml"
  ln -s "${fixture_remote}/releases/release-0" "${fixture_remote}/current"
  FAIL_READY=true

  run_remote_fixture

  [ "${status}" -ne 0 ]
  [ "$(readlink -f "${fixture_remote}/previous")" = "${fixture_remote}/releases/release-0" ]
  [ "$(readlink -f "${fixture_remote}/current")" = "${fixture_remote}/releases/release-0" ]
  prior_prefix="-f ${fixture_remote}/releases/release-0/deploy/compose.yaml -f ${fixture_remote}/releases/release-0/deploy/compose.production.yaml"
  database_line="$(grep -nF -- "${prior_prefix} up -d database" "${fixture_calls}" | cut -d: -f1)"
  server_line="$(grep -nF -- "${prior_prefix} up -d server" "${fixture_calls}" | cut -d: -f1)"
  nginx_line="$(grep -nF -- "${prior_prefix} up -d nginx" "${fixture_calls}" | cut -d: -f1)"
  [ "${database_line}" -lt "${server_line}" ]
  [ "${server_line}" -lt "${nginx_line}" ]
  [ "$(grep -c 'manage.py migrate' "${fixture_calls}")" -eq 1 ]
  ! grep -Eq 'pg_restore|restore-backup' "${fixture_calls}"
}

@test "healthy deployment prunes safely after public health and retention" {
  create_remote_fixture
  PUBLIC_HEALTHY=true

  run_remote_fixture

  [ "${status}" -eq 0 ]
  [ "$(grep -Fxc 'system prune --force' "${fixture_calls}")" -eq 1 ]
  ! grep -Eq 'system prune .*--all|system prune .*--volumes' "${fixture_calls}"
  health_line="$(grep -n '^curl .*health/live$' "${fixture_calls}" | cut -d: -f1)"
  retention_line="$(grep -n "^find ${fixture_remote}/releases " "${fixture_calls}" | cut -d: -f1)"
  prune_line="$(grep -n '^system prune --force$' "${fixture_calls}" | cut -d: -f1)"
  [ "${health_line}" -lt "${retention_line}" ]
  [ "${retention_line}" -lt "${prune_line}" ]
}

@test "prune failure warns without failing a healthy deployment" {
  create_remote_fixture
  PUBLIC_HEALTHY=true
  FAIL_PRUNE=true

  run_remote_fixture

  [ "${status}" -eq 0 ]
  [[ "${output}" == *"Warning: Podman cleanup failed after successful deployment."* ]]
  [ "$(grep -Fxc 'system prune --force' "${fixture_calls}")" -eq 1 ]
}
