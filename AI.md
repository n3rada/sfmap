# sfmap: AI Engineering Guide

This file is the canonical AI guidance for this repository. Architecture, design decisions, module contracts, and protocol notes live in [DEVELOPMENT.md](DEVELOPMENT.md) — that file is the source of truth when the two diverge.

## Runtime Requirement

Python 3.12+. Run via `uv run sfmap`. Never install globally.

## Read Order

1. [README.md](README.md) — CLI behavior, command reference, authentication concepts.
2. [DEVELOPMENT.md](DEVELOPMENT.md) — architecture, source map, design principles, logging conventions, CLI surfaces, output conventions, error handling, Salesforce protocol notes.
3. [src/sfmap/cli.py](src/sfmap/cli.py) — parser construction and command handler wiring.
4. [src/sfmap/core/client.py](src/sfmap/core/client.py) — `AuraClient`, session auth model.
5. [src/sfmap/core/session.py](src/sfmap/core/session.py) — `Session`, guest detection.
6. [src/sfmap/core/modules/](src/sfmap/core/modules/) — one module per capability surface.

## Python Rules

1. **Imports** — standard library, then third-party, then local. One blank line between groups. Section comment for each: `# Built-in imports`, `# Third-party imports`, `# Local imports`.

2. **Typing** — use `X | Y` and `X | None` union syntax. No `Optional`. No `Any` unless unavoidable. Declare reusable complex types with the `type` statement (PEP 695): `type Headers = dict[str, str]`.

3. **Pathlib** — use `pathlib.Path` for filesystem operations, not `os.path`. PEP 428.

4. **f-strings** — all string interpolation uses f-strings. Never `.format()` or `%` formatting. PEP 498.

5. **Walrus operator** — use `:=` to avoid evaluating an expression twice when the result is needed in both the condition and the body. PEP 572.

6. **`match`/`case`** — prefer structural pattern matching over `if/elif` chains when dispatching on the shape or value of data. PEP 634.

7. **No mutable default arguments** — never use `[]`, `{}`, or other mutable objects as parameter defaults. Use `None` and assign inside the function body. PEP 8.

8. **Comprehensions over `map`/`filter`** — use list/dict/set comprehensions. Generator expressions when the result is only iterated once. Never `map()` or `filter()`.

9. **Error handling** — inside `except` blocks, use `logger.exception(...)` from loguru, never `logger.debug(f"... {exc}")`. Drop the `as exc` binding unless the exception value is stored or re-raised. `logger.exception` appends the full traceback automatically.

10. **No comments explaining the obvious** — only comment non-obvious invariants, workarounds, or hidden constraints. Never document what the code does; let names do that.

11. **No backward-compatibility shims** — no unused variables prefixed `_`, no re-exports for dead imports, no version guards.

12. **No premature abstractions** — three similar lines is better than a helper that exists for one caller.

## Definition of Done

A change is complete only if all are true:

1. Behavior matches CLI semantics in [README.md](README.md).
2. No module bypasses `AuraClient` for HTTP.
3. No module hard-codes auth state.
4. Exception handlers use `logger.exception`, not `logger.debug`.
5. New commands are wired in `build_parser()` and documented in [README.md](README.md).
6. No unrelated refactors or comment churn.
