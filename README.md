# sfmap

Salesforce surface-centric security assessment toolkit targeting Experience Cloud (community portal) deployments.

## Installation

```bash
uv tool install git+https://github.com/n3rada/sfmap.git
```

Upgrade:

```bash
uv tool upgrade sfmap
```

Run without installing:

```bash
uvx --from git+https://github.com/n3rada/sfmap.git sfmap --help
```

---

## Authentication Concepts

Salesforce exposes two distinct access surfaces with different credential requirements.

### Community session (Aura surface)

Experience Cloud portals authenticate through the Aura framework. Every request requires three values:

| Credential | CLI flag | Default file | Description |
|---|---|---|---|
| `aura.context` | `-C` / `--context` | `ctx.json` | Framework version descriptor (JSON) |
| `aura.token` | `-T` / `--token` | `token.txt` | HMAC-signed JWT — Aura CSRF token |
| Cookie header | `--cookie` | `cookies.txt` | Raw `Cookie:` header from an authenticated browser session |

All three are captured from a single browser request. Open DevTools → Network tab → filter by `aura` → click any POST to `/s/sfsites/aura` → inspect the request body and headers.

```
Request body (form-encoded):
  aura.context = {"mode":"PROD","fwuid":"a1dKZ0Zr","app":"siteforce:communityApp","loaded":{...}}
  aura.token   = eyJub25jZSI6...
Request header:
  Cookie: sid=00DAP...; ...
```

Save those three values:

```bash
# save context to ctx.json  (default)
# save token to token.txt   (default)
# save cookie to cookies.txt (default)
```

When the default files are present in the working directory, no flags are needed:

```bash
sfmap target.my.site.com <surface> <action>
```

Pass them explicitly if needed:

```bash
sfmap target.my.site.com -C @/path/ctx.json <surface> <action> \
  -T @/path/token.txt --cookie @/path/cookies.txt
```

**Token lifetime:** `aura.token` uses session-based expiry (not a hard timestamp). A token from an active browser session covers a full assessment. If requests return `Invalid token`, capture a fresh one.

**Context staleness:** if every request returns `exceptionEvent: true`, the context is outdated. Salesforce pushes new framework builds three times a year; reload the portal and re-capture.

### Internal user / OAuth Bearer token (REST API surface)

The Salesforce REST API (`/services/data/`, Tooling API, Bulk API, SOQL query endpoint) requires an OAuth Bearer token. Community sessions are **explicitly blocked** from the REST API regardless of what cookies or Aura tokens are provided — the server returns `"This session is not valid for use with the REST API"`.

An OAuth Bearer token requires a **full Salesforce license user** (internal employee or administrator) with the **API Enabled** permission in their profile. Community/portal users cannot obtain one through the community portal.

To capture one from an authenticated browser session logged into the org (not the community portal):

1. Log in at `https://yourdomain.my.salesforce.com` as an internal user
2. Open DevTools → Network → filter by `/services/data/` → inspect any request
3. Copy the `Authorization: Bearer 00D...` header value

Or from the browser console (Lightning Experience):

```javascript
// Returns the Session ID which doubles as the Bearer token
document.cookie.match(/sid=([^;]+)/)[1]
```

Save to `bearer.txt` (default) or pass via `--bearer`:

```bash
sfmap target.my.site.com --bearer @bearer.txt rest soql-query
```

If `bearer.txt` is present in the working directory, it is picked up automatically. If absent, REST API commands still run but will receive 401 and report access as blocked.

---

## Global Options

```
sfmap [--debug | --trace | --log-level LEVEL] [--proxy [URL]] [-C ctx] URL SURFACE ACTION [options]
```

| Flag | Description |
|---|---|
| `--debug` | Enable debug logging |
| `--trace` | Most verbose logging (raw requests) |
| `--log-level` | Explicit level: TRACE DEBUG INFO WARNING ERROR CRITICAL |
| `--proxy [URL]` | Proxy all traffic. Bare flag defaults to `http://127.0.0.1:8080` (Burp) |
| `-C` / `--context` | `aura.context` as JSON string or `@file`. Default: `@ctx.json` |
| `-o` / `--output` | Output directory. Default: derived from URL |
| `-T` / `--token` | `aura.token` value or `@file`. Default: `@token.txt` |
| `--cookie` | Raw `Cookie:` header or `@file`. Default: `@cookies.txt` |
| `--bearer` | OAuth Bearer token or `@file`. Default: `@bearer.txt` |

Route through Burp:

```bash
sfmap --proxy target.my.site.com aura dump-all
```

---

## Commands

### `aura list-objects`

Enumerate all Salesforce objects visible to the current session via `getConfigData`. Caches the result for use by other commands.

```bash
sfmap target.my.site.com aura list-objects
```

---

### `aura dump OBJECT [OBJECT ...]`

