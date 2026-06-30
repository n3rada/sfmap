# sfmap

**Salesforce security assessment toolkit.** Covers both Experience Cloud community portals and internal Lightning Experience orgs. Enumerate guest and authenticated attack surfaces, probe IDOR, test CRUD and injection vectors, map REST and Aura endpoints, and generate a self-contained HTML report.

New to Salesforce internals? Read [SALESFORCE_101.md](SALESFORCE_101.md) before starting an assessment.

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

## Surface Detection

Run sfmap against any target with no surface argument and it probes both Aura endpoints, logs what it finds, and saves a `surface_profile.json` to the output directory:

```bash
sfmap TARGET
```

Example output:

```
Experience Cloud: not detected (https://TARGET/s/sfsites/aura)
Lightning: detected at https://TARGET/aura
Lightning: app=one:one fwuid=...
Lightning: always authenticated, no guest access
Lightning: run sfmap TARGET lightning assess
```

The profile is used by `assess` to route automatically, no surface argument needed on subsequent runs:

```bash
sfmap TARGET assess
# reads surface_profile.json, routes to lightning assess if Lightning-only
```

If you already know the surface, skip detection and run any command directly. The profile is written on first use:

```bash
sfmap TARGET lightning controllers   # writes surface_profile.json: ["lightning"]
sfmap TARGET aura objects            # writes surface_profile.json: ["experience_cloud"]
```

## Surfaces

sfmap covers two distinct Aura surfaces.

### Experience Cloud (`aura` surface)

Public-facing community portals built on `siteforce:communityApp`. Accessible at `/s/sfsites/aura`. Supports both guest (unauthenticated) and authenticated assessment. This is the surface for customer and partner portals.

### Lightning Experience (`lightning` surface)

Internal Salesforce org UI built on `one:one`. Accessible at `/aura` on `my.salesforce.com` or `my.salesforce-setup.com`. Always authenticated, no guest access. This is the surface for internal CRM orgs, integration platforms, and orgs exposing APIs to internal users.

## Credentials

### Experience Cloud

`ctx.json` (the Aura framework context) is auto-extracted if absent.

| File | CLI flag | Value | Required |
|---|---|---|---|
| `ctx.json` | `-C` | `aura.context` JSON | auto-extracted if missing |
| `token.txt` | `-T` | `aura.token` from the POST body | optional |
| `cookies.txt` | `--cookie` | Raw `Cookie:` header | yes (authenticated) |

The session cookie authenticates the session. Without it, every command runs as an unauthenticated guest and output goes to `guest/`.

> [!TIP]
> Drop a Burp Suite XML export or raw HTTP request as `burp.txt` in the working directory. sfmap parses it automatically and uses it in preference over `cookies.txt` and `token.txt`.

> [!NOTE]
> `aura.token` expiry is session-based, not timestamp-based. If requests return `Invalid token`, capture a fresh one.

### Lightning Experience

Lightning has no guest mode. All three files are required.

| File | CLI flag | Value |
|---|---|---|
| `lightning_ctx.json` | `-C` | `aura.context` JSON from a POST to `/aura` |
| `token.txt` | `-T` | `aura.token` from the POST body |
| `cookies.txt` | `--cookie` | Raw `Cookie:` header (`sid=` required) |

Capture from DevTools: Network tab, filter by `/aura`, click any POST, copy the `Cookie:` header and the `aura.context` and `aura.token` fields from the POST body.

> [!TIP]
> Drop a Burp capture of a Lightning POST as `burp.txt`. sfmap parses cookie, token, and context automatically.

### REST API surface

`rest soql`, `rest tooling`, and `rest config` require an OAuth Bearer token from a full Salesforce license user with **API Enabled** in their profile.

| File | CLI flag | Value |
|---|---|---|
| `bearer.txt` | `--bearer` | OAuth Bearer token from `/services/data/` requests |

```bash
sfmap TARGET rest soql
sfmap TARGET rest tooling
sfmap TARGET rest config
```

> [!NOTE]
> The Salesforce `sid` cookie is the OAuth access token for the session. Pass it as `--cookie "sid=VALUE"` and sfmap derives the Bearer token automatically. This works for Chatter but not for SOQL or config review unless the user's profile has API Enabled.

## Surfaces and Commands

```
sfmap URL                 (auto-detect surfaces and print next steps)
sfmap URL detect          (same as above, explicit)

sfmap URL aura    objects | dump | record | info | crud | inject | related |
                  follow | idor | apex | controllers | flow | network |
                  bootstrap | views

sfmap URL lightning   controllers | objects | config | assess

sfmap URL rest    graphql introspect | query | dump
                  content enum | download | distribution
                  static | apexrest | soql | sosl | tooling | chatter | config

sfmap URL surface exposure
sfmap URL files   download ID
sfmap URL assess
sfmap     report  -o DIR
```

> [!TIP]
> Run any command with `--help` for its options and flags.

## Assessment Runbook

### Step 1: Detect

```bash
sfmap TARGET
```

Identifies which surfaces are present and saves `surface_profile.json`. Skip this if you already know the surface.

### Step 2: Assess

