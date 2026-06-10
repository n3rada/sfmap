# Built-in imports
import html
import json
import re
from datetime import datetime
from importlib.resources import files as resource_files
from pathlib import Path

# Third-party imports
from loguru import logger


def _load_json(path: Path | str) -> dict | list | None:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
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
        return _minify_css(
            resource_files("sfmap.report_assets").joinpath("style.css").read_text(encoding="utf-8")
        )
    except Exception:
        logger.exception("Failed to load report CSS asset")
        return ""


def _load_js() -> str:
    try:
        return _minify_js(
            resource_files("sfmap.report_assets").joinpath("app.js").read_text(encoding="utf-8")
        )
    except Exception:
        logger.exception("Failed to load report JS asset")
        return ""


def _load_purify() -> str:
    try:
        return resource_files("sfmap.report_assets").joinpath("purify.min.js").read_text(encoding="utf-8")
    except Exception:
        logger.exception("Failed to load DOMPurify asset")
        return ""


_HTML_TAG_RE = re.compile(r'<[a-zA-Z][^>]*>.*?</[a-zA-Z]+>', re.DOTALL)


def _is_html_content(value: str) -> bool:
    return bool(_HTML_TAG_RE.search(value))


def _html_cell(value: str) -> str:
    escaped = html.escape(value, quote=True)
    return f'<div class="html-render" data-html="{escaped}"></div>'


def _clean_target(raw: str) -> str:
    return re.sub(r"_s(?:_sfsites)?(?:_aura)?$", "", raw.removeprefix("salesforce_"))


def _is_identity_dir(path: Path) -> bool:
    return (
        any(path.glob("graphql_dump_*.json"))
        or any(path.glob("*__page1.json"))
        or (path / "exposure_summary.json").is_file()
        or (path / "graphql").is_dir()
    )


def _read_display_name(identity_dir: Path) -> str:
    p = identity_dir / "display_name.txt"
    if p.is_file():
        name = p.read_text(encoding="utf-8").strip()
        if name:
            return name
    return identity_dir.name


def _card(section_id: str, title: str, body: str, severity: str | None = None) -> str:
    badge = (
        f'<span class="sev-badge sev-{severity.lower()}">{severity.upper()}</span>'
        if severity else ""
    )
    return (
        f'<div class="card" id="{_h(section_id)}">'
        f'<div class="card-title">{_h(title)}{badge}</div>'
        f'<div class="card-body">{body}</div>'
        f'</div>'
    )


def _table(headers: list[str], rows: list[list[str]]) -> str:
    ths = "".join(f"<th>{_h(h)}</th>" for h in headers)
    trs = "".join(
        "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>"
        for row in rows
    )
    return (
        '<div class="table-wrap">'
        f'<table><thead><tr>{ths}</tr></thead><tbody>{trs}</tbody></table>'
        '</div>'
    )


def _flat_val(v: object) -> str:
    """Unwrap Salesforce GraphQL {value: X} envelope, stringify."""
    if isinstance(v, dict):
        v = v.get("value", v)
    return str(v) if v is not None else ""


# ── Section builders ──────────────────────────────────────────────────────────

