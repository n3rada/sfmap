# sfmap

Salesforce surface-centric security assessment toolkit.

## Installation

```bash
uv tool install git+https://github.com/n3rada/sfmap.git
```

To upgrade later:

```bash
uv tool upgrade sfmap
```

Or run without installing:

```bash
uvx --from git+https://github.com/n3rada/sfmap.git sfmap --help
```

## Usage

`URL` and `CONTEXT` are positional arguments that come before the surface group and action.

Most authenticated subcommands use `-T` (the `aura.token`) and optionally `--cookie`.
Guest scanning intentionally runs unauthenticated.

The context can be a raw JSON string or a file reference using `@`. The URL accepts a bare domain or any base URL; `/s/sfsites/aura` is appended automatically when not present:

```bash
sfmap target.my.site.com @ctx.json <surface> <action> -T "eyJ" --cookie "sid=; "
```

## Surface-centric command model

sfmap groups actions by Salesforce surface:

- Aura: `aura list-objects`, `aura dump`, `aura dump-all`, `aura record`, `aura apex-fuzz`
- Guest Aura: `guest aura`
- REST: `rest content-enum`
- Cross-surface mapping: `surface exposure`
- Files: `files download`

### What is `aura.context` and why is it required?

The Salesforce Aura framework authenticates every POST request not only by session cookie but also by a versioned context descriptor. The server uses this descriptor to confirm that the client is talking to the right application and that the client's cached component versions match the server's current build. **Without a valid context the server will refuse the request entirely**, returning an `exceptionEvent` or a redirect asking the browser to reload.

The `aura.context` field is an internal Aura wire-format object. Salesforce does not document it publicly. Its structure is stable across all Experience Cloud deployments:

```json
{
  "mode":   "PROD",
  "fwuid":  "a1dKZ0Zr",
  "app":    "siteforce:communityApp",
  "loaded": {
    "APPLICATION@markup://siteforce:communityApp": "1642_QTDmpl7q",
    "COMPONENT@markup://forceCommunity:recordDetail": "1540_r4ziamdX"
  },
  "dn":      [],
  "globals": {},
  "uad":     true
}
```

| Field | Purpose | Required |
|---|---|---|
| `mode` | Framework execution mode. Always `PROD` on live deployments, `DEV` on scratch orgs. | Yes |
| `fwuid` | Framework UID. A base64-encoded hash of the Aura framework bundle currently served by the org. The server rejects any request where this value does not match its own build. | Yes |
| `app` | Aura application descriptor. Always `siteforce:communityApp` for Experience Cloud portals. | Yes |
| `loaded` | Map of component and application descriptors to their build hashes. The server checks these against its own build. | Yes |
| `dn` | Dynamic namespaces. Always empty in requests. | No |
| `globals` | Client-side global overrides. Always empty in requests. | No |
| `uad` | User-agent detection flag. Typically `true`. | No |

`fwuid` and the `loaded` hashes are deployment-specific and change every time Salesforce pushes a new release (three times per year). A context captured today may stop working after the next release window.

### How to capture `aura.context` and `aura.token`

Open the target Community portal in a browser, open DevTools **Network** tab, filter by `aura`, and trigger any page action. Click on a POST to `/s/sfsites/aura` and inspect its request body:

```
Request Body (form-encoded):
  message={"actions":[]}
  aura.context={"mode":"PROD","fwuid":"","app":"siteforce:communityApp",}
  aura.token=eyJub25jZSI6
```

1. Copy the `aura.context` value and save it to `ctx.json`
2. Copy the `aura.token` value (pass it with `-T`)
3. Copy the full `Cookie` header (pass it with `--cookie`)

**Token lifetime**: `aura.token` is an HMAC-signed JWT. It contains an `iat` claim but `exp: 0`, so the server enforces session-based expiry rather than a hard timestamp. A token from an active browser session covers a full assessment. If requests return `Invalid token`, grab a fresh one from the browser.

**Context staleness**: if the server returns `exceptionEvent: true` on every request, the context is stale. Reload the portal page and re-capture.

Route traffic through Burp Suite (defaults to `http://127.0.0.1:8080`):

```bash
sfmap --proxy target.my.site.com @ctx.json <surface> <action> -T "eyJ"
```

Custom proxy:

```bash
sfmap --proxy http://192.168.1.10:8080 target.my.site.com @ctx.json <surface> <action> -T "eyJ"
```


## Commands by category

### Aura

#### `aura list-objects`

Enumerate all objects visible to the current session via `getConfigData`.

