#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
readonly script_dir
set -a
# shellcheck disable=SC1091
source "${script_dir}/shared/.env"
# shellcheck disable=SC1091
source "${script_dir}/release.env"
set +a
: "${PENNI_MORE_DOMAIN:?PENNI_MORE_DOMAIN is required}"
: "${LETSENCRYPT_EMAIL:?LETSENCRYPT_EMAIL is required}"
compose=(podman compose -p penni-more -f "${script_dir}/deploy/compose.yaml" -f "${script_dir}/deploy/compose.production.yaml")

"${compose[@]}" run -d --service-ports --name penni-more-nginx-bootstrap \
  -v "${script_dir}/deploy/nginx/bootstrap.conf.template:/etc/nginx/default.conf.template:ro" nginx
cleanup() { podman rm -f penni-more-nginx-bootstrap >/dev/null 2>&1 || true; }
trap cleanup EXIT
"${compose[@]}" --profile operations run --rm certbot certonly --webroot -w /var/www/certbot \
  --non-interactive --agree-tos --email "${LETSENCRYPT_EMAIL}" -d "${PENNI_MORE_DOMAIN}"
"${compose[@]}" --profile operations run --rm --entrypoint sh certbot -c \
  'chgrp -R 101 /etc/letsencrypt/archive && find /etc/letsencrypt/archive -type d -exec chmod 0750 {} + && find /etc/letsencrypt/archive -type f -exec chmod 0640 {} +'
cleanup
trap - EXIT
"${compose[@]}" up -d nginx
