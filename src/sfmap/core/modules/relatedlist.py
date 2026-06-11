# Built-in imports
import json
import re
from pathlib import Path

# Third-party imports
from loguru import logger

# Local imports
from ..client import AuraClient
from ..utils.storage import OutputWriter
from . import dump

_DESCRIPTOR = (
    "serviceComponent://ui.force.components.controllers.relatedList"
    ".RelatedListContainerDataProviderController/ACTION$getRecords"
)


def _payload(record_id: str, relationship_names: list[str], num_records: int = 50) -> dict:
    return {
        "actions": [{
            "id": "rl;a",
            "descriptor": _DESCRIPTOR,
            "callingDescriptor": "UNKNOWN",
            "params": {
                "recordId": record_id,
                "relatedListApiNames": relationship_names,
                "numRecordsToShow": num_records,
                "showPartialCount": True,
            },
            "storable": True,
        }]
    }


def _get_object_api_name(client: AuraClient, record_id: str) -> str | None:
    """Resolve the object API name for a record ID via getRecord."""
    resp = client.aura_post({
        "actions": [{
            "id": "rn;a",
            "descriptor": "serviceComponent://ui.force.components.controllers.detail.DetailController/ACTION$getRecord",
            "callingDescriptor": "UNKNOWN",
            "params": {
                "recordId": record_id,
                "record": None,
                "inContextOfComponent": "",
                "mode": "VIEW",
                "layoutType": "FULL",
                "defaultFieldValues": None,
                "navigationLocation": "LIST_VIEW_ROW",
            },
        }]
    })
    actions = resp.get("actions", [])
    if not actions or actions[0].get("state") != "SUCCESS":
        return None
    return actions[0].get("returnValue", {}).get("apiName")


def _get_child_relationships(client: AuraClient, object_api_name: str) -> list[str]:
    """Return relationship names (the __r names) from getObjectInfo."""
    info = dump.get_object_info(client, object_api_name)
    if not info:
        return []
    relationships = info.get("childRelationships", [])
    return [r["relationshipName"] for r in relationships if r.get("relationshipName")]


def _probe_relationship(
    client: AuraClient,
    record_id: str,
    relationship_name: str,
    num_records: int = 50,
) -> dict | None:
    """Call getRecords for a single relationship. Returns the list data or None."""
    resp = client.aura_post(_payload(record_id, [relationship_name], num_records))
    actions = resp.get("actions", [])
    if not actions or actions[0].get("state") != "SUCCESS":
        return None
    rv = actions[0].get("returnValue", {})
    lists = rv.get("lists", [])
    if not lists:
        return None
    return lists[0]


def probe(
    client: AuraClient,
    record_id: str,
    out: OutputWriter,
    object_api_name: str | None = None,
) -> dict[str, int]:
    """
    Enumerate child records for every relationship on a given record.

    1. Resolves the object API name via getRecord (unless provided).
    2. Fetches childRelationships from getObjectInfo.
    3. Calls getRecords per relationship and reports accessible records.

    Returns {relationship_name: record_count} for relationships with data.
    """
    if not object_api_name:
        logger.info(f"Resolving object type for {record_id}")
        object_api_name = _get_object_api_name(client, record_id)
        if not object_api_name:
            logger.warning(f"Could not resolve object type for {record_id}, cannot continue")
            return {}

    logger.info(f"Record {record_id} is {object_api_name}")

    relationships = _get_child_relationships(client, object_api_name)
    if not relationships:
        logger.info(f"{object_api_name}: no child relationships found")
        return {}

    logger.info(f"{object_api_name}: {len(relationships)} child relationship(s) to probe")

    results: dict[str, int] = {}
    findings: dict[str, dict] = {}

    for rel in relationships:
        logger.debug(f"Probing {rel}")
        data = _probe_relationship(client, record_id, rel)
        if data is None:
            logger.debug(f"{rel}: no response")
            continue

        records = data.get("records", {})
        count = records.get("totalCount") or len(records.get("records", []))
        results[rel] = count

        if count:
            logger.success(f"{rel}: {count} record(s) accessible")
            findings[rel] = data
        else:
            logger.debug(f"{rel}: 0 records")

    path = out.save(f"relatedlists_{record_id}.json", {
        "record_id": record_id,
        "object_api_name": object_api_name,
        "results": results,
        "findings": findings,
    })

    hit_count = sum(1 for v in results.values() if v > 0)
    if hit_count:
        logger.success(f"{hit_count}/{len(relationships)} relationship(s) returned data, saved to {path}")
    else:
        logger.info(f"No accessible child records found across {len(relationships)} relationship(s)")

    return results


def sweep(client: AuraClient, out: OutputWriter) -> dict[str, dict[str, int]]:
    """
    Scan output_dir for existing Aura and GraphQL dumps, probe child
    relations from one sample record per object type. Discovers objects
    reachable through relations that enumeration alone would miss.

    Returns {object_name: {relation: count}} for objects with accessible children.
    """
    base = out.path
    samples: dict[str, str] = {}  # object_name -> record_id

    for page_file in sorted(base.glob("*__page1.json")):
        if m := re.match(r"^(.+)__page1\.json$", page_file.name):
            obj_name = m.group(1)
            if obj_name in samples:
                continue
            try:
                data = json.loads(page_file.read_text(encoding="utf-8"))
                result = data.get("result", [])
                if result and isinstance(result[0], dict):
                    record_id = result[0].get("record", {}).get("Id")
                    if record_id:
                        samples[obj_name] = record_id
            except Exception:
                logger.exception(f"Failed to read {page_file}")

    for dump_file in sorted(base.glob("graphql_dump_*.json")):
        obj_name = dump_file.stem.removeprefix("graphql_dump_")
        if obj_name in samples:
            continue
        try:
            data = json.loads(dump_file.read_text(encoding="utf-8"))
            if isinstance(data, list) and data and isinstance(data[0], dict):
                record_id = data[0].get("Id")
                if record_id:
                    samples[obj_name] = record_id
        except Exception:
            logger.exception(f"Failed to read {dump_file}")

    if not samples:
        logger.info("No existing dumps found to follow relations from")
        return {}

    logger.info(f"Following relations from {len(samples)} object type(s)")
    probed: dict[str, dict[str, int]] = {}
    for obj_name, record_id in sorted(samples.items()):
        logger.info(f"Probing {obj_name} ({record_id})")
        results = probe(client, record_id, out, object_api_name=obj_name)
        if any(v > 0 for v in results.values()):
            probed[obj_name] = results

    total_hits = sum(len(v) for v in probed.values())
    if total_hits:
        logger.success(f"Relation sweep: {total_hits} accessible relationship(s) across {len(probed)} object(s)")
    else:
        logger.info("Relation sweep: no accessible child records found")

    return probed
