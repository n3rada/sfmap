# Built-in imports
import json
import os

# Third-party imports
from loguru import logger

# Local imports
from ..client import AuraClient
from . import dump

_OBJECTS = [
    "Network",
    "NetworkMemberGroup",
    "NetworkSelfRegistration",
]

_INTERESTING_FIELDS = {
    "Network": [
        "Name", "UrlPathPrefix", "GuestProfileId", "SelfRegistrationEnabled",
        "AllowedExtensions", "Status", "OptionsAllowMembersToFlag",
        "OptionsAllowInternalUserLogin", "MaxFileSizeKb",
    ],
}


def _get_records(client: AuraClient, obj_name: str) -> list[dict]:
    rv = dump.get_items(client, obj_name, page_size=200, page=1, silent=True)
    if rv is None:
        return []
    return rv.get("result", [])


def _get_full_record(client: AuraClient, record_id: str) -> dict | None:
    """Attempt getRecord for a Network record to retrieve all fields."""
    payload = {
        "actions": [{
            "id": "net;r",
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
    }
    try:
        resp = client.aura_post(payload)
        actions = resp.get("actions", [])
        if actions and actions[0].get("state") == "SUCCESS":
            return actions[0].get("returnValue", {})
    except Exception:
        logger.exception(f"getRecord failed for {record_id}")
    return None


def fetch(client: AuraClient, output_dir: str) -> dict[str, list]:
    """
    Enumerate Experience Cloud network configuration.
    Network.GuestProfileId reveals the profile governing all unauthenticated
    access. NetworkMemberGroup shows which profiles can join the community.
    """
    results: dict[str, list] = {}

    for obj in _OBJECTS:
        records = _get_records(client, obj)
        if records:
            logger.success(f"Network {obj}: {len(records)} record(s) accessible")
            results[obj] = records
        else:
            logger.debug(f"Network {obj}: not accessible or empty")

    if not results:
        logger.info("Network config: no objects accessible via Aura")
        return results

    # Attempt to enrich Network records with full field set via getRecord
    enriched: list[dict] = []
    for rec in results.get("Network", []):
        record_id = rec.get("record", rec).get("Id") or rec.get("Id")
        if not record_id:
            enriched.append(rec)
            continue
        full = _get_full_record(client, record_id)
        if full and not full.get("onLoadErrorMessage"):
            enriched.append(full)
            fields = full.get("fields", {})
            guest_id = (fields.get("GuestProfileId") or {}).get("value")
            name = (fields.get("Name") or {}).get("value") or record_id
            if guest_id:
                logger.success(f"Community '{name}' guest profile ID: {guest_id}")
            self_reg = (fields.get("SelfRegistrationEnabled") or {}).get("value")
            if self_reg:
                logger.success(f"Community '{name}': self-registration is ENABLED")
            allowed_ext = (fields.get("AllowedExtensions") or {}).get("value")
            if allowed_ext:
                logger.info(f"Community '{name}' allowed file extensions: {allowed_ext}")
        else:
            enriched.append(rec)
            logger.debug(f"Network record {record_id}: getRecord layout not supported, using getItems data")
    if enriched:
        results["Network"] = enriched

    os.makedirs(output_dir, exist_ok=True)
    out = os.path.join(output_dir, "network_config.json")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(results, ensure_ascii=False, indent=2))
    logger.info(f"Network config saved to {out}")

    return results
