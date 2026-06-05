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


def list_objects(client: AuraClient) -> dict[str, str]:
    """
    Returns {object_name: key_prefix} for all visible objects.
    Raises on Aura exception or missing data.
    """
    mode = "guest" if client.is_guest else "authenticated"
    response = client.aura_post(PAYLOAD_GET_CONFIG)

    if response.get("exceptionEvent"):
        raise RuntimeError(f"Aura exception: {response}")

    actions = response.get("actions", [])
    if not actions or actions[0].get("state") is None:
        raise RuntimeError(f"Unexpected response: {response}")

    return_value = actions[0].get("returnValue", {})
    prefixes: dict = return_value.get("apiNamesToKeyPrefixes", {})
    logger.debug(f"Fetched object config in {mode} mode")
    return dict(sorted(prefixes.items()))


def list_standard(client: AuraClient) -> dict[str, str]:
    return {k: v for k, v in list_objects(client).items() if not k.endswith("__c")}


def list_custom(client: AuraClient) -> dict[str, str]:
    return {k: v for k, v in list_objects(client).items() if k.endswith("__c")}


def print_objects(client: AuraClient) -> dict[str, str]:
    objects = list_objects(client)
    standard = {k: v for k, v in objects.items() if not k.endswith("__c")}
    custom = {k: v for k, v in objects.items() if k.endswith("__c")}

    logger.success(
        f"Found {len(objects)} objects — {len(standard)} standard | {len(custom)} custom"
    )

    logger.info("Standard objects:")
    for name, prefix in standard.items():
        logger.info(f"  {name:<50} {prefix}")

    if custom:
        logger.warning("Custom objects:")
        for name, prefix in custom.items():
            logger.warning(f"  {name:<50} {prefix}")
    else:
        logger.info("Custom objects: none")

    return objects