```bash
sfmap target.my.site.com @ctx.json aura list-objects -T "eyJ"
```


#### `aura dump`

Dump records for one or more named objects. First page only by default; use `-f` for all pages.

```bash
# Single object
sfmap target.my.site.com @ctx.json aura dump User -T "eyJ" --cookie "sid="

# Multiple objects, all pages, print to stdout
sfmap target.my.site.com @ctx.json aura dump User Account Contact -f --display \
  -T "eyJ" --cookie "sid="
```


#### `aura dump-all`

Dump every visible object to files. Filter by type with `--type`.

```bash
# Custom objects only (__c), all pages
sfmap target.my.site.com @ctx.json aura dump-all --type custom -f -T "eyJ" --cookie "sid="

# Everything
sfmap target.my.site.com @ctx.json aura dump-all -T "eyJ" --cookie "sid="
```

Output is written to a directory derived from the URL (override with `-o`).


#### `aura record`

Dump a single record by its Salesforce ID.

```bash
sfmap target.my.site.com @ctx.json aura record 0015g00000XyZaAAA -T "eyJ" --cookie "sid="
```


#### `aura apex-fuzz`

Wordlist-fuzz `ApexController` `ACTION$` methods. Tests each controller name from the wordlist and reports those that respond without an Aura exception.

```bash
sfmap target.my.site.com @ctx.json aura apex-fuzz -w wordlists/apex_controllers.txt -T "eyJ"

# Custom method name
sfmap target.my.site.com @ctx.json aura apex-fuzz -w wordlists/apex_controllers.txt --method getData -T "eyJ"
```


### Guest

#### `guest aura`

Guest visibility scan: enumerate objects, then probe each one without any authentication (`token=undefined`, no cookies). Any object returning data is written to the guest output directory so you can review exactly what is exposed.

```bash
sfmap target.my.site.com @ctx.json guest aura
```

Exits with code `1` if any guest-accessible objects are found, `0` otherwise, usable in CI/pipelines.

For deeper checks, run dedicated surfaces such as `rest content-enum` and `surface exposure` explicitly.


### REST

#### `rest content-enum`

Enumerate `ContentDocument` and `ContentVersion` records, then probe unauthenticated REST access to file content (`VersionData`).

```bash
sfmap target.my.site.com @ctx.json rest content-enum -T "eyJ" --cookie "sid="
```

Returns exit code `1` when critical unauthenticated file access is detected.


### Cross-surface

#### `surface exposure`

Run broad Salesforce surface checks in one command (self-registration, REST, SOAP, GraphQL, and custom controller discovery).

```bash
sfmap target.my.site.com @ctx.json surface exposure -T "eyJ" --cookie "sid="
```

Writes `exposure_summary.json` in the selected output directory.


### Files

#### `files download`

Download a Salesforce file by its `ContentDocument` (prefix `069`) or `ContentVersion` (prefix `068`) ID. Uses the servlet shepherd endpoint, not the Aura API — a session cookie is required.

```bash
sfmap target.my.site.com @ctx.json files download 069XXXXXXXXXXXXXXX \
  -T "eyJ" --cookie "sid="
```

The filename is taken from the `Content-Disposition` response header. Output goes to the same directory as other results (override with `-o`).

## Salesforce documentation

- [Lightning Aura Components Developer Guide](https://developer.salesforce.com/docs/atlas.en-us.lightning.meta/lightning/) — official reference for the Aura framework, component model, and wire protocol
- [Experience Cloud Developer Guide](https://developer.salesforce.com/docs/atlas.en-us.communities_dev.meta/communities_dev/) — building and securing Experience Cloud (Community) portals
- [Salesforce Security Guide](https://developer.salesforce.com/docs/atlas.en-us.securityImplGuide.meta/securityImplGuide/) — org-level security controls, sharing rules, guest user settings
- [Guest User Security Best Practices](https://help.salesforce.com/s/articleView?id=sf.networks_guest_user_license_overview.htm&type=5) — guest user profile permissions, OWD settings for public portals
- [ContentDocument / ContentVersion object reference](https://developer.salesforce.com/docs/atlas.en-us.object_reference.meta/object_reference/sforce_api_objects_contentdocument.htm) — file storage objects queried by the `files download` subcommand

## Disclaimer

sfmap is intended for use in legal penetration testing, bug bounty programmes, or other authorized security assessments only.

Any use against systems without explicit written permission from the owner is strictly prohibited. The authors are not responsible for any misuse or damage caused.
