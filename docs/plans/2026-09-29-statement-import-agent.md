# Local statement import agent

## Summary

Add a repository-versioned Codex `statement` skill that turns one text-based PDF bank statement
into a Penni More transaction-import CSV through an interactive review. The tracked skill contains
only general behavior, schemas, helper code, fictional tests, and repository attribution. All
account mappings, statement-specific parsing knowledge, learned rules, and generated CSVs remain
under the fully ignored `.local/statement/` directory.

The skill uses a small, separately locked `pypdf` helper managed by uv. The helper extracts text,
validates private JSON, and commits an approved CSV and approved rule changes. Actual statement
processing runs offline, without application, database, or external-service access. Every detected
statement transaction maps to exactly one CSV row with the same settled value; the user reviews all
rows and any proposed learning before either artifact is written.

## Goals

- Make the skill discoverable from a natural-language request and explicitly invocable as
  `$statement`, without requiring a custom slash command or `.codex/agents` definition.
- Extract text from one readable, unencrypted, text-based PDF and enrich its transactions through a
  guided conversation.
- Produce the exact CSV accepted by the existing Penni More transaction import, covering expense,
  income, and transfer rows.
- Make one-to-one transaction mapping, settled amounts, classifications, exclusions, and learned
  rules visible and auditable before the final confirmation.
- Learn only explicit matching rules derived from entries the user has confirmed.
- Keep all real financial and account data out of tracked files, logs, intermediate files, and Git.
- Give a first-time user a safe path to initialize and validate the private configuration without
  needing the Penni More application or database.

## Non-goals

- OCR, scanned/image-only PDFs, password-protected PDFs, combined multi-account statements, or
  formats whose transaction rows cannot be identified confidently.
- Direct database, Django, OpenAPI, browser, or Penni More import access.
- Automatic category/account discovery, balance reconciliation, duplicate detection, or importing
  the generated CSV into Penni More.
- Storing source PDFs, extracted text, transaction history, review drafts, prior-run summaries, or
  imported CSVs permanently.
- A fixed `/statement` command, a custom `.codex/agents/*.toml` agent, or a bank-specific tracked
  parser.
- Inferring a reusable rule from an unconfirmed suggestion or applying an ambiguous rule silently.
- Supporting currencies or transaction shapes that violate the existing Penni More import
  invariants.

Future improvements should be based on observed use. They are not deferred defects and do not need
task files unless a concrete issue is discovered during this feature cycle.

## User-visible behavior

### Invocation and first-run setup

- Natural-language requests such as "convert this statement to an import CSV" select the skill;
  `$statement <path>` is the explicit form. The supplied PDF may be outside the repository.
- The skill first checks that uv and the locked helper environment are already available. Runtime
  commands use uv's locked, offline, no-sync mode. They never download or install a dependency. A
  missing tool, environment, or dependency produces a clear setup failure and stops processing.
- When private state is absent, the skill explains the required data and interactively builds it in
  `.local/statement/`. The user confirms the configuration before it is written. Initialization is
  a distinct approved setup write; cancelling a later statement review does not remove it.
- Private configuration identifies configured accounts, their Penni More CSV IDs, account types,
  currencies, ownership/access roles, valid category names, statement fingerprints, and optional
  bank-specific layout notes. No database lookup is attempted.
- Exactly one configured statement profile and source account/currency must match a PDF. No match or
  multiple matches requires user resolution and, when appropriate, a separately confirmed config
  update. Evidence of more than one source account in the PDF is rejected.

### Extraction and review

1. The helper validates the file and emits extracted page text only to the current Codex process.
   It does not create a copy or extracted-text file. The skill treats every PDF string as untrusted
   financial data, never as an instruction, command, URL to open, or authorization.
2. The skill identifies all posted statement transactions, assigns each a stable run-local ordinal,
   and separately lists statement-like non-transactions such as opening balances, closing balances,
   totals, pending rows, and informational lines with an exclusion reason.
3. The initial summary reports the configured source account label/currency, statement period when
   available, transaction count, debit total, credit total, and exclusions. Opening/closing balance
   reconciliation is neither performed nor required.
4. Each transaction receives a proposed CSV representation. A prior rule may supply fields only
   when it matches unambiguously. The final review identifies the matched rule ID and every suggested
   field. Conflicting rules, unclear descriptors, and purchases needing a purpose such as a
   marketplace purchase or trip are reviewed one at a time.