def _section_access_objects(output_dir: str, is_guest: bool, display_name: str = "", guest_dir: str | None = None) -> str:
    base = Path(output_dir)

    primary: dict[str, int] = {}
    for p in sorted(base.glob("graphql_dump_*.json")):
        obj_name = p.stem.removeprefix("graphql_dump_")
        data = _load_json(p)
        primary[obj_name] = len(data) if isinstance(data, list) else 0

    for p in sorted(base.glob("*__page1.json")):
        if m := re.match(r"^(.+)__page1\.json$", p.name):
            obj = m.group(1)
            if obj not in primary:
                data = _load_json(p)
                total = (data.get("totalCount", 0) or 0) if isinstance(data, dict) else 0
                primary[obj] = total

    sweep: dict[str, int] = {}
    graphql_dir = base / "graphql"
    if graphql_dir.is_dir():
        for p in sorted(graphql_dir.glob("graphql_*.json")):
            if p.name == "graphql_schema.json":
                continue
            obj_name = p.stem.removeprefix("graphql_")
            data = _load_json(p)
            if isinstance(data, dict):
                total = (
                    data.get("data", {})
                        .get("uiapi", {})
                        .get("query", {})
                        .get(obj_name, {})
                        .get("totalCount", 0)
                ) or 0
                sweep[obj_name] = total

    if not primary and not sweep:
        return ""

    # Load guest objects for comparison column in auth tabs
    guest_set: set[str] = set()
    if guest_dir and not is_guest:
        gbase = Path(guest_dir)
        for p in gbase.glob("graphql_dump_*.json"):
            guest_set.add(p.stem.removeprefix("graphql_dump_"))
        for p in gbase.glob("*__page1.json"):
            if m := re.match(r"^(.+)__page1\.json$", p.name):
                guest_set.add(m.group(1))

    sweep_only = sorted(set(sweep) - set(primary))
    parts: list[str] = []

    if is_guest:
        parts.append(
            '<p>The Salesforce Guest User profile exposes the objects below to anyone on the internet '
            'without authentication. This is a misconfiguration under the Shared Responsibility Model: '
            'the guest profile has been granted read access beyond what the application requires.</p>'
        )
    else:
        parts.append('<p>Objects accessible with this authenticated session.</p>')

    if primary:
        total_recs = sum(primary.values())
        show_guest_col = bool(guest_set) and not is_guest
        headers = ["Object", "Records"] + (["Also as Guest"] if show_guest_col else [])
        rows = []
        for obj in sorted(primary, key=lambda x: -primary[x]):
            row = [f"<code>{_h(obj)}</code>", f'<span class="num">{primary[obj]:,}</span>']
            if show_guest_col:
                row.append('<span class="guest-flag">GUEST</span>' if obj in guest_set else '<span class="muted">-</span>')
            rows.append(row)
        label = "Without Authentication" if is_guest else f"Authenticated ({display_name})" if display_name else "Authenticated"
        parts.append(f'<h3>Accessible ({label}): {len(primary)} object(s), {total_recs:,} record(s)</h3>')
        parts.append(_table(headers, rows))

    if sweep_only:
        rows2 = [
            [f"<code>{_h(obj)}</code>", f'<span class="num">{sweep[obj]:,}</span>']
            for obj in sorted(sweep_only, key=lambda x: -sweep[x])
        ]
        parts.append(f'<h3>Query Sweep Only: {len(sweep_only)} additional object(s)</h3>')
        parts.append(_table(["Object", "Total Records"], rows2))

    if is_guest:
        has_custom = any("__c" in obj for obj in list(primary) + list(sweep))
        sev = "critical" if has_custom else ("high" if primary else None)
        return _card("access", "Guest User Data Exposure", "\n".join(parts), severity=sev)

    return _card("access", "Authenticated Access", "\n".join(parts))




def _section_listviews(output_dir: str) -> str:
    p = Path(output_dir) / "listviews.json"
    if not p.is_file():
        return ""
    data = _load_json(p)
    if not data or not isinstance(data, dict):
        return ""
    urls = data.get("accessible_urls", [])
    if not urls:
        return ""

    rows = [
        [
            f"<code>{_h(url.rstrip('/').rsplit('/', 2)[-2])}</code>" if "/recordlist/" in url else "",
            f'<a href="{_h(url)}" target="_blank" rel="noopener"><code>{_h(url)}</code></a>',
        ]
        for url in urls
    ]
    body = f'<p>{len(urls)} object list view(s) directly browsable in the community UI.</p>' + _table(["Object", "URL"], rows)
    return _card("listviews", "UI List Views", body, severity="medium")


def _section_graphql_query(output_dir: str) -> str:
    graphql_dir = Path(output_dir) / "graphql"
    if not graphql_dir.is_dir():
        return ""

    hits: list[tuple[str, int]] = []
    for p in sorted(graphql_dir.glob("graphql_*.json")):
        if p.name == "graphql_schema.json":
            continue
        obj_name = p.stem.removeprefix("graphql_")
        data = _load_json(p)
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

    has_schema = (graphql_dir / "graphql_schema.json").is_file()
    if not hits and not has_schema:
        return ""

    parts: list[str] = []
    if has_schema:
        parts.append('<p>Introspection schema saved: <code>graphql/graphql_schema.json</code>.</p>')
    if hits:
        total_recs = sum(c for _, c in hits)
        rows = [
            [f"<code>{_h(obj)}</code>", f'<span class="num">{count:,}</span>']
            for obj, count in sorted(hits, key=lambda x: -x[1])
        ]
        parts.append(f'<p>{len(hits)} object(s), {total_recs:,} total record(s) returned via GraphQL <code>uiapi</code>:</p>')
        parts.append(_table(["Object", "Total Records"], rows))
    else:
        parts.append('<p class="muted">No objects returned records in the query sweep.</p>')

    return _card("graphql-query", "GraphQL: Object Query Sweep", "\n".join(parts))


