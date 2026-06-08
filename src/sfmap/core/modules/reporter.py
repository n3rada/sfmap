# Built-in imports
import glob
import html
import json
import os
import re
from datetime import datetime

# Third-party imports
from loguru import logger


def _load_json(path: str) -> dict | list | None:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        logger.exception(f"Failed to read {path}")
        return None


def _h(text: str) -> str:
    return html.escape(str(text))


def _css() -> str:
    return """
:root {
  --bg: #f1f5f9;
  --surface: #ffffff;
  --border: #e2e8f0;
  --border-strong: #cbd5e1;
  --text: #0f172a;
  --text-secondary: #475569;
  --text-muted: #94a3b8;
  --header-bg: #0f172a;
  --header-text: #f8fafc;
  --code-bg: #f8fafc;
  --row-hover: #f8fafc;
  --shadow: 0 1px 3px rgba(15,23,42,.06), 0 1px 2px rgba(15,23,42,.04);
  --shadow-md: 0 4px 6px rgba(15,23,42,.07), 0 2px 4px rgba(15,23,42,.05);
  --radius: 10px;
  --radius-sm: 6px;
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif;
  font-size: 14px;
  line-height: 1.6;
  color: var(--text);
  background: var(--bg);
  -webkit-font-smoothing: antialiased;
}

/* ── Header ──────────────────────────────────────────── */
.site-header {
  background: var(--header-bg);
  padding: 0;
  border-bottom: 1px solid rgba(255,255,255,.06);
}
.header-inner {
  max-width: 1280px;
  margin: 0 auto;
  padding: 1.75rem 2rem;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 2rem;
  flex-wrap: wrap;
}
.header-brand { display: flex; flex-direction: column; gap: .25rem; }
.header-tool {
  font-size: .65rem;
  font-weight: 700;
  letter-spacing: .15em;
  text-transform: uppercase;
  color: #64748b;
}
.header-title {
  font-size: 1.35rem;
  font-weight: 700;
  color: var(--header-text);
  letter-spacing: -.01em;
}
.header-meta {
  display: flex;
  gap: 2.5rem;
  flex-wrap: wrap;
  margin-top: .2rem;
}
.meta-item { display: flex; flex-direction: column; gap: .1rem; }
.meta-item span {
  font-size: .65rem;
  font-weight: 600;
  letter-spacing: .1em;
  text-transform: uppercase;
  color: #475569;
}
.meta-item strong, .meta-item code {
  font-size: .8rem;
  color: #cbd5e1;
  font-family: inherit;
  background: none;
  border: none;
  padding: 0;
}
.meta-item code {
  font-family: 'SF Mono', ui-monospace, monospace;
  font-size: .75rem;
}

/* ── Layout ──────────────────────────────────────────── */
.layout {
  max-width: 1280px;
  margin: 0 auto;
  padding: 1.75rem 2rem;
  display: grid;
  grid-template-columns: 210px 1fr;
  gap: 1.5rem;
  align-items: start;
}

/* ── TOC sidebar ─────────────────────────────────────── */
.toc {
  position: sticky;
  top: 1.5rem;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 1rem 1.1rem;
  box-shadow: var(--shadow);
}
.toc-label {
  font-size: .65rem;
  font-weight: 700;
  letter-spacing: .12em;
  text-transform: uppercase;
  color: var(--text-muted);
  margin-bottom: .6rem;
  display: block;
}
.toc ol { list-style: none; counter-reset: toc-n; }
.toc li { counter-increment: toc-n; }
.toc a {
  font-size: .775rem;
  color: var(--text-secondary);
  text-decoration: none;
  display: block;
  padding: .22rem .4rem;
  border-radius: var(--radius-sm);
  line-height: 1.35;
  transition: background .12s, color .12s;
}
.toc a::before {
  content: counter(toc-n) ". ";
  color: var(--text-muted);
  font-size: .7rem;
}
.toc a:hover { background: var(--bg); color: var(--text); }

/* ── Content ─────────────────────────────────────────── */
.content { min-width: 0; }

/* ── Card ────────────────────────────────────────────── */
.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 1.5rem;
  margin-bottom: 1.1rem;
  box-shadow: var(--shadow);
}
.card h2 {
  font-size: .9rem;
  font-weight: 700;
  letter-spacing: -.005em;
  color: var(--text);
  padding-bottom: .75rem;
  margin-bottom: .9rem;
  border-bottom: 1px solid var(--border);
}
.card h3 {
  font-size: .8125rem;
  font-weight: 600;
  color: var(--text);
  margin: 1.1rem 0 .4rem;
}
.card p {
  font-size: .8125rem;
  color: var(--text-secondary);
  margin: .3rem 0;
}

/* ── Tables ──────────────────────────────────────────── */
table {
  width: 100%;
  border-collapse: collapse;
  font-size: .7875rem;
  margin: .6rem 0 .4rem;
}
thead th {
  text-align: left;
  padding: .45rem .75rem;
  font-size: .65rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .08em;
  color: var(--text-muted);
  background: var(--bg);
  border-bottom: 1px solid var(--border-strong);
  white-space: nowrap;
}
tbody td {
  padding: .45rem .75rem;
  border-bottom: 1px solid var(--border);
  vertical-align: top;
  color: var(--text-secondary);
}
tbody tr:last-child td { border-bottom: none; }
tbody tr:hover td { background: var(--row-hover); }
.count { font-weight: 600; color: var(--text); }
.none { color: var(--text-muted); font-style: italic; font-size: .775rem; }

/* ── Code ────────────────────────────────────────────── */
code {
  font-family: 'SF Mono', ui-monospace, 'Cascadia Code', monospace;
  font-size: .78em;
  background: var(--code-bg);
  border: 1px solid var(--border);
  color: #0f172a;
  padding: .1em .35em;
  border-radius: 4px;
  word-break: break-all;
}
pre {
  font-family: 'SF Mono', ui-monospace, monospace;
  font-size: .75rem;
  background: var(--code-bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: .9rem 1rem;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-all;
  margin: .6rem 0;
  color: var(--text);
}

/* ── Lists ───────────────────────────────────────────── */
ul { padding-left: 1.25rem; margin: .4rem 0; }
li { font-size: .8125rem; color: var(--text-secondary); margin: .2rem 0; }
"""


