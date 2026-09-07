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
compose_files=(-p penni-more -f "${release_dir}/deploy/compose.yaml" -f "${release_dir}/deploy/compose.production.yaml")

set -a
# shellcheck disable=SC1091
source "${shared_dir}/.env"
# shellcheck disable=SC1091
source "${release_dir}/release.env"
set +a
[[ "${PENNI_MORE_ENVIRONMENT:-}" == production ]] || { printf 'Remote environment is not production.\n' >&2; exit 2; }

ln -sfn "${shared_dir}" "${release_dir}/shared"
podman compose "${compose_files[@]}" build server nginx
podman compose "${compose_files[@]}" run --rm --no-deps server \
  python manage.py check --deploy --fail-level WARNING
podman compose "${compose_files[@]}" up -d database

for _ in {1..60}; do
  if podman compose "${compose_files[@]}" exec -T database pg_isready \
    -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" >/dev/null; then break; fi
  sleep 1
done
podman compose "${compose_files[@]}" exec -T database pg_isready \
  -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" >/dev/null

mkdir -p "${shared_dir}/backups"
backup="${shared_dir}/backups/${release_id}.dump"
podman compose "${compose_files[@]}" exec -T database pg_dump \
  -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" --format=custom >"${backup}"
find "${shared_dir}/backups" -type f -name '*.dump' ! -path "${backup}" -delete

podman compose "${compose_files[@]}" run --rm server python manage.py migrate --noinput
previous_target=''
if [[ -L "${remote_dir}/current" ]]; then
  candidate_target="$(readlink -f "${remote_dir}/current" 2>/dev/null || true)"
  if [[ "${candidate_target}" == "${remote_dir}/releases/"* \
    && -d "${candidate_target}" \
    && -f "${candidate_target}/deploy/compose.yaml" \
    && -f "${candidate_target}/deploy/compose.production.yaml" ]]; then
    previous_target="${candidate_target}"
    ln -sfn "${previous_target}" "${remote_dir}/previous"
  fi
fi
ln -sfn "${release_dir}" "${remote_dir}/current"
podman compose "${compose_files[@]}" up -d server

healthy=false
for _ in {1..60}; do
  if podman compose "${compose_files[@]}" exec -T server \
    python -c "import os, urllib.request; request = urllib.request.Request('http://127.0.0.1:8000/health/ready', headers={'Host': os.environ['PENNI_MORE_DOMAIN'], 'X-Forwarded-Proto': 'https'}); urllib.request.urlopen(request, timeout=2)"; then
    healthy=true
    break
  fi
  sleep 1
done
if [[ "${healthy}" == true ]]; then
  if podman compose "${compose_files[@]}" --profile operations run --rm --entrypoint sh certbot \
    -c "test -f '/etc/letsencrypt/live/${PENNI_MORE_DOMAIN}/fullchain.pem'"; then
    podman compose "${compose_files[@]}" up -d nginx
  else
    "${release_dir}/deploy/scripts/bootstrap-certificates.sh"
  fi
  public_healthy=false
  for _ in {1..60}; do
    if [[ "$(curl --fail --silent --show-error "https://${PENNI_MORE_DOMAIN}/health/live" 2>/dev/null || true)" == '{"status": "ok"}' ]]; then
      public_healthy=true
      break
    fi
    sleep 1
  done
  [[ "${public_healthy}" == true ]] || healthy=false
fi
if [[ "${healthy}" != true ]]; then
  if [[ -n "${previous_target}" ]]; then
    ln -sfn "${previous_target}" "${remote_dir}/current"
    previous_id="$(basename "${previous_target}")"
    PENNI_MORE_RELEASE_ID="${previous_id}" podman compose -p penni-more \
      -f "${previous_target}/deploy/compose.yaml" \
      -f "${previous_target}/deploy/compose.production.yaml" up -d server nginx
  fi
  printf 'New release failed readiness; previous code was restored. Database was not restored.\n' >&2
  exit 1
fi

find "${remote_dir}/releases" -mindepth 1 -maxdepth 1 -type d \
  ! -path "$(readlink -f "${remote_dir}/current")" \
  ! -path "$(readlink -f "${remote_dir}/previous" 2>/dev/null || printf '/nonexistent')" -exec rm -rf -- {} +

if ! podman system prune --force; then
  printf 'Warning: Podman cleanup failed after successful deployment.\n' >&2
fi