def _section_graphql_dumps(output_dir: str) -> str:
    dumps: list[tuple[str, int, list[dict]]] = []
    for p in sorted(Path(output_dir).glob("graphql_dump_*.json")):
        obj_name = p.stem.removeprefix("graphql_dump_")
        data = _load_json(p)
        if isinstance(data, list) and data:
            dumps.append((obj_name, len(data), data[:5]))

    if not dumps:
        return ""

    total_recs = sum(count for _, count, _ in dumps)
    parts: list[str] = [f'<p>{len(dumps)} object(s), {total_recs:,} total record(s) with full field data extracted.</p>']

    for obj_name, count, samples in dumps:
        parts.append(f'<h3><code>{_h(obj_name)}</code>: {count:,} record(s)</h3>')
        if not samples:
            continue
        all_keys = list(samples[0].keys())
        max_cols  = 12
        headers   = list(all_keys[:max_cols])
        if len(all_keys) > max_cols:
            headers.append(f"+{len(all_keys) - max_cols} more")
        rows = []
        for rec in samples:
            row = []
            for k in all_keys[:max_cols]:
                val = _flat_val(rec.get(k, ""))
                row.append(_html_cell(val) if _is_html_content(val) else _h(val))
            if len(all_keys) > max_cols:
                row.append('<span class="muted">&hellip;</span>')
            rows.append(row)
        parts.append(_table(headers, rows))
        if count > 5:
            parts.append(f'<p class="muted">{count - 5:,} additional record(s) in file.</p>')

    return _card("graphql-dumps", "GraphQL: Field-Level Dumps", "\n".join(parts))


def _section_aura_dump(output_dir: str) -> str:
    base    = Path(output_dir)
    objects: dict[str, tuple[int, int]] = {}  # obj -> (pages, total)

    for p in sorted(base.glob("*__page*.json")):
        if m := re.match(r"^(.+)__page(\d+)\.json$", p.name):
            obj, page_num = m.group(1), int(m.group(2))
            pages, total = objects.get(obj, (0, 0))
            if page_num == 1:
                data  = _load_json(p)
                total = (data.get("totalCount", 0) or 0) if isinstance(data, dict) else 0
            objects[obj] = (pages + 1, total)

    if not objects:
        return ""

    total_recs = sum(t for _, t in objects.values())
    rows = [
        [
            f"<code>{_h(obj)}</code>",
            f'<span class="num">{total:,}</span>' if total else '<span class="muted">?</span>',
            str(pages),
        ]
        for obj, (pages, total) in sorted(objects.items(), key=lambda x: -x[1][1])
    ]
    body = (
        f'<p>{len(objects)} object(s), {total_recs:,} total record(s) accessible via Aura <code>getItems</code>.</p>'
        + _table(["Object", "Total Records", "Pages Saved"], rows)
    )
    return _card("aura-dump", "Aura: getItems Dump", body)


def _section_idor(output_dir: str) -> str:
    p = Path(output_dir) / "idor_findings.json"
    if not p.is_file():
        return ""
    data = _load_json(p)
    if not data:
        return ""
    findings = data if isinstance(data, list) else data.get("findings", [])
    if not findings:
        return ""

    rows = []
    for f in findings:
        rec_id  = _h(f.get("id", f.get("record_id", "")))
        obj     = _h(f.get("object_type", f.get("object", f.get("apiName", ""))))
        keys    = f.get("return_value_keys", list(f.get("fields", {}).keys()))
        key_str = ", ".join(_h(k) for k in keys) if keys else '<span class="muted">unknown</span>'
        rows.append([f"<code>{rec_id}</code>", f"<code>{obj}</code>", key_str])

    body = (
        f'<p>{len(findings)} record ID(s) responded with data when fetched without authentication.</p>'
        + _table(["Record ID", "Object", "Return Value Keys"], rows)
    )
    return _card("idor", "IDOR: Unauthenticated getRecord", body, severity="critical")


def _section_chatter(output_dir: str) -> str:
    for candidate in [
        Path(output_dir) / "chatter" / "chatter_summary.json",
        Path(output_dir) / "chatter_summary.json",
    ]:
        if candidate.is_file():
            p = candidate
            break
    else:
        return ""

    data = _load_json(p)
    if not data or not isinstance(data, dict):
        return ""

    parts: list[str] = []

    file_upload = data.get("file_upload")
    if file_upload and isinstance(file_upload, dict):
        leaked_ips = file_upload.get("leaked_ips", [])
        endpoint   = file_upload.get("endpoint", "")
        status     = file_upload.get("http_status", "")
        if leaked_ips:
            ip_list = ", ".join(f"<code>{_h(ip)}</code>" for ip in leaked_ips)
            parts.append('<h3>IP Address Leak via Chatter File Upload Endpoint</h3>')
            parts.append(
                f'<p>Endpoint: <code>{_h(endpoint)}</code> (HTTP {status})<br>'
                f'The error response disclosed the following IP address(es): {ip_list}</p>'
            )
        elif endpoint:
            parts.append(f'<p>File upload endpoint: <code>{_h(endpoint)}</code> (HTTP {status}), no IP leak detected.</p>')

    for key, heading in [("rest_endpoints", "Accessible Chatter REST Endpoints"), ("aura_objects", "Aura Objects via Chatter")]:
        items = data.get(key) or {}
        if isinstance(items, dict):
            items = list(items.keys())
        if items:
            lis = "".join(f"<li><code>{_h(str(i))}</code></li>" for i in items)
            parts.append(f'<h3>{heading}</h3><ul>{lis}</ul>')

    if not parts:
        return ""
    has_ip_leak = any("<h3>IP Address Leak" in p for p in parts)
    sev = "medium" if has_ip_leak else None
    return _card("chatter", "Chatter: File Upload & REST Probe", "\n".join(parts), severity=sev)


