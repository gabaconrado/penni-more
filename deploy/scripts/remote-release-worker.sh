#!/usr/bin/env bash
set -euo pipefail

remote_dir="${1:?remote directory required}"
release_id="${2:?release id required}"
[[ "${remote_dir}" =~ ^/[A-Za-z0-9._/-]+$ && "${remote_dir}" != / && "${remote_dir}" != *..* ]] || {
  printf 'Unsafe remote directory.\n' >&2
  exit 2
}
[[ "${release_id}" =~ ^[A-Za-z0-9._-]+$ ]] || { printf 'Unsafe release identifier.\n' >&2; exit 2; }
release_dir="${remote_dir}/releases/${release_id}"
shared_dir="${remote_dir}/shared"
previous_target=''
recovery_armed=false

release_image_version() {
  local target="${1:?release directory required}"
  local target_id="${2:?release id required}"
  local metadata_id=''
  local image_version=''
  local image_version_present=false
  local key value
  [[ -f "${target}/release.env" ]] || {
    printf 'Release metadata is unavailable: %s\n' "${target}/release.env" >&2
    return 2
  }
  while IFS='=' read -r key value; do
    case "${key}" in
      PENNI_MORE_RELEASE_ID) metadata_id="${value}" ;;
      PENNI_MORE_IMAGE_VERSION)
        image_version="${value}"
        image_version_present=true
        ;;
    esac
  done <"${target}/release.env"
  [[ "${metadata_id}" == "${target_id}" ]] || {
    printf 'Release metadata does not match release %s.\n' "${target_id}" >&2
    return 2
  }
  if [[ "${image_version_present}" == true ]]; then
    [[ "${image_version}" =~ ^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]] || {
      printf 'Release %s has an invalid image version.\n' "${target_id}" >&2
      return 2
    }
  fi
  printf '%s\n' "${image_version}"
}

compose_release() {
  local target="${1:?release directory required}"
  local target_id="${2:?release id required}"
  local image_version
  shift 2
  image_version="$(release_image_version "${target}" "${target_id}")" || return $?
  if [[ -n "${image_version}" ]]; then
    PENNI_MORE_RELEASE_ID="${target_id}" PENNI_MORE_IMAGE_VERSION="${image_version}" \
      PENNI_MORE_ENV_FILE="${shared_dir}/.env" \
      podman compose -p penni-more \
      -f "${target}/deploy/compose.yaml" \
      -f "${target}/deploy/compose.production.yaml" "$@"
  else
    # Pre-versioned releases select their local images by release ID. Prevent the failed release's
    # exported version from affecting legacy Compose interpolation during the first upgrade.
    (
      unset PENNI_MORE_IMAGE_VERSION
      PENNI_MORE_RELEASE_ID="${target_id}" PENNI_MORE_ENV_FILE="${shared_dir}/.env" \
        podman compose -p penni-more \
        -f "${target}/deploy/compose.yaml" \
        -f "${target}/deploy/compose.production.yaml" "$@"
    )
  fi
}

wait_for_database() {
  local target="${1:?release directory required}"
  local target_id="${2:?release id required}"
  for _ in {1..60}; do
    if compose_release "${target}" "${target_id}" exec -T database pg_isready \
      -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" >/dev/null; then
      return 0
    fi
    sleep 1
  done
  return 1
}

wait_for_server() {
  local target="${1:?release directory required}"
  local target_id="${2:?release id required}"
  for _ in {1..60}; do
    if compose_release "${target}" "${target_id}" exec -T server \
      python -c "import os, urllib.request; request = urllib.request.Request('http://127.0.0.1:8000/health/ready', headers={'Host': os.environ['PENNI_MORE_DOMAIN'], 'X-Forwarded-Proto': 'https'}); urllib.request.urlopen(request, timeout=2)"; then
      return 0
    fi
    sleep 1
  done
  return 1
}

capture_previous_target() {
  local candidate_target=''
  if [[ -L "${remote_dir}/current" ]]; then
    candidate_target="$(readlink -f "${remote_dir}/current" 2>/dev/null || true)"
  fi
  if [[ "${candidate_target}" == "${remote_dir}/releases/"* \
    && -d "${candidate_target}" \
    && -f "${candidate_target}/deploy/compose.yaml" \
    && -f "${candidate_target}/deploy/compose.production.yaml" ]]; then
    previous_target="${candidate_target}"
  fi
}

current_points_to_failed_release() {
  local current_target=''
  [[ -L "${remote_dir}/current" ]] || return 1
  current_target="$(readlink -f "${remote_dir}/current" 2>/dev/null || true)"
  [[ "${current_target}" == "${release_dir}" ]]
}

