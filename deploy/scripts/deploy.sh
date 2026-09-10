#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly script_dir
repository_root="$(cd "${script_dir}/../.." && pwd)"
readonly repository_root

fail() { printf 'Deployment preflight failed: %s\n' "$*" >&2; return 2; }

validate_version() {
  [[ "$1" =~ ^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]] ||
    fail "VERSION must be a stable MAJOR.MINOR.PATCH value"
}

require_tool() {
  command -v "$1" >/dev/null 2>&1 || fail "required tool is unavailable: $1"
}

validate_remote_dir() {
  [[ "${DEPLOY_REMOTE_DIR}" =~ ^/[A-Za-z0-9._/-]+$ && "${DEPLOY_REMOTE_DIR}" != "/" && "${DEPLOY_REMOTE_DIR}" != *".."* ]] ||
    fail "DEPLOY_REMOTE_DIR must be a safe absolute path"
}

main() {
  [[ "$#" -ge 1 ]] || fail "expected VERSION and optional --dry-run"
  local version="$1"
  shift
  validate_version "${version}"
  local dry_run=false
  while (($#)); do
    case "$1" in
      --dry-run) dry_run=true ;;
      *) fail "unknown argument: $1"; return ;;
    esac
    shift
  done
  require_tool git; require_tool ssh; require_tool rsync
  : "${DEPLOY_SSH_TARGET:?DEPLOY_SSH_TARGET is required}"
  : "${DEPLOY_REMOTE_DIR:?DEPLOY_REMOTE_DIR is required}"
  [[ "${DEPLOY_SSH_TARGET}" =~ ^[A-Za-z0-9_.@:-]+$ ]] || fail "DEPLOY_SSH_TARGET contains unsafe characters"
  validate_remote_dir
  [[ -z "$(git -C "${repository_root}" status --porcelain)" ]] || fail "working tree is dirty"
  local branch commit short_commit release_id
  branch="$(git -C "${repository_root}" branch --show-current)"
  [[ "${branch}" == main ]] || fail "deployments must originate from main"
  commit="$(git -C "${repository_root}" rev-parse HEAD)"
  local tag="v${version}"
  [[ "$(git -C "${repository_root}" cat-file -t "refs/tags/${tag}" 2>/dev/null || true)" == tag ]] ||
    fail "local tag ${tag} must exist and be annotated"
  [[ "$(git -C "${repository_root}" rev-parse "${tag}^{commit}" 2>/dev/null || true)" == "${commit}" ]] ||
    fail "local tag ${tag} must reference HEAD"
  short_commit="$(git -C "${repository_root}" rev-parse --short=12 HEAD)"
  release_id="$(date -u +%Y%m%dT%H%M%SZ)-${short_commit}"
  printf 'Release: %s\nImage version: %s\nCommit: %s\nBranch: %s\nTarget: %s:%s\n' \
    "${release_id}" "${version}" "${commit}" "${branch}" "${DEPLOY_SSH_TARGET}" "${DEPLOY_REMOTE_DIR}"
  ssh "${DEPLOY_SSH_TARGET}" bash -s -- "${DEPLOY_REMOTE_DIR}" \
    <"${repository_root}/deploy/scripts/preflight.sh"
  if [[ "${dry_run}" == true ]]; then
    printf '%s\n' 'Dry run complete; no files copied and no remote state changed.'
    return 0
  fi
  # shellcheck disable=SC2029
  ssh "${DEPLOY_SSH_TARGET}" \
    "mkdir -p '${DEPLOY_REMOTE_DIR}/releases/${release_id}/deploy'"
  rsync -a --delete "${repository_root}/deploy/" \
    "${DEPLOY_SSH_TARGET}:${DEPLOY_REMOTE_DIR}/releases/${release_id}/deploy/"
  # shellcheck disable=SC2029
  printf 'PENNI_MORE_RELEASE_ID=%s\nPENNI_MORE_IMAGE_VERSION=%s\nPENNI_MORE_GIT_COMMIT=%s\nPENNI_MORE_GIT_BRANCH=%s\n' \
    "${release_id}" "${version}" "${commit}" "${branch}" |
    ssh "${DEPLOY_SSH_TARGET}" \
      "umask 077; cat > '${DEPLOY_REMOTE_DIR}/releases/${release_id}/release.env'; chmod 0600 '${DEPLOY_REMOTE_DIR}/releases/${release_id}/release.env'"
  # shellcheck disable=SC2029
  ssh "${DEPLOY_SSH_TARGET}" \
    "'${DEPLOY_REMOTE_DIR}/releases/${release_id}/deploy/scripts/remote-release.sh' '${DEPLOY_REMOTE_DIR}' '${release_id}'"
}

main "$@"