def _section_network(output_dir: str) -> str:
    p = Path(output_dir) / "network_config.json"
    if not p.is_file():
        return ""
    data = _load_json(p)
    if not data or not isinstance(data, dict):
        return ""

    # Two shapes: {"Network": [{"record": {...}}]} or {"records": N, "raw": [...]}
    record: dict = {}
    if "Network" in data:
        entries = data["Network"]
        if entries and isinstance(entries[0], dict):
            inner = entries[0].get("record", entries[0])
            fields = inner.get("fields", {})
            if fields:
                record = {k: (v.get("value") if isinstance(v, dict) else v) for k, v in fields.items()}
            else:
                record = {k: v for k, v in inner.items() if k != "sobjectType"}
    elif "raw" in data:
        raw_entries = data.get("raw", [])
        if raw_entries and isinstance(raw_entries[0], dict):
            inner  = raw_entries[0].get("record", raw_entries[0])
            fields = inner.get("fields", {})
            record = {k: (v.get("value") if isinstance(v, dict) else v) for k, v in fields.items()} if fields else inner

    interesting = [
        ("Id",                       "Network ID"),
        ("Name",                     "Community Name"),
        ("UrlPathPrefix",            "URL Path"),
        ("SelfRegistrationEnabled",  "Self-Registration"),
        ("PasswordlessLoginEnabled", "Passwordless Login"),
        ("AllowMembersToFlag",       "Allow Flagging"),
        ("Status",                   "Status"),
        ("LoginUrl",                 "Login URL"),
        ("AllowedExtensions",        "Allowed File Extensions"),
    ]
    rows = [
        [label, f"<code>{_h(str(val))}</code>"]
        for key, label in interesting
        if (val := record.get(key)) is not None
    ]
    if not rows:
        return ""
    return _card("network", "Network: Community Configuration", _table(["Field", "Value"], rows))


def _section_static(output_dir: str) -> str:
    p = Path(output_dir) / "staticresource_summary.json"
    if not p.is_file():
        return ""
    data = _load_json(p)
    if not data:
        return ""
    resources = data if isinstance(data, list) else data.get("resources", data.get("hits", []))
    if not resources:
        return ""

    # Resources < 4 KB are almost certainly redirect/error pages, not actual files
    _PLACEHOLDER_THRESHOLD = 4096
    real     = [r for r in resources if isinstance(r, dict) and (r.get("size") or 0) >= _PLACEHOLDER_THRESHOLD]
    redirect = [r for r in resources if r not in real]

    parts: list[str] = [
        f'<p>{len(resources)} resource(s) enumerated: '
        f'{len(real)} with actual content, {len(redirect)} appear to be redirect/placeholder responses.</p>'
    ]

    if real:
        rows = [
            [
                f"<code>{_h(r.get('name', r.get('Name', '')))}</code>",
                f'<span class="num">{r.get("size", 0):,}</span>',
                _h(r.get("content_type", r.get("ContentType", r.get("type", "")))),
                f'<a href="{_h(r["url"])}" target="_blank" rel="noopener">link</a>' if r.get("url") else "",
            ]
            for r in sorted(real, key=lambda x: -(x.get("size") or 0))
        ]
        parts.append(f'<h3>Downloaded Resources ({len(real)})</h3>')
        parts.append(_table(["Name", "Size (bytes)", "Content Type", "URL"], rows))

    if redirect:
        names = ", ".join(f"<code>{_h(r.get('name', str(r)))}</code>" for r in redirect[:10])
        overflow = f" and {len(redirect) - 10} more" if len(redirect) > 10 else ""
        parts.append(f'<h3>Redirect / Placeholder Responses ({len(redirect)})</h3>')
        parts.append(f'<p>{names}{overflow}</p>')

    return _card("static", "Static Resources", "\n".join(parts))


def _section_crud(output_dir: str) -> str:
    for candidate in [
        Path(output_dir) / "crud_probe.json",
        Path(output_dir) / "crud_findings.json",
    ]:
        if candidate.is_file():
            p = candidate
            break
    else:
        return ""

    data = _load_json(p)
    if not data:
        return ""

    # crud_probe.json is {ObjectName: {create, delete, created_id, error}}
    # crud_findings.json is [{object, operations}] or similar
    findings: list[tuple[str, list[str]]] = []
    match data:
        case dict():
            for obj, result in data.items():
                if isinstance(result, dict) and result.get("create"):
                    ops = ["create"]
                    if result.get("delete"):
                        ops.append("delete")
                    findings.append((obj, ops))
        case list():
            for f in data:
                if isinstance(f, dict):
                    findings.append((f.get("object", ""), f.get("operations", [])))

    if not findings:
        return ""

    rows = [
        [f"<code>{_h(obj)}</code>", _h(", ".join(ops))]
        for obj, ops in findings
    ]
    body = f'<p>{len(findings)} object(s) allow write operations with this session.</p>' + _table(["Object", "Allowed Operations"], rows)
    return _card("crud", "CRUD: Write Access", body, severity="high")