```bash
sfmap TARGET assess
```

Routes automatically based on `surface_profile.json`. Runs all applicable phases in sequence, skips completed ones (sentinel files are checked), and generates the HTML report at the end.

For Lightning orgs, place credential files in the working directory first:

```
lightning_ctx.json
cookies.txt
token.txt
bearer.txt   (optional, enables REST phases)
```

Then run:

```bash
sfmap TARGET assess
```

### Experience Cloud: manual phase-by-phase

Run each phase twice: once authenticated (with `cookies.txt` present, output to `users/<username>/`) and once as guest (no credentials, output to `guest/`).

#### Phase 1: Surface Reconnaissance

```bash
sfmap TARGET surface exposure
sfmap TARGET rest graphql introspect
sfmap TARGET rest static
sfmap TARGET rest apexrest
sfmap TARGET rest chatter
sfmap TARGET aura network
sfmap TARGET aura bootstrap
```

#### Phase 2: Object Enumeration

```bash
sfmap TARGET aura objects
```

#### Phase 3: Object-Level Enumeration

```bash
sfmap TARGET aura dump
sfmap TARGET aura crud
sfmap TARGET aura inject
sfmap TARGET aura views
sfmap TARGET rest graphql query
sfmap TARGET rest soql
sfmap TARGET rest sosl
sfmap TARGET aura flow
sfmap TARGET aura controllers
```

#### Phase 4: Post-Dump Enumeration

```bash
sfmap TARGET rest graphql dump
sfmap TARGET aura follow
sfmap TARGET rest content enum
```

#### Phase 5: IDOR Probe

```bash
sfmap TARGET aura idor
```

Requires a prior `aura dump` in the same output directory to collect record IDs.

#### Phase 6: Content Download (optional)

```bash
sfmap TARGET rest content download
sfmap TARGET rest content distribution
```

### Lightning: manual phase-by-phase

```bash
sfmap TARGET lightning controllers   # fuzz aura:// framework controllers
sfmap TARGET lightning objects       # enumerate visible objects via getConfigData
sfmap TARGET lightning config        # configuration review (requires API Enabled or admin bearer)
```

`lightning config` only needs a `sid` cookie. No Aura context or token required:

```bash
sfmap TARGET lightning config --cookie "sid=VALUE"
```

It queries ConnectedApplications, NamedCredentials, RemoteSiteSettings, AuthProviders, Profiles, PermissionSets, active Flows, and SessionSettings (via Tooling API). Flags broad scopes, HTTP endpoints, ModifyAllData/ViewAllData on profiles, and flows running without sharing.

### Report

```bash
sfmap report -o salesforce_TARGET
```

Generates a self-contained `report.html`. Open directly in a browser, no server required.

## Output

```
salesforce_{host}/
  surface_profile.json        ← detected surfaces (written by detect or first command)
  {identity}/
    exposure_summary.json
    crud_probe.json
    injection_findings.json
    idor_findings.json
    apexrest_hits.json
    staticresource_summary.json, staticresource_*.bin
    network_config.json
    flow_hits.json
    lightning_controller_hits.json
    lightning_objects.json
    csp_trusted_sites.json
    {Object}__page{N}.json
    graphql/
    chatter/
    soql/
    tooling/
    config/
    downloads/
  report.html
```

## aura.context

Required for every Aura request. Salesforce pushes framework builds three times a year; re-capture when requests return `exceptionEvent: true`.

Experience Cloud:

```json
{
  "mode":   "PROD",
  "fwuid":  "a1dKZ0Zr...",
  "app":    "siteforce:communityApp",
  "loaded": { "APPLICATION@markup://siteforce:communityApp": "1652_-1TRj7Ek7" },
  "dn": [], "globals": {}, "uad": true
}
```

Lightning Experience:

```json
{
  "mode":   "PROD",
  "fwuid":  "cmpKNld...",
  "app":    "one:one",
  "loaded": { "APPLICATION@markup://one:one": "4146_iERZh3UX..." },
  "dn": [], "globals": { "setupAppContextId": "all" }, "uad": true
}
```

## Prior Art

sfmap was built after working with existing tools and hitting their limits on real engagements.

[aura-inspector](https://github.com/google/aura-inspector) (Mandiant/Google) and [aura-dump](https://github.com/prjblk/aura-dump) (Project Black) both cover Aura object enumeration and record dumping via a single script. They require the caller to supply the full `aura.context` and token manually, operate on one object at a time, stop at a fixed page count, and produce raw JSON with no cross-run correlation. Neither covers REST surfaces (GraphQL, ApexREST, Chatter, SOQL), IDOR probing across sessions, CRUD/injection testing, or report generation.

sfmap was written to run a complete assessment autonomously: auto-extracting the Aura context, paginating all objects to exhaustion, covering every REST surface, correlating findings across guest and authenticated sessions, and producing a structured HTML report suitable for a pentest deliverable.

[Salesforce CLI (sf)](https://github.com/salesforcecli/cli) is the official tool for org inspection when admin credentials are in scope.

## Disclaimer

For authorized security assessments, bug bounty programs, and penetration testing engagements only.
