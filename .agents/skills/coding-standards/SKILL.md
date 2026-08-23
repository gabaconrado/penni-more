---
name: coding-standards
description: Apply shared implementation and review standards to any Penni More source-code change.
---

# Coding standards

Apply these standards whenever implementing or reviewing source code in this repository.

## Priorities

Evaluate decisions in this order:

1. Correctness and data integrity.
2. Security and privacy.
3. Simplicity and maintainability.
4. Performance supported by evidence.

Prefer the smallest design that completely satisfies the approved plan. Add a dependency only when
its benefit is concrete and larger than its maintenance, security, and deployment cost.

## Ownership and contracts

- Change only files owned by the assigned role unless the plan explicitly coordinates a cross-scope
  change.
- Treat the OpenAPI artifact as the source of truth for communication between backend and web code.
- Do not silently reinterpret an approved contract. Escalate contract changes to the architect and
  contract coding agent.
- Build a thin end-to-end slice before duplicating the same pattern across multiple modules.
- Keep modules cohesive and keep policy decisions out of transport and rendering code.

## Correctness and failure handling

- Validate data at trust boundaries and preserve domain invariants inside the domain layer.
- Make invalid states difficult to represent.
- Return errors with enough context to diagnose the failed operation without exposing secrets.
- Handle empty, malformed, duplicate, and concurrent inputs deliberately.
- Never claim that a check passed unless it was actually run and its result was observed.

## Testing

- Test public behavior and important invariants, not incidental implementation details.
- Cover the successful path, expected failures, and regressions for every corrected defect.
- Use mocks only at real external boundaries. Prefer small deterministic fakes for owned components.
- Keep tests independent, deterministic, and readable as examples of expected behavior.

## Readability

- Use names that express domain intent.
- Keep functions focused. Extract concepts, not arbitrary line ranges.
- Comment decisions and constraints that code alone cannot communicate.
- Remove obsolete code instead of leaving commented-out alternatives.
- Keep formatting and lint suppressions local, rare, and justified.
