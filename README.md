# Penni More

A personal-use money manager.

## Status

The repository currently contains project and Codex infrastructure only. Application source code
has not been implemented.

## Intended stack

- Rust server
- Server-rendered HTML with Tailwind CSS
- Minimal vanilla JavaScript only when browser behavior requires it
- OpenAPI as the shared API contract
- Podman for local and deployed execution

## Repository layout

- `src/backend`: Rust server source
- `src/web`: Web GUI source and assets
- `src/contract`: OpenAPI contract artifacts
- `deploy`: Podman and deployment infrastructure
- `docs/plans`: Architect-authored implementation plans
- `docs/tasks`: Explicitly deferred follow-up work
- `docs/reports`: Completed feature-cycle reports

## Development workflow

Feature requests begin with a one-question-at-a-time interview and an architect-authored plan.
Implementation agents and their reviewers iterate until no blocking findings remain. The deployment
agent then validates and commits the result locally, and the cycle ends with a concise report.

Agents never write to Git remotes. Public documentation and Git remote reads are allowed;
authenticated or operational access to external services requires explicit approval.

## License

MIT
