---
name: api-standards
description: Design and review the OpenAPI contract shared by the backend and web GUI.
---

# API standards

The OpenAPI documents under `src/contract` are the source of truth for backend and web integration.
The contract coding agent owns edits; the architect reviews and approves their design.

## Completeness

- Specify every path, method, parameter, request body, response status, and content type.
- Give operations stable, unique `operationId` values.
- Define reusable schemas for domain objects and consistent error responses.
- Express required fields, formats, bounds, enumerations, and nullability explicitly.
- Include concise examples that contain no secrets or realistic personal financial information.
- Document authentication, authorization expectations, and idempotency where relevant.

## Money semantics

- Represent monetary amounts exactly and document their unit and serialization.
- Make currency explicit whenever more than one interpretation is possible.
- Document rounding, sign, precision, and range rules.
- Distinguish identifiers, display labels, dates, timestamps, and accounting periods precisely.

## Compatibility

- Prefer additive, backward-compatible evolution.
- Treat removed or renamed fields, narrower validation, changed meanings, and status-code changes as
  potentially breaking.
- Require an architect-approved migration or versioning plan for a breaking change.
- Keep generated artifacts subordinate to the reviewed source contract.

## Review and validation

- Confirm each operation supports the approved user behavior and failure cases.
- Check that backend implementation and web consumption agree with the same contract revision.
- Run the repository's existing OpenAPI validator when one is available. Fix reported contract
  errors and rerun it. If the validator is missing, stop rather than installing or substituting one.
- Record unresolved compatibility or domain questions in the implementation plan.
