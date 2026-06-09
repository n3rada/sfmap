# Built-in imports
import json
import os
from urllib.parse import urlparse

# Third-party imports
from loguru import logger

# Local imports
from ..client import AuraClient, REST_API_VERSION

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
    url = f"{_base_url(aura_url)}/services/data/{REST_API_VERSION}/graphql"
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
    except Exception:
        logger.exception("REST GraphQL probe failed")
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
    except Exception:
        logger.exception("Aura GraphQL probe failed")
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
    logger.info(f"GraphQL schema saved → {graphql_dir}/")

    _summarise(schema)
    return True


def _fields_to_gql(fields: list[str]) -> str:
    """
    Convert dot-notation field specs to GraphQL fragment strings.
    "Name"         → "Name { value }"
    "Profile.Name" → "Profile { Name { value } }"
    """
    def _wrap(parts: list[str]) -> str:
        if len(parts) == 1:
            return f"{parts[0]} {{ value }}"
        return f"{parts[0]} {{ {_wrap(parts[1:])} }}"

    return " ".join(_wrap(f.split(".")) for f in fields)


def _gql_dump_payload(
    object_name: str,
    fields: list[str],
    first: int = 200,
    after: str | None = None,
) -> dict:
    op_name = f"Query{object_name.replace('__', '')}"
    cursor_arg = f', after: "{after}"' if after else ""
    field_frag = _fields_to_gql(fields)
    query = (
        f"query {op_name} {{ uiapi {{ query {{ "
        f"{object_name}(first: {first}{cursor_arg}) {{ "
        f"totalCount edges {{ node {{ Id {field_frag} }} }} "
        f"pageInfo {{ hasNextPage endCursor }} }} }} }} }}"
    )
    return {
        "actions": [{
            "id": "gql;d",
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


def dump_object(
    client: AuraClient,
    object_name: str,
    fields: list[str],
    output_dir: str,
    page_size: int = 200,
) -> list[dict]:
    """
    Query *object_name* via GraphQL uiapi requesting *fields* (dot notation).
    Paginates until exhausted. Returns all node dicts.
    Saves raw pages to output_dir/graphql_dump_{object_name}.json.
    """
    all_nodes: list[dict] = []
    after: str | None = None
    page = 0

    while True:
        page += 1
        payload = _gql_dump_payload(object_name, fields, first=page_size, after=after)
        try:
            resp = client.aura_post(payload)
        except Exception:
            logger.exception(f"GraphQL dump error {object_name} page {page}")
            break

        actions = resp.get("actions", [])
        if not actions or actions[0].get("state") != "SUCCESS":
            logger.debug(f"{object_name}: GraphQL dump failed on page {page}")
            break

        rv = actions[0].get("returnValue", {})
        gql_errors = rv.get("errors") or []
        if gql_errors:
            for e in gql_errors:
                logger.warning(f"{object_name}: GraphQL error: {e.get('message', '')}")
            break

        obj_data = (
            rv.get("data", {})
              .get("uiapi", {})
              .get("query", {})
              .get(object_name, {})
        )
        total = obj_data.get("totalCount", 0)
        edges = obj_data.get("edges", [])
        nodes = [e.get("node", {}) for e in edges]
        all_nodes.extend(nodes)

        page_info = obj_data.get("pageInfo", {})
        logger.debug(f"{object_name}: page {page}, got {len(nodes)} records (total={total})")

        if not page_info.get("hasNextPage"):
            break
        after = page_info.get("endCursor")

    if all_nodes:
        logger.success(f"{object_name}: {len(all_nodes)} record(s) accessible via GraphQL dump")
        os.makedirs(output_dir, exist_ok=True)
        path = os.path.join(output_dir, f"graphql_dump_{object_name}.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(all_nodes, ensure_ascii=False, indent=2))
        logger.info(f"Saved to {path}")
    else:
        logger.info(f"{object_name}: no records returned")

    return all_nodes


_SCALAR_TYPES = {
    "String", "Boolean", "Integer", "Double", "Date", "DateTime",
    "Email", "Phone", "Url", "TextArea", "LongTextArea", "Picklist",
    "Currency", "Percent", "AutoNumber",
}

# Used when getObjectInfo is blocked — covers fields present on nearly all objects
_FALLBACK_FIELDS = ["Name", "CreatedDate", "LastModifiedDate", "Description", "Status"]


def autodump(
    client: AuraClient,
    output_dir: str,
    object_names: list[str] | None = None,
    max_fields: int = 30,
) -> dict[str, int]:
    """
    For each object (auto-detected via GraphQL query sweep if none given),
    discover scalar fields via getObjectInfo and run dump_object.
    Returns {object_name: record_count}.
    """
    from . import dump as _dump
    from . import enum as _enum

    if not object_names:
        all_objects = _enum.list_objects(client)
        logger.info(f"GraphQL autodump: scanning {len(all_objects)} object(s) for accessible records")
        counts = query_objects(client, list(all_objects.keys()), output_dir)
        object_names = [name for name, count in counts.items() if count > 0]

    if not object_names:
        logger.info("GraphQL autodump: no objects with accessible records")
        return {}

    logger.info(f"GraphQL autodump: {len(object_names)} object(s) with data, fetching field metadata")

    results: dict[str, int] = {}
    for obj_name in object_names:
        info = _dump.get_object_info(client, obj_name)
        if info:
            fields_meta = info.get("fields", {})
            fields = [
                name for name, meta in fields_meta.items()
                if meta.get("dataType") in _SCALAR_TYPES and name != "Id"
            ][:max_fields]
        else:
            logger.debug(f"GraphQL autodump {obj_name}: getObjectInfo blocked, using fallback fields")
            fields = _FALLBACK_FIELDS

        if not fields:
            logger.debug(f"GraphQL autodump {obj_name}: no fields to query")
            continue

        logger.info(f"GraphQL autodump {obj_name}: querying {len(fields)} field(s)")
        nodes = dump_object(client, obj_name, fields, output_dir)
        if nodes:
            results[obj_name] = len(nodes)

    hit_count = len(results)
    total = sum(results.values())
    if results:
        logger.success(f"GraphQL autodump: {total} record(s) across {hit_count} object(s)")
    else:
        logger.info("GraphQL autodump: no records returned")

    return results


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
                logger.success(f"GraphQL {obj_name}: {total} record(s)")
                path = os.path.join(graphql_dir, f"graphql_{obj_name}.json")
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(json.dumps(rv, ensure_ascii=False, indent=2))
            else:
                logger.debug(f"{obj_name}: 0 records via GraphQL")

        except Exception:
            logger.exception(f"GraphQL query error for {obj_name}")

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
