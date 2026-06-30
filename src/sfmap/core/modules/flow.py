# Built-in imports
from importlib.resources import files as resource_files

# Third-party imports
from loguru import logger

# Local imports
from ..client import AuraClient
from ..utils import storage

_DESCRIPTOR = (
    "serviceComponent://ui.flow.components.controllers.InterviewController"
    "/ACTION$getFlowUIMetadata"
)


def _load_wordlist(custom_path: str | None) -> list[str]:
    if custom_path:
        with open(custom_path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    else:
        text = resource_files("sfmap.data").joinpath("flows.txt").read_text(encoding="utf-8")
        lines = text.splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]


def _probe(client: AuraClient, flow_name: str) -> dict | None:
    """
    Probe a flow via getFlowUIMetadata.
    Returns the returnValue dict on SUCCESS, {"_error": msg} if the flow
    exists but access is denied, or None if the flow is not found.
    """
    payload = {
        "actions": [{
            "id": "flw;a",
            "descriptor": _DESCRIPTOR,
            "callingDescriptor": "UNKNOWN",
            "params": {"flowApiName": flow_name},
        }]
    }
    try:
        resp = client.aura_post(payload)
    except Exception:
        logger.exception(f"Flow probe error {flow_name}")
        return None

    actions = resp.get("actions", [])
    if not actions:
        return None

    action = actions[0]
    if action.get("state") == "SUCCESS":
        return action.get("returnValue") or {}

    errors = action.get("error", [])
    if not errors:
        return None

    try:
        msg = errors[0]["event"]["attributes"]["values"]["message"]
    except (IndexError, KeyError, TypeError):
        msg = str(errors[0]) if errors else ""

    low = msg.lower()
    if any(phrase in low for phrase in ("not found", "does not exist", "no flow", "invalid flow")):
        return None

    return {"_error": msg}


def fuzz(client: AuraClient, out: storage.OutputWriter, wordlist_path: str | None = None) -> list[dict]:
    """
    Wordlist-fuzz Flow API names via InterviewController/ACTION$getFlowUIMetadata.
    SUCCESS → flow fully accessible (metadata returned).
    Error that is not "not found" → flow exists but execution is restricted.
    Returns a list of hit dicts saved to flow_hits.json.
    """
    names = _load_wordlist(wordlist_path)
    logger.info(f"Flow fuzz: {len(names)} name(s) to probe")

    hits: list[dict] = []

    for name in names:
        logger.debug(f"Probing flow: {name}")
        result = _probe(client, name)
        if result is None:
            continue

        if result.get("_error"):
            logger.success(f"Flow exists (restricted): {name} ({result['_error']})")
        else:
            screens = result.get("screens") or result.get("nodes") or []
            logger.success(f"Flow accessible: {name} ({len(screens)} screen(s) exposed)")

        hits.append({"flow_api_name": name, "metadata": result})

    path = out.save("flow_hits.json", hits)

    if hits:
        logger.success(f"Flow fuzz: {len(hits)} flow(s) found, saved to {path}")
    else:
        logger.info("Flow fuzz: no flows found")

    return hits