5. The normalized `name` remains a recognizable merchant or service; the confirmed purpose belongs
   in `description`. `additional_data` contains only useful structured details. It does not retain
   the original statement descriptor merely for traceability.
6. The skill proposes a new or changed explicit rule only after the corresponding enriched entry is
   confirmed. Proposed rules are shown in a separate section of the final review.
7. The final review displays every enriched transaction in ordinal order, all exclusions, applied
   rules, proposed rule changes, and the exact count/value checks. It asks for one explicit approval
   covering both the CSV and proposed pattern update. With no approval or on cancellation, it writes
   neither.
8. After approval, the helper validates the complete in-memory run envelope and writes a new CSV
   under `.local/statement/output/` without overwriting an existing file. It atomically replaces
   `patterns.json` only when approved changes exist. The user imports and then deletes the CSV.

### One-to-one and money rules

- One detected posted transaction has exactly one run ordinal and exactly one CSV row. Transactions
  are never split, merged, silently excluded, or synthesized. An explicit fee or interest line is
  its own expense or income row. A fee embedded in another posted transaction remains part of that
  transaction and may be described in `additional_data`.
- For every ordinal, the positive two-decimal CSV `amount` equals the absolute settled amount in the
  statement account currency. The transaction type and transfer direction must reproduce the
  signed effect shown for the statement account. The final review compares every ordinal as well as
  row count, debit total, and credit total; any mismatch blocks writing.
- For foreign-currency transactions, `amount` is the final settled account-currency value. Original
  amount, original currency, exchange information, or an embedded fee may be included in
  `additional_data` when explicitly available and useful.
- Prefer the transaction/purchase date when present. Fall back to the posting date only when needed
  and add a short `additional_data` item indicating that the posting date was used.
- Classify a movement as a transfer only when both sides are configured Penni More accounts. A
  transfer's `account_id` is always its true sending account and `target_account_id` its receiving
  account, so an incoming movement on the statement reverses the statement account into the target
  position. A movement to or from an untracked external account is an expense or income.

## Decisions and assumptions

### Tracked skill structure

Use progressive disclosure and keep `SKILL.md` focused on activation, trust boundaries, workflow,
and stopping conditions. Detailed private-state and import rules belong in linked references. The
planned tree is:

```text
.agents/skills/statement/
├── SKILL.md
├── agents/openai.yaml
├── pyproject.toml
├── uv.lock
├── references/
│   ├── private-state.md
│   └── transaction-mapping.md
├── scripts/statement_helper.py
└── tests/test_statement_helper.py
```

`agents/openai.yaml` supplies only general display metadata and a generic default prompt. Implicit
invocation remains enabled. `SKILL.md` attributes the skill to the Penni More project and links to
the repository MIT `LICENSE`; it contains no person-specific attribution beyond existing repository
facts.

The helper is its own non-package uv project rather than a Django dependency. Its runtime dependency
is a compatible constrained `pypdf` release, with the exact resolved version committed in `uv.lock`.
Development-only test/lint dependencies should be added only when an existing repository tool
cannot run the checks. Real processing always invokes the locked environment with `--offline` and
`--no-sync` so a cache miss or absent environment fails instead of contacting the network.

### Private state

Add the repository-root ignore rule `/.local/statement/`. The helper creates `.local/statement/`
and `output/` with mode `0700` and private files with mode `0600`, subject to stricter existing
permissions. It rejects symlinked state paths and unsafe output basenames. It never stages or asks
to stage ignored files.

`config.json` uses a top-level integer `schema_version` and these validated collections:

- `accounts`: unique local keys with positive `account_id`, `bank` or `card` type, three-letter
  currency code, `owned` or `accessible` role, and a user-facing local label;
- `categories`: unique nonblank category names, compared case-insensitively;
- `statement_profiles`: unique keys selecting one owned source account, required issuer/account
  fingerprint regular expressions, date/layout hints, and optional parsing notes treated as data.

The validator compiles every regular expression, bounds strings and collection sizes, rejects
unknown fields, verifies references, and requires statement-source accounts to be owned. Configured
account types, currencies, access roles, and category names let the helper enforce the current
import rules without querying the application.

