#!/usr/bin/env bash
set -euo pipefail
release_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
readonly release_dir
action="${1:-up}"
[[ "${action}" == up || "${action}" == down ]] || { printf 'Expected up or down.\n' >&2; exit 2; }
set -a
# shellcheck disable=SC1091
source "${release_dir}/shared/.env"
# shellcheck disable=SC1091
source "${release_dir}/release.env"
set +a
compose=(podman compose -p penni-more -f "${release_dir}/deploy/compose.yaml" \
  -f "${release_dir}/deploy/compose.production.yaml")
if [[ "${action}" == up ]]; then
  "${compose[@]}" up -d
else
  "${compose[@]}" down
fi