def _section_flow(output_dir: str) -> str:
    p = Path(output_dir) / "flow_hits.json"
    if not p.is_file():
        return ""
    data = _load_json(p)
    if not data:
        return ""
    hits = data if isinstance(data, list) else data.get("hits", [])
    if not hits:
        return ""
    lis  = "".join(f"<li><code>{_h(str(h))}</code></li>" for h in hits)
    body = f'<p>{len(hits)} flow(s) accessible via <code>InterviewController</code>.</p><ul>{lis}</ul>'
    return _card("flow", "Flow API Names", body)


def _section_apex(output_dir: str) -> str:
    base = Path(output_dir)
    parts: list[str] = []

    # ApexREST endpoints
    p_rest = base / "apexrest_hits.json"
    if p_rest.is_file():
        data = _load_json(p_rest)
        hits = (data if isinstance(data, list) else data.get("hits", [])) if data else []
        if hits:
            lis = "".join(f"<li><code>{_h(str(h))}</code></li>" for h in hits)
            parts.append(f'<h3>ApexREST Endpoints ({len(hits)})</h3>')
            parts.append(f'<p>{len(hits)} endpoint(s) reachable at <code>/services/apexrest/</code>.</p><ul>{lis}</ul>')

    # Apex ACTION controllers (discovered + probed)
    p_hits = base / "apex_hits.json"
    if p_hits.is_file():
        data = _load_json(p_hits)
        if data and isinstance(data, dict):
            callable_ones = data.get("callable", [])
            denied = data.get("exists_denied", [])
            if callable_ones or denied:
                parts.append(f'<h3>Apex ACTION Controllers</h3>')
                if callable_ones:
                    rows = [[f"<code>{_h(d)}</code>", '<span style="color:#16a34a;font-weight:600">callable</span>']
                            for d in callable_ones]
                    parts.append(f'<p>{len(callable_ones)} descriptor(s) returned SUCCESS with empty params:</p>')
                    parts.append(_table(["Descriptor", "Status"], rows))
                if denied:
                    rows2 = [[f"<code>{_h(d)}</code>", '<span class="muted">access denied</span>']
                             for d in denied]
                    parts.append(f'<p>{len(denied)} descriptor(s) exist but returned ACCESS_DENIED:</p>')
                    parts.append(_table(["Descriptor", "Status"], rows2))

    if not parts:
        return ""
    has_callable = any("callable" in p for p in parts)
    sev = "high" if has_callable else None
    return _card("apexrest", "Apex Endpoints", "\n".join(parts), severity=sev)


