# Built-in imports
import json
import os

# Third-party imports
from loguru import logger

# Local imports
from ..client import AuraClient


def fetch(client: AuraClient, output_dir: str) -> dict[str, str]:
    """
    Fetch bootstrap data via CMCAppController.

    Returns a dict mapping object API name to its community home URL,
    e.g. {"Account": "/s/account"}.
    These are UI-level object list views that are directly browsable in the community.
    """
    payload = {
        "actions": [{
            "id": "bootstrap;a",
            "descriptor": (
                "serviceComponent://ui.communities.components.aura.components"
                ".communitySetup.cmc.CMCAppController/ACTION$getAppBootstrapData"
            ),
            "callingDescriptor": "UNKNOWN",
            "params": {},
        }]
    }
    try:
        resp = client.aura_post(payload)
        actions = resp.get("actions", [])
        if not actions:
            logger.debug("Bootstrap: no actions in response")
            return {}
        action = actions[0]
        if action.get("state") != "SUCCESS":
            errs = action.get("error", [])
            try:
                msg = errs[0]["event"]["attributes"]["values"]["message"]
            except (IndexError, KeyError, TypeError):
                msg = str(errs)
            logger.debug(f"Bootstrap: state={action.get('state')} — {msg}")
            return {}

        rv = action.get("returnValue", {})
        home_urls: dict[str, str] = {}
        for comp in rv.get("components", []):
            urls = comp.get("model", {}).get("apiNameToObjectHomeUrls", {})
            home_urls.update(urls)

    except Exception:
        logger.exception("Bootstrap: CMCAppController fetch failed")
        return {}

    if not home_urls:
        logger.info("Bootstrap: no object home URLs returned")
        return {}

    logger.success(f"Bootstrap: {len(home_urls)} object home URL(s) accessible")
    for obj, url in sorted(home_urls.items()):
        logger.info(f"  {obj}: {url}")

    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "bootstrap_urls.json")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(home_urls, ensure_ascii=False, indent=2))
    logger.info(f"Bootstrap URLs saved to {path}")

    return home_urls
