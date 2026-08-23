---
name: rust-standards
description: Apply Penni More Rust backend implementation and review standards.
---

# Rust standards

Apply these rules to Rust code under `src/backend`.

## Design

- Keep domain logic independent from HTTP, persistence, and process startup code.
- Represent money with an exact type and explicit currency semantics. Never use floating-point types
  for stored or calculated monetary values.
- Encode invariants in types when practical and validate untrusted input at the boundary.
- Prefer standard-library facilities and small focused crates over frameworks with unused surface
  area.
- Keep asynchronous code at I/O boundaries. Do not make pure domain logic async.

## Errors and diagnostics

- Use typed errors for library and domain boundaries; `thiserror` is acceptable when justified.
- Use contextual application errors only at the executable boundary; `anyhow` is acceptable there.
- Map internal failures to the documented OpenAPI error response without leaking sensitive data.
- Do not use `unwrap`, `expect`, `panic!`, `todo!`, or `unimplemented!` in production paths.
- Ensure debug output cannot reveal credentials or personal financial data.

## API and persistence

- Implement the OpenAPI contract exactly, including validation, status codes, and content types.
- Keep database details out of domain types where doing so preserves a clear boundary.
- Make transactions explicit for operations that must be atomic.
- Treat migrations and backward compatibility as planned changes, not incidental implementation.

## Tests and lints

- Put focused module tests beside the module, using a `tests.rs` submodule when they grow.
- Use integration tests for behavior through public interfaces.
- Test arithmetic boundaries, rounding rules, currency rules, and transactional failures.
- Run formatting, compilation, tests, and Clippy with warnings denied when the project provides
  them.
- Do not add a lint allowance without a narrow scope and written rationale.
- Document public APIs and derive `Debug` only when its output is safe.
