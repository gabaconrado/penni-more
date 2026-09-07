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
compose=(podman compose -p penni-more -f "${script_dir}/deploy/compose.yaml" -f "${script_dir}/deploy/compose.production.yaml")
"${compose[@]}" --profile operations run --rm certbot renew --webroot -w /var/www/certbot \
  --deploy-hook 'true'
"${compose[@]}" --profile operations run --rm --entrypoint sh certbot -c \
  'chgrp 101 /etc/letsencrypt && chmod 0750 /etc/letsencrypt && chgrp -R 101 /etc/letsencrypt/live /etc/letsencrypt/archive && find /etc/letsencrypt/live /etc/letsencrypt/archive -type d -exec chmod 0750 {} + && find /etc/letsencrypt/archive -type f -exec chmod 0640 {} +'
"${compose[@]}" exec -T nginx nginx -s reload
