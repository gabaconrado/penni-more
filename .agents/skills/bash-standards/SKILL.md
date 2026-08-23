---
name: bash-standards
description: Apply safe, portable Bash and Podman scripting standards to deployment changes.
---

# Bash standards

Apply these standards to shell scripts and shell fragments maintained by the deployment agent.

## Script baseline

- Use Bash explicitly and begin executable scripts with `#!/usr/bin/env bash`.
- Enable `set -euo pipefail` near the beginning of the script.
- Quote expansions and use braces: `"${value}"`.
- Resolve paths relative to the script or repository root, not the caller's current directory.
- Assign a value before marking it `readonly` so command failures are not masked.
- Use lowercase names for local variables and uppercase names only for exported configuration or
  constants.
- Use arrays for argument lists. Do not construct commands with `eval`.

## Functions and errors

- Keep top-level flow short and place distinct operations in named functions.
- Use `local` for function variables and return meaningful nonzero exit codes.
- Send diagnostic messages to standard error.
- Check required tools explicitly. Do not install or download missing tools automatically.
- Use cleanup traps for temporary resources and preserve the original exit status.

## Safety and repeatability

- Make repeated execution safe wherever practical.
- Validate paths and identifiers before destructive or privileged operations.
- Do not use broad globs or unresolved environment variables as destructive targets.
- Wait for PIDs created by the script instead of searching process lists by ambiguous text.
- Never contact an external operational service without explicit user approval.

## Podman

- Prefer rootless Podman-compatible behavior.
- Pin meaningful image versions and avoid hidden dependence on mutable tags.
- Keep persistent state in named, documented volumes.
- Make health checks and startup dependencies explicit.
- Do not remove containers, images, or volumes outside the exact requested scope.

## Verification

- Run `bash -n` and `shellcheck` for changed Bash scripts.
- Exercise safe dry-run or read-only paths when available.
- Report commands that were not run and explain why.
