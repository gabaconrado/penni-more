# Penni More agent instructions

## Project

Penni More is a personal-use money manager. The intended implementation is a Rust server that
renders HTML styled with Tailwind CSS, with minimal vanilla JavaScript and no JavaScript framework.
OpenAPI is the shared contract between the server and Web GUI. Podman owns runtime packaging.

## Instruction and skill loading

- Follow this file before performing project work.
- Load every repository skill named by the active agent or workflow before acting.
- Repository skills live in `.agents/skills`; custom agents live in `.codex/agents`.

## Hard boundaries

- Never run Git operations that mutate a remote: no push, force-push, remote tag creation, remote
  branch deletion, or equivalent API operation. Remote reads are allowed.
- Only `deployment_agent` may stage files, create commits, amend commits, rebase, switch branches,
  or otherwise mutate local Git state. Every other agent is limited to read-only Git inspection.
- Never access an authenticated or operational external service, including cloud providers and
  live APIs, without explicit approval immediately before access. Public documentation and
  read-only Git remote access are allowed.
- Never download, install, or execute a missing tool automatically. Report the missing capability
  and stop.
- On any tool or permission failure, stop and report the exact failure. Do not use another command,
  path, tool, or service to work around it.
- Preserve unrelated user changes. Never perform destructive cleanup without explicit approval.

## Ownership

- `backend_coder` owns Rust server implementation under `src/backend`.
- `backend_reviewer` reviews backend changes and never edits them.
- `web_gui_coder` owns Web GUI implementation under `src/web`.
- `web_gui_reviewer` reviews Web GUI changes and never edits them.
- `contract_coder` owns OpenAPI artifacts under `src/contract`.
- `architect` interviews the user, writes plans under `docs/plans`, resolves cross-scope design,
  and reviews contract changes.
- `deployment_agent` owns `deploy`, shell automation, repository Git mutations, final validation,
  and local commits.

Ownership is exclusive for implementation. An agent may read other scopes to understand contracts
and integration points but must not edit them. Cross-scope changes are split among the owning
agents.

## Feature workflow

Use the `feature-development` skill for every requested feature.

1. Use `grill-me` to interview the user one question at a time until material ambiguity is gone.
2. Dispatch `architect` to write the agreed implementation plan before source changes begin.
3. Dispatch the relevant coding agents. Parallelize only independent scopes with explicit file
   ownership.
4. After coding completes, dispatch `backend_reviewer` for backend work, `web_gui_reviewer` for Web
   GUI work, and `architect` for contract work.
5. Send every actionable finding back to its owning coding agent, then repeat review. Continue until
   all reviewers report no blocking findings.
6. Do not silently drop issues. Resolve them in the cycle or, when the user or plan explicitly
   defers them, add a focused task under `docs/tasks`.
7. Dispatch `deployment_agent` for final checks and one or more justified local commits.
8. Write a concise cycle report under `docs/reports`.

## Documentation

- Plans are detailed agent-facing execution documents with scope, assumptions, contract effects,
  ordered work, verification, risks, and completion criteria.
- Follow-up tasks state the problem, evidence, scope, acceptance criteria, and reason for deferral.
- Reports are concise human-facing summaries of the plan, implementation, review iterations,
  verification, deferred tasks, and commits.
- Use stable names in the form `YYYY-MM-DD-<short-kebab-case-topic>.md`.
- Follow the `docs-standards` skill for every Markdown edit.

## Quality

- Run `.codex/lint.sh` before handing work to reviewers and before committing.
- Review findings must lead with concrete defects and evidence. Do not block on style-only
  preferences already handled by automated checks.
- Never claim a test or check passed unless it was actually run and its result observed.