Dump all records for one or more objects. Always performs a full multi-page dump.

```bash
sfmap target.my.site.com aura dump User
sfmap target.my.site.com aura dump User Account Contact --display
sfmap target.my.site.com aura dump Invoice__c --custom-fields
```

`--display` prints records to stdout in addition to writing files.  
`--custom-fields` extracts `__c` field names and appends them to `custom_fields_summary.txt`.

---

### `aura dump-all [--type standard|custom|both]`

Dump every visible object. Default type is `both`.

```bash
sfmap target.my.site.com aura dump-all
sfmap target.my.site.com aura dump-all --type custom --custom-fields
```

---

### `aura record RECORD_ID`

Dump a single record by its Salesforce ID and print it to stdout.

```bash
sfmap target.my.site.com aura record 0015g00000XyZaAAA
```

---

### `aura object-info [OBJECT ...]`

Fetch full field-level metadata for objects via `RecordUiController/ACTION$getObjectInfo`. Returns field names, types, access levels, and labels — including fields not visible in `getItems` dumps.

```bash
# Specific objects
sfmap target.my.site.com aura object-info User Invoice__c

# All visible objects (slow on large orgs)
sfmap target.my.site.com aura object-info
```

Output: `objectinfo_{ObjectName}.json` per object in the output directory.

---

### `aura apex-fuzz [-w wordlist] [--method METHOD]`

Wordlist-fuzz `apex://ControllerName/ACTION$method` descriptors. Reports which Apex controllers respond without an Aura exception.

```bash
sfmap target.my.site.com aura apex-fuzz
sfmap target.my.site.com aura apex-fuzz -w ./custom_controllers.txt --method getData
```

Uses a bundled wordlist of common Salesforce community controllers by default.

---

### `aura crud-probe [--type standard|custom|both]`

Probe CREATE and DELETE access on visible objects. Creates a sentinel record, then immediately attempts to delete it. Reports which objects allow write access. Default type is `custom`.

```bash
sfmap target.my.site.com aura crud-probe
sfmap target.my.site.com aura crud-probe --type both
```

Output: `crud_probe.json`.

---

### `aura soql-inject [--apex-hits DESCRIPTOR ...]`

Test SOQL injection via the `getItems` where-clause parameter and optional Apex method parameters. Compares baseline record counts with injected payloads.

```bash
sfmap target.my.site.com aura soql-inject
sfmap target.my.site.com aura soql-inject --apex-hits "apex://MyCtrl/ACTION$query"
```

Output: `injection_findings.json`.

---

### `aura related-lists RECORD_ID [--object OBJECT_API_NAME]`

Enumerate every child relationship on a record and probe each via `RelatedListContainerDataProviderController/ACTION$getRecords`. This is a distinct data access vector from `getItems` — child records reachable through a relationship may be accessible even when direct enumeration of the child object is denied.

The object API name is resolved automatically from the record via `getRecord`. Pass `--object` to skip that round-trip if the type is already known.

```bash
sfmap target.my.site.com aura related-lists a0cAP000004q1k5YAA
sfmap target.my.site.com aura related-lists a0cAP000004q1k5YAA --object DownloadRequest__c
```

Output: `relatedlists_{RECORD_ID}.json` in the output directory.

---

### `aura flow-fuzz [-w wordlist]`

Wordlist-fuzz Salesforce Flow API names via `InterviewController/ACTION$getFlowUIMetadata`. A successful response reveals the flow's screen and variable definitions — registration flows, password-reset flows, and case-creation flows are high-value targets. Flows that exist but restrict access return a distinct error and are still reported.

```bash
sfmap target.my.site.com aura flow-fuzz
sfmap target.my.site.com aura flow-fuzz -w ./custom_flows.txt
```

Output: `flow_hits.json`.

---

### `aura network-access`

Enumerate Experience Cloud network configuration: `Network`, `NetworkMemberGroup`, `NetworkSelfRegistration`. The `Network` record exposes the community name, URL prefix, and — when accessible — the guest profile ID (the profile controlling all unauthenticated access). `NetworkMemberGroup` shows which profiles can join the community.

```bash
sfmap target.my.site.com aura network-access
```

Output: `network_config.json`.

---

### `aura idor-probe`

Test whether `getRecord` (Aura) returns actual field data for authenticated records when queried as an unauthenticated guest. Collects record IDs from the authenticated output directory, subtracts IDs already known to be guest-accessible, then probes the remainder against a guest session.

A finding is only raised when the `returnValue` contains real field data — not when Salesforce returns a blocked `onLoadErrorMessage`.

```bash
# Requires prior dump-all or dump to populate the output directory
sfmap target.my.site.com aura dump-all
sfmap target.my.site.com aura idor-probe
```

Output: `idor_findings.json`.

---

### `guest aura`

