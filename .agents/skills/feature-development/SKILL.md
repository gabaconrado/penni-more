---
name: feature-development
description: Orchestrate the complete feature development cycle from interview through report.
---

# Feature development

Use this workflow for every requested Penni More feature. Read
[`references/artifacts.md`](references/artifacts.md) before creating a plan, task, or report.

## Hard stops

Stop and report immediately when a required tool or permission fails. Do not substitute another
tool, bypass the restriction, or silently skip the affected check. Obtain explicit user approval
before contacting an external operational service. Never perform a Git remote write.

## Cycle

1. Run the `grill-me` interview, asking one question at a time until no material ambiguity remains.
2. Dispatch the architect to write an implementation plan in `docs/plans`. The plan must allocate
   files and interfaces to owners, identify contract work, define review checks, and state completion
   criteria.
3. Obtain user agreement when the plan introduces a material choice not already settled during
   the interview.
4. Dispatch the backend, web GUI, and contract coding agents whose scopes are affected. Run
   independent assignments concurrently when the environment permits it.
5. Dispatch the matching reviewers after implementation:
   - the backend reviewer checks Django backend work;
   - the web GUI reviewer checks web work;
   - the architect reviews contract work and cross-scope consistency.
6. Give every actionable finding back to the responsible coding agent. Repeat implementation and
   review until reviewers report no unresolved blocking findings.
7. Defer an issue only when it is outside the agreed feature, cannot safely be completed in the
   cycle, and does not invalidate completion. Write each deferral to `docs/tasks` with evidence and
   acceptance criteria.
8. Dispatch the deployment agent for final repository checks and a local commit. No other agent may
   mutate Git state.
9. Write a concise implementation report in `docs/reports` containing the result, review cycles,
   observed verification, deferred tasks, and commit identifiers.

## Completion

The cycle is complete only when the approved behavior exists, affected contracts agree, required
checks pass, all blocking review findings are resolved, the local commit exists, and the report is
written. If the report is committed separately, the deployment agent must create that local commit.
