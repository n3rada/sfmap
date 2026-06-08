# sfmap: AI Engineering Guide

This file is the canonical AI guidance for this repository.

## Runtime Requirement

- Python 3.12+. Use `uv` for all environment and dependency workflows.
- Run via `uv run sfmap`. Never install globally.

## Read Order

1. [README.md](README.md) — CLI behavior, command reference, authentication concepts.
2. [DEVELOPMENT.md](DEVELOPMENT.md) — architecture, data flow, module contracts, extension model (source of truth for structural decisions).
3. [src/sfmap/cli.py](src/sfmap/cli.py) — parser construction and command handler wiring.
4. [src/sfmap/core/client.py](src/sfmap/core/client.py) — `AuraClient`, session auth model.
5. [src/sfmap/core/session.py](src/sfmap/core/session.py) — `Session`, guest detection.
6. [src/sfmap/core/modules/](src/sfmap/core/modules/) — one module per capability surface.

If this file and [DEVELOPMENT.md](DEVELOPMENT.md) ever diverge on architecture or design decisions, follow [DEVELOPMENT.md](DEVELOPMENT.md).

## Source Map

- CLI entry and parser: [src/sfmap/cli.py](src/sfmap/cli.py)
- HTTP client and auth: [src/sfmap/core/client.py](src/sfmap/core/client.py)
- Session model: [src/sfmap/core/session.py](src/sfmap/core/session.py)
- Aura object enumeration: [src/sfmap/core/modules/enum.py](src/sfmap/core/modules/enum.py)
- Aura record dump: [src/sfmap/core/modules/dump.py](src/sfmap/core/modules/dump.py)
- GraphQL uiapi: [src/sfmap/core/modules/graphql.py](src/sfmap/core/modules/graphql.py)
- Content files: [src/sfmap/core/modules/content.py](src/sfmap/core/modules/content.py)
- Flow fuzzing: [src/sfmap/core/modules/flow.py](src/sfmap/core/modules/flow.py)
- Network config: [src/sfmap/core/modules/network.py](src/sfmap/core/modules/network.py)
- IDOR probing: [src/sfmap/core/modules/idor.py](src/sfmap/core/modules/idor.py)
- Apex controller fuzzing: [src/sfmap/core/modules/apex.py](src/sfmap/core/modules/apex.py)
- ApexREST fuzzing: [src/sfmap/core/modules/apexrest.py](src/sfmap/core/modules/apexrest.py)
- SOQL queries: [src/sfmap/core/modules/soql.py](src/sfmap/core/modules/soql.py)
- Tooling API: [src/sfmap/core/modules/tooling.py](src/sfmap/core/modules/tooling.py)
- Static resources: [src/sfmap/core/modules/staticresource.py](src/sfmap/core/modules/staticresource.py)
- Cross-surface exposure: [src/sfmap/core/modules/exposure.py](src/sfmap/core/modules/exposure.py)
- HTML report generator: [src/sfmap/core/modules/reporter.py](src/sfmap/core/modules/reporter.py)
- Bundled wordlists: [src/sfmap/data/](src/sfmap/data/)

## Architecture and Design Principles

Enforce these on every change:

### 1. Single Responsibility

- Each module in `core/modules/` owns exactly one capability surface.
- Transport (Aura POST, REST GET/POST) stays in `AuraClient`. Modules call client methods, not `httpx` directly.
- Credential and auth logic stays in `Session` + `AuraClient`. Modules are auth-agnostic.

### 2. Guest mode is automatic

`AuraClient` derives authenticated/guest from `Session.is_guest` when `authenticated` is not explicitly set. `Session.is_guest` is True when `token == "undefined"` and `cookie is None`. No module should hard-code `authenticated=False` or replicate this logic.

### 3. No guest surface

There is no separate guest command surface. Every command runs unauthenticated automatically when no credentials are found. Output goes to the same directory regardless of auth state.

### 4. SRP on tool scope

Tools do one thing. Secret scanning belongs in trufflehog, not in sfmap. File downloading and secret detection are separate responsibilities — sfmap downloads, external tools analyze.

### 5. CLI structure

Surfaces: `aura`, `rest`, `surface`, `files`.

`rest` has two subgroups with their own sub-subcommands:
- `rest graphql dump|query|introspect`
- `rest content enum|download|distribution`

`aura` commands: `objects`, `dump`, `record`, `info`, `related`, `idor`, `crud`, `inject`, `apex`, `flow`, `network`.

`rest` flat commands: `static`, `apexrest`, `soql`, `tooling`, `chatter`.

`report`: reads an existing output directory and generates a self-contained HTML file (`report.html`). No credentials required.

## Python Rules

1. **Imports** — standard library, then third-party, then local. One blank line between groups. Section comment for each: `# Built-in imports`, `# Third-party imports`, `# Local imports`.

2. **Typing** — use `X | Y` and `X | None` union syntax. No `Optional`. No `Any` unless unavoidable.

3. **Error handling** — inside `except` blocks, use `logger.exception(...)` from loguru, never `logger.debug(f"... {exc}")`. Drop the `as exc` binding unless the exception value is needed for something other than logging (e.g. storing in a result dict). `logger.exception` appends the full traceback automatically.

4. **No comments explaining the obvious** — only comment non-obvious invariants, workarounds, or hidden constraints. Never document what the code does; let names do that.

5. **No backward-compatibility shims** — no unused variables prefixed `_`, no re-exports for dead imports, no version guards.

6. **No premature abstractions** — three similar lines is better than a helper that exists for one caller.

## Logging Conventions

- `logger.debug` — internal state, loop progress, skip reasons (expected control flow).
- `logger.info` — operational steps, normal findings with no security impact.
- `logger.warning` — security findings, accessible records, exposed endpoints.
- `logger.success` — scan complete, no issues found.
- `logger.error` — unrecoverable failures that stop the current operation.
- `logger.exception` — inside `except` blocks; includes traceback automatically.

## Key Protocol Facts

- Aura endpoint: `/s/sfsites/aura` — form-encoded POST with `message=`, `aura.context=`, `aura.token=`.
- Guest token: `aura.token=undefined`, no cookies.
- GraphQL: `aura://RecordUiController/ACTION$executeGraphQL` — WAF silently returns `totalCount: 0` for operation names prefixed with `Dump`. Use `Query` prefix.
- `getObjectInfo` via `aura://RecordUiController/ACTION$getObjectInfo` — not `DetailController`.
- REST API (`/services/data/`) requires OAuth Bearer token. Community sessions are blocked at the platform level regardless of cookies.
- `Session.is_guest` = True only when both `token == "undefined"` AND `cookie is None`.

## Definition of Done

A change is complete only if all are true:

1. Behavior matches CLI semantics in [README.md](README.md).
2. No module bypasses `AuraClient` for HTTP.
3. No module hard-codes auth state.
4. Exception handlers use `logger.exception`, not `logger.debug`.
5. New commands are wired in `build_parser()` and documented in [README.md](README.md).
6. No unrelated refactors or comment churn.