def _card(section_id: str, title: str, body: str) -> str:
    return (
        f'<div class="card" id="{_h(section_id)}">'
        f'<h2>{_h(title)}</h2>'
        f'{body}'
        f'</div>'
    )


# ── Section builders ─────────────────────────────────────────────────────────

def _section_guest_vs_auth(output_dir: str) -> str:
    guest_objects: dict[str, int] = {}
    for path in sorted(glob.glob(os.path.join(output_dir, "graphql_dump_*.json"))):
        obj_name = re.sub(r"^graphql_dump_", "", os.path.basename(path)[:-5])
        data = _load_json(path)
        guest_objects[obj_name] = len(data) if isinstance(data, list) else 0

    auth_objects: dict[str, int] = {}
    graphql_dir = os.path.join(output_dir, "graphql")
    if os.path.isdir(graphql_dir):
        for path in sorted(glob.glob(os.path.join(graphql_dir, "graphql_*.json"))):
            name = os.path.basename(path)
            if name == "graphql_schema.json":
                continue
            obj_name = re.sub(r"^graphql_", "", name[:-5])
            data = _load_json(path)
            if isinstance(data, dict):
                total = (
                    data.get("data", {})
                        .get("uiapi", {})
                        .get("query", {})
                        .get(obj_name, {})
                        .get("totalCount", 0)
                ) or 0
                auth_objects[obj_name] = total

    if not guest_objects and not auth_objects:
        return ""

    auth_set = set(auth_objects)
    auth_only = sorted(set(auth_objects) - set(guest_objects))

    parts: list[str] = []
    parts.append(
        '<p>Root-level <code>graphql_dump_*</code> files are unauthenticated autodump artifacts. '
        '<code>graphql/*.json</code> files are from the authenticated sweep.</p>'
    )

    if guest_objects:
        parts.append(f'<h3>Accessible Without Authentication &mdash; {len(guest_objects)} objects</h3>')
        parts.append('<table><thead><tr><th>Object</th><th>Records Extracted</th><th>Also Authenticated</th></tr></thead><tbody>')
        for obj in sorted(guest_objects, key=lambda x: -guest_objects[x]):
            also = "yes" if obj in auth_set else "no"
            parts.append(
                f'<tr><td><code>{_h(obj)}</code></td>'
                f'<td class="count">{guest_objects[obj]:,}</td>'
                f'<td>{also}</td></tr>'
            )
        parts.append('</tbody></table>')

    if auth_only:
        parts.append(f'<h3>Authenticated-Only Objects &mdash; {len(auth_only)} additional</h3>')
        parts.append('<table><thead><tr><th>Object</th><th>Total Records</th></tr></thead><tbody>')
        for obj in sorted(auth_only, key=lambda x: -auth_objects[x]):
            parts.append(
                f'<tr><td><code>{_h(obj)}</code></td>'
                f'<td class="count">{auth_objects[obj]:,}</td></tr>'
            )
        parts.append('</tbody></table>')

    return _card("guest-auth-diff", "Access Comparison — Unauthenticated vs Authenticated", "\n".join(parts))


