# Built-in imports
import json
import os
from urllib.parse import urlparse

# Third-party imports
import httpx
from loguru import logger

# Local imports
from ..client import AuraClient

_REST_API_VERSION = "v59.0"

_INTROSPECTION_QUERY = """
{
  __schema {
    queryType { name }
    mutationType { name }
    types {
      name
      kind
      description
      fields(includeDeprecated: true) {
        name
        description
        isDeprecated
        deprecationReason
        type {
          name
          kind
          ofType { name kind ofType { name kind } }
        }
        args {
          name
          description
          type { name kind ofType { name kind } }
          defaultValue
        }
      }
      inputFields {
        name
        type { name kind ofType { name kind } }
        defaultValue
      }
      interfaces { name }
      enumValues(includeDeprecated: true) { name description isDeprecated }
      possibleTypes { name }
    }
  }
}
""".strip()


def _base_url(aura_url: str) -> str:
    parsed = urlparse(aura_url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _via_rest(client: AuraClient, aura_url: str) -> dict | None:
    """Try standard GraphQL introspection via the direct REST endpoint."""
    url = f"{_base_url(aura_url)}/services/data/{_REST_API_VERSION}/graphql"
    try:
        resp = client._http.post(
            url,
            json={"query": _INTROSPECTION_QUERY, "variables": {}},
            headers={"Content-Type": "application/json"},
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("data") or data.get("errors"):
                logger.info(f"GraphQL introspection via REST succeeded ({url})")
                return data
        logger.debug(f"REST GraphQL → HTTP {resp.status_code} (introspection blocked or endpoint requires auth)")
    except Exception as exc:
        logger.debug(f"REST GraphQL probe failed: {exc}")
    return None


def _via_aura(client: AuraClient) -> dict | None:
    """Try GraphQL introspection via Aura executeGraphQL action."""
    payload = {
        "actions": [{
            "id": "gql;a",
            "descriptor": "aura://RecordUiController/ACTION$executeGraphQL",
            "callingDescriptor": "UNKNOWN",
            "params": {
                "queryInput": {
                    "operationName": "Introspection",
                    "query": _INTROSPECTION_QUERY,
                    "variables": {},
                }
            },
        }]
    }
    try:
        resp = client.aura_post(payload)
        actions = resp.get("actions", [])
        if not actions:
            return None
        action = actions[0]
        if action.get("state") == "SUCCESS":
            rv = action.get("returnValue", {})
            logger.info("GraphQL introspection via Aura executeGraphQL succeeded")
            return rv
        errors = action.get("error", [])
        try:
            msg = errors[0]["event"]["attributes"]["values"]["message"]
        except (IndexError, KeyError):
            msg = str(errors)
        logger.debug(f"Aura GraphQL state={action.get('state')}: {msg}")
    except Exception as exc:
        logger.debug(f"Aura GraphQL probe failed: {exc}")
    return None


def introspect(client: AuraClient, aura_url: str, output_dir: str) -> bool:
    """
    Run GraphQL introspection against the target.

    Tries the direct REST endpoint first, then falls back to Aura's
    executeGraphQL action. Saves the raw schema JSON to output_dir.

    Returns True if introspection succeeded, False otherwise.
    """
    logger.info("Attempting GraphQL introspection via REST endpoint")
    schema = _via_rest(client, aura_url)

    if schema is None:
        logger.info("REST introspection failed, retrying via Aura executeGraphQL")
        schema = _via_aura(client)

    if schema is None:
        logger.info(
            "GraphQL introspection is blocked (endpoint may still be usable, "
            "use 'surface exposure' to confirm, then probe manually via Burp)"
        )
        return False

    graphql_dir = os.path.join(output_dir, "graphql")
    os.makedirs(graphql_dir, exist_ok=True)
    path = os.path.join(graphql_dir, "graphql_schema.json")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(schema, ensure_ascii=False, indent=2))
    logger.success(f"GraphQL schema saved → {graphql_dir}/")

    _summarise(schema)
    return True


def _gql_query_payload(object_name: str, first: int = 200, after: str | None = None) -> dict:
    op_name = f"Query{object_name}"
    cursor_arg = f', after: "{after}"' if after else ""
    query = (
        f"query {op_name} {{ uiapi {{ query {{ "
        f"{object_name}(first: {first}{cursor_arg}) {{ "
        f"totalCount edges {{ node {{ Id }} }} "
        f"pageInfo {{ hasNextPage endCursor }} }} }} }} }}"
    )
    return {
        "actions": [{
            "id": "gql;q",
            "descriptor": "aura://RecordUiController/ACTION$executeGraphQL",
            "callingDescriptor": "UNKNOWN",
            "params": {
                "queryInput": {
                    "operationName": op_name,
                    "query": query,
                    "variables": {},
                }
            },
        }]
    }


def query_objects(
    client: AuraClient,
    object_names: list[str],
    output_dir: str,
    page_size: int = 200,
) -> dict[str, int]:
    """
    Query each object via GraphQL uiapi and record how many records are
    returned. Saves raw responses per object. Returns {name: total_count}.
    """
    graphql_dir = os.path.join(output_dir, "graphql")
    os.makedirs(graphql_dir, exist_ok=True)
    results: dict[str, int] = {}

    for i, obj_name in enumerate(object_names, 1):
        logger.debug(f"[{i}/{len(object_names)}] GraphQL query: {obj_name}")
        try:
            resp = client.aura_post(_gql_query_payload(obj_name, first=page_size))
            actions = resp.get("actions", [])
            if not actions or actions[0].get("state") != "SUCCESS":
                logger.debug(f"{obj_name}: GraphQL query failed")
                continue

            rv = actions[0].get("returnValue", {})
            gql_errors = rv.get("errors") or []
            if gql_errors:
                msg = gql_errors[0].get("message", "")
                logger.debug(f"{obj_name}: GraphQL error: {msg}")
                continue

            obj_data = (
                rv.get("data", {})
                  .get("uiapi", {})
                  .get("query", {})
                  .get(obj_name, {})
            )
            total = obj_data.get("totalCount", 0)
            results[obj_name] = total

            if total:
                logger.warning(f"GraphQL {obj_name}: {total} record(s)")
                path = os.path.join(graphql_dir, f"graphql_{obj_name}.json")
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(json.dumps(rv, ensure_ascii=False, indent=2))
            else:
                logger.debug(f"{obj_name}: 0 records via GraphQL")

        except Exception as exc:
            logger.debug(f"GraphQL query error for {obj_name}: {exc}")

    hit_count = sum(1 for v in results.values() if v > 0)
    logger.info(f"GraphQL queries complete: {hit_count}/{len(object_names)} object(s) returned data")
    return results


def _summarise(schema: dict) -> None:
    """Log a quick human-readable summary of exposed types."""
    types_raw = (
        schema.get("data", {}).get("__schema", {}).get("types")
        or schema.get("__schema", {}).get("types")
        or []
    )
    object_types = [
        t["name"] for t in types_raw
        if t.get("kind") == "OBJECT" and not t["name"].startswith("__")
    ]
    if object_types:
        logger.info(f"{len(object_types)} exposed GraphQL object type(s):")
        for name in sorted(object_types):
            logger.info(f"  {name}")
    else:
        logger.info("No object types found in schema (schema may be restricted)")
