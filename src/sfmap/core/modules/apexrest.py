# Built-in imports
import json
import os
from importlib.resources import files as resource_files
from urllib.parse import urlparse

# Third-party imports
from loguru import logger

# Local imports
from ..client import AuraClient

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
    output_dir: str,
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
                    resp = client._http.get(url)
                else:
                    resp = client._http.post(url, json={})

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
                    logger.warning(f"ApexREST {method} /{name}: HTTP {sc} — ACCESSIBLE")
                elif sc in (401, 403):
                    logger.info(f"ApexREST {method} /{name}: HTTP {sc} — exists (auth required)")
                elif sc == 400:
                    logger.info(f"ApexREST {method} /{name}: HTTP {sc} — exists (bad request)")
                else:
                    logger.info(f"ApexREST {method} /{name}: HTTP {sc}")

            except Exception as exc:
                logger.debug(f"ApexREST probe error {method} {name}: {exc}")

    if hits:
        os.makedirs(output_dir, exist_ok=True)
        path = os.path.join(output_dir, "apexrest_hits.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(hits, ensure_ascii=False, indent=2))

        accessible = [h for h in hits if h["status"] == 200]
        if accessible:
            logger.warning(
                f"ApexREST: {len(accessible)}/{len(hits)} endpoint(s) returned HTTP 200 (no auth required)"
            )
        else:
            logger.info(
                f"ApexREST: {len(hits)} endpoint(s) discovered — all require authentication"
            )
    else:
        logger.info("ApexREST: no custom endpoints found")

    return hits
