# Built-in imports
from urllib.parse import urlparse

# Third-party imports
import httpx
from loguru import logger

# Local imports
from ..client import AuraClient, REST_API_VERSION
from . import dump


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
                f"{api_base}/services/data/{REST_API_VERSION}"
                f"/sobjects/ContentVersion/{vid}/VersionData"
            )
            try:
                resp = http.get(url)
            except Exception:
                logger.exception(f"REST probe error for {vid}")
                continue

            if resp.status_code == 200:
                logger.success(
                    f"ContentVersion/{vid} accessible without authentication: GET {url}"
                )
                accessible.append(vid)
            else:
                logger.debug(f"ContentVersion/{vid}: REST → HTTP {resp.status_code}")

    return accessible


def download_all(
    client: AuraClient,
    aura_url: str,
    output_dir: str,
    download_dir: str,
) -> int:
    """
    Enumerate ContentDocument + ContentVersion via Aura then download every
    file through the servlet.shepherd endpoint.

    Metadata JSON is written to *output_dir*; binary files go to *download_dir*.
    Returns the number of files successfully downloaded.
    """
    found = enumerate_content(client, output_dir)

    all_ids: list[str] = []
    for ids in found.values():
        all_ids.extend(ids)

    if not all_ids:
        logger.info("No content records found, nothing to download.")
        return 0

    logger.info(f"Downloading {len(all_ids)} file(s) to {download_dir}")
    downloaded = 0
    for sf_id in all_ids:
        path = dump.download_file(client, sf_id, aura_url, download_dir)
        if path:
            downloaded += 1

    logger.info(f"Downloaded {downloaded}/{len(all_ids)} file(s)")
    return downloaded


def check_content_distribution(
    client: AuraClient,
    aura_url: str,
    output_dir: str,
) -> list[dict]:
    """
    Enumerate ContentDistribution records and probe each public URL without auth.
    ContentDistribution exposes files as publicly shareable links — if the link
    is active and not expired, anyone with the URL can download the file.
    Returns list of accessible distribution records.
    """
    rv = dump.get_items(client, "ContentDistribution", page_size=1000, page=1)
    if rv is None:
        logger.info("ContentDistribution: no records visible")
        return []

    results = rv.get("result", [])
    total = rv.get("totalCount", len(results))
    logger.info(f"ContentDistribution: {total} record(s) found")
    dump.write_page(output_dir, "ContentDistribution", 1, rv)

    public_hits: list[dict] = []
    parsed = urlparse(aura_url)
    base = f"{parsed.scheme}://{parsed.netloc}"

    for item in results:
        record = item.get("record", item)
        dist_id = record.get("id") or record.get("Id")
        fields = record.get("fields", {})

        pub_url: str | None = None
        for field_name, field_val in fields.items():
            low = field_name.lower()
            if "public" in low and "url" in low:
                pub_url = (
                    field_val.get("value") if isinstance(field_val, dict) else field_val
                )
                break
            if "distributionpublicurl" in low or "contentdownloadurl" in low:
                pub_url = (
                    field_val.get("value") if isinstance(field_val, dict) else field_val
                )
                break

        if not pub_url and dist_id:
            pub_url = f"{base}/sfc/p/#{dist_id}"

        if not pub_url:
            continue

        try:
            with httpx.Client(verify=False, follow_redirects=True, timeout=10) as http:
                resp = http.get(pub_url)
            if resp.status_code == 200:
                logger.success(
                    f"ContentDistribution public URL accessible: {pub_url} ({len(resp.content):,} bytes)"
                )
                public_hits.append(
                    {
                        "id": dist_id,
                        "url": pub_url,
                        "status": resp.status_code,
                        "size": len(resp.content),
                    }
                )
            else:
                logger.debug(f"ContentDistribution {dist_id}: HTTP {resp.status_code}")
        except Exception:
            logger.exception(f"ContentDistribution URL probe error for {dist_id}")

    if public_hits:
        logger.success(
            f"ContentDistribution: {len(public_hits)} publicly accessible file(s)"
        )
    else:
        logger.info("ContentDistribution: no publicly accessible files found")

    return public_hits


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
        logger.info("No ContentVersion records found, skipping REST probe.")
        return 0

    logger.info(
        f"Probing {len(version_ids)} ContentVersion ID(s) " "via unauthenticated REST"
    )
    critical = probe_rest(aura_url, version_ids)

    if critical:
        logger.success(
            f"{len(critical)} ContentVersion file(s) downloadable without authentication:"
        )
        for vid in critical:
            parsed = urlparse(aura_url)
            logger.success(
                f"  GET {parsed.scheme}://{parsed.netloc}"
                f"/services/data/{REST_API_VERSION}"
                f"/sobjects/ContentVersion/{vid}/VersionData"
            )
    else:
        logger.info("REST probe: no unauthenticated access found.")

    return len(critical)