Unauthenticated object visibility scan. Probes every known object via `getItems` without any session credentials and writes any accessible records to `guest/`.

```bash
sfmap target.my.site.com guest aura
```

Uses the cached object list from `aura list-objects` when available. Exits `1` if any guest-readable objects are found.

---

### `rest content-enum`

Enumerate `ContentDocument` and `ContentVersion` records via Aura, then probe each `ContentVersion` ID against the unauthenticated REST endpoint. A HTTP 200 without credentials means the guest profile has **API Enabled** — critical finding.

```bash
sfmap target.my.site.com rest content-enum
```

---

### `rest content-download`

Enumerate all ContentDocument/ContentVersion records and download every file via the `servlet.shepherd` endpoint.

```bash
sfmap target.my.site.com rest content-download
```

Output: metadata JSON in the output directory, binaries in `downloads/`.

---

### `rest content-distribution`

Enumerate `ContentDistribution` records and probe each `DistributionPublicUrl` without authentication. A publicly accessible URL means files are shared with anyone who has the link — no session required.

```bash
sfmap target.my.site.com rest content-distribution
```

---

### `rest graphql-introspect`

Run GraphQL introspection against `aura://RecordUiController/ACTION$executeGraphQL` and the REST GraphQL endpoint. Saves the schema if accessible.

```bash
sfmap target.my.site.com rest graphql-introspect
```

Output: `graphql/graphql_schema.json`.

---

### `rest graphql-query`

Query all known objects via GraphQL `uiapi` and record accessible record counts. Only objects returning data are written to disk.

```bash
sfmap target.my.site.com rest graphql-query
```

Output: `graphql/graphql_{ObjectName}.json` per object with data.

---

### `rest graphql-dump OBJECT --fields FIELD [...]`

Dump all records for a specific object via GraphQL `uiapi`. Fields use dot notation — `Name` becomes `Name { value }`, `Profile.Name` becomes `Profile { Name { value } }`. Paginates automatically.

```bash
sfmap target.my.site.com rest graphql-dump StaticResource --fields Name ContentType
sfmap target.my.site.com rest graphql-dump Knowledge__kav --fields Title Summary PublishStatus UrlName
sfmap target.my.site.com rest graphql-dump User --fields Name Email Profile.Name
```

Output: `graphql_dump_{ObjectName}.json`.

---

### `rest graphql-autodump [OBJECT ...]`

Automatically discover all GraphQL-accessible objects, resolve their scalar fields via `getObjectInfo`, and dump every record. Without arguments, runs a full sweep: enumerate all visible objects, filter to those with accessible records, then dump each with all scalar fields.

```bash
# Full sweep — enumerate, discover fields, dump everything
sfmap target.my.site.com rest graphql-autodump

# Target specific objects
sfmap target.my.site.com rest graphql-autodump User Contact Account
```

Output: `graphql_dump_{ObjectName}.json` per object with records.

---

### `rest chatter`

Enumerate Chatter feed objects (FeedItem, FeedComment, FeedAttachment) and REST Chatter endpoints. Also probes `/chatter/handlers/file/body` with a crafted multipart request — error responses from this endpoint sometimes disclose the internal IP address of the application server.

```bash
sfmap target.my.site.com rest chatter
```

Output: `chatter/chatter_summary.json`.

---

### `rest static-resources [-w wordlist]`

Enumerate and download Salesforce static resources. First attempts to list `StaticResource` records via Aura `getItems` to get actual names. Falls back to wordlist fuzzing if the object is not accessible.

```bash
sfmap target.my.site.com rest static-resources
sfmap target.my.site.com rest static-resources -w ./custom_resources.txt
```

Output: `staticresource_*.bin` (raw downloads) and `staticresource_summary.json` in the output directory. Run trufflehog or similar against the downloads directory for credential detection.

---

### `rest apexrest-fuzz [-w wordlist]`

Wordlist-fuzz `/services/apexrest/{name}` via GET and POST. Any non-404 response indicates the endpoint exists. HTTP 200 without authentication is a critical finding.

```bash
sfmap target.my.site.com rest apexrest-fuzz
sfmap target.my.site.com rest apexrest-fuzz -w ./my_endpoints.txt
```

When `--bearer` is set, the Bearer token is included in the probe requests.

Output: `apexrest_hits.json`.

---

### `rest soql-query`

Run a battery of SOQL probe queries via `/services/data/v59.0/query`. Requires an OAuth Bearer token — community sessions are blocked by Salesforce at the platform level.

```bash
# With a bearer token
sfmap target.my.site.com --bearer @bearer.txt rest soql-query

# Without (will report 401 and exit)
sfmap target.my.site.com rest soql-query
```

Probes: User, Profile, Account, Contact, Lead, Opportunity, Case, ContentDocument, ContentVersion, ApexClass, PermissionSet.

