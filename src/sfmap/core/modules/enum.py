# Third-party imports
from loguru import logger

# Local imports
from ..client import AuraClient

PAYLOAD_GET_CONFIG = {
    "actions": [
        {
            "id": "mar;a",
            "descriptor": "serviceComponent://ui.force.components.controllers.hostConfig.HostConfigController/ACTION$getConfigData",
            "callingDescriptor": "UNKNOWN",
            "params": {},
        }
    ]
}


def _get_config_returnvalue(client: AuraClient) -> dict:
    mode = "guest" if client.is_guest else "authenticated"
    logger.trace(f"getConfigData ({mode})")
    response = client.aura_post(PAYLOAD_GET_CONFIG)
    actions = response.get("actions", [])
    if not actions or actions[0].get("state") is None:
        raise RuntimeError(f"Unexpected response: {response}")
    rv: dict = actions[0].get("returnValue", {})
    prefixes: dict = rv.get("apiNamesToKeyPrefixes", {})
    logger.trace(f"getConfigData → {len(prefixes)} object(s) in {mode} mode")
    logger.debug(f"Fetched object config in {mode} mode")
    return rv


def list_objects(client: AuraClient) -> dict[str, str]:
    """Returns {object_name: key_prefix} for all visible objects."""
    rv = _get_config_returnvalue(client)
    prefixes: dict = rv.get("apiNamesToKeyPrefixes", {})
    return dict(sorted(prefixes.items()))


def list_objects_with_csp(client: AuraClient) -> tuple[dict[str, str], list[str]]:
    """Single getConfigData call returning (objects, csp_trusted_sites)."""
    rv = _get_config_returnvalue(client)
    prefixes: dict = rv.get("apiNamesToKeyPrefixes", {})
    sites: list[str] = rv.get("cspTrustedSites") or []
    if sites:
        logger.success(f"CSP trusted sites ({len(sites)}): {', '.join(str(s) for s in sites)}")
    else:
        logger.debug("No cspTrustedSites in getConfigData")
    return dict(sorted(prefixes.items())), sites


def list_standard(client: AuraClient) -> dict[str, str]:
    return {k: v for k, v in list_objects(client).items() if not k.endswith("__c")}


def list_custom(client: AuraClient) -> dict[str, str]:
    return {k: v for k, v in list_objects(client).items() if k.endswith("__c")}


def _print_objects_from(objects: dict[str, str]) -> None:
    standard = {k: v for k, v in objects.items() if not k.endswith("__c")}
    custom = {k: v for k, v in objects.items() if k.endswith("__c")}
    logger.info(f"Found {len(objects)} objects ({len(standard)} standard, {len(custom)} custom)")
    logger.info("Standard objects:")
    for name, prefix in standard.items():
        logger.info(f"  {name:<50} {prefix}")
    if custom:
        logger.info("Custom objects:")
        for name, prefix in custom.items():
            logger.info(f"  {name:<50} {prefix}")
    else:
        logger.info("Custom objects: none")


def print_objects(client: AuraClient) -> dict[str, str]:
    objects = list_objects(client)
    _print_objects_from(objects)
    return objects
