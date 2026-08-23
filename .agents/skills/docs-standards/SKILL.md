---
name: docs-standards
description: Write concise human documentation and detailed unambiguous agent documentation.
---

# Documentation standards

Apply these standards to Markdown, plans, tasks, reports, and agent-facing instructions.

## Audience

- Keep documents written for the user concise and easy to scan.
- Make documents written for agents detailed enough to remove ambiguity about ownership, inputs,
  constraints, validation, and completion.
- Put the outcome first. Include background only when it changes a decision.
- Do not copy implementation detail into multiple documents when a single authoritative reference
  is sufficient.

## Markdown

- Wrap prose at 100 columns without breaking URLs, code, or tables.
- Use sentence-case headings and descriptive link text.
- Include a blank line around headings, lists, and fenced code blocks.
- Use reference-style links when repeated URLs would make source text hard to read.
- Keep terminology consistent with the OpenAPI contract and source code.
- Never include credentials, tokens, private financial data, or realistic secrets in examples.

## Repository artifacts

- Store implementation plans in `docs/plans`.
- Store deliberately deferred follow-up work in `docs/tasks`.
- Store completed feature-cycle reports in `docs/reports`.
- Name artifacts `YYYY-MM-DD-topic.md` using a short lowercase topic.
- Update an existing artifact when it represents the same work; do not create competing versions.
- Record facts, decisions, and observed checks. Clearly label assumptions and unverified claims.

## Editing and validation

- Preserve useful existing content and link definitions during edits.
- Avoid formatter-wide rewrites unrelated to the requested change.
- Run the repository Markdown linter and correct findings before completion.