def _section_listviews(output_dir: str) -> str:
    path = os.path.join(output_dir, "listviews.json")
    if not os.path.isfile(path):
        return ""
    data = _load_json(path)
    if not data or not isinstance(data, dict):
        return ""
    urls = data.get("accessible_urls", [])
    if not urls:
        return ""

    rows = []
    for url in urls:
        obj = url.rstrip("/").rsplit("/", 2)[-2] if "/recordlist/" in url else ""
        rows.append(f'<tr><td><code>{_h(url)}</code></td><td><code>{_h(obj)}</code></td></tr>')

    body = (
        f'<p>{len(urls)} list view(s) browsable directly in the community UI:</p>'
        '<table><thead><tr><th>URL</th><th>Object</th></tr></thead><tbody>'
        + "\n".join(rows)
        + '</tbody></table>'
    )
    return _card("listviews", "UI List Views — Directly Browsable", body)


def _section_graphql_query(output_dir: str) -> str:
    graphql_dir = os.path.join(output_dir, "graphql")
    if not os.path.isdir(graphql_dir):
        return ""

    hits: list[tuple[str, int]] = []
    for path in sorted(glob.glob(os.path.join(graphql_dir, "graphql_*.json"))):
        name = os.path.basename(path)
        if name == "graphql_schema.json":
            continue
        obj_name = re.sub(r"^graphql_", "", name[:-5])
        data = _load_json(path)
        if not isinstance(data, dict):
            continue
        total = (
            data.get("data", {})
                .get("uiapi", {})
                .get("query", {})
                .get(obj_name, {})
                .get("totalCount", 0)
        ) or 0
        if total > 0:
            hits.append((obj_name, total))

    has_schema = os.path.isfile(os.path.join(graphql_dir, "graphql_schema.json"))

    if not hits and not has_schema:
        return ""

    parts: list[str] = []
    if has_schema:
        parts.append('<p>Introspection schema saved (<code>graphql/graphql_schema.json</code>).</p>')

    if hits:
        parts.append(f'<p>{len(hits)} object(s) returned records via GraphQL <code>uiapi</code>:</p>')
        parts.append('<table><thead><tr><th>Object</th><th>Total Records</th></tr></thead><tbody>')
        for obj, count in sorted(hits, key=lambda x: -x[1]):
            parts.append(f'<tr><td><code>{_h(obj)}</code></td><td class="count">{count:,}</td></tr>')
        parts.append('</tbody></table>')
    else:
        parts.append('<p class="none">No objects returned records in the query sweep.</p>')

    return _card("graphql-query", "GraphQL — Object Query Sweep", "\n".join(parts))


def _section_graphql_dumps(output_dir: str) -> str:
    dumps: list[tuple[str, int, list[dict]]] = []
    for path in sorted(glob.glob(os.path.join(output_dir, "graphql_dump_*.json"))):
        obj_name = re.sub(r"^graphql_dump_", "", os.path.basename(path)[:-5])
        data = _load_json(path)
        if isinstance(data, list) and data:
            dumps.append((obj_name, len(data), data[:3]))

    if not dumps:
        return ""

    parts: list[str] = [f'<p>{len(dumps)} object(s) with full field data extracted:</p>']

    for obj_name, count, samples in dumps:
        parts.append(f'<h3><code>{_h(obj_name)}</code> &mdash; {count:,} record(s)</h3>')
        if not samples:
            continue
        all_keys = list(samples[0].keys())
        max_cols = 12
        parts.append('<table><thead><tr>')
        for k in all_keys[:max_cols]:
            parts.append(f'<th>{_h(k)}</th>')
        if len(all_keys) > max_cols:
            parts.append(f'<th>+{len(all_keys) - max_cols}</th>')
        parts.append('</tr></thead><tbody>')
        for rec in samples:
            parts.append('<tr>')
            for k in all_keys[:max_cols]:
                val = rec.get(k, "")
                if isinstance(val, dict):
                    val = val.get("value", val)
                parts.append(f'<td>{_h(str(val) if val is not None else "")}</td>')
            if len(all_keys) > max_cols:
                parts.append('<td class="none">&hellip;</td>')
            parts.append('</tr>')
        parts.append('</tbody></table>')
        if count > 3:
            parts.append(f'<p class="none">{count - 3:,} additional record(s) in file.</p>')

    return _card("graphql-dumps", "GraphQL — Field-Level Dumps", "\n".join(parts))


