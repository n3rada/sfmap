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
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: 'Helvetica Neue', Arial, sans-serif;
            font-size: 14px;
            line-height: 1.6;
            color: #111;
            background: #fff;
            max-width: 1100px;
            margin: 0 auto;
            padding: 2.5rem 2rem;
        }
        h1 { font-size: 1.75rem; padding-bottom: .6rem; border-bottom: 2px solid #111; margin-bottom: 1.2rem; }
        h2 { font-size: 1.15rem; font-weight: 700; margin-top: 2.5rem; margin-bottom: .75rem; border-bottom: 1px solid #ccc; padding-bottom: .3rem; }
        h3 { font-size: .95rem; font-weight: 700; margin-top: 1.5rem; margin-bottom: .4rem; color: #333; }
        p { margin: .4rem 0; }
        .meta { color: #555; font-size: .875rem; margin: .2rem 0; }
        .toc {
            background: #f8f8f8;
            border: 1px solid #ddd;
            padding: 1rem 1.5rem;
            margin: 1.8rem 0;
            display: inline-block;
            min-width: 260px;
        }
        .toc strong { display: block; margin-bottom: .5rem; font-size: .95rem; }
        .toc ol { padding-left: 1.3rem; }
        .toc li { margin: .2rem 0; font-size: .875rem; }
        .toc a { color: #111; text-decoration: none; }
        .toc a:hover { text-decoration: underline; }
        table { width: 100%; border-collapse: collapse; margin: .9rem 0 1.2rem; font-size: .875rem; }
        th {
            text-align: left;
            padding: .45rem .75rem;
            border-bottom: 2px solid #111;
            background: #f5f5f5;
            font-weight: 600;
            font-size: .825rem;
            text-transform: uppercase;
            letter-spacing: .03em;
        }
        td { padding: .38rem .75rem; border-bottom: 1px solid #e5e5e5; vertical-align: top; }
        tr:last-child td { border-bottom: none; }
        code {
            font-family: 'SF Mono', Consolas, 'Liberation Mono', monospace;
            background: #f0f0f0;
            padding: .1em .3em;
            border-radius: 3px;
            font-size: .82em;
            word-break: break-all;
        }
        pre {
            background: #f5f5f5;
            border: 1px solid #e0e0e0;
            padding: .75rem 1rem;
            overflow-x: auto;
            font-size: .78rem;
            font-family: 'SF Mono', Consolas, monospace;
            margin: .75rem 0;
            white-space: pre-wrap;
            word-break: break-all;
        }
        .none { color: #888; font-style: italic; font-size: .875rem; }
        .count { font-weight: 600; }
        section { margin-bottom: 1rem; }
        ul { padding-left: 1.5rem; margin: .5rem 0; }
        li { margin: .2rem 0; font-size: .875rem; }
    """


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

    out = ['<section id="graphql-query">', '<h2>GraphQL — Object Query Sweep</h2>']

    if has_schema:
        out.append('<p>Introspection schema saved (<code>graphql/graphql_schema.json</code>).</p>')

    if not hits:
        out.append('<p class="none">No objects returned records in the query sweep.</p>')
    else:
        out.append(f'<p>{len(hits)} object(s) returned records via GraphQL <code>uiapi</code>:</p>')
        out.append('<table><thead><tr><th>Object</th><th>Total Records</th></tr></thead><tbody>')
        for obj, count in sorted(hits, key=lambda x: -x[1]):
            out.append(f'<tr><td><code>{_h(obj)}</code></td><td class="count">{count:,}</td></tr>')
        out.append('</tbody></table>')

    out.append('</section>')
    return "\n".join(out)


def _section_graphql_dumps(output_dir: str) -> str:
    dumps: list[tuple[str, int, list[dict]]] = []
    for path in sorted(glob.glob(os.path.join(output_dir, "graphql_dump_*.json"))):
        obj_name = re.sub(r"^graphql_dump_", "", os.path.basename(path)[:-5])
        data = _load_json(path)
        if isinstance(data, list) and data:
            dumps.append((obj_name, len(data), data[:3]))

    if not dumps:
        return ""

    out = ['<section id="graphql-dumps">',
           '<h2>GraphQL — Field-Level Dumps</h2>',
           f'<p>{len(dumps)} object(s) with full field data extracted:</p>']

    for obj_name, count, samples in dumps:
        out.append(f'<h3><code>{_h(obj_name)}</code> &mdash; {count:,} record(s)</h3>')
        if not samples:
            continue
        all_keys = list(samples[0].keys())
        max_cols = 12
        out.append('<table><thead><tr>')
        for k in all_keys[:max_cols]:
            out.append(f'<th>{_h(k)}</th>')
        if len(all_keys) > max_cols:
            out.append(f'<th>+{len(all_keys) - max_cols} more</th>')
        out.append('</tr></thead><tbody>')
        for rec in samples:
            out.append('<tr>')
            for k in all_keys[:max_cols]:
                val = rec.get(k, "")
                if isinstance(val, dict):
                    val = val.get("value", val)
                out.append(f'<td>{_h(str(val) if val is not None else "")}</td>')
            if len(all_keys) > max_cols:
                out.append('<td class="none">…</td>')
            out.append('</tr>')
        out.append('</tbody></table>')
        if count > 3:
            out.append(f'<p class="none">{count - 3:,} additional record(s) in file.</p>')

    out.append('</section>')
    return "\n".join(out)


def _section_aura_dump(output_dir: str) -> str:
    pages: dict[str, int] = {}
    for path in sorted(glob.glob(os.path.join(output_dir, "*__page*.json"))):
        match = re.match(r"^(.+)__page(\d+)\.json$", os.path.basename(path))
        if match:
            obj = match.group(1)
            pages[obj] = pages.get(obj, 0) + 1

    if not pages:
        return ""

    out = ['<section id="aura-dump">',
           '<h2>Aura — Object Dump (getItems)</h2>',
           f'<p>{len(pages)} object(s) with accessible records via Aura <code>getItems</code>:</p>',
           '<table><thead><tr><th>Object</th><th>Pages</th></tr></thead><tbody>']

    for obj, page_count in sorted(pages.items()):
        out.append(f'<tr><td><code>{_h(obj)}</code></td><td>{page_count}</td></tr>')

    out.append('</tbody></table></section>')
    return "\n".join(out)


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

    out = ['<section id="idor">',
           '<h2>IDOR — Unauthenticated getRecord Access</h2>',
           f'<p>{len(findings)} record(s) returned field data when queried without authentication:</p>',
           '<table><thead><tr><th>Record ID</th><th>Object Type</th><th>Fields Returned</th></tr></thead><tbody>']

    for f in findings:
        rec_id = _h(f.get("record_id", f.get("id", "")))
        obj = _h(f.get("object_type", f.get("object", f.get("apiName", ""))))
        fields = f.get("fields", {})
        field_count = len(fields) if isinstance(fields, dict) else 0
        out.append(f'<tr><td><code>{rec_id}</code></td><td><code>{obj}</code></td><td>{field_count}</td></tr>')

    out.append('</tbody></table></section>')
    return "\n".join(out)


def _section_chatter(output_dir: str) -> str:
    path = os.path.join(output_dir, "chatter_summary.json")
    if not os.path.isfile(path):
        return ""
    data = _load_json(path)
    if not data or not isinstance(data, dict):
        return ""

    out = ['<section id="chatter">', '<h2>Chatter — REST Endpoint Probe</h2>']
    has_content = False

    file_upload = data.get("file_upload")
    if file_upload and isinstance(file_upload, dict):
        raw = str(file_upload.get("raw_response", ""))
        if raw:
            has_content = True
            out.append('<h3>File Upload Endpoint Response</h3>')
            out.append(f'<pre>{_h(raw[:3000])}</pre>')
            ip_match = re.search(r'\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b', raw)
            if ip_match:
                out.append(f'<p>IP address in response: <code>{_h(ip_match.group(0))}</code></p>')

    rest_endpoints = data.get("rest_endpoints", [])
    if rest_endpoints:
        has_content = True
        out.append('<h3>REST Endpoints Discovered</h3><ul>')
        for ep in rest_endpoints:
            out.append(f'<li><code>{_h(str(ep))}</code></li>')
        out.append('</ul>')

    aura_objects = data.get("aura_objects", [])
    if aura_objects:
        has_content = True
        out.append('<h3>Aura Objects via Chatter</h3><ul>')
        for obj in aura_objects:
            out.append(f'<li><code>{_h(str(obj))}</code></li>')
        out.append('</ul>')

    if not has_content:
        return ""

    out.append('</section>')
    return "\n".join(out)


def _section_network(output_dir: str) -> str:
    path = os.path.join(output_dir, "network_config.json")
    if not os.path.isfile(path):
        return ""
    data = _load_json(path)
    if not data or not isinstance(data, dict):
        return ""

    out = ['<section id="network">',
           '<h2>Network — Community Configuration</h2>',
           '<table><thead><tr><th>Field</th><th>Value</th></tr></thead><tbody>']

    interesting = [
        ("Id", "Network ID"),
        ("Name", "Community Name"),
        ("UrlPathPrefix", "URL Path"),
        ("SelfRegistrationEnabled", "Self-Registration Enabled"),
        ("PasswordlessLoginEnabled", "Passwordless Login"),
        ("AllowMembersToFlag", "Allow Member Flagging"),
        ("Status", "Status"),
    ]
    for key, label in interesting:
        val = data.get(key)
        if val is not None:
            out.append(f'<tr><td>{_h(label)}</td><td><code>{_h(str(val))}</code></td></tr>')

    out.append('</tbody></table></section>')
    return "\n".join(out)


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

    out = ['<section id="static">',
           '<h2>Static Resources</h2>',
           f'<p>{len(resources)} resource(s) downloaded:</p>',
           '<table><thead><tr><th>Name</th><th>Size</th><th>Content Type</th></tr></thead><tbody>']

    for r in resources:
        if isinstance(r, dict):
            name = _h(r.get("name", r.get("Name", "")))
            size = r.get("size", r.get("ContentSize", ""))
            ctype = _h(r.get("content_type", r.get("ContentType", r.get("type", ""))))
        else:
            name = _h(str(r))
            size = ""
            ctype = ""
        out.append(f'<tr><td><code>{name}</code></td><td>{size}</td><td>{ctype}</td></tr>')

    out.append('</tbody></table></section>')
    return "\n".join(out)


def _section_exposure(output_dir: str) -> str:
    path = os.path.join(output_dir, "exposure_summary.json")
    if not os.path.isfile(path):
        return ""
    data = _load_json(path)
    if not data or not isinstance(data, dict):
        return ""

    out = ['<section id="exposure">', '<h2>Surface — Exposure Checks</h2>',
           '<table><thead><tr><th>Check</th><th>Result</th></tr></thead><tbody>']

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

    has_rows = False
    for key, label in checks:
        val = data.get(key)
        if val is None:
            continue
        has_rows = True
        if isinstance(val, dict):
            parts = [f"{k}: {v}" for k, v in val.items() if v not in (None, "", [], {})]
            summary = "; ".join(parts[:6])
        elif isinstance(val, list):
            summary = f"{len(val)} item(s)" if val else "none found"
        else:
            summary = str(val)
        out.append(f'<tr><td>{_h(label)}</td><td>{_h(summary[:400])}</td></tr>')

    if not has_rows:
        return ""

    out.append('</tbody></table></section>')
    return "\n".join(out)


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

    out = ['<section id="flow">',
           '<h2>Flow — Accessible Flow API Names</h2>',
           f'<p>{len(hits)} flow(s) accessible via <code>InterviewController</code>:</p>',
           '<ul>']
    for h in hits:
        out.append(f'<li><code>{_h(str(h))}</code></li>')
    out.append('</ul></section>')
    return "\n".join(out)


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

    out = ['<section id="crud">',
           '<h2>CRUD — Create / Delete Findings</h2>',
           f'<p>{len(findings)} object(s) with unexpected write access:</p>',
           '<table><thead><tr><th>Object</th><th>Operations</th></tr></thead><tbody>']

    for f in findings:
        if isinstance(f, dict):
            obj = _h(f.get("object", ""))
            ops = ", ".join(f.get("operations", []))
        else:
            obj = _h(str(f))
            ops = ""
        out.append(f'<tr><td><code>{obj}</code></td><td>{_h(ops)}</td></tr>')

    out.append('</tbody></table></section>')
    return "\n".join(out)


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

    out = ['<section id="apexrest">',
           '<h2>ApexREST — Accessible Endpoints</h2>',
           f'<p>{len(hits)} endpoint(s) found at <code>/services/apexrest/</code>:</p>',
           '<ul>']
    for h in hits:
        out.append(f'<li><code>{_h(str(h))}</code></li>')
    out.append('</ul></section>')
    return "\n".join(out)


def _section_guest_vs_auth(output_dir: str) -> str:
    """
    Compare unauthenticated vs authenticated GraphQL access.

    Root-level graphql_dump_*.json files are produced by unauthenticated autodump.
    graphql/*.json files are produced by the authenticated query sweep.
    The difference surface shows what is exposed without any credentials.
    """
    guest_objects: dict[str, int] = {}
    for path in sorted(glob.glob(os.path.join(output_dir, "graphql_dump_*.json"))):
        obj_name = re.sub(r"^graphql_dump_", "", os.path.basename(path)[:-5])
        data = _load_json(path)
        count = len(data) if isinstance(data, list) else 0
        guest_objects[obj_name] = count

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

    guest_set = set(guest_objects)
    auth_set = set(auth_objects)
    both = sorted(guest_set & auth_set)
    guest_only = sorted(guest_set - auth_set)
    auth_only = sorted(auth_set - guest_set)

    out = ['<section id="guest-auth-diff">',
           '<h2>Access Comparison — Unauthenticated vs Authenticated</h2>',
           '<p>Objects accessible without credentials (root <code>graphql_dump_*</code>) compared to objects returned in the authenticated GraphQL sweep (<code>graphql/</code>).</p>']

    if guest_objects:
        out.append(f'<h3>Accessible Without Authentication ({len(guest_objects)} objects)</h3>')
        out.append('<table><thead><tr><th>Object</th><th>Records Extracted</th><th>Also in Authenticated Sweep</th></tr></thead><tbody>')
        for obj in sorted(guest_objects, key=lambda x: -guest_objects[x]):
            count = guest_objects[obj]
            also_auth = "yes" if obj in auth_set else "no"
            out.append(f'<tr><td><code>{_h(obj)}</code></td><td class="count">{count:,}</td><td>{also_auth}</td></tr>')
        out.append('</tbody></table>')

    if auth_only:
        out.append(f'<h3>Additional Objects Accessible Authenticated Only ({len(auth_only)} objects)</h3>')
        out.append('<table><thead><tr><th>Object</th><th>Total Records</th></tr></thead><tbody>')
        for obj in sorted(auth_only, key=lambda x: -auth_objects[x]):
            out.append(f'<tr><td><code>{_h(obj)}</code></td><td class="count">{auth_objects[obj]:,}</td></tr>')
        out.append('</tbody></table>')

    out.append('</section>')
    return "\n".join(out)


def generate(output_dir: str, target: str | None = None) -> str:
    """
    Scan output_dir for finding files and generate a self-contained HTML report.
    Returns the path to the saved report file.
    """
    if target is None:
        target = os.path.basename(os.path.abspath(output_dir))

    date_str = datetime.now().strftime("%Y-%m-%d")

    sections = [
        ("guest-auth-diff", "Access Comparison — Unauthenticated vs Authenticated", _section_guest_vs_auth(output_dir)),
        ("graphql-query", "GraphQL Object Query Sweep", _section_graphql_query(output_dir)),
        ("graphql-dumps", "GraphQL Field-Level Dumps", _section_graphql_dumps(output_dir)),
        ("aura-dump", "Aura Object Dump (getItems)", _section_aura_dump(output_dir)),
        ("idor", "IDOR Findings", _section_idor(output_dir)),
        ("chatter", "Chatter Endpoint Probe", _section_chatter(output_dir)),
        ("network", "Network Configuration", _section_network(output_dir)),
        ("static", "Static Resources", _section_static(output_dir)),
        ("crud", "CRUD Write Findings", _section_crud(output_dir)),
        ("flow", "Flow Hits", _section_flow(output_dir)),
        ("apexrest", "ApexREST Endpoints", _section_apex(output_dir)),
        ("exposure", "Exposure Checks", _section_exposure(output_dir)),
    ]
    active = [(sid, label, body) for sid, label, body in sections if body]

    if not active:
        logger.warning(f"No finding files found in {output_dir}")

    toc_items = "\n".join(
        f'<li><a href="#{sid}">{_h(label)}</a></li>'
        for sid, label, _ in active
    )

    body_parts = [s for _, _, s in active]

    html_content = "\n".join([
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>sfmap &mdash; {_h(target)}</title>",
        f"<style>{_css()}</style>",
        "</head>",
        "<body>",
        "<h1>Salesforce Security Assessment</h1>",
        f'<p class="meta">Target: <code>{_h(target)}</code></p>',
        f'<p class="meta">Date: {date_str}</p>',
        '<p class="meta">Tool: sfmap</p>',
        '<nav class="toc">',
        "<strong>Contents</strong>",
        f"<ol>{toc_items}</ol>",
        "</nav>",
        *body_parts,
        "</body>",
        "</html>",
    ])

    report_path = os.path.join(output_dir, "report.html")
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write(html_content)

    logger.success(f"HTML report saved → {report_path}")
    return report_path
