# Built-in imports
import os
from pathlib import Path
from urllib.parse import urlparse

# Third-party imports
import httpx
from loguru import logger

# Local imports
from ..client import AuraClient
from . import dump

# Salesforce REST API version used for the VersionData probe.
_REST_API_VERSION = "v59.0"


def _extract_ids(rv: dict) -> list[str]:
    """Pull Salesforce record IDs out of a getItems returnValue dict."""
    ids: list[str] = []
    for item in rv.get("result", []):
        record = item.get("record", item)
        rid = record.get("id") or record.get("Id")
        if rid:
            ids.append(rid)
    return ids


def enumerate_content(
    client: AuraClient,
    output_dir: str,
) -> dict[str, list[str]]:
    """
    Dump ContentDocument and ContentVersion via Aura getItems.

    Writes one JSON file per object to *output_dir* and returns a mapping
    ``{object_name: [id, ]}`` for all records found.
    """
    found: dict[str, list[str]] = {}

    for obj_name in ("ContentDocument", "ContentVersion"):
        rv = dump.get_items(client, obj_name, page_size=1000, page=1)
        if rv is None:
            logger.debug(f"{obj_name}: no records visible via Aura")
            continue

        results = rv.get("result", [])
        total = rv.get("totalCount", "?")
        logger.info(
            f"{obj_name}: {len(results)} record(s) returned (totalCount={total})"
        )

        ids = _extract_ids(rv)
        if ids:
            found[obj_name] = ids

        dump.write_page(output_dir, obj_name, 1, rv)

    return found


def probe_rest(
    aura_url: str,
    version_ids: list[str],
    verify_ssl: bool = False,
) -> list[str]:
    """
    For each ContentVersion ID attempt an *unauthenticated* REST download:

        GET /services/data/{version}/sobjects/ContentVersion/{Id}/VersionData

    Returns the list of IDs that returned HTTP 200 without any credentials.
    A non-empty result is a critical finding: "API Enabled" is active on the
    Guest profile, allowing arbitrary file download without an Aura session.
    """
    parsed = urlparse(aura_url)
    api_base = f"{parsed.scheme}://{parsed.netloc}"
    accessible: list[str] = []

    # Deliberately no cookies, no Authorization header.
    with httpx.Client(verify=verify_ssl, follow_redirects=False) as http:
        for vid in version_ids:
            url = (
                f"{api_base}/services/data/{_REST_API_VERSION}"
                f"/sobjects/ContentVersion/{vid}/VersionData"
            )
            try:
                resp = http.get(url)
            except Exception as exc:
                logger.debug(f"REST probe error for {vid}: {exc}")
                continue

            if resp.status_code == 200:
                logger.warning(
                    f"CRITICAL — ContentVersion/{vid} accessible via "
                    f"unauthenticated REST: GET {url}"
                )
                accessible.append(vid)
            else:
                logger.debug(f"ContentVersion/{vid}: REST → HTTP {resp.status_code}")

    return accessible


def run(client: AuraClient, aura_url: str, output_dir: str) -> int:
    """
    Full content-enumeration check.

    1. Dump ContentDocument + ContentVersion via Aura.
    2. Probe each ContentVersion ID via unauthenticated REST.

    Returns the number of ContentVersion IDs accessible without authentication
    (0 = no critical finding).
    """
    logger.info("Enumerating ContentDocument / ContentVersion via Aura")
    found = enumerate_content(client, output_dir)

    version_ids = found.get("ContentVersion", [])

    if not version_ids:
        logger.info("No ContentVersion records found — skipping REST probe.")
        return 0

    logger.info(
        f"Probing {len(version_ids)} ContentVersion ID(s) " "via unauthenticated REST"
    )
    critical = probe_rest(aura_url, version_ids)

    if critical:
        logger.warning(
            f"CRITICAL: {len(critical)} ContentVersion file(s) downloadable "
            "without authentication:"
        )
        for vid in critical:
            parsed = urlparse(aura_url)
            logger.warning(
                f"  GET {parsed.scheme}://{parsed.netloc}"
                f"/services/data/{_REST_API_VERSION}"
                f"/sobjects/ContentVersion/{vid}/VersionData"
            )
    else:
        logger.info("REST probe: no unauthenticated access found.")

    return len(critical)
