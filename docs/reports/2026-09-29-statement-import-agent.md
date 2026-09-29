# Statement import agent report

## Outcome

Added a repository-local `statement` skill that converts one text-based PDF statement into a
reviewed Penni More import CSV. The workflow keeps configuration, learned rules, and generated CSVs
under the ignored `.local/statement/` path and writes a CSV or pattern update only after explicit
approval. No backend, Web GUI, or OpenAPI behavior changed.

Implementation commit: `7192f124433f7c1a8cde9e5121b38a2da496697c`.

## Changes

- Added the skill instructions, private-state and transaction-mapping references, and generic Codex
  display metadata with Penni More repository attribution only.
- Added a separately locked `pypdf` helper for PDF text extraction, strict private-state validation,
  bounded rule matching, exact CSV mapping, atomic finalization, and concurrent-update detection.
- Added 36 fictional tests covering extraction failures, schema and permission boundaries, safe
  matching, import invariants, cancellation, rollback, and concurrent mutations.
- Added `/.local/statement/` to `.gitignore`; no private state or generated output is tracked.

## Review

The first independent review found blocking concurrent state-update and regular-expression
performance risks. The implementation serialized config/finalization mutations and restricted
regular expressions to a bounded safe subset, with regression coverage. The repeated independent
review and the architect's contract/privacy review then reported no blocking findings. No issue was
deferred.

## Verification

Observed on 2026-09-29:

- `uv lock --check --project .agents/skills/statement` passed.
- The locked, offline, no-sync unittest command passed all 36 tests.
- Ruff passed for the helper and its tests.
- The skill validator passed through the existing locked backend environment. Its documented plain
  system-Python invocation could not import `yaml`; no package was installed.
- `git check-ignore -v` confirmed config, patterns, and output paths use the anchored
  `/.local/statement/` rule.
- `./.codex/lint.sh` passed.
- `./penni-more.sh check` completed successfully: 77 shell tests, 195 backend tests, 23 Web unit
  tests, 32 browser tests, and the formatting, lint, contract, build, migration, static, and
  integration phases passed.
- Staged diff, whitespace, file list, ignore status, and tracked-content privacy scans passed. The
  implementation commit contains only the ten planned files and fictional test data.

An isolated `/tmp` forward test generated a fictional text PDF containing prompt-like text. The
helper extracted it as data, initialized mode-`0700` directories and mode-`0600` files, and a
cancelled pre-finalization path left both output and patterns unchanged. An approved one-row expense
then produced the exact CSV header and value, atomically saved an approved rule, and matched that
rule on a later descriptor. The existing backend import syntax parser accepted the generated row
from the `src/backend` working directory with no errors.

A separate fresh interactive Codex conversation was not available, so natural-language activation
and the conversational question/summary presentation were not re-exercised outside this feature
cycle. The direct helper forward test covered the persistence, privacy, mapping, cancellation, and
import-syntax boundaries.

## Deferred work

None.
