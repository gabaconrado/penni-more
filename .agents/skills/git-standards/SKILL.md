---
name: git-standards
description: Govern safe local Git operations performed exclusively by the deployment agent.
---

# Git standards

Only the deployment agent may perform Git operations that change repository state. Other agents may
use read-only inspection commands.

## Absolute boundaries

- Never push, force-push, delete remote refs, or otherwise write to a Git remote.
- Remote reads such as fetch are allowed only when required by the task and permitted by the active
  environment.
- Use direct sandbox elevation when an approved local Git mutation requires it. Never alter Git
  configuration, environment, hooks, paths, or command semantics to bypass a restriction, and stop
  if direct elevation fails or is denied.
- Do not rewrite, amend, squash, or rebase existing user commits unless the approved plan explicitly
  requires it.
- Never discard uncommitted user work.

## Preparing a commit

1. Inspect status, the full diff, and relevant recent history.
2. Separate unrelated user changes from the task. Stage only files belonging to the task.
3. Run the applicable repository checks. Fix ordinary validation failures, but stop if a required
   host tool is missing or an environment restriction cannot be resolved by direct elevation.
4. Verify staged content with `git diff --cached` before committing.
5. Use a Conventional Commits subject that describes one coherent change.

Use this trailer for commits created by the deployment agent:

```text
Co-authored-by: deployment-agent <deployment-agent@penni-more.local>
```

## History

- Prefer a linear local history.
- Fetch before comparing against a remote base; do not use `git pull` as a shortcut.
- Resolve conflicts using the approved feature intent and preserve unrelated user edits.
- Report the commit hash after a successful commit.