def _section_exposure(output_dir: str) -> str:
    p = Path(output_dir) / "exposure_summary.json"
    if not p.is_file():
        return ""
    data = _load_json(p)
    if not data or not isinstance(data, dict):
        return ""

    parts: list[str] = []

    # ── API surface ────────────────────────────────────────────
    api_rows: list[list[str]] = []

    gql = data.get("graphql") or {}
    if isinstance(gql, dict):
        status = "Enabled, usable" if gql.get("usable") else ("Enabled, restricted" if gql.get("enabled") else "Not available")
        api_rows.append(["GraphQL", status])

    rest = data.get("rest_api") or {}
    if isinstance(rest, dict):
        if rest.get("version_listing_exposed"):
            url = _h(rest.get("latest_url", ""))
            api_rows.append(["REST API", f"Version listing exposed ({url})"])
        else:
            api_rows.append(["REST API", "Not exposed"])

    soap = data.get("soap_api") or {}
    if isinstance(soap, dict):
        status = f'Exposed (HTTP {soap.get("status_code", "")})' if soap.get("exposed") else "Not exposed"
        api_rows.append(["SOAP API", status])

    selfreg = data.get("self_registration") or {}
    if isinstance(selfreg, dict):
        if selfreg.get("enabled"):
            url = _h(selfreg.get("url") or "")
            api_rows.append(["Self-Registration", f"Enabled{' (' + url + ')' if url else ''}"])
        else:
            api_rows.append(["Self-Registration", "Disabled"])

    extra = data.get("extra_endpoints") or {}
    if isinstance(extra, dict):
        for name, code in extra.items():
            if code is not None:
                api_rows.append([_h(name.replace("_", " ").title()), f"HTTP {code}"])

    if api_rows:
        parts.append('<h3>API Surface</h3>')
        parts.append(_table(["Endpoint / Feature", "Status"], api_rows))

    # ── Security headers ───────────────────────────────────────
    sec = data.get("security_headers") or {}
    if isinstance(sec, dict):
        url_checked = sec.get("url_checked", "")
        present     = sec.get("present", {})
        missing     = sec.get("missing", [])
        weaknesses  = sec.get("weaknesses", [])

        parts.append(f'<h3>Security Headers<span class="muted" style="font-weight:400;margin-left:.5rem">checked against <code>{_h(url_checked)}</code></span></h3>')

        if present:
            hdr_rows = [[f"<code>{_h(k)}</code>", _h(str(v)[:200])] for k, v in sorted(present.items())]
            parts.append('<p style="margin-bottom:.3rem">Present:</p>')
            parts.append(_table(["Header", "Value"], hdr_rows))

        if missing:
            lis = "".join(f"<li><code>{_h(h)}</code></li>" for h in missing)
            parts.append(f'<p style="margin-top:.6rem">Missing: <ul>{lis}</ul></p>')

        if weaknesses:
            lis = "".join(f"<li>{_h(w)}</li>" for w in weaknesses)
            parts.append(f'<p style="margin-top:.4rem">Weaknesses: <ul>{lis}</ul></p>')

    # ── Visualforce pages ──────────────────────────────────────
    vf = data.get("visualforce") or {}
    if isinstance(vf, dict):
        accessible = {name: code for name, code in vf.items() if code == 200}
        other      = {name: code for name, code in vf.items() if code != 200}
        parts.append('<h3>Visualforce Pages</h3>')
        if accessible:
            rows = [[f"<code>/apex/{_h(name)}</code>", f"HTTP {code}"] for name, code in sorted(accessible.items())]
            parts.append(f'<p>{len(accessible)} page(s) returned HTTP 200:</p>')
            parts.append(_table(["Page", "Status"], rows))
        if other:
            rows2 = [[f"<code>/apex/{_h(name)}</code>", f"HTTP {code}"] for name, code in sorted(other.items())]
            parts.append(f'<p class="muted">{len(other)} page(s) not accessible:</p>')
            parts.append(_table(["Page", "Status"], rows2))
        if not vf:
            parts.append('<p class="muted">No Visualforce pages probed.</p>')

    # ── Custom controllers ─────────────────────────────────────
    controllers = data.get("custom_controllers") or {}
    if isinstance(controllers, dict) and controllers:
        parts.append('<h3>Custom Apex Controller Descriptors</h3>')
        for source_url, descriptors in controllers.items():
            parts.append(f'<p>From <code>{_h(source_url)}</code>:</p>')
            lis = "".join(f"<li><code>{_h(d)}</code></li>" for d in descriptors)
            parts.append(f'<ul>{lis}</ul>')

    if not parts:
        return ""
    has_weaknesses = any("Weaknesses:" in p or "weaknesses" in p.lower() for p in parts)
    sev = "low" if has_weaknesses else None
    return _card("exposure", "Surface Exposure Checks", "\n".join(parts), severity=sev)


def _section_graphql_schema(output_dir: str) -> str:
    schema_path = Path(output_dir) / "graphql" / "graphql_schema.json"
    if not schema_path.is_file():
        return ""

    raw = _load_json(schema_path)
    if not raw:
        return ""

    types_raw = (
        raw.get("data", {}).get("__schema", {}).get("types")
        or raw.get("__schema", {}).get("types")
        or []
    )
    object_types = [
        t for t in types_raw
        if t.get("kind") == "OBJECT" and not t.get("name", "").startswith("__")
    ]
    if not object_types:
        return ""

    rows = []
    for t in sorted(object_types, key=lambda x: x.get("name", "")):
        name        = t.get("name", "")
        fields      = t.get("fields") or []
        field_names = [f.get("name", "") for f in fields]
        count       = len(field_names)
        preview     = ", ".join(field_names[:10])
        if count > 10:
            preview += f", +{count - 10} more"
        rows.append([
            f"<code>{_h(name)}</code>",
            f'<span class="num">{count}</span>',
            f'<span class="muted">{_h(preview)}</span>',
        ])

    # Ensure the schema is in {data: {__schema: ...}} form that Voyager expects
    if "data" not in raw:
        voyager_payload = {"data": raw}
    else:
        voyager_payload = raw

    # Escape </script> so the JSON is safe inside a <script> block
    schema_js = json.dumps(voyager_payload).replace("</", "<\\/")

    copy_btn = (
        f'<script>var __sfmap_schema__ = {schema_js};</script>'
        '<button class="copy-btn" onclick="'
        "navigator.clipboard.writeText(JSON.stringify(__sfmap_schema__,null,2))"
        ".then(function(){var b=this;b.textContent='Copied!';setTimeout(function(){b.textContent='Copy introspection JSON'},2000)}.bind(this))"
        '.catch(function(){alert(\'Clipboard not available\')})">'
        "Copy introspection JSON</button>"
        ' <a class="voyager-link" href="https://apis.guru/graphql-voyager/" target="_blank" rel="noopener">'
        "open GraphQL Voyager</a>"
        ' <span class="muted">(paste via "Change Schema" in Voyager)</span>'
    )

    body = (
        f'<p>{len(object_types)} OBJECT type(s) in the GraphQL introspection schema.</p>'
        f'<p class="schema-actions">{copy_btn}</p>'
        + _table(["Type", "Fields", "Field Names"], rows)
    )
    return _card("graphql-schema", "GraphQL: Schema Types", body)


