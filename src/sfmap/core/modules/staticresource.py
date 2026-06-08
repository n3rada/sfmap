# Built-in imports
import io
import json
import os
import re
import zipfile
from importlib.resources import files as resource_files
from urllib.parse import urlparse

# Third-party imports
from loguru import logger

# Local imports
from ..client import AuraClient
from . import dump

_SENSITIVE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'AKIA[0-9A-Z]{16}'), "AWS access key"),
    (re.compile(r'-----BEGIN (?:RSA |EC )?PRIVATE KEY-----'), "private key"),
    (re.compile(r'eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}'), "JWT token"),
    (re.compile(r'https?://[^\s"\'<>]{3,}:[^\s"\'<>@]{3,}@[^\s"\'<>]+'), "URL with credentials"),
    (re.compile(r'(?i)["\']?(?:api[_-]?key|client[_-]?secret|consumer[_-]?secret)\s*["\':]?\s*["\']([A-Za-z0-9_\-]{16,})["\']'), "API key"),
    (re.compile(r'(?i)(?:password|passwd)\s*[:=]\s*["\']([^"\']{8,})["\']'), "hardcoded password"),
]

_SCANNABLE_EXTENSIONS = {'.js', '.json', '.txt', '.xml', '.html', '.htm', '.css', '.properties', '.yaml', '.yml', '.env', '.config'}


def _base_url(aura_url: str) -> str:
    parsed = urlparse(aura_url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _load_wordlist(custom_path: str | None) -> list[str]:
    if custom_path:
        with open(custom_path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    else:
        text = resource_files("sfmap.data").joinpath("static_resources.txt").read_text(encoding="utf-8")
        lines = text.splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]


def _enumerate_via_aura(client: AuraClient) -> list[str]:
    rv = dump.get_items(client, "StaticResource", page_size=500, page=1, silent=True)
    if rv is None:
        return []
    names: list[str] = []
    for item in rv.get("result", []):
        record = item.get("record", item)
        fields = record.get("fields", {})
        name_field = fields.get("Name", {})
        name = name_field.get("value") if isinstance(name_field, dict) else name_field
        if name:
            names.append(name)
    return names


def _fetch(client: AuraClient, base: str, name: str) -> tuple[int, bytes]:
    for url in (f"{base}/resource/{name}", f"{base}/s/resource/{name}"):
        try:
            resp = client.get(url)
            if resp.status_code == 200:
                return 200, resp.content
        except Exception as exc:
            logger.debug(f"StaticResource fetch error {name}: {exc}")
    return 404, b""


def _scan_bytes(content: bytes, source: str) -> list[dict]:
    findings: list[dict] = []
    try:
        text = content.decode("utf-8", errors="replace")
    except Exception:
        return findings
    for pattern, label in _SENSITIVE_PATTERNS:
        for match in pattern.finditer(text):
            line_no = text[: match.start()].count("\n") + 1
            findings.append({
                "source": source,
                "type": label,
                "match": match.group(0)[:200],
                "line": line_no,
            })
    return findings


def _inspect(name: str, content: bytes) -> list[dict]:
    if content[:2] == b"PK":
        try:
            findings: list[dict] = []
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                for entry in zf.namelist():
                    ext = os.path.splitext(entry)[1].lower()
                    if ext not in _SCANNABLE_EXTENSIONS:
                        continue
                    try:
                        data = zf.read(entry)
                        findings.extend(_scan_bytes(data, f"{name}/{entry}"))
                    except Exception:
                        pass
            return findings
        except zipfile.BadZipFile:
            pass
    return _scan_bytes(content, name)


def fuzz(
    client: AuraClient,
    aura_url: str,
    output_dir: str,
    wordlist_path: str | None = None,
) -> list[dict]:
    base = _base_url(aura_url)
    hits: list[dict] = []
    all_findings: list[dict] = []

    aura_names = _enumerate_via_aura(client)
    if aura_names:
        logger.info(f"StaticResource: {len(aura_names)} name(s) enumerated via Aura")
        names = aura_names
    else:
        logger.info("StaticResource: not accessible via Aura, using wordlist")
        names = _load_wordlist(wordlist_path)
        logger.info(f"StaticResource: {len(names)} name(s) to probe")

    os.makedirs(output_dir, exist_ok=True)

    for name in names:
        sc, content = _fetch(client, base, name)
        if sc != 200:
            logger.debug(f"StaticResource {name}: not accessible")
            continue

        logger.warning(f"StaticResource accessible: /resource/{name} ({len(content):,} bytes)")
        findings = _inspect(name, content)

        for f in findings:
            logger.warning(f"Sensitive content in {name}: {f['type']} ({f['source']}:{f['line']})")

        safe = name.replace("/", "_").replace("\\", "_")
        out_path = os.path.join(output_dir, f"staticresource_{safe}.bin")
        with open(out_path, "wb") as fh:
            fh.write(content)

        hit = {
            "name": name,
            "url": f"{base}/resource/{name}",
            "size": len(content),
            "is_zip": content[:2] == b"PK",
            "sensitive_findings": findings,
        }
        hits.append(hit)
        all_findings.extend(findings)

    summary_path = os.path.join(output_dir, "staticresource_summary.json")
    with open(summary_path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(hits, ensure_ascii=False, indent=2))

    if hits:
        logger.warning(
            f"StaticResource: {len(hits)} accessible resource(s), "
            f"{len(all_findings)} sensitive pattern(s) found"
        )
    else:
        logger.info("StaticResource: no accessible resources found")

    return hits
