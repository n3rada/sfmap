# Built-in imports
from urllib.parse import quote_plus

# Third-party imports
from loguru import logger

# Local imports
from ..client import AuraClient, REST_API_VERSION
from ..utils import common, storage

_SOSL_PROBE_TERMS = [
    "admin",
    "user",
    "password",
    "token",
    "secret",
    "key",
    "api",
]

_SOSL_RETURNING = (
    "User(Id, Name, Username, Email) "
    "Account(Id, Name) "
    "Contact(Id, Name, Email) "
    "Lead(Id, Name, Email) "
    "Case(Id, Subject)"
)


def run_sosl(client: AuraClient, aura_url: str, out: storage.OutputWriter) -> dict[str, int]:
    """
    Run SOSL FIND queries via REST /services/data/{v}/search.
    Returns {search_term: total_results} for each term that returned data.
    """
    from urllib.parse import quote_plus as _qp

    base = common.resolve_rest_base_url(aura_url)
    endpoint = f"{base}/services/data/{REST_API_VERSION}/search"

    test_q = f"FIND {{admin}} IN ALL FIELDS RETURNING {_SOSL_RETURNING} LIMIT 5"
    try:
        resp = client.rest_get(f"{endpoint}?q={_qp(test_q)}")
    except Exception:
        logger.exception("REST SOSL probe failed")
        return {}

    if resp.status_code not in (200, 201):
        hint = " (pass --bearer for OAuth access)" if not client.has_bearer else ""
        logger.info(f"REST SOSL endpoint not accessible (HTTP {resp.status_code}){hint}")
        return {}

    logger.info("REST SOSL endpoint accessible, running probe queries")
    results: dict[str, int] = {}

    for term in _SOSL_PROBE_TERMS:
        query = f"FIND {{{term}}} IN ALL FIELDS RETURNING {_SOSL_RETURNING} LIMIT 50"
        try:
            resp = client.rest_get(f"{endpoint}?q={_qp(query)}")
            if resp.status_code != 200:
                logger.debug(f"SOSL {term!r}: HTTP {resp.status_code}")
                continue
            data = resp.json()
            records = data.get("searchRecords", [])
            if records:
                results[term] = len(records)
                logger.success(f"SOSL {term!r}: {len(records)} record(s)")
                out.save(f"sosl_{term}.json", data)
            else:
                logger.debug(f"SOSL {term!r}: 0 records")
        except Exception:
            logger.exception(f"SOSL query error for {term!r}")

    out.save("sosl_summary.json", results)

    if results:
        logger.success(f"REST SOSL: hits on {len(results)} term(s), see {out}/sosl_*.json")
    else:
        logger.info("REST SOSL: endpoint accessible but no records returned")

    return results


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


def run(client: AuraClient, aura_url: str, out: storage.OutputWriter) -> dict[str, int]:
    """
    Run SOQL queries via the REST /services/data/{v}/query endpoint.
    If the endpoint is inaccessible returns an empty dict.
    Returns {object_name: record_count} for each successful query.
    """
    base = common.resolve_rest_base_url(aura_url)
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
                logger.success(f"SOQL {obj_name}: {total} record(s) accessible via REST")
                out.save(f"soql_{obj_name}.json", data)
            else:
                logger.debug(f"SOQL {obj_name}: 0 records")

        except Exception:
            logger.exception(f"SOQL query error for {obj_name}")

    out.save("soql_summary.json", results)

    if results:
        total_records = sum(results.values())
        logger.success(
            f"REST SOQL: {total_records} record(s) across {len(results)} object(s), "
            f"see {out}/soql_*.json"
        )
    else:
        logger.info("REST SOQL: endpoint accessible but no records returned")

    return results