def _section_summary(output_dir: str, is_guest: bool, display_name: str) -> str:
    base = Path(output_dir)

    obj_names: set[str] = set()
    rec_count = 0
    for p in base.glob("graphql_dump_*.json"):
        obj_names.add(p.stem.removeprefix("graphql_dump_"))
        data = _load_json(p)
        if isinstance(data, list):
            rec_count += len(data)
    for p in base.glob("*__page1.json"):
        if m := re.match(r"^(.+)__page1\.json$", p.name):
            obj_names.add(m.group(1))
            data = _load_json(p)
            rec_count += (data.get("totalCount", 0) or 0) if isinstance(data, dict) else 0

    gql_hits = 0
    graphql_dir = base / "graphql"
    if graphql_dir.is_dir():
        for p in graphql_dir.glob("graphql_*.json"):
            if p.name == "graphql_schema.json":
                continue
            obj_name = p.stem.removeprefix("graphql_")
            data = _load_json(p)
            if isinstance(data, dict):
                total = (
                    data.get("data", {}).get("uiapi", {}).get("query", {}).get(obj_name, {}).get("totalCount", 0)
                ) or 0
                if total > 0:
                    gql_hits += 1

    idor_count = 0
    p_idor = base / "idor_findings.json"
    if p_idor.is_file():
        data = _load_json(p_idor)
        if data:
            findings = data if isinstance(data, list) else data.get("findings", [])
            idor_count = len(findings)

    crud_objs = 0
    for candidate in [base / "crud_probe.json", base / "crud_findings.json"]:
        if candidate.is_file():
            data = _load_json(candidate)
            if data and isinstance(data, dict):
                crud_objs = sum(1 for r in data.values() if isinstance(r, dict) and r.get("create"))
            elif data and isinstance(data, list):
                crud_objs = len(data)
            break

    ip_leak = False
    for candidate in [base / "chatter" / "chatter_summary.json", base / "chatter_summary.json"]:
        if candidate.is_file():
            data = _load_json(candidate)
            if data and isinstance(data, dict):
                ip_leak = bool(data.get("file_upload", {}).get("leaked_ips"))
            break

    apex_callable = 0
    p_apex = base / "apex_hits.json"
    if p_apex.is_file():
        data = _load_json(p_apex)
        if data and isinstance(data, dict):
            apex_callable = len(data.get("callable", []))

    listview_count = 0
    p_lv = base / "listviews.json"
    if p_lv.is_file():
        data = _load_json(p_lv)
        if data and isinstance(data, dict):
            listview_count = len(data.get("accessible_urls", []))

    metrics: list[tuple[str, str]] = []
    if obj_names:
        metrics.append((str(len(obj_names)), "Objects"))
        metrics.append((f"{rec_count:,}", "Records"))
    if gql_hits:
        metrics.append((str(gql_hits), "GraphQL Types"))
    if idor_count:
        metrics.append((str(idor_count), "IDOR Records"))
    if crud_objs:
        metrics.append((str(crud_objs), "Writable Objects"))
    if listview_count:
        metrics.append((str(listview_count), "List Views"))
    if apex_callable:
        metrics.append((str(apex_callable), "Callable Apex"))

    key_findings: list[tuple[str, str]] = []
    if is_guest and obj_names:
        has_custom = any("__c" in o for o in obj_names)
        sev = "critical" if has_custom else "high"
        key_findings.append((sev, f"Unauthenticated read access to {len(obj_names)} object(s), {rec_count:,} record(s)"))
    if idor_count:
        key_findings.append(("critical", f"IDOR: {idor_count} record(s) readable without authentication"))
    if crud_objs:
        key_findings.append(("high", f"Write access to {crud_objs} object(s)"))
    if apex_callable:
        key_findings.append(("high", f"{apex_callable} Apex ACTION descriptor(s) callable with no params"))
    if ip_leak:
        key_findings.append(("medium", "Internal IP address(es) leaked via Chatter upload endpoint"))
    if listview_count:
        key_findings.append(("medium", f"{listview_count} UI list view(s) directly browsable"))

    parts: list[str] = []
    if metrics:
        metric_html = "".join(
            f'<div class="summary-metric">'
            f'<div class="summary-metric-value">{val}</div>'
            f'<div class="summary-metric-label">{label}</div>'
            f'</div>'
            for val, label in metrics
        )
        parts.append(f'<div class="summary-metrics">{metric_html}</div>')

    if key_findings:
        sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        key_findings.sort(key=lambda x: sev_order.get(x[0], 9))
        lis = "".join(
            f'<li class="summary-finding">'
            f'<span class="sev-badge sev-{sev}">{sev.upper()}</span>'
            f'<span>{_h(msg)}</span>'
            f'</li>'
            for sev, msg in key_findings
        )
        parts.append(f'<h3>Key Findings</h3><ul class="summary-findings">{lis}</ul>')

    if not parts:
        return ""

    context = "Guest" if is_guest else display_name
    return _card("summary", f"{context}: Overview", "\n".join(parts))


