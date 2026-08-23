# Feature artifact templates

Use the minimum content needed for the feature while retaining every applicable section below.

## Implementation plan

Path: `docs/plans/YYYY-MM-DD-topic.md`

```markdown
# Feature title

## Summary

## Goals

## Non-goals

## User-visible behavior

## Decisions and assumptions

## Scope and ownership

## Contract impact

## Implementation sequence

## Review and verification

## Risks

## Completion criteria
```

Allocate each changed path to one agent. Identify dependencies between assignments and which work
can run concurrently. State exact commands or observable checks when they are known.

## Follow-up task

Path: `docs/tasks/YYYY-MM-DD-topic.md`

```markdown
# Task title

## Problem

## Evidence

## Scope

## Acceptance criteria

## Deferral reason and dependencies
```

Do not use a task file to hide a blocking defect or unfinished agreed scope.

## Implementation report

Path: `docs/reports/YYYY-MM-DD-topic.md`

```markdown
# Feature title report

## Outcome

## Changes

## Review cycles

## Verification

## Deferred tasks

## Commits
```

Keep the report concise. Record observed outcomes, not a transcript of agent activity. Link the plan
and any deferred task files.
