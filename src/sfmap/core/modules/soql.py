# Built-in imports
import json
import os
from urllib.parse import quote_plus, urlparse

# Third-party imports
from loguru import logger

# Local imports
from ..client import AuraClient, REST_API_VERSION

_PROBE_QUERIES: list[tuple[str, str]] = [
    ("User", "SELECT Id, Username, Email, Name, IsActive FROM User LIMIT 50"),
    ("Profile", "SELECT Id, Name, PermissionsApiEnabled, PermissionsModifyAllData FROM Profile LIMIT 50"),
    ("Account", "SELECT Id, Name, Industry, BillingCity, OwnerId FROM Account LIMIT 50"),
    ("Contact", "SELECT Id, FirstName, LastName, Email, Phone, AccountId FROM Contact LIMIT 50"),
    ("Lead", "SELECT Id, Name, Email, Phone, Status, Company FROM Lead LIMIT 50"),
    ("Opportunity", "SELECT Id, Name, Amount, StageName, CloseDate FROM Opportunity LIMIT 50"),
    ("Case", "SELECT Id, Subject, Status, Priority, Description FROM Case LIMIT 50"),
    ("ContentDocument", "SELECT Id, Title, FileType, ContentSize, OwnerId FROM ContentDocument LIMIT 50"),
    ("ContentVersion", "SELECT Id, Title, FileType, ContentSize, CreatedDate FROM ContentVersion LIMIT 50"),
    ("ApexClass", "SELECT Id, Name, Status FROM ApexClass LIMIT 20"),
    ("PermissionSet", "SELECT Id, Name, IsCustom, PermissionsApiEnabled FROM PermissionSet LIMIT 50"),
    ("SetupEntityAccess", "SELECT Id, SetupEntityId, SetupEntityType FROM SetupEntityAccess LIMIT 50"),
]


def _base_url(aura_url: str) -> str:
    parsed = urlparse(aura_url)
    return f"{parsed.scheme}://{parsed.netloc}"


def run(client: AuraClient, aura_url: str, output_dir: str) -> dict[str, int]:
    """
    Run SOQL queries via the REST /services/data/{v}/query endpoint.
    If the endpoint is inaccessible returns an empty dict.
    Returns {object_name: record_count} for each successful query.
    """
    base = _base_url(aura_url)
    endpoint = f"{base}/services/data/{REST_API_VERSION}/query"

    test_url = f"{endpoint}?q={quote_plus('SELECT Id FROM User LIMIT 1')}"
    try:
        resp = client.rest_get(test_url)
    except Exception:
        logger.exception("REST SOQL probe failed")
        return {}

    if resp.status_code not in (200, 201):
        hint = " (pass --bearer for OAuth access)" if not client.has_bearer else ""
        logger.info(f"REST SOQL endpoint not accessible (HTTP {resp.status_code}){hint}")
        return {}

    logger.info("REST SOQL endpoint accessible, running probe queries")
    os.makedirs(output_dir, exist_ok=True)

    results: dict[str, int] = {}

    for obj_name, query in _PROBE_QUERIES:
        url = f"{endpoint}?q={quote_plus(query)}"
        try:
            resp = client.rest_get(url)
            if resp.status_code != 200:
                logger.debug(f"SOQL {obj_name}: HTTP {resp.status_code}")
                continue

            data = resp.json()
            total = data.get("totalSize", 0)
            if total:
                results[obj_name] = total
                logger.warning(f"SOQL {obj_name}: {total} record(s) accessible via REST")
                path = os.path.join(output_dir, f"soql_{obj_name}.json")
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(json.dumps(data, ensure_ascii=False, indent=2))
            else:
                logger.debug(f"SOQL {obj_name}: 0 records")

        except Exception:
            logger.exception(f"SOQL query error for {obj_name}")

    summary_path = os.path.join(output_dir, "soql_summary.json")
    with open(summary_path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(results, ensure_ascii=False, indent=2))

    if results:
        total_records = sum(results.values())
        logger.warning(
            f"REST SOQL: {total_records} record(s) across {len(results)} object(s), "
            f"see {output_dir}/soql_*.json"
        )
    else:
        logger.info("REST SOQL: endpoint accessible but no records returned")

    return results
