# Third-party imports
from loguru import logger

# Local imports
from ..client import AuraClient
from ..utils.storage import OutputWriter

_PROBE_MARKER = "sfmap_probe_do_not_use"

_SAVE_DESCRIPTOR = (
    "serviceComponent://ui.force.components.controllers.detail"
    ".DetailController/ACTION$saveRecord"
)
_DELETE_DESCRIPTOR = (
    "serviceComponent://ui.force.components.controllers.detail"
    ".DetailController/ACTION$deleteRecord"
)


def _save_payload(object_name: str, extra_fields: dict | None = None) -> dict:
    fields = {"Name": _PROBE_MARKER}
    if extra_fields:
        fields.update(extra_fields)
    return {
        "actions": [{
            "id": "crud;a",
            "descriptor": _SAVE_DESCRIPTOR,
            "callingDescriptor": "UNKNOWN",
            "params": {
                "recordInput": {"apiName": object_name, "fields": fields},
                "viewedFields": [],
            },
        }]
    }


def _delete_payload(record_id: str) -> dict:
    return {
        "actions": [{
            "id": "crud;d",
            "descriptor": _DELETE_DESCRIPTOR,
            "callingDescriptor": "UNKNOWN",
            "params": {"recordId": record_id},
        }]
    }


def _first_error(actions: list) -> str:
    try:
        return actions[0]["error"][0]["event"]["attributes"]["values"]["message"]
    except (IndexError, KeyError):
        return ""


def probe_object(client: AuraClient, object_name: str) -> dict:
    """
    Probe create and delete access for a single object.
    Cleans up any created record before returning.

    Returns a dict with keys: create, delete, created_id, error.
    """
    result = {"create": False, "delete": False, "created_id": None, "error": None}

    resp = client.aura_post(_save_payload(object_name))
    actions = resp.get("actions", [])
    if not actions:
        result["error"] = "no actions in response"
        return result

    state = actions[0].get("state", "")
    if state == "SUCCESS":
        rv = actions[0].get("returnValue", {})
        record_id = (rv.get("record") or {}).get("id") or (rv.get("id"))
        result["create"] = True
        result["created_id"] = record_id
        logger.success(f"CREATE allowed on {object_name} (id={record_id})")

        if record_id:
            del_resp = client.aura_post(_delete_payload(record_id))
            del_actions = del_resp.get("actions", [])
            if del_actions and del_actions[0].get("state") == "SUCCESS":
                result["delete"] = True
                logger.success(f"DELETE allowed on {object_name}/{record_id}, probe record cleaned up")
            else:
                logger.success(
                    f"DELETE failed for probe record {object_name}/{record_id}, "
                    "manual cleanup may be required"
                )
    else:
        err = _first_error(actions)
        result["error"] = err
        logger.debug(f"{object_name}: create denied: {err[:120]}")

    return result


def probe(
    client: AuraClient,
    objects: dict[str, str],
    out: OutputWriter,
) -> dict[str, dict]:
    """
    Probe create/delete access for each object in *objects*.
    Saves a summary JSON to output_dir.
    Returns {object_name: result_dict} for all objects where create succeeded.
    """
    findings: dict[str, dict] = {}

    for i, obj_name in enumerate(objects, 1):
        logger.debug(f"[{i}/{len(objects)}] CRUD probe: {obj_name}")
        result = probe_object(client, obj_name)
        if result["create"]:
            findings[obj_name] = result

    if findings:
        logger.success(f"{len(findings)} object(s) allow CREATE by this session:")
        for name in findings:
            logger.success(f"  {name}")
    else:
        logger.info("No CREATE access found on any probed object.")

    path = out.save("crud_probe.json", findings)
    logger.info(f"CRUD probe results saved → {path}")

    return findings
