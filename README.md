# Penni More

[![Latest Docker image](https://img.shields.io/docker/v/gabaconrado/penni-more?sort=semver&label=latest%20image)](https://hub.docker.com/r/gabaconrado/penni-more/tags)

A personal-use money manager.

## Status

The application includes authentication and account management, with production deployment and
local development workflows built around Podman.

## Intended stack

- Python server using Django
- uv for Python versions, virtual environments, dependencies, locking, and project commands
- Server-rendered HTML with Tailwind CSS and daisyUI components
- Modern, page-specific vanilla JavaScript rather than a client application framework
- Chart.js for responsive data visualizations
- OpenAPI as the shared API contract
- Podman for local and deployed execution

## Web GUI architecture

The Web GUI uses fast, complete server-rendered pages. Account management, transaction entry,
transfers, CSV import, filtering, and aggregation do not require client-side application state.
CSV import uses a server-rendered validation and results flow rather than an interactive browser
preview.

The interface is fully usable on phones and may require a modern browser with JavaScript enabled.
JavaScript remains limited to focused enhancements such as chart behavior and visual polish. A
client-side framework or partial-page navigation library should be introduced only when a concrete
interaction cannot remain simple with normal links, forms, and page navigation.

## Repository layout

- `src/backend`: Django server source
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

## Tests

Database-dependent commands require Podman and automatically run a fresh PostgreSQL container on a
dynamically assigned loopback port. The container and its temporary data are removed when the
command succeeds, fails, or is interrupted. This test database is independent of the local Compose
stack, so no local database needs to be started first and an existing local stack is left unchanged.

The self-contained database lifecycle applies to these commands:

```bash
./penni-more.sh test
./penni-more.sh check backend
./penni-more.sh check integration
./penni-more.sh check
```

Concurrent commands receive separate containers and ports.

## License

MIT