# ── Report generator ──────────────────────────────────────────────────────────

def _build_tab_panel(
    identity_dir: Path,
    display_name: str,
    tab_id: str,
    is_active: bool,
    guest_dir: Path | None,
) -> str:
    is_guest = identity_dir.name == "guest"
    od = str(identity_dir)
    gd = str(guest_dir) if guest_dir and guest_dir != identity_dir else None

    sections: list[tuple[str, str]] = [
        ("summary",        _section_summary(od, is_guest, display_name)),
        ("access",         _section_access_objects(od, is_guest, display_name, gd)),
        ("idor",           _section_idor(od)),
        ("crud",           _section_crud(od)),
        ("chatter",        _section_chatter(od)),
        ("graphql-dumps",  _section_graphql_dumps(od)),
        ("aura-dump",      _section_aura_dump(od)),
        ("listviews",      _section_listviews(od)),
        ("exposure",       _section_exposure(od)),
        ("graphql-query",  _section_graphql_query(od)),
        ("graphql-schema", _section_graphql_schema(od)),
        ("flow",           _section_flow(od)),
        ("apexrest",       _section_apex(od)),
        ("network",        _section_network(od)),
        ("static",         _section_static(od)),
    ]
    active_sections = [(sid, body) for sid, body in sections if body]

    if not active_sections:
        logger.warning(f"No finding files found in {identity_dir}")

    cards = "\n".join(body for _, body in active_sections)
    active_class = " active" if is_active else ""
    return (
        f'<div id="{_h(tab_id)}" class="tab-panel{active_class}">'
        f'<div class="layout">{cards}</div>'
        f'</div>'
    )


def generate(output_dir: str, target: str | None = None) -> str:
    """
    Generate a single self-contained HTML report with one tab per identity.
    Accepts either a parent directory (contains identity subdirs) or a single
    identity directory. The report is saved at the parent directory level.
    Returns the path to the saved file.
    """
    base = Path(output_dir).resolve()

    if _is_identity_dir(base):
        identity_dirs = [base]
        report_dir = base.parent if base.parent.is_dir() else base
    else:
        identity_dirs = sorted(d for d in base.iterdir() if d.is_dir() and _is_identity_dir(d))
        report_dir = base

    if not identity_dirs:
        logger.warning(f"No identity directories found in {output_dir}")
        return ""

    if target is None:
        target = _clean_target(report_dir.name)

    guest_dir = next((d for d in identity_dirs if d.name == "guest"), None)
    date_str  = datetime.now().strftime("%Y-%m-%d")
    css    = _load_css()
    js     = _load_js()
    purify = _load_purify()

    tab_btns:   list[str] = []
    tab_panels: list[str] = []

    for i, id_dir in enumerate(identity_dirs):
        tab_id       = f"tab-{i}"
        is_active    = i == 0
        display_name = _read_display_name(id_dir)
        active_class = " active" if is_active else ""
        tab_btns.append(
            f'<button class="tab-btn{active_class}" data-target="{_h(tab_id)}">'
            f'{_h(display_name)}</button>'
        )
        tab_panels.append(_build_tab_panel(id_dir, display_name, tab_id, is_active, guest_dir))

    tab_bar    = '<div class="tab-bar">' + "".join(tab_btns) + '</div>'
    panels_html = "\n".join(tab_panels)

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
      <span class="header-title">Security Assessment Report</span>
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
        <span class="meta-label">Identities</span>
        <span class="meta-value">{len(identity_dirs)}</span>
      </div>
    </div>
  </div>
</header>

{tab_bar}

{panels_html}

<script>{purify}</script>
<script>{js}</script>
</body>
</html>"""

    report_path = report_dir / "report.html"
    report_path.write_text(page, encoding="utf-8")
    logger.info(f"HTML report saved → {report_path}")
    return str(report_path)
