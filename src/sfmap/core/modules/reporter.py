# Built-in imports
import glob
import html
import json
import os
import re
from datetime import datetime
from pathlib import Path

# Third-party imports
from loguru import logger

_ASSETS_DIR = Path(__file__).parent.parent.parent / "report_assets"


def _load_json(path: str) -> dict | list | None:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        logger.exception(f"Failed to read {path}")
        return None


def _h(text: str) -> str:
    return html.escape(str(text))


def _minify_css(css: str) -> str:
    css = re.sub(r'/\*.*?\*/', '', css, flags=re.DOTALL)
    css = re.sub(r'[ \t]+', ' ', css)
    css = re.sub(r'\s*([{};,>~+])\s*', r'\1', css)
    css = re.sub(r'\s*:\s*', ':', css)
    css = re.sub(r'\n+', '\n', css)
    return css.strip()


def _minify_js(js: str) -> str:
    js = re.sub(r'//[^\n]*', '', js)
    js = re.sub(r'/\*.*?\*/', '', js, flags=re.DOTALL)
    js = re.sub(r'[ \t]+', ' ', js)
    js = re.sub(r'\n\s*\n+', '\n', js)
    return js.strip()


def _load_css() -> str:
    try:
        return _minify_css((_ASSETS_DIR / "style.css").read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Failed to load report CSS asset")
        return ""


def _load_js() -> str:
    try:
        return _minify_js((_ASSETS_DIR / "app.js").read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Failed to load report JS asset")
        return ""


def _detect_identities(output_dir: str) -> list[tuple[str, bool]]:
    current = Path(output_dir)
    parent = current.parent
    if not parent.is_dir():
        return []
    result = []
    for d in sorted(parent.iterdir()):
        if not d.is_dir():
            continue
        is_current = d.name == current.name
        if is_current or (d / "report.html").exists():
            result.append((d.name, is_current))
    return result


def _identity_switcher_html(identities: list[tuple[str, bool]]) -> str:
    if len(identities) <= 1:
        return ""
    pills = ""
    for name, is_current in identities:
        if is_current:
            pills += f'<span class="identity-pill active">{_h(name)}</span>'
        else:
            pills += f'<a class="identity-pill" href="../{_h(name)}/report.html">{_h(name)}</a>'
    return (
        '<div class="identity-switcher">'
        '<span class="switcher-label">Identity</span>'
        f'<div class="switcher-pills">{pills}</div>'
        '</div>'
    )


def _card(section_id: str, title: str, body: str) -> str:
    return (
        f'<div class="card collapsible" id="{_h(section_id)}">'
        f'<div class="card-title">{_h(title)}'
        f'<span class="card-toggle" aria-hidden="true"></span>'
        f'</div>'
        f'<div class="card-body">{body}</div>'
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
        parts.append(f'<h3>Accessible Without Authentication ({len(guest_objects)} object(s))</h3>')
        parts.append(_table(["Object", "Records Extracted", "Also Authenticated"], rows))

    if auth_only:
        rows2 = [
            [f"<code>{_h(obj)}</code>", f'<span class="num">{auth_objects[obj]:,}</span>']
            for obj in sorted(auth_only, key=lambda x: -auth_objects[x])
        ]
        parts.append(f'<h3>Authenticated-Only Objects ({len(auth_only)} additional)</h3>')
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
        parts.append('<p>Introspection schema saved: <code>graphql/graphql_schema.json</code>.</p>')
    if hits:
        rows = [
            [f"<code>{_h(obj)}</code>", f'<span class="num">{count:,}</span>']
            for obj, count in sorted(hits, key=lambda x: -x[1])
        ]
        parts.append(f'<p>{len(hits)} object(s) returned records via GraphQL <code>uiapi</code>:</p>')
        parts.append(_table(["Object", "Total Records"], rows))
    else:
        parts.append('<p class="muted">No objects returned records in the query sweep.</p>')

    return _card("graphql-query", "GraphQL: Object Query Sweep", "\n".join(parts))


def _section_graphql_dumps(output_dir: str) -> str:
    dumps: list[tuple[str, int, list[dict]]] = []
    for path in sorted(glob.glob(os.path.join(output_dir, "graphql_dump_*.json"))):
        obj_name = re.sub(r"^graphql_dump_", "", os.path.basename(path)[:-5])
        data = _load_json(path)
        if isinstance(data, list) and data:
            dumps.append((obj_name, len(data), data[:5]))

    if not dumps:
        return ""

    parts: list[str] = [f'<p>{len(dumps)} object(s) with full field data extracted.</p>']

    for obj_name, count, samples in dumps:
        parts.append(f'<h3><code>{_h(obj_name)}</code> ({count:,} record(s))</h3>')
        if not samples:
            continue
        all_keys = list(samples[0].keys())
        max_cols = 12
        headers = list(all_keys[:max_cols])
        if len(all_keys) > max_cols:
            headers.append(f"+{len(all_keys) - max_cols} more")
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
        if count > 5:
            parts.append(f'<p class="muted">{count - 5:,} additional record(s) in file.</p>')

    return _card("graphql-dumps", "GraphQL: Field-Level Dumps", "\n".join(parts))


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
    return _card("aura-dump", "Aura: getItems Dump", body)


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
    return _card("idor", "IDOR: Unauthenticated getRecord", body)


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
    return _card("chatter", "Chatter: REST Endpoint Probe", "\n".join(parts))


def _section_network(output_dir: str) -> str:
    path = os.path.join(output_dir, "network_config.json")
    if not os.path.isfile(path):
        return ""
    data = _load_json(path)
    if not data or not isinstance(data, dict):
        return ""

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
    return _card("network", "Network: Community Configuration", _table(["Field", "Value"], rows))


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
    return _card("crud", "CRUD: Write Access", body)


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
    identities = _detect_identities(output_dir)
    switcher_html = _identity_switcher_html(identities)

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

    css = _load_css()
    js = _load_js()

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>sfmap: {_h(target)}</title>
<style>{css}</style>
</head>
<body>

<header class="page-header">
  <div class="page-header-inner">
    <div class="header-left">
      <span class="badge-sfmap">sfmap</span>
      <h1 class="header-title">Security Assessment Report</h1>
    </div>
    {switcher_html}
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

<div id="detail-overlay" class="detail-overlay" onclick="closeDetail()"></div>
<div id="detail-panel" class="detail-panel" role="complementary" aria-label="Record detail">
  <div class="detail-header">
    <span>
      <span class="detail-title" id="detail-title">Record Detail</span>
      <span class="detail-hint">Click a value to copy</span>
    </span>
    <button class="detail-close-btn" onclick="closeDetail()" title="Close (Esc)">Close</button>
  </div>
  <div class="detail-body" id="detail-body"></div>
</div>
<div id="copy-toast" class="copy-toast">Copied</div>

<script>{js}</script>
</body>
</html>"""

    report_path = os.path.join(output_dir, "report.html")
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write(page)

    logger.info(f"HTML report saved → {report_path}")
    return report_path
