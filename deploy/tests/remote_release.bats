#!/usr/bin/env bats

setup() {
  repository_root="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
  script="${repository_root}/deploy/scripts/remote-release.sh"
}

@test "remote deployment uses a non-waiting advisory lock" {
  grep -Fq 'flock -n 9' "${script}"
}

@test "backup precedes the single explicit migration" {
  backup_line="$(grep -n 'pg_dump' "${script}" | cut -d: -f1)"
  migration_line="$(grep -n 'manage.py migrate' "${script}" | cut -d: -f1)"
  [ "${backup_line}" -lt "${migration_line}" ]
  [ "$(grep -c 'manage.py migrate' "${script}")" -eq 1 ]
}

@test "production deployment check precedes every database mutation" {
  grep -Fq 'run --rm --no-deps server' "${script}"
  deploy_check_line="$(grep -n 'check --deploy --fail-level WARNING' "${script}" | cut -d: -f1)"
  database_start_line="$(grep -n 'up -d database' "${script}" | cut -d: -f1)"
  backup_line="$(grep -n 'pg_dump' "${script}" | cut -d: -f1)"
  migration_line="$(grep -n 'manage.py migrate' "${script}" | cut -d: -f1)"
  [ "${deploy_check_line}" -lt "${database_start_line}" ]
  [ "${deploy_check_line}" -lt "${backup_line}" ]
  [ "${deploy_check_line}" -lt "${migration_line}" ]
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
  ! grep -q 'up -d database\|pg_dump\|manage.py migrate' "${CALL_LOG}"
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
  grep -Fq 'previous code was restored' "${script}"
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
