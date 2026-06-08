# sfmap — Development Guide

Architecture, design rationale, and extension model. This is the source of truth for structural decisions. [AI.md](AI.md) summarises the rules; this file explains the why.

## High-Level Flow

```
CLI args
  └─ build_parser()       [cli.py]
       └─ cmd_*(args)     [cli.py]
            ├─ _build_session(args) → Session
            ├─ AuraClient(session)  → HTTP client (auth derived from session)
            └─ module.function(client, ...)
```

Every command handler in `cli.py` follows this pattern exactly: build session, open client, call module, return exit code.

## Session and Auth Model

`Session` (`core/session.py`) holds the four credentials:

| Field | Source | Default |
|---|---|---|
| `context` | `ctx.json` or `-C` flag | required |
| `token` | `token.txt` or `-T` flag | `"undefined"` |
| `cookie` | `cookies.txt` or `--cookie` flag | `None` |
| `bearer_token` | `bearer.txt` or `--bearer` flag | `None` |

`Session.is_guest` is `True` when `token == "undefined"` **and** `cookie is None`. This is the single source of truth for unauthenticated state.

`AuraClient` (`core/client.py`) derives `authenticated` from `session.is_guest` when the caller does not override it. Modules never set `authenticated` explicitly — they pass the session and let `AuraClient` decide.

## AuraClient Methods

| Method | Use |
|---|---|
| `aura_post(payload)` | Aura framework POST — appends token, context, form encoding |
| `rest_get(url)` | REST API GET — appends Bearer header if available |
| `rest_post(url, ...)` | REST API POST with Bearer |
| `get(url)` | Plain GET with no auth headers (used for content probing) |

## Module Structure

Each file in `core/modules/` is one capability surface. Modules are stateless functions; they receive a client and return results. They do not hold state between calls.

Modules call `client.aura_post()` or `client.rest_get()` — never `httpx` directly.

### Key Modules

**`enum.py`** — `list_objects(client)` via `getConfigData`. Returns `{name: prefix}` dict. Raises on Aura exception. Called by most other modules to get the object list.

**`dump.py`** — `get_items()` (single page), `dump_object()` (all pages), `get_object_info()`, `get_record()`, `download_file()`. The `get_items` function is the workhorse: it calls `getItems` Aura action and returns the `returnValue` dict or None.

**`graphql.py`** — Three entry points: `introspect()`, `query_objects()` (count sweep), `dump_object()` (field-level dump), `autodump()` (full sweep with auto-discovered fields). WAF note: operation names prefixed `Dump` return `totalCount: 0` silently. Use `Query` prefix.

**`idor.py`** — Collects IDs from authenticated output directory, subtracts guest-known IDs, probes remainder as guest. Only flags records where `returnValue` contains actual field data, not just `onLoadErrorMessage`.

**`reporter.py`** — `generate(output_dir, target)`. Scans an existing output directory for all known finding file patterns and produces a single self-contained `report.html`. Sections that have no backing data are omitted. No network access, no credentials needed.

Guest vs auth diff is derived automatically within a single output directory:
- Root `graphql_dump_*.json` = unauthenticated autodump artifacts
- `graphql/*.json` = authenticated query sweep artifacts
- The diff section shows which objects are accessible without credentials vs only authenticated

**`exposure.py`** — Cross-surface check: self-reg, REST/SOAP/GraphQL availability, custom controller discovery, security headers, Visualforce enumeration, network config. Each check is isolated and returns a result dict with an `error` key on failure.

## CLI Extension Model

To add a new command:

1. Create or extend a module in `core/modules/`.
2. Add a `cmd_*` handler in `cli.py` following the session/client/module pattern.
3. Register the subparser in `build_parser()` under the correct surface group.
4. Add `_add_common_args(parser)` to pick up `-T`, `--cookie`, `--output`, `--bearer`.
5. Document in `README.md`.

To add a new `rest` subgroup (like `graphql` or `content`):

```python
p_group = rest_sub.add_parser("groupname", help="...")
group_sub = p_group.add_subparsers(dest="groupname_command", required=True)
p_cmd = group_sub.add_parser("subcommand", help="...")
_add_common_args(p_cmd)
p_cmd.set_defaults(func=cmd_handler)
```

## Output Conventions

All output goes under a directory derived from the target URL (e.g. `aura_target.my.site.com_s_sfsites_aura/`). Override with `-o`.

There is no separate guest output directory. Authenticated and unauthenticated runs write to the same path. The caller compares runs by re-running with and without credentials.

File naming:
- Aura dump pages: `{ObjectName}__page{N}.json`
- GraphQL dumps: `graphql_dump_{ObjectName}.json`
- GraphQL query hits: `graphql/{ObjectName}.json`
- Object info: `objectinfo_{ObjectName}.json`
- Module summaries: `{module}_summary.json` or `{module}_hits.json`

## Error Handling Pattern

```python
try:
    resp = client.aura_post(payload)
except Exception:
    logger.exception("context message")
    return None  # or {} or []
```

`logger.exception` appends the full traceback automatically. The `as exc` binding is only needed when the exception value itself is stored (e.g. `result["error"] = str(exc)` in exposure checks).

Never use `logger.debug(f"... {exc}")` inside an except block.

## Salesforce Protocol Notes

**Aura POST format:**
```
POST /s/sfsites/aura
Content-Type: application/x-www-form-urlencoded

message={"actions":[...]}
&aura.context={"mode":"PROD","fwuid":"...","app":"siteforce:communityApp",...}
&aura.token=eyJ...   (or "undefined" for guest)
```

**GraphQL WAF:** Operation names starting with `Dump` are silently filtered — Salesforce returns `totalCount: 0` with `state: SUCCESS`. The fix is to use `Query` as the operation name prefix.

**REST API:** Requires OAuth Bearer token. Community portal sessions (`sid=` cookie) are rejected at the platform level with `"This session is not valid for use with the REST API"`. Bearer tokens come from internal user sessions on `login.salesforce.com`.

**getObjectInfo vs DetailController:** On this target, `aura://RecordUiController/ACTION$getObjectInfo` works. `DetailController` returns empty. Do not switch them.
