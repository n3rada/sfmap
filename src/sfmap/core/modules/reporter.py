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
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

:root {
  --white:       #ffffff;
  --bg:          #f5f7fa;
  --border:      #e4e8ef;
  --border-soft: #edf0f5;
  --text:        #0d1117;
  --text-2:      #4b5563;
  --text-3:      #9ca3af;
  --accent:      #2563eb;
  --accent-soft: #eff6ff;
  --code-bg:     #f0f2f5;
  --radius:      12px;
  --radius-sm:   7px;
  --shadow-sm:   0 1px 2px rgba(13,17,23,.04);
  --shadow:      0 2px 8px rgba(13,17,23,.07), 0 1px 2px rgba(13,17,23,.04);
  --font:        'Inter', system-ui, -apple-system, sans-serif;
  --mono:        'JetBrains Mono', 'SF Mono', ui-monospace, monospace;
}

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

html { scroll-behavior: smooth; }

body {
  font-family: var(--font);
  font-size: 13.5px;
  line-height: 1.65;
  color: var(--text);
  background: var(--bg);
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

/* ─── Page header ───────────────────────────────────────── */
.page-header {
  background: var(--white);
  border-bottom: 1px solid var(--border);
}
.page-header-inner {
  max-width: 1240px;
  margin: 0 auto;
  padding: 1.6rem 2rem 1.4rem;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1.5rem;
  flex-wrap: wrap;
}
.header-left { display: flex; flex-direction: column; gap: .35rem; }
.badge-sfmap {
  display: inline-flex;
  align-items: center;
  gap: .35rem;
  font-size: .65rem;
  font-weight: 700;
  letter-spacing: .13em;
  text-transform: uppercase;
  color: var(--accent);
  background: var(--accent-soft);
  padding: .18em .65em;
  border-radius: 99px;
  width: fit-content;
}
.header-title {
  font-size: 1.25rem;
  font-weight: 700;
  color: var(--text);
  letter-spacing: -.025em;
}
.header-right {
  display: flex;
  gap: 2rem;
  flex-wrap: wrap;
  padding-top: .15rem;
}
.meta-block { display: flex; flex-direction: column; gap: .12rem; }
.meta-label {
  font-size: .6rem;
  font-weight: 600;
  letter-spacing: .1em;
  text-transform: uppercase;
  color: var(--text-3);
}
.meta-value {
  font-size: .8rem;
  font-weight: 500;
  color: var(--text-2);
  font-family: var(--mono);
}

/* ─── Layout ─────────────────────────────────────────────── */
.layout {
  max-width: 1240px;
  margin: 0 auto;
  padding: 1.75rem 2rem;
  display: grid;
  grid-template-columns: 200px 1fr;
  gap: 1.5rem;
  align-items: start;
}

/* ─── TOC ────────────────────────────────────────────────── */
.toc {
  position: sticky;
  top: 1.5rem;
  background: var(--white);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 1rem 1.1rem 1.1rem;
  box-shadow: var(--shadow-sm);
}
.toc-heading {
  font-size: .6rem;
  font-weight: 700;
  letter-spacing: .13em;
  text-transform: uppercase;
  color: var(--text-3);
  display: block;
  margin-bottom: .65rem;
  padding-bottom: .55rem;
  border-bottom: 1px solid var(--border-soft);
}
.toc ol { list-style: none; counter-reset: toc; }
.toc li {
  counter-increment: toc;
  display: flex;
  align-items: baseline;
  gap: .4rem;
}
.toc li::before {
  content: counter(toc);
  font-size: .6rem;
  font-weight: 600;
  color: var(--text-3);
  min-width: 14px;
  text-align: right;
  flex-shrink: 0;
}
.toc a {
  font-size: .775rem;
  font-weight: 450;
  color: var(--text-2);
  text-decoration: none;
  display: block;
  padding: .22rem .35rem;
  border-radius: var(--radius-sm);
  line-height: 1.3;
  transition: background .12s, color .12s;
  width: 100%;
}
.toc a:hover { background: var(--bg); color: var(--text); }

/* ─── Cards ──────────────────────────────────────────────── */
.card {
  background: var(--white);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 1.5rem 1.6rem;
  margin-bottom: 1rem;
  box-shadow: var(--shadow-sm);
}
.card-title {
  font-size: .875rem;
  font-weight: 650;
  color: var(--text);
  letter-spacing: -.015em;
  padding-bottom: .8rem;
  margin-bottom: 1rem;
  border-bottom: 1px solid var(--border-soft);
  display: flex;
  align-items: center;
  gap: .55rem;
}
.card-title::before {
  content: '';
  display: inline-block;
  width: 3px;
  height: 1em;
  background: var(--accent);
  border-radius: 2px;
  flex-shrink: 0;
}
.card h3 {
  font-size: .775rem;
  font-weight: 600;
  color: var(--text);
  margin: 1.1rem 0 .45rem;
  letter-spacing: -.01em;
}
.card p {
  font-size: .8rem;
  color: var(--text-2);
  margin: .3rem 0;
  line-height: 1.55;
}
.card ul {
  padding-left: 1.1rem;
  margin: .4rem 0;
}
.card li {
  font-size: .8rem;
  color: var(--text-2);
  margin: .22rem 0;
  line-height: 1.5;
}

/* ─── Tables ─────────────────────────────────────────────── */
.table-wrap { overflow-x: auto; margin: .6rem 0; border-radius: var(--radius-sm); border: 1px solid var(--border); }
table { width: 100%; border-collapse: collapse; font-size: .775rem; }
thead tr { background: var(--bg); }
thead th {
  text-align: left;
  padding: .5rem .85rem;
  font-size: .62rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .09em;
  color: var(--text-3);
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
}
tbody td {
  padding: .5rem .85rem;
  border-bottom: 1px solid var(--border-soft);
  color: var(--text-2);
  vertical-align: top;
}
tbody tr:last-child td { border-bottom: none; }
tbody tr:hover td { background: #fafbfd; }
.num { font-weight: 600; color: var(--text); font-variant-numeric: tabular-nums; }
.muted { color: var(--text-3); font-style: italic; font-size: .75rem; }

/* ─── Code ───────────────────────────────────────────────── */
code {
  font-family: var(--mono);
  font-size: .78em;
  background: var(--code-bg);
  color: var(--text);
  padding: .12em .4em;
  border-radius: 5px;
  font-weight: 500;
  word-break: break-all;
}
pre {
  font-family: var(--mono);
  font-size: .74rem;
  background: var(--code-bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: .9rem 1rem;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-all;
  margin: .65rem 0;
  line-height: 1.6;
  color: var(--text);
}

/* ─── Responsive ─────────────────────────────────────────── */
@media (max-width: 820px) {
  .layout { grid-template-columns: 1fr; }
  .toc { position: static; }
  .page-header-inner { flex-direction: column; gap: 1rem; }
}
"""


def _card(section_id: str, title: str, body: str) -> str:
    return (
        f'<div class="card" id="{_h(section_id)}">'
        f'<div class="card-title">{_h(title)}</div>'
        f'{body}'
        f'</div>'
    )


def _table(headers: list[str], rows: list[list[str]]) -> str:
    ths = "".join(f"<th>{_h(h)}</th>" for h in headers)
    trs = "".join(
        "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>"
        for row in rows
    )
    return f'<div class="table-wrap"><table><thead><tr>{ths}</tr></thead><tbody>{trs}</tbody></table></div>'


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
    parts: list[str] = [
        '<p>Root-level <code>graphql_dump_*</code> artifacts are from the unauthenticated run. '
        '<code>graphql/*.json</code> artifacts are from the authenticated sweep.</p>'
    ]

    if guest_objects:
        rows = [
            [f"<code>{_h(obj)}</code>", f'<span class="num">{guest_objects[obj]:,}</span>', "yes" if obj in auth_set else "no"]
            for obj in sorted(guest_objects, key=lambda x: -guest_objects[x])
        ]
        parts.append(f'<h3>Accessible Without Authentication &mdash; {len(guest_objects)} object(s)</h3>')
        parts.append(_table(["Object", "Records Extracted", "Also Authenticated"], rows))

    if auth_only:
        rows2 = [
            [f"<code>{_h(obj)}</code>", f'<span class="num">{auth_objects[obj]:,}</span>']
            for obj in sorted(auth_only, key=lambda x: -auth_objects[x])
        ]
        parts.append(f'<h3>Authenticated-Only Objects &mdash; {len(auth_only)} additional</h3>')
        parts.append(_table(["Object", "Total Records"], rows2))

    return _card("guest-auth-diff", "Access: Unauthenticated vs Authenticated", "\n".join(parts))


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

    rows = [
        [f"<code>{_h(url)}</code>",
         f"<code>{_h(url.rstrip('/').rsplit('/', 2)[-2])}</code>" if "/recordlist/" in url else ""]
        for url in urls
    ]
    body = f'<p>{len(urls)} list view(s) directly browsable in the community UI.</p>' + _table(["URL", "Object"], rows)
    return _card("listviews", "UI List Views", body)


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
        parts.append('<p>Introspection schema saved &mdash; <code>graphql/graphql_schema.json</code>.</p>')
    if hits:
        rows = [
            [f"<code>{_h(obj)}</code>", f'<span class="num">{count:,}</span>']
            for obj, count in sorted(hits, key=lambda x: -x[1])
        ]
        parts.append(f'<p>{len(hits)} object(s) returned records via GraphQL <code>uiapi</code>:</p>')
        parts.append(_table(["Object", "Total Records"], rows))
    else:
        parts.append('<p class="muted">No objects returned records in the query sweep.</p>')

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

    parts: list[str] = [f'<p>{len(dumps)} object(s) with full field data extracted.</p>']

    for obj_name, count, samples in dumps:
        parts.append(f'<h3><code>{_h(obj_name)}</code> &mdash; {count:,} record(s)</h3>')
        if not samples:
            continue
        all_keys = list(samples[0].keys())
        max_cols = 10
        headers = [k for k in all_keys[:max_cols]]
        if len(all_keys) > max_cols:
            headers.append(f"+{len(all_keys) - max_cols}")
        rows = []
        for rec in samples:
            row = []
            for k in all_keys[:max_cols]:
                val = rec.get(k, "")
                if isinstance(val, dict):
                    val = val.get("value", val)
                row.append(_h(str(val) if val is not None else ""))
            if len(all_keys) > max_cols:
                row.append('<span class="muted">&hellip;</span>')
            rows.append(row)
        parts.append(_table(headers, rows))
        if count > 3:
            parts.append(f'<p class="muted">{count - 3:,} additional record(s) in file.</p>')

    return _card("graphql-dumps", "GraphQL — Field-Level Dumps", "\n".join(parts))


def _section_aura_dump(output_dir: str) -> str:
    pages: dict[str, int] = {}
    for path in sorted(glob.glob(os.path.join(output_dir, "*__page*.json"))):
        m = re.match(r"^(.+)__page(\d+)\.json$", os.path.basename(path))
        if m:
            obj = m.group(1)
            pages[obj] = pages.get(obj, 0) + 1
    if not pages:
        return ""

    rows = [[f"<code>{_h(obj)}</code>", str(n)] for obj, n in sorted(pages.items())]
    body = (
        f'<p>{len(pages)} object(s) with records accessible via Aura <code>getItems</code>.</p>'
        + _table(["Object", "Pages"], rows)
    )
    return _card("aura-dump", "Aura — getItems Dump", body)


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
        rows.append([f"<code>{rec_id}</code>", f"<code>{obj}</code>", str(field_count)])

    body = (
        f'<p>{len(findings)} record(s) returned field data when queried without authentication.</p>'
        + _table(["Record ID", "Object", "Fields"], rows)
    )
    return _card("idor", "IDOR — Unauthenticated getRecord", body)


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
                parts.append(f'<p>IP address disclosed in response: <code>{_h(ip_match.group(0))}</code></p>')

    for key, heading in [("rest_endpoints", "REST Endpoints"), ("aura_objects", "Aura Objects via Chatter")]:
        items = data.get(key, [])
        if items:
            lis = "".join(f"<li><code>{_h(str(i))}</code></li>" for i in items)
            parts.append(f'<h3>{heading}</h3><ul>{lis}</ul>')

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

    # data may be {Network: [records]} or a flat record
    if "Network" in data:
        records = data["Network"]
        record = records[0] if records else {}
        if isinstance(record, dict) and "fields" in record:
            get = lambda k: (record["fields"].get(k) or {}).get("value")
        else:
            get = lambda k: record.get(k)
    else:
        get = lambda k: data.get(k)

    interesting = [
        ("Id", "Network ID"), ("Name", "Community Name"), ("UrlPathPrefix", "URL Path"),
        ("SelfRegistrationEnabled", "Self-Registration"), ("PasswordlessLoginEnabled", "Passwordless Login"),
        ("AllowMembersToFlag", "Allow Flagging"), ("Status", "Status"),
    ]
    rows = []
    for key, label in interesting:
        val = get(key)
        if val is not None:
            rows.append([label, f"<code>{_h(str(val))}</code>"])

    if not rows:
        return ""
    return _card("network", "Network — Community Configuration", _table(["Field", "Value"], rows))


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
            size = str(r.get("size", r.get("ContentSize", "")))
            ctype = _h(r.get("content_type", r.get("ContentType", r.get("type", ""))))
        else:
            name, size, ctype = _h(str(r)), "", ""
        rows.append([f"<code>{name}</code>", size, ctype])

    body = f'<p>{len(resources)} resource(s) enumerated and downloaded.</p>' + _table(["Name", "Size", "Content Type"], rows)
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
            rows.append([f"<code>{_h(f.get('object', ''))}</code>", _h(", ".join(f.get("operations", [])))])
        else:
            rows.append([f"<code>{_h(str(f))}</code>", ""])

    body = f'<p>{len(findings)} object(s) with unexpected write access.</p>' + _table(["Object", "Operations"], rows)
    return _card("crud", "CRUD — Write Access", body)


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
    lis = "".join(f"<li><code>{_h(str(h))}</code></li>" for h in hits)
    body = f'<p>{len(hits)} flow(s) accessible via <code>InterviewController</code>.</p><ul>{lis}</ul>'
    return _card("flow", "Flow API Names", body)


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
    lis = "".join(f"<li><code>{_h(str(h))}</code></li>" for h in hits)
    body = f'<p>{len(hits)} endpoint(s) at <code>/services/apexrest/</code>.</p><ul>{lis}</ul>'
    return _card("apexrest", "ApexREST Endpoints", body)


def _section_exposure(output_dir: str) -> str:
    path = os.path.join(output_dir, "exposure_summary.json")
    if not os.path.isfile(path):
        return ""
    data = _load_json(path)
    if not data or not isinstance(data, dict):
        return ""

    checks = [
        ("self_registration", "Self-Registration"), ("rest_api", "REST API"),
        ("soap_api", "SOAP API"), ("graphql", "GraphQL Endpoint"),
        ("custom_controllers", "Custom Apex Controllers"), ("security_headers", "Security Headers"),
        ("visualforce", "Visualforce Pages"), ("network_config", "Network Configuration"),
    ]
    rows = []
    for key, label in checks:
        val = data.get(key)
        if val is None:
            continue
        if isinstance(val, dict):
            summary = "; ".join(f"{k}: {v}" for k, v in val.items() if v not in (None, "", [], {}))[:400]
        elif isinstance(val, list):
            summary = f"{len(val)} item(s)" if val else "none found"
        else:
            summary = str(val)[:400]
        rows.append([label, _h(summary)])

    if not rows:
        return ""
    return _card("exposure", "Surface Exposure Checks", _table(["Check", "Result"], rows))


# ── Report generator ─────────────────────────────────────────────────────────

def generate(output_dir: str, target: str | None = None) -> str:
    """
    Scan output_dir for finding files and write a self-contained HTML report.
    Returns the path to the saved file.
    """
    if target is None:
        target = os.path.basename(os.path.abspath(output_dir))

    date_str = datetime.now().strftime("%Y-%m-%d")

    sections: list[tuple[str, str, str]] = [
        ("guest-auth-diff", "Unauth vs Auth",         _section_guest_vs_auth(output_dir)),
        ("listviews",       "UI List Views",           _section_listviews(output_dir)),
        ("graphql-query",   "GraphQL Query Sweep",     _section_graphql_query(output_dir)),
        ("graphql-dumps",   "GraphQL Field Dumps",     _section_graphql_dumps(output_dir)),
        ("aura-dump",       "Aura getItems Dump",      _section_aura_dump(output_dir)),
        ("idor",            "IDOR",                    _section_idor(output_dir)),
        ("chatter",         "Chatter Probe",           _section_chatter(output_dir)),
        ("network",         "Network Config",          _section_network(output_dir)),
        ("static",          "Static Resources",        _section_static(output_dir)),
        ("crud",            "CRUD Write Access",       _section_crud(output_dir)),
        ("flow",            "Flow API Names",          _section_flow(output_dir)),
        ("apexrest",        "ApexREST Endpoints",      _section_apex(output_dir)),
        ("exposure",        "Exposure Checks",         _section_exposure(output_dir)),
    ]
    active = [(sid, label, body) for sid, label, body in sections if body]

    if not active:
        logger.warning(f"No finding files found in {output_dir}")

    toc_items = "\n".join(
        f'<li><a href="#{_h(sid)}">{_h(label)}</a></li>'
        for sid, label, _ in active
    )
    cards = "\n".join(body for _, _, body in active)

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>sfmap &mdash; {_h(target)}</title>
<style>{_css()}</style>
</head>
<body>

<header class="page-header">
  <div class="page-header-inner">
    <div class="header-left">
      <span class="badge-sfmap">sfmap</span>
      <h1 class="header-title">Security Assessment Report</h1>
    </div>
    <div class="header-right">
      <div class="meta-block">
        <span class="meta-label">Target</span>
        <span class="meta-value">{_h(target)}</span>
      </div>
      <div class="meta-block">
        <span class="meta-label">Date</span>
        <span class="meta-value">{date_str}</span>
      </div>
      <div class="meta-block">
        <span class="meta-label">Sections</span>
        <span class="meta-value">{len(active)}</span>
      </div>
    </div>
  </div>
</header>

<div class="layout">
  <nav class="toc">
    <span class="toc-heading">Contents</span>
    <ol>{toc_items}</ol>
  </nav>
  <main>
{cards}
  </main>
</div>

</body>
</html>"""

    report_path = os.path.join(output_dir, "report.html")
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write(page)

    logger.success(f"HTML report saved → {report_path}")
    return report_path