def _section_aura_dump(output_dir: str) -> str:
    pages: dict[str, int] = {}
    for path in sorted(glob.glob(os.path.join(output_dir, "*__page*.json"))):
        match = re.match(r"^(.+)__page(\d+)\.json$", os.path.basename(path))
        if match:
            obj = match.group(1)
            pages[obj] = pages.get(obj, 0) + 1

    if not pages:
        return ""

    rows = "\n".join(
        f'<tr><td><code>{_h(obj)}</code></td><td>{n}</td></tr>'
        for obj, n in sorted(pages.items())
    )
    body = (
        f'<p>{len(pages)} object(s) with records accessible via Aura <code>getItems</code>:</p>'
        '<table><thead><tr><th>Object</th><th>Pages</th></tr></thead><tbody>'
        + rows + '</tbody></table>'
    )
    return _card("aura-dump", "Aura — Object Dump (getItems)", body)


def _section_idor(output_dir: str) -> str:
    path = os.path.join(output_dir, "idor_findings.json")
    if not os.path.isfile(path):
        return ""
    data = _load_json(path)
    if not data:
        return ""
    findings = data if isinstance(data, list) else data.get("findings", [])
    if not findings:
        return ""

    rows = []
    for f in findings:
        rec_id = _h(f.get("record_id", f.get("id", "")))
        obj = _h(f.get("object_type", f.get("object", f.get("apiName", ""))))
        fields = f.get("fields", {})
        field_count = len(fields) if isinstance(fields, dict) else 0
        rows.append(f'<tr><td><code>{rec_id}</code></td><td><code>{obj}</code></td><td>{field_count}</td></tr>')

    body = (
        f'<p>{len(findings)} record(s) returned field data when queried without authentication:</p>'
        '<table><thead><tr><th>Record ID</th><th>Object Type</th><th>Fields Returned</th></tr></thead><tbody>'
        + "\n".join(rows) + '</tbody></table>'
    )
    return _card("idor", "IDOR — Unauthenticated getRecord Access", body)


def _section_chatter(output_dir: str) -> str:
    path = os.path.join(output_dir, "chatter_summary.json")
    if not os.path.isfile(path):
        return ""
    data = _load_json(path)
    if not data or not isinstance(data, dict):
        return ""

    parts: list[str] = []

    file_upload = data.get("file_upload")
    if file_upload and isinstance(file_upload, dict):
        raw = str(file_upload.get("raw_response", ""))
        if raw:
            parts.append('<h3>File Upload Endpoint Response</h3>')
            parts.append(f'<pre>{_h(raw[:3000])}</pre>')
            ip_match = re.search(
                r'\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b', raw
            )
            if ip_match:
                parts.append(f'<p>IP address in response: <code>{_h(ip_match.group(0))}</code></p>')

    rest_endpoints = data.get("rest_endpoints", [])
    if rest_endpoints:
        parts.append('<h3>REST Endpoints Discovered</h3><ul>')
        for ep in rest_endpoints:
            parts.append(f'<li><code>{_h(str(ep))}</code></li>')
        parts.append('</ul>')

    aura_objects = data.get("aura_objects", [])
    if aura_objects:
        parts.append('<h3>Aura Objects via Chatter</h3><ul>')
        for obj in aura_objects:
            parts.append(f'<li><code>{_h(str(obj))}</code></li>')
        parts.append('</ul>')

    if not parts:
        return ""

    return _card("chatter", "Chatter — REST Endpoint Probe", "\n".join(parts))