recover_previous_release() {
  local original_status=$?
  local recovery_failed=false
  local previous_id=''
  if [[ "${recovery_armed}" != true ]]; then
    trap - EXIT
    exit "${original_status}"
  fi
  recovery_armed=false
  trap - EXIT
  set +e

  printf 'Deployment failed with status %s; attempting recovery.\n' "${original_status}" >&2
  if ! compose_release "${release_dir}" "${release_id}" down; then
    recovery_failed=true
  fi
  if [[ -n "${previous_target}" ]]; then
    previous_id="$(basename "${previous_target}")"
    if ! ln -sfn "${previous_target}" "${remote_dir}/current" \
      || ! compose_release "${previous_target}" "${previous_id}" up -d database \
      || ! wait_for_database "${previous_target}" "${previous_id}" \
      || ! compose_release "${previous_target}" "${previous_id}" up -d server \
      || ! wait_for_server "${previous_target}" "${previous_id}" \
      || ! compose_release "${previous_target}" "${previous_id}" --profile operations run \
        --rm --entrypoint sh certbot \
        -c "test -f '/etc/letsencrypt/live/${PENNI_MORE_DOMAIN}/fullchain.pem'" \
      || ! compose_release "${previous_target}" "${previous_id}" up -d nginx; then
      recovery_failed=true
    fi
  else
    if current_points_to_failed_release && ! rm -- "${remote_dir}/current"; then
      recovery_failed=true
    fi
    printf 'No previous release code is available to restart.\n' >&2
  fi

  printf 'Database migrations and data were not rolled back.\n' >&2
  if [[ "${recovery_failed}" == true ]]; then
    printf 'Previous-release recovery could not be verified.\n' >&2
  elif [[ -n "${previous_target}" ]]; then
    printf 'Previous release code was restarted.\n' >&2
  fi
  exit "${original_status}"
}

certificate_exists() {
  compose_release "${release_dir}" "${release_id}" --profile operations run --rm \
    --entrypoint sh certbot \
    -c "test -f '/etc/letsencrypt/live/${PENNI_MORE_DOMAIN}/fullchain.pem'"
}

wait_for_public_health() {
  for _ in {1..60}; do
    if [[ "$(curl --fail --silent --show-error "https://${PENNI_MORE_DOMAIN}/health/live" 2>/dev/null || true)" == '{"status": "ok"}' ]]; then
      return 0
    fi
    sleep 1
  done
  return 1
}

set -a
# shellcheck disable=SC1091
source "${shared_dir}/.env"
# shellcheck disable=SC1091
source "${release_dir}/release.env"
set +a
[[ "${PENNI_MORE_ENVIRONMENT:-}" == production ]] || { printf 'Remote environment is not production.\n' >&2; exit 2; }
[[ "${PENNI_MORE_RELEASE_ID:-}" == "${release_id}" ]] || {
  printf 'Release metadata does not match release %s.\n' "${release_id}" >&2
  exit 2
}
[[ "${PENNI_MORE_IMAGE_VERSION:-}" =~ ^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]] || {
  printf 'Release %s has an invalid image version.\n' "${release_id}" >&2
  exit 2
}

capture_previous_target
compose_release "${release_dir}" "${release_id}" pull server
compose_release "${release_dir}" "${release_id}" pull nginx
compose_release "${release_dir}" "${release_id}" run --rm --no-deps server \
  python manage.py check --deploy --fail-level WARNING
ln -sfn "${shared_dir}" "${release_dir}/shared"

recovery_armed=true
trap recover_previous_release EXIT
compose_release "${release_dir}" "${release_id}" down
compose_release "${release_dir}" "${release_id}" up -d database
wait_for_database "${release_dir}" "${release_id}"

mkdir -p "${shared_dir}/backups"
backup="${shared_dir}/backups/${release_id}.dump"
compose_release "${release_dir}" "${release_id}" exec -T database pg_dump \
  -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" --format=custom >"${backup}"
find "${shared_dir}/backups" -type f -name '*.dump' ! -path "${backup}" -delete
compose_release "${release_dir}" "${release_id}" run --rm server python manage.py migrate --noinput

if [[ -n "${previous_target}" ]]; then
  ln -sfn "${previous_target}" "${remote_dir}/previous"
fi
ln -sfn "${release_dir}" "${remote_dir}/current"
compose_release "${release_dir}" "${release_id}" up -d server
wait_for_server "${release_dir}" "${release_id}"
if certificate_exists; then
  compose_release "${release_dir}" "${release_id}" up -d nginx
else
  "${release_dir}/deploy/scripts/bootstrap-certificates.sh"
fi
wait_for_public_health

recovery_armed=false
trap - EXIT
find "${remote_dir}/releases" -mindepth 1 -maxdepth 1 -type d \
  ! -path "$(readlink -f "${remote_dir}/current")" \
  ! -path "$(readlink -f "${remote_dir}/previous" 2>/dev/null || printf '/nonexistent')" -exec rm -rf -- {} +

if ! podman system prune --force; then
  printf 'Warning: Podman cleanup failed after successful deployment.\n' >&2
fi