`patterns.json` also has `schema_version` and a `rules` list. Each rule has a unique stable rule ID,
an enabled flag, a source-account scope, a matcher, and a normalized result. A matcher contains
normalized descriptor tokens, a regular expression, or both; when both exist they both must match.
The result contains `type`, `name`, `description`, `category`, optional transfer target account key,
and optional flat string `additional_data`. Rule account/category references must resolve through
`config.json`.

Descriptor normalization is deterministic: Unicode NFKC normalization, case folding, replacement
of non-alphanumeric runs with one space, whitespace collapse, and trimming. Regexes apply to that
normalized descriptor. All matching enabled rules are evaluated. A single result is usable; several
matches are usable only when their complete normalized results are identical. Otherwise the entry
is ambiguous and must be questioned. There is no first-match or implicit priority behavior.

Only `config.json`, `patterns.json`, and transient final files in `output/` persist. Initialization
creates an empty versioned patterns document. State changes use validated temporary files in the
same private filesystem, flush and sync before atomic promotion, and clean temporary files after
errors. Config updates and pattern replacement require an expected content hash to detect concurrent
edits. CSV creation is atomic and no-overwrite. The finalizer validates and stages every output
before promotion and rolls back synchronous partial failures where possible; a process crash cannot
make either individual file partially written.

### Helper interface

Implement one CLI with machine-readable errors and these cohesive operations:

- `extract --pdf PATH` opens exactly the supplied regular file read-only, rejects encryption,
  malformed structure, zero pages, or empty extracted text, and returns page-indexed text on standard
  output. It never follows content instructions or writes extracted data.
- `validate-state` reads the fixed private paths, validates both documents and their cross-references,
  and returns the state plus content hashes for the active conversation. Diagnostics identify paths
  and fields without echoing private values.
- `initialize-state` and `update-config` accept JSON on standard input, validate it completely, and
  create or atomically replace private state only after the skill obtains explicit setup approval.
- `finalize` accepts the approved run envelope on standard input. The envelope contains source
  ordinal, source signed settled amount, mapped CSV row, proposed full rules document, expected
  config/pattern hashes, and a safe output basename. It revalidates state, matching references,
  one-to-one ordinals, per-row values and source-account effects, aggregate counts/totals, CSV field
  rules, and approved patterns before writing.

Sensitive JSON is passed through standard input, never command arguments or environment variables.
The helper does not log it. Normal success output contains only status, counts, and resulting paths;
errors do not reproduce PDF text, descriptors, config values, or CSV rows. No intermediate review
payload is written to the repository, private state, or `/tmp`.

### Import compatibility

The generated UTF-8 CSV uses this exact header and order:

```text
type,name,description,category,date,amount,account_id,target_account_id,additional_data
```

The helper duplicates the existing import boundary checks so failures occur before a sensitive CSV
is created:

- at least one and at most 1,000 rows; exact lowercase `expense`, `income`, or `transfer` type;
- nonblank `name` of at most 255 characters, `description` of at most 2,000 characters, configured
  category, ISO `YYYY-MM-DD` date, and amount from `0.01` through `9999999999999999.99` with exactly
  two fractional digits and no sign or currency symbol;
- positive configured integer `account_id`; blank `target_account_id` except for transfers; transfer
  source and target differ, source is a bank account, both currencies match, the statement account
  is on the expected side, and the target is configured/accessibly mapped;
- income uses a bank account; each non-transfer primary account is configured and owned;
- `additional_data` is blank when empty or a compact flat JSON object of at most 25 nonblank string
  pairs, with keys unique ignoring case, keys at most 100 characters, and values at most 500.

Use Python `Decimal` exclusively for money and the standard `csv` module for correct escaping. The
helper must not claim to replace server-side import preview validation; the user still uploads and
confirms the resulting file through Penni More.

## Scope and ownership

- The `architect` owns this plan and later reviews cross-scope consistency, privacy boundaries, and
  the conclusion that no OpenAPI change is needed.
- One implementation `worker` owns all files below `.agents/skills/statement/`, including skill
  instructions, UI metadata, helper project and lock, references, and fictional tests. The worker
  must load `skill-creator`, `coding-standards`, and `docs-standards`, and must not edit `.gitignore`,
  application code, contracts, deployment files, or feature documents.
- The `deployment_agent` owns the single `.gitignore` addition, final repository validation, the
  implementation commit, `docs/reports/2026-09-29-statement-import-agent.md`, and a report commit if
  the report is written after the implementation commit. It must load `git-standards`,
  `bash-standards` when running or changing shell automation, and `docs-standards` for the report.