def _section_network(output_dir: str) -> str:
    path = os.path.join(output_dir, "network_config.json")
    if not os.path.isfile(path):
        return ""
    data = _load_json(path)
    if not data or not isinstance(data, dict):
        return ""

    interesting = [
        ("Id", "Network ID"),
        ("Name", "Community Name"),
        ("UrlPathPrefix", "URL Path"),
        ("SelfRegistrationEnabled", "Self-Registration Enabled"),
        ("PasswordlessLoginEnabled", "Passwordless Login"),
        ("AllowMembersToFlag", "Allow Member Flagging"),
        ("Status", "Status"),
    ]

    rows = []
    for key, label in interesting:
        # data may be a nested dict from fetch() which stores {Network: [...]}
        if isinstance(data, dict) and "Network" in data:
            records = data["Network"]
            record = records[0] if records else {}
            if isinstance(record, dict) and "fields" in record:
                field = record["fields"].get(key, {})
                val = field.get("value") if isinstance(field, dict) else None
            else:
                val = record.get(key)
        else:
            val = data.get(key)
        if val is not None:
            rows.append(f'<tr><td>{_h(label)}</td><td><code>{_h(str(val))}</code></td></tr>')

    if not rows:
        return ""

    body = (
        '<table><thead><tr><th>Field</th><th>Value</th></tr></thead><tbody>'
        + "\n".join(rows) + '</tbody></table>'
    )
    return _card("network", "Network — Community Configuration", body)


def _section_static(output_dir: str) -> str:
    path = os.path.join(output_dir, "staticresource_summary.json")
    if not os.path.isfile(path):
        return ""
    data = _load_json(path)
    if not data:
        return ""
    resources = data if isinstance(data, list) else data.get("resources", data.get("hits", []))
    if not resources:
        return ""

    rows = []
    for r in resources:
        if isinstance(r, dict):
            name = _h(r.get("name", r.get("Name", "")))
            size = r.get("size", r.get("ContentSize", ""))
            ctype = _h(r.get("content_type", r.get("ContentType", r.get("type", ""))))
        else:
            name, size, ctype = _h(str(r)), "", ""
        rows.append(f'<tr><td><code>{name}</code></td><td>{size}</td><td>{ctype}</td></tr>')

    body = (
        f'<p>{len(resources)} resource(s) downloaded:</p>'
        '<table><thead><tr><th>Name</th><th>Size</th><th>Content Type</th></tr></thead><tbody>'
        + "\n".join(rows) + '</tbody></table>'
    )
    return _card("static", "Static Resources", body)


def _section_crud(output_dir: str) -> str:
    path = os.path.join(output_dir, "crud_findings.json")
    if not os.path.isfile(path):
        return ""
    data = _load_json(path)
    if not data:
        return ""
    findings = data if isinstance(data, list) else data.get("findings", [])
    if not findings:
        return ""

    rows = []
    for f in findings:
        if isinstance(f, dict):
            obj = _h(f.get("object", ""))
            ops = ", ".join(f.get("operations", []))
        else:
            obj, ops = _h(str(f)), ""
        rows.append(f'<tr><td><code>{obj}</code></td><td>{_h(ops)}</td></tr>')

    body = (
        f'<p>{len(findings)} object(s) with unexpected write access:</p>'
        '<table><thead><tr><th>Object</th><th>Operations</th></tr></thead><tbody>'
        + "\n".join(rows) + '</tbody></table>'
    )
    return _card("crud", "CRUD — Write Access Findings", body)


def _section_flow(output_dir: str) -> str:
    path = os.path.join(output_dir, "flow_hits.json")
    if not os.path.isfile(path):
        return ""
    data = _load_json(path)
    if not data:
        return ""
    hits = data if isinstance(data, list) else data.get("hits", [])
    if not hits:
        return ""

    items = "\n".join(f'<li><code>{_h(str(h))}</code></li>' for h in hits)
    body = (
        f'<p>{len(hits)} flow(s) accessible via <code>InterviewController</code>:</p>'
        f'<ul>{items}</ul>'
    )
    return _card("flow", "Flow — Accessible Flow API Names", body)


def _section_apex(output_dir: str) -> str:
    path = os.path.join(output_dir, "apexrest_hits.json")
    if not os.path.isfile(path):
        return ""
    data = _load_json(path)
    if not data:
        return ""
    hits = data if isinstance(data, list) else data.get("hits", [])
    if not hits:
        return ""

    items = "\n".join(f'<li><code>{_h(str(h))}</code></li>' for h in hits)
    body = (
        f'<p>{len(hits)} endpoint(s) found at <code>/services/apexrest/</code>:</p>'
        f'<ul>{items}</ul>'
    )
    return _card("apexrest", "ApexREST — Accessible Endpoints", body)


