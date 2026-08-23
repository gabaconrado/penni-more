---
name: grill-me
description: Interview the user one question at a time before planning a Penni More feature.
---

# Grill me

Use this skill before the architect writes an implementation plan for a requested feature.

## Interview method

- Ask exactly one focused question per message.
- Resolve answers available from the repository and prior conversation before questioning the user.
- Explain a recommendation briefly when the user is choosing between meaningful alternatives.
- Continue until the feature is testable and no material decision is being silently assumed.
- Do not begin implementation or write the plan during the interview.

## Topics to resolve

Cover only topics relevant to the feature, including:

- desired user behavior and completion criteria;
- explicit non-goals and boundaries;
- domain concepts, ownership, and financial semantics;
- OpenAPI inputs, outputs, errors, and compatibility;
- persistence, migration, concurrency, and idempotency;
- privacy, authorization, auditability, and failure recovery;
- web states, accessibility, and behavior without JavaScript;
- deployment or operational effects;
- verification strategy and representative edge cases;
- preference for the simplest approach with the fewest dependencies.

Probe vague words such as "simple", "automatic", "recent", and "balance" until they have an
observable meaning. When money is involved, explicitly resolve currencies, precision, rounding,
sign conventions, and dates.

## Architect handoff

At the end, give the architect a compact structured handoff containing:

- confirmed requirements and non-goals;
- decisions and their rationale;
- assumptions explicitly accepted by the user;
- constraints and affected ownership areas;
- remaining open questions, which must be empty before planning starts.
