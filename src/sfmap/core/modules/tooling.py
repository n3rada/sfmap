# Built-in imports
import json
import os
from urllib.parse import quote_plus, urlparse

# Third-party imports
from loguru import logger

# Local imports
from ..client import AuraClient, REST_API_VERSION

_QUERIES: list[tuple[str, str]] = [
    (
        "ApexClass",
        "SELECT Id, Name, Status, Body FROM ApexClass ORDER BY Name",
    ),
    (
        "ApexTrigger",
        "SELECT Id, Name, TableEnumOrId, Status, Body FROM ApexTrigger ORDER BY Name",
    ),
    (
        "ApexPage",
        "SELECT Id, Name, Markup FROM ApexPage ORDER BY Name",
    ),
    (
        "ApexComponent",
        "SELECT Id, Name, Markup FROM ApexComponent ORDER BY Name",
    ),
]


def _base_url(aura_url: str) -> str:
    parsed = urlparse(aura_url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _query_all(client: AuraClient, endpoint: str, soql: str) -> list[dict]:
    records: list[dict] = []
    url = f"{endpoint}?q={quote_plus(soql)}"
    while url:
        try:
            resp = client.rest_get(url)
        except Exception:
            logger.exception("Tooling query error")
            break
        if resp.status_code != 200:
            logger.debug(f"Tooling query HTTP {resp.status_code}")
            break
        data = resp.json()
        records.extend(data.get("records", []))
        next_url = data.get("nextRecordsUrl")
        url = f"{_base_url(url)}{next_url}" if next_url else None
    return records


def run(client: AuraClient, aura_url: str, output_dir: str) -> dict[str, int]:
    """
    Query Salesforce Tooling API for Apex source code.
    Requires a Bearer token — community sessions are blocked.
    Returns {type_name: record_count}.
    """
    base = _base_url(aura_url)
    endpoint = f"{base}/services/data/{REST_API_VERSION}/tooling/query"

    probe = f"{endpoint}?q={quote_plus('SELECT Id FROM ApexClass LIMIT 1')}"
    try:
        resp = client.rest_get(probe)
    except Exception:
        logger.exception("Tooling API probe failed")
        return {}

    if resp.status_code not in (200, 201):
        hint = " (pass --bearer for OAuth access)" if not client.has_bearer else ""
        logger.info(f"Tooling API not accessible (HTTP {resp.status_code}){hint}")
        return {}

    logger.info("Tooling API accessible, querying Apex source")
    tooling_dir = os.path.join(output_dir, "tooling")
    os.makedirs(tooling_dir, exist_ok=True)

    results: dict[str, int] = {}

    for type_name, soql in _QUERIES:
        records = _query_all(client, endpoint, soql)
        if not records:
            logger.debug(f"Tooling {type_name}: 0 records")
            continue

        results[type_name] = len(records)
        logger.success(f"Tooling {type_name}: {len(records)} record(s) with source accessible")

        path = os.path.join(tooling_dir, f"tooling_{type_name}.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(records, ensure_ascii=False, indent=2))
        logger.info(f"Saved to {path}")

    if results:
        logger.success(
            f"Tooling API: source code for {sum(results.values())} object(s) "
            f"across {len(results)} type(s), see {tooling_dir}/"
        )
    else:
        logger.info("Tooling API: accessible but no Apex source returned")

    return results
