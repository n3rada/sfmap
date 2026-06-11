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

Every request requires three values captured from a single authenticated browser request:

| File | CLI flag | Value |
|---|---|---|
| `ctx.json` | `-C` | `aura.context` JSON from the POST body |
| `token.txt` | `-T` | `aura.token` JWT from the POST body |
| `cookies.txt` | `--cookie` | Raw `Cookie:` header |

Capture from DevTools: Network tab, filter by `aura`, click any POST to `/s/sfsites/aura`, copy the request body fields and Cookie header.

When those files are present in the working directory, no flags are needed:

```bash
sfmap target.my.site.com scan
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

## 🚀 Quick Start

Run the full assessment (all modules, then generates the HTML report):

```bash
sfmap target.my.site.com scan
```

Skip specific modules:

```bash
sfmap target.my.site.com scan --skip idor graphql-dump
```

Generate a report from an existing output directory without re-running:

```bash
sfmap report -o salesforce_target.my.site.com_s_sfsites_aura
```

Route traffic through Burp:

```bash
sfmap --proxy target.my.site.com scan
```

---

## 🗺️ Surfaces and Commands

```
sfmap URL aura    objects | dump | record | info | crud | inject | related |
                  follow | idor | apex | controllers | flow | network |
                  bootstrap | views
sfmap URL rest    graphql introspect | query | dump
                  content enum | download | distribution
                  static | apexrest | soql | tooling | chatter
sfmap URL surface exposure
sfmap URL files   download ID
sfmap URL scan    [--skip MODULE ...]
sfmap     report  -o DIR
```

> [!TIP]
> Run any command with `--help` for its options and flags.

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
