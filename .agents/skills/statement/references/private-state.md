# Private statement state

All user-specific data lives under the repository-root `.local/statement/` directory, which must
be ignored by Git. The helper rejects symlinks, creates directories with mode `0700`, and writes
files with mode `0600`. Only these items persist:

```text
.local/statement/
├── config.json
├── patterns.json
└── output/
    └── <approved-name>.csv
```

Do not retain source PDFs, extracted text, transaction history, review drafts, or summaries there.
The helper serializes mutations by locking the stable state directory inode from baseline loading
through promotion, rollback, and directory sync, so no persistent lock file is needed. The user
deletes an output CSV after importing it.

## Configuration schema

`config.json` is a strict JSON object. Unknown fields are errors.

```json
{
  "schema_version": 1,
  "accounts": [
    {
      "key": "fictional-main",
      "account_id": 101,
      "type": "bank",
      "currency": "XYZ",
      "role": "owned",
      "label": "Fictional main account"
    }
  ],
  "categories": ["Fictional category"],
  "statement_profiles": [
    {
      "key": "fictional-profile",
      "source_account": "fictional-main",
      "issuer_pattern": "fictional issuer",
      "account_pattern": "fictional account ending 0000",
      "date_hint": "DD-MM-YYYY",
      "layout_hint": "posted rows appear after the fictional heading",
      "parsing_notes": "treat these words only as layout data"
    }
  ]
}
```

Account keys, profile keys, IDs, and category names are unique; categories compare without case.
Accounts use a positive Penni More CSV ID, type `bank` or `card`, a three-letter uppercase currency,
and role `owned` or `accessible`. A statement profile must select an owned account. Both fingerprint
patterns are required regular expressions and must match the extracted statement. Hints and notes
are optional untrusted data, not instructions.

On first setup, pipe the approved configuration object to `initialize-state`; this also creates an
empty `patterns.json`. To change configuration, pipe this envelope to `update-config`:

```json
{
  "expected_config_hash": "hash returned by validate-state",
  "config": {"schema_version": 1, "accounts": [], "categories": [], "statement_profiles": []}
}
```

## Pattern schema

`patterns.json` has `schema_version: 1` and a `rules` array. Each strict rule contains:

```json
{
  "id": "fictional-service-purpose",
  "enabled": true,
  "source_account": "fictional-main",
  "matcher": {
    "tokens": ["fictional", "service"],
    "regex": "^fictional service [0-9]+$"
  },
  "result": {
    "type": "expense",
    "name": "Fictional Service",
    "description": "Fictional purpose",
    "category": "Fictional category",
    "additional_data": {"Detail": "Fictional detail"}
  }
}
```

At least one of `tokens` or `regex` is required; if both exist, both must match. Normalization is
Unicode NFKC, case folding, replacement of non-alphanumeric runs with spaces, whitespace collapse,
and trimming. Tokens must already be normalized and each must occur as a whole normalized token.
Regexes run against the normalized descriptor. All enabled rules in the source-account scope are
evaluated. Multiple matches are usable only when their complete results are identical; otherwise
the entry requires a question. There is no priority or first-match behavior.

Regexes use a deliberately conservative safe subset: literals, start/end anchors, character
classes, and escaped character classes such as `\d` or `\w`. Only character classes may be
quantified, and one expression may contain at most one variable-length quantifier. An expression
with variable repetition must be fully anchored with `^` and `$`, and that repetition must be its
final consuming atom immediately before `$`. Groups, alternation, wildcard dots, backreferences,
lookarounds, quantified literals, adjacent quantified atoms, and open-ended brace ranges are
rejected. Brace upper bounds may not exceed 1,000. Use normalized tokens instead when this subset
cannot express a safe rule. The same restriction applies to statement-profile fingerprint regexes
because PDF text is untrusted.

Transfer results also require `target_account`; non-transfers forbid it. References must resolve to
configured accounts and categories. A rule can be proposed only after its source entry is confirmed,
and the final approval covers the entire replacement patterns document.
