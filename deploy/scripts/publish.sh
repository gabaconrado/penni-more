#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly script_dir
repository_root="$(cd "${script_dir}/../.." && pwd)"
readonly repository_root
readonly registry="docker.io"
readonly application_repository="${registry}/gabaconrado/penni-more"
readonly nginx_repository="${registry}/gabaconrado/penni-more-nginx"

fail() { printf 'Publication preflight failed: %s\n' "$*" >&2; return 2; }

validate_version() {
  [[ "$1" =~ ^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]] ||
    fail "VERSION must be a stable MAJOR.MINOR.PATCH value"
}

require_tool() {
  command -v "$1" >/dev/null 2>&1 || fail "required tool is unavailable: $1"
}

validate_git_state() {
  [[ -z "$(git -C "${repository_root}" status --porcelain)" ]] || fail "working tree is dirty"
  [[ "$(git -C "${repository_root}" branch --show-current)" == main ]] ||
    fail "publications must originate from main"
}

require_registry_authentication() {
  if ! podman login --get-login "${registry}" >/dev/null 2>&1; then
    fail "Docker Hub authentication is unavailable; run podman login docker.io"
  fi
}

main() {
  [[ "$#" -eq 1 ]] || fail "expected exactly one VERSION argument"
  local version="${1:-}"
  validate_version "${version}"
  local tool
  for tool in git podman uv npm curl shellcheck bats find xargs bash; do
    require_tool "${tool}"
  done
  validate_git_state
  require_registry_authentication

  "${repository_root}/penni-more.sh" check
  validate_git_state

  local tag="v${version}"
  local application_image="${application_repository}:${version}"
  local nginx_image="${nginx_repository}:${version}"
  git -C "${repository_root}" tag --force --annotate "${tag}" --message "Release ${version}" HEAD

  local build=(podman build --platform linux/amd64 --file "${repository_root}/deploy/Containerfile")
  "${build[@]}" --target application --tag "${application_image}" "${repository_root}"
  "${build[@]}" --target nginx --tag "${nginx_image}" "${repository_root}"
  podman push "${application_image}"
  podman push "${nginx_image}"
}

main "$@"