def _section_exposure(output_dir: str) -> str:
    path = os.path.join(output_dir, "exposure_summary.json")
    if not os.path.isfile(path):
        return ""
    data = _load_json(path)
    if not data or not isinstance(data, dict):
        return ""

    checks = [
        ("self_registration", "Self-Registration"),
        ("rest_api", "REST API"),
        ("soap_api", "SOAP API"),
        ("graphql", "GraphQL Endpoint"),
        ("custom_controllers", "Custom Apex Controllers"),
        ("security_headers", "Security Headers"),
        ("visualforce", "Visualforce Pages"),
        ("network_config", "Network Configuration"),
    ]

    rows = []
    for key, label in checks:
        val = data.get(key)
        if val is None:
            continue
        if isinstance(val, dict):
            parts = [f"{k}: {v}" for k, v in val.items() if v not in (None, "", [], {})]
            summary = "; ".join(parts[:6])
        elif isinstance(val, list):
            summary = f"{len(val)} item(s)" if val else "none found"
        else:
            summary = str(val)
        rows.append(f'<tr><td>{_h(label)}</td><td>{_h(summary[:400])}</td></tr>')

    if not rows:
        return ""

    body = (
        '<table><thead><tr><th>Check</th><th>Result</th></tr></thead><tbody>'
        + "\n".join(rows) + '</tbody></table>'
    )
    return _card("exposure", "Surface — Exposure Checks", body)


# ── Report generator ─────────────────────────────────────────────────────────

def generate(output_dir: str, target: str | None = None) -> str:
    """
    Scan output_dir for finding files and generate a self-contained HTML report.
    Returns the path to the saved report file.
    """
    if target is None:
        target = os.path.basename(os.path.abspath(output_dir))

    date_str = datetime.now().strftime("%Y-%m-%d")

    sections: list[tuple[str, str, str]] = [
        ("guest-auth-diff", "Access: Unauth vs Auth", _section_guest_vs_auth(output_dir)),
        ("listviews",       "UI List Views",          _section_listviews(output_dir)),
        ("graphql-query",   "GraphQL Query Sweep",    _section_graphql_query(output_dir)),
        ("graphql-dumps",   "GraphQL Field Dumps",    _section_graphql_dumps(output_dir)),
        ("aura-dump",       "Aura Object Dump",       _section_aura_dump(output_dir)),
        ("idor",            "IDOR Findings",          _section_idor(output_dir)),
        ("chatter",         "Chatter Probe",          _section_chatter(output_dir)),
        ("network",         "Network Config",         _section_network(output_dir)),
        ("static",          "Static Resources",       _section_static(output_dir)),
        ("crud",            "CRUD Write Access",      _section_crud(output_dir)),
        ("flow",            "Flow Hits",              _section_flow(output_dir)),
        ("apexrest",        "ApexREST Endpoints",     _section_apex(output_dir)),
        ("exposure",        "Exposure Checks",        _section_exposure(output_dir)),
    ]
    active = [(sid, label, body) for sid, label, body in sections if body]

    if not active:
        logger.warning(f"No finding files found in {output_dir}")

    toc_items = "\n".join(
        f'<li><a href="#{_h(sid)}">{_h(label)}</a></li>'
        for sid, label, _ in active
    )
    cards = "\n".join(body for _, _, body in active)

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>sfmap &mdash; {_h(target)}</title>
<style>{_css()}</style>
</head>
<body>

<header class="site-header">
  <div class="header-inner">
    <div class="header-brand">
      <span class="header-tool">sfmap</span>
      <h1 class="header-title">Security Assessment</h1>
    </div>
    <div class="header-meta">
      <div class="meta-item"><span>Target</span><code>{_h(target)}</code></div>
      <div class="meta-item"><span>Date</span><strong>{date_str}</strong></div>
      <div class="meta-item"><span>Sections</span><strong>{len(active)}</strong></div>
    </div>
  </div>
</header>

<div class="layout">
  <nav class="toc">
    <span class="toc-label">Contents</span>
    <ol>{toc_items}</ol>
  </nav>
  <main class="content">
    {cards}
  </main>
</div>

</body>
</html>"""

    report_path = os.path.join(output_dir, "report.html")
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write(html_content)

    logger.success(f"HTML report saved → {report_path}")
    return report_path