- An independent read-only `worker` reviews the completed statement skill, helper, tests, and ignore
  boundary for plan compliance, privacy, security, and data-integrity defects. It edits nothing.
- No `backend_coder`, `web_gui_coder`, `contract_coder`, backend reviewer, or Web GUI reviewer is
  required because `src/backend`, `src/web`, and `src/contract` do not change.

The skill worker and deployment agent may implement their non-overlapping paths concurrently after
this plan is approved. Review starts only after both are complete. Every actionable finding returns
to the owner of the affected path, followed by the same focused review until no blocking findings
remain.

## Contract impact

There is no OpenAPI or application behavior change. The skill is an offline producer for the
existing transaction-import CSV boundary. `src/contract/openapi.yaml`, Django models/services, and
Web GUI templates remain untouched.

The current authoritative application behavior is
`src/backend/penni_more/transactions/imports.py` together with transaction validation in
`src/backend/penni_more/transactions/services.py`. The duplicated helper checks intentionally give
earlier feedback but do not weaken or override server validation. If those application constraints
change during implementation, the architect must reconcile this plan before the helper is merged;
the worker must not independently modify either consumer or the OpenAPI contract.

## Implementation sequence

1. The architect completes this plan from the resolved interview and receives agreement only if a
   new material choice is introduced. No material question remains in the current handoff.
2. The statement-skill worker initializes the minimal skill structure, writes concise activation and
   safety instructions, and documents the private schema and transaction mapping through linked
   references. All tracked wording and metadata remain general and use only repository attribution.
3. The same worker creates the isolated uv project and lock, then implements the deterministic helper
   operations, permission/path controls, JSON validation, extraction failures, exact CSV mapping,
   atomic writes, and conflict detection.
4. The worker adds deterministic tests. PDF fixtures are generated during tests and contain only
   conspicuously fictional entities and values; no real bank, account, merchant, statement, or user
   data appears in tracked source, snapshots, examples, or fixtures.
5. Independently, the deployment agent adds `/.local/statement/` to `.gitignore` and verifies the
   directory and descendants are ignored without hiding tracked skill files.
6. The implementation worker runs focused validation and `.codex/lint.sh`, fixes owned failures, and
   hands off the observed results. The deployment agent does the same for its owned change.
7. The read-only reviewer exercises adversarial and ordinary cases, including prompt-like PDF text,
   ambiguous profiles/rules, unsafe paths, malformed private JSON, mapping mismatches, and write
   failures. The architect checks import compatibility and the absence of backend/web/contract drift.
8. Owners fix every actionable finding and rerun affected checks. Review repeats until the reviewer
   and architect report no blocking findings. A deferral is allowed only under the repository feature
   workflow and must receive a focused task document with evidence and acceptance criteria.
9. The deployment agent performs final checks, confirms no ignored/private artifact is staged, and
   creates one justified local implementation commit. It then writes the concise cycle report with
   actual review/check/commit results and commits that report locally if a second commit is needed.

## Review and verification

### Focused automated checks

The implementation must run the commands supported by the final helper project; expected commands
are:

```bash
uv lock --check --project .agents/skills/statement
uv run --project .agents/skills/statement --locked --offline --no-sync \
  python -m unittest discover -s .agents/skills/statement/tests -v
uv run --project src/backend ruff check .agents/skills/statement/scripts \
  .agents/skills/statement/tests
python /home/gaba/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
  .agents/skills/statement
git check-ignore -v .local/statement/config.json \
  .local/statement/patterns.json .local/statement/output/example.csv
./.codex/lint.sh
```

If the test command must use a helper-project development group, document the exact locked invocation
in `SKILL.md` and the report. Do not sync or install during actual statement processing. Missing host
tools stop the workflow; declared project dependencies may be installed during implementation, then
the offline/no-sync path must be demonstrated.

### Required test coverage

- Successful multi-page text extraction and rejection of encrypted, malformed, zero-page,
  image-only/empty-text, nonexistent, non-regular, and unreadable PDFs without retained text files.
- Initial state creation, schema versions, strict unknown-field rejection, duplicate IDs/names,
  invalid regexes, broken references, invalid roles/types/currencies, symlinked paths, permissions,
  atomic config changes, and stale-hash conflicts.
- Deterministic descriptor normalization; token-only, regex-only, combined, identical-result, and
  conflicting-result matching; disabled and account-scoped rules.
