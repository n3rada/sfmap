# sfmap

Chart every accessible surface of a Salesforce Experience Cloud deployment: enumerate objects, probe access controls, extract records, and detect misconfigurations — from a session or as a guest.

## 📦 Installation

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

## 🔑 Credentials

Salesforce exposes two surfaces with different credential requirements.

### Aura surface (community portal)

Authenticated requests need a session token and cookie. `ctx.json` (the Aura framework context) is auto-extracted if absent.

| File | CLI flag | Value | Required |
|---|---|---|---|
| `ctx.json` | `-C` | `aura.context` JSON | auto-extracted if missing |
| `token.txt` | `-T` | `aura.token` JWT from the POST body | yes (authenticated) |
| `cookies.txt` | `--cookie` | Raw `Cookie:` header | yes (authenticated) |

Capture `token.txt` and `cookies.txt` from DevTools: Network tab, filter by `aura`, click any POST to `/s/sfsites/aura`, copy the `aura.token` field and the `Cookie:` header.

When credential files are present in the working directory, no flags are needed:

```bash
sfmap target.my.site.com surface exposure
```

> [!TIP]
> Drop a Burp Suite XML export or raw HTTP request as `burp.txt` in the working directory. sfmap parses it automatically and uses it in preference over `cookies.txt` and `token.txt`.

> [!NOTE]
> `aura.token` expiry is session-based, not timestamp-based. A token from an active browser session covers a full assessment. If requests return `Invalid token`, capture a fresh one.

> [!NOTE]
> If no credentials are found, every command runs as an unauthenticated guest automatically.

### REST API surface

`rest soql`, `rest tooling`, and the Bulk API require an OAuth Bearer token from a **full Salesforce license user** (internal org user, not a community member). Community sessions are blocked at the platform level regardless of credentials.

Capture from DevTools on a session logged into `yourdomain.my.salesforce.com` (not the community portal):

```bash
echo "00DAP..." > bearer.txt
sfmap target.my.site.com --bearer @bearer.txt rest soql
```

---

## 🗺️ Surfaces and Commands

```
sfmap URL aura    objects | dump | record | info | crud | inject | related |
                  follow | idor | apex | controllers | flow | network |
                  bootstrap | views
sfmap URL rest    graphql introspect | query | dump
                  content enum | download | distribution
                  static | apexrest | soql | sosl | tooling | chatter
sfmap URL surface exposure
sfmap URL files   download ID
sfmap     report  -o DIR
```

> [!TIP]
> Run any command with `--help` for its options and flags.

---

## 🚀 Assessment Runbook

Replace `TARGET` with your target domain throughout.

**Run each phase twice:**

1. **Authenticated** — with `token.txt`/`cookies.txt` (or `burp.txt`) present. Output lands in `salesforce_<TARGET>/<username>/`.
2. **Guest** — no credential files present. Output lands in `salesforce_<TARGET>/guest/`. The report then shows both tabs side by side.

`ctx.json` is optional: if absent, sfmap auto-extracts the Aura context from the target and saves it for subsequent runs.

Route all traffic through Burp with `--proxy` appended to any command.

### Phase 1: Surface Reconnaissance

```bash
sfmap TARGET surface exposure
sfmap TARGET rest graphql introspect
sfmap TARGET rest static
sfmap TARGET rest apexrest
sfmap TARGET rest chatter
sfmap TARGET aura network
sfmap TARGET aura bootstrap
```

### Phase 2: Object Enumeration

```bash
sfmap TARGET aura objects
```

### Phase 3: Object-Level Enumeration

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

### Phase 4: Post-Dump Enumeration

```bash
sfmap TARGET rest graphql dump
sfmap TARGET aura follow
sfmap TARGET rest content enum
```

### Phase 5: IDOR Probe

```bash
sfmap TARGET aura idor
```

Requires a prior `aura dump` in the same output directory to collect record IDs.

### Phase 6: Content Download (optional)

```bash
sfmap TARGET rest content download
sfmap TARGET rest content distribution
```

### Report

```bash
sfmap report -o salesforce_TARGET_s_sfsites_aura
```

---

## 📂 Output

All output goes to a directory derived from the target URL (override with `-o`):

```
salesforce_{host}_{path}/
  {identity}/
    exposure_summary.json
    crud_probe.json
    injection_findings.json
    idor_findings.json
    apexrest_hits.json
    staticresource_summary.json, staticresource_*.bin
    network_config.json
    flow_hits.json
    {Object}__page{N}.json
    graphql/
    chatter/
    soql/
    tooling/
    downloads/
  report.html
```

---

## 🧩 aura.context

Required for every Aura request. Salesforce pushes framework builds three times a year — re-capture when every request returns `exceptionEvent: true`.

```json
{
  "mode":   "PROD",
  "fwuid":  "a1dKZ0Zr...",
  "app":    "siteforce:communityApp",
  "loaded": { "APPLICATION@markup://siteforce:communityApp": "1652_-1TRj7Ek7" },
  "dn": [], "globals": {}, "uad": true
}
```

---

## ⚠️ Disclaimer

For authorized security assessments, bug bounty programs, and penetration testing engagements only.
