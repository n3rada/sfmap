# sfmap — Copilot Instructions

Read [AI.md](../AI.md) and [DEVELOPMENT.md](../DEVELOPMENT.md) before making any change. They are the canonical source of truth for architecture, module responsibilities, and Python rules.

## What This Project Is

Salesforce Experience Cloud security assessment CLI. Targets Aura framework endpoints (`/s/sfsites/aura`), GraphQL `uiapi`, and the REST API surface.

## Non-Negotiable Rules

- Every `except` block uses `logger.exception(...)` from loguru — never `logger.debug(f"... {exc}")`.
- No module calls `httpx` directly. All HTTP goes through `AuraClient` methods.
- No module hard-codes auth state. `AuraClient` derives guest/authenticated from `Session.is_guest` automatically.
- Tools do one thing. sfmap downloads and enumerates — it does not scan for secrets.
- No backward-compatibility shims. Delete old code, do not wrap it.
- No comments that explain what code does. Only comment non-obvious invariants or constraints.
- Modern Python only: `X | Y` unions, `X | None`, `pathlib`. No `Optional`, no `Any`.

## Module Pattern

```python
def some_capability(client: AuraClient, output_dir: str, ...) -> ...:
    # call client.aura_post() or client.rest_get()
    # parse response
    # write output files
    # return results
```

Modules are stateless functions. They receive a client and return results. Command handlers in `cli.py` own session construction and client lifetime.

## Commit Style

Single-line messages. No co-author lines.