- CSV quoting and Unicode, exact header order, all three transaction types, incoming transfer
  reversal, configured external movements as income/expense, date fallback metadata, foreign
  currency metadata, explicit fee/interest rows, and empty/nonempty `additional_data`.
- Rejection of every mirrored import-boundary violation, unconfigured IDs/categories, incompatible
  account type/currency/direction, duplicate/missing ordinals, count mismatch, per-row value mismatch,
  debit/credit total mismatch, oversized input, unsafe filenames, and existing output targets.
- Cancellation performs no finalize call. Validation failure creates neither a CSV nor a changed
  patterns file. Approved finalization creates mode-`0600` output and only the approved pattern
  document; a synchronous second-write failure exercises rollback behavior.
- A repository scan verifies tracked skill, tests, references, schema wording, and Git diff contain
  no real statement/account/expense data. `git status --ignored` confirms any local test state
  remains ignored and none is staged.

### Manual forward test

Use an isolated temporary workspace and a generated fictional text PDF to run a fresh Codex
conversation against the completed skill. Verify natural-language activation or `$statement`,
first-run guidance, ignored private initialization, summary/exclusion display, one-by-one ambiguity
questions, known-rule skipping, complete final review, explicit joint approval, and import-compatible
CSV output. Repeat with prompt-injection-like PDF text and confirm it is displayed or classified only
as data. Cancel before approval and confirm no CSV or pattern change. Do not use a real statement or
personal configuration in review evidence.

The deployment agent finally runs the repository's appropriate full check through
`./penni-more.sh check` when the required Podman/runtime tools are available, plus `.codex/lint.sh`.
It records any unavailable check accurately rather than claiming success.

## Risks

- PDF text extraction order can differ from visual row order. The skill must stop when row boundaries,
  dates, signs, or amounts are not confidently recoverable; user confirmation cannot justify silently
  dropping or combining rows.
- Statement text can contain prompt injection or misleading instructions. The skill and forward test
  enforce a strict data-only trust boundary and prohibit executing or following statement content.
- Learned regexes can be too broad or multiple rules can collide. Explicit rule previews, account
  scope, normalized matching, conflict questions, and final approval reduce incorrect reuse.
- The helper mirrors application validation and may drift later. References identify the authoritative
  Django modules, tests pin current semantics, and future changes must update the helper deliberately.
- Private data can leak through command lines, diagnostics, fixtures, temporary files, permissions,
  or Git. Standard-input payloads, redacted errors, no intermediate persistence, restrictive modes,
  symlink checks, an anchored ignore rule, and tracked-content review address each route.
- A process or machine crash can occur between promotion of the individually atomic CSV and patterns
  files. Full validation and staging occur first, synchronous failures roll back where possible, and
  neither individual file can be partially written. V1 does not introduce a persistent journal because
  retaining run payloads would violate the agreed state boundary.
- Config is intentionally independent of the application and can become stale. The helper catches
  internal inconsistencies, but the normal Penni More upload preview remains the final authority for
  current account access, category activity, and other database state.

## Completion criteria

- The tracked `statement` skill is naturally discoverable and explicitly invocable, contains the
  agreed general purpose/responsibilities/repository attribution, and contains no personal financial
  information.
- Its locked `pypdf` helper successfully runs offline/no-sync and safely rejects every unsupported
  PDF class without retaining extracted content or contacting a network or application service.
- First-run setup produces validated, restrictive, fully ignored private state with no database
  dependency; only the agreed config, patterns, and final output paths persist.
- A confirmed fictional statement demonstrates a one-to-one row mapping, exact per-row settled
  values and aggregate checks, supported type/date/currency/transfer semantics, complete review, and
  an exact import-compatible CSV.
- Ambiguous entries are questioned individually; unambiguous confirmed-rule matches are visibly
  suggested; only confirmed entries produce separately approved explicit rules.
- Cancellation writes neither CSV nor patterns, output never overwrites a file, and config/pattern
  writes are validated, conflict-aware, permission-restricted, and individually atomic.
- Focused tests, the skill validator, ignore checks, `.codex/lint.sh`, applicable repository checks,
  manual forward tests, and privacy inspection have observed results recorded in the report.
- All actionable review findings are resolved or explicitly deferred under the approved workflow;
  the architect reports no blocking cross-scope/contract finding.
- The deployment agent creates the required local commit or commits, and the final report names them.