Output: `soql/soql_{ObjectName}.json` per accessible object, `soql/soql_summary.json`.

---

### `rest tooling-query`

Dump Apex source code (classes, triggers, pages, components) via the Salesforce Tooling API. Requires an OAuth Bearer token — community sessions are blocked at the platform level.

```bash
sfmap target.my.site.com --bearer @bearer.txt rest tooling-query
```

Queries: `ApexClass` (Id, Name, Status, Body), `ApexTrigger` (Id, Name, TableEnumOrId, Status, Body), `ApexPage` (Id, Name, Markup), `ApexComponent` (Id, Name, Markup).

Output: `tooling/tooling_{Type}.json` per accessible type.

---

### `surface exposure`

Run all cross-surface checks in one command:

- Self-registration enabled
- REST API version listing
- SOAP API exposure
- GraphQL endpoint status
- Custom Apex controller discovery
- Security headers (CSP, HSTS, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy, CORS)
- Visualforce page enumeration (`/apex/` wordlist)
- Network object configuration (self-registration, allowed extensions, login URL)
- Extra endpoint inventory: OAuth, CometD, Tooling API, Bulk API, Metadata WSDL

```bash
sfmap target.my.site.com surface exposure
```

Output: `exposure_summary.json`.

---

### `files download ID`

Download a single file by `ContentDocument` (prefix `069`) or `ContentVersion` (prefix `068`) ID.

```bash
sfmap target.my.site.com files download 069XXXXXXXXXXXXXXX
```

Output goes to `downloads/` within the output directory.

---

## Output Structure

All output is written to a directory derived from the target URL (override with `-o`):

```
aura_{host}_{path}/
├── config_data.json           # Cached object list
├── exposure_summary.json      # surface exposure results
├── crud_probe.json            # aura crud-probe results
├── injection_findings.json    # aura soql-inject results
├── idor_findings.json         # aura idor-probe results
├── apexrest_hits.json         # rest apexrest-fuzz results
├── staticresource_summary.json  # rest static-resources results
├── staticresource_*.bin       # downloaded static resource files
├── network_config.json        # aura network-access results
├── flow_hits.json             # aura flow-fuzz results
├── objectinfo_{Object}.json   # aura object-info per object
├── {Object}__page{N}.json     # aura dump / dump-all pages
├── chatter/
│   ├── chatter_summary.json
│   └── rest_*.json
├── graphql/
│   ├── graphql_schema.json
│   ├── graphql_{Object}.json
│   └── graphql_dump_{Object}.json
├── guest/
│   └── {Object}__page{N}.json
├── soql/
│   ├── soql_summary.json
│   └── soql_{Object}.json
├── tooling/
│   └── tooling_{Type}.json
└── downloads/
    └── {filename}             # Binary files
```

---

## What sfmap Cannot Automate

The following surfaces require an OAuth Bearer token from an **internal Salesforce user** (full license, API Enabled permission — not obtainable from a community portal session):

| Surface | Endpoint | Why blocked |
|---|---|---|
| REST SOQL | `/services/data/v*/query` | Requires API Enabled permission |
| Tooling API | `/services/data/v*/tooling/` | Requires API Enabled |
| Bulk API | `/services/data/v*/jobs/` | Requires API Enabled |
| Metadata WSDL | `/services/Soap/m/` | Requires Modify Metadata |

An internal user is a Salesforce employee/admin who authenticates directly to the org (`login.salesforce.com`), not via the community portal. Their session ID can be used directly as a Bearer token:

```bash
# Capture from a browser session logged into the org (not the community)
# DevTools → Network → any /services/data/ request → Authorization header
# Or from Lightning Experience console:
#   document.cookie.match(/sid=([^;]+)/)[1]

echo "00DAP00000GTNZh!..." > bearer.txt
sfmap target.my.site.com --bearer @bearer.txt rest soql-query
```

---

## aura.context Reference

The `aura.context` object is required for every Aura request. It authenticates the client's framework version to the server.

```json
{
  "mode":   "PROD",
  "fwuid":  "a1dKZ0Zr...",
  "app":    "siteforce:communityApp",
  "loaded": {
    "APPLICATION@markup://siteforce:communityApp": "1652_-1TRj7Ek7"
  },
  "dn":      [],
  "globals": {},
  "uad":     true
}
```

| Field | Description |
|---|---|
| `mode` | `PROD` on live deployments, `DEV` on scratch orgs |
| `fwuid` | Framework UID — base64 hash of the Aura bundle. Deployment-specific, changes on Salesforce releases (3×/year) |
| `app` | Always `siteforce:communityApp` for Experience Cloud |
| `loaded` | Component descriptor → build hash map. Server validates these |

---

## Disclaimer

sfmap is for authorized security assessments, bug bounty programs, and penetration testing engagements only. Use against systems without explicit written permission is prohibited.
