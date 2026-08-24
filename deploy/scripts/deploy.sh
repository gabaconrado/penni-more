#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly script_dir
repository_root="$(git -C "${script_dir}" rev-parse --show-toplevel)"
readonly repository_root

fail() { printf 'Deployment preflight failed: %s\n' "$*" >&2; return 2; }

require_tool() {
  command -v "$1" >/dev/null 2>&1 || fail "required tool is unavailable: $1"
}

validate_remote_dir() {
  [[ "${DEPLOY_REMOTE_DIR}" =~ ^/[A-Za-z0-9._/-]+$ && "${DEPLOY_REMOTE_DIR}" != "/" && "${DEPLOY_REMOTE_DIR}" != *".."* ]] ||
    fail "DEPLOY_REMOTE_DIR must be a safe absolute path"
}

main() {
  local dry_run=false
  local allow_other_branch=false
  while (($#)); do
    case "$1" in
      --dry-run) dry_run=true ;;
      --allow-non-primary-branch) allow_other_branch=true ;;
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
  if [[ "${branch}" != "main" && "${allow_other_branch}" != true ]]; then
    fail "deployments must originate from main; use --allow-non-primary-branch for emergencies"
  fi
  commit="$(git -C "${repository_root}" rev-parse HEAD)"
  short_commit="$(git -C "${repository_root}" rev-parse --short=12 HEAD)"
  release_id="$(date -u +%Y%m%dT%H%M%SZ)-${short_commit}"
  printf 'Release: %s\nCommit: %s\nBranch: %s\nTarget: %s:%s\n' \
    "${release_id}" "${commit}" "${branch}" "${DEPLOY_SSH_TARGET}" "${DEPLOY_REMOTE_DIR}"
  if [[ "${allow_other_branch}" == true ]]; then printf 'Emergency branch override: enabled\n'; fi
  ssh "${DEPLOY_SSH_TARGET}" bash -s -- "${DEPLOY_REMOTE_DIR}" \
    <"${repository_root}/deploy/scripts/preflight.sh"
  if [[ "${dry_run}" == true ]]; then
    printf '%s\n' 'Dry run complete; no files copied and no remote state changed.'
    return 0
  fi
  # shellcheck disable=SC2029
  ssh "${DEPLOY_SSH_TARGET}" \
    "mkdir -p '${DEPLOY_REMOTE_DIR}/releases/${release_id}/deploy' '${DEPLOY_REMOTE_DIR}/releases/${release_id}/src/backend' '${DEPLOY_REMOTE_DIR}/releases/${release_id}/src/web'"
  rsync -a --delete "${repository_root}/deploy/" \
    "${DEPLOY_SSH_TARGET}:${DEPLOY_REMOTE_DIR}/releases/${release_id}/deploy/"
  rsync -a --delete --exclude=.venv --exclude=coverage.xml --exclude=test-results.xml \
    "${repository_root}/src/backend/" \
    "${DEPLOY_SSH_TARGET}:${DEPLOY_REMOTE_DIR}/releases/${release_id}/src/backend/"
  rsync -a --delete --exclude=node_modules --exclude=playwright-report --exclude=test-results \
    --exclude=static/css/app.css "${repository_root}/src/web/" \
    "${DEPLOY_SSH_TARGET}:${DEPLOY_REMOTE_DIR}/releases/${release_id}/src/web/"
  # shellcheck disable=SC2029
  printf 'PENNI_MORE_RELEASE_ID=%s\nPENNI_MORE_GIT_COMMIT=%s\nPENNI_MORE_GIT_BRANCH=%s\nPENNI_MORE_EMERGENCY_BRANCH_OVERRIDE=%s\n' \
    "${release_id}" "${commit}" "${branch}" "${allow_other_branch}" |
    ssh "${DEPLOY_SSH_TARGET}" "umask 077; cat > '${DEPLOY_REMOTE_DIR}/releases/${release_id}/release.env'"
  # shellcheck disable=SC2029
  ssh "${DEPLOY_SSH_TARGET}" \
    "'${DEPLOY_REMOTE_DIR}/releases/${release_id}/deploy/scripts/remote-release.sh' '${DEPLOY_REMOTE_DIR}' '${release_id}'"
}

main "$@"
