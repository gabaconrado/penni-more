#!/usr/bin/env bash
set -euo pipefail

remote_dir="${1:?remote directory required}"
release_id="${2:?release id required}"
[[ "${remote_dir}" =~ ^/[A-Za-z0-9._/-]+$ && "${remote_dir}" != / && "${remote_dir}" != *..* ]] || {
  printf 'Unsafe remote directory.\n' >&2
  exit 2
}
[[ "${release_id}" =~ ^[A-Za-z0-9._-]+$ ]] || { printf 'Unsafe release identifier.\n' >&2; exit 2; }

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly script_dir
worker="${script_dir}/remote-release-worker.sh"
lock_file="${remote_dir}/deployment.lock"
readonly worker lock_file
readonly lock_conflict_status=73

command -v flock >/dev/null 2>&1 || {
  printf 'Required host tool is unavailable: flock\n' >&2
  exit 2
}
[[ -x "${worker}" ]] || {
  printf 'Deployment worker is unavailable or not executable: %s\n' "${worker}" >&2
  exit 2
}

if flock --exclusive --nonblock --close --conflict-exit-code "${lock_conflict_status}" \
  "${lock_file}" "${worker}" "${remote_dir}" "${release_id}"; then
  exit 0
else
  status=$?
fi

if [[ "${status}" -eq "${lock_conflict_status}" ]]; then
  printf 'Another deployment is already running.\n' >&2
  exit 3
fi
exit "${status}"
