# Built-in imports
from importlib.resources import files as resource_files
from urllib.parse import urlparse

# Third-party imports
from loguru import logger

# Local imports
from ..client import AuraClient
from ..utils.storage import OutputWriter

_METHODS = ("GET", "POST")


def _base_url(aura_url: str) -> str:
    parsed = urlparse(aura_url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _load_wordlist(custom_path: str | None) -> list[str]:
    if custom_path:
        with open(custom_path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    else:
        text = (
            resource_files("sfmap.data")
            .joinpath("apexrest_endpoints.txt")
            .read_text(encoding="utf-8")
        )
        lines = text.splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]


def fuzz(
    client: AuraClient,
    aura_url: str,
    out: OutputWriter,
    wordlist_path: str | None = None,
    methods: tuple[str, ...] = _METHODS,
) -> list[dict]:
    """
    Probe /services/apexrest/{name} for each entry in the wordlist.
    HTTP 404 → not found; any other status → endpoint exists.
    Returns list of hit dicts: {name, url, method, status, response_snippet}.
    """
    base = _base_url(aura_url)
    names = _load_wordlist(wordlist_path)
    hits: list[dict] = []

    logger.info(f"ApexREST fuzzing: {len(names)} endpoint(s) × {len(methods)} method(s)")

    for i, name in enumerate(names, 1):
        for method in methods:
            url = f"{base}/services/apexrest/{name}"
            logger.debug(f"[{i}/{len(names)}] {method} {url}")
            try:
                if method == "GET":
                    resp = client.rest_get(url)
                else:
                    resp = client.rest_post(url, json={})

                sc = resp.status_code
                if sc == 404:
                    continue

                snippet = resp.text[:300].replace("\n", " ").strip()
                hit = {
                    "name": name,
                    "url": url,
                    "method": method,
                    "status": sc,
                    "response_snippet": snippet,
                }
                hits.append(hit)

                if sc == 200:
                    logger.success(f"ApexREST {method} /{name}: HTTP {sc} (accessible)")
                elif sc in (401, 403):
                    logger.info(f"ApexREST {method} /{name}: HTTP {sc} (auth required)")
                elif sc == 400:
                    logger.info(f"ApexREST {method} /{name}: HTTP {sc} (bad request)")
                else:
                    logger.info(f"ApexREST {method} /{name}: HTTP {sc}")

            except Exception:
                logger.exception(f"ApexREST probe error {method} {name}")

    if hits:
        out.save("apexrest_hits.json", hits)

        accessible = [h for h in hits if h["status"] == 200]
        if accessible:
            logger.success(
                f"ApexREST: {len(accessible)}/{len(hits)} endpoint(s) returned HTTP 200 (no auth required)"
            )
        else:
            logger.info(
                f"ApexREST: {len(hits)} endpoint(s) discovered, all require authentication"
            )
    else:
        logger.info("ApexREST: no custom endpoints found")

    return hits
