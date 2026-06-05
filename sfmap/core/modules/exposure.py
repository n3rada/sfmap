# Built-in imports
import re
from urllib.parse import urljoin, urlparse

# Third-party imports
from loguru import logger

# Local imports
from ..client import AuraClient
from ..session import Session
from ..utils import storage

_REST_API_VERSION = "v59.0"


def _base_url(aura_url: str) -> str:
    parsed = urlparse(aura_url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _infer_app_url(aura_url: str) -> str:
    parsed = urlparse(aura_url)
    path = parsed.path
    if "/s/sfsites/aura" in path:
        app_path = path.split("/s/sfsites/aura", 1)[0] + "/s"
    elif path.endswith("/aura"):
        app_path = path[: -len("/aura")] or "/"
    else:
        app_path = "/s"
    return f"{parsed.scheme}://{parsed.netloc}{app_path}"


def _action(act_id: str, descriptor: str, params: dict) -> dict:
    return {
        "actions": [{
            "id": act_id,
            "descriptor": descriptor,
            "callingDescriptor": "UNKNOWN",
            "params": params,
        }]
    }


def check_self_registration(client: AuraClient) -> dict:
    result = {
        "enabled": False,
        "url": None,
        "error": None,
    }
    try:
        enabled_resp = client.aura_post(_action(
            "selfreg_enabled",
            "apex://applauncher.LoginFormController/ACTION$getIsSelfRegistrationEnabled",
            {},
        ))
        url_resp = client.aura_post(_action(
            "selfreg_url",
            "apex://applauncher.LoginFormController/ACTION$getSelfRegistrationUrl",
            {},
        ))

        enabled_actions = enabled_resp.get("actions", [])
        url_actions = url_resp.get("actions", [])

        if enabled_actions and enabled_actions[0].get("state") == "SUCCESS":
            result["enabled"] = bool(enabled_actions[0].get("returnValue"))

        if url_actions and url_actions[0].get("state") == "SUCCESS":
            result["url"] = url_actions[0].get("returnValue")

        if result["enabled"]:
            logger.warning(f"Self-registration enabled: {result['url']}")
        else:
            logger.info("Self-registration is not enabled")

    except Exception as exc:
        result["error"] = str(exc)
        logger.debug(f"Self-registration check failed: {exc}")

    return result


def check_graphql(client: AuraClient) -> dict:
    result = {
        "enabled": False,
        "usable": False,
        "error": None,
    }
    payload = _action(
        "graphql",
        "aura://RecordUiController/ACTION$executeGraphQL",
        {
            "queryInput": {
                "operationName": "getUsersCount",
                "query": "query getUsersCount{uiapi{query{User{totalCount}}}}",
                "variables": {},
            }
        },
    )
    try:
        resp = client.aura_post(payload)
        actions = resp.get("actions", [])
        if not actions:
            return result

        action = actions[0]
        if action.get("state") == "SUCCESS":
            result["enabled"] = True
            rv = action.get("returnValue", {})
            errors = rv.get("errors") or []
            result["usable"] = len(errors) == 0

        if result["enabled"] and result["usable"]:
            logger.warning("GraphQL is enabled and usable")
        elif result["enabled"]:
            logger.info("GraphQL endpoint exists but appears restricted")
        else:
            logger.info("GraphQL not available")

    except Exception as exc:
        result["error"] = str(exc)
        logger.debug(f"GraphQL check failed: {exc}")

    return result


def check_rest_api(client: AuraClient, aura_url: str) -> dict:
    base = _base_url(aura_url)
    result = {
        "version_listing_exposed": False,
        "latest_url": None,
        "accessible_with_session": False,
        "error": None,
    }

    try:
        listing = client.get(f"{base}/services/data")
        if listing.status_code == 200:
            result["version_listing_exposed"] = True
            versions = listing.json()
            if isinstance(versions, list) and versions:
                latest_url = versions[-1].get("url")
                if latest_url:
                    result["latest_url"] = latest_url

        if result["latest_url"]:
            latest = client.get(f"{base}{result['latest_url']}")
            result["accessible_with_session"] = latest.status_code == 200

        if result["version_listing_exposed"]:
            logger.warning("REST /services/data listing is exposed")
        else:
            logger.info("REST /services/data listing is not exposed")

    except Exception as exc:
        result["error"] = str(exc)
        logger.debug(f"REST check failed: {exc}")

    return result


def check_soap_api(client: AuraClient, aura_url: str) -> dict:
    base = _base_url(aura_url)
    result = {
        "exposed": False,
        "status_code": None,
        "error": None,
    }
    try:
        resp = client.get(f"{base}/services/Soap/u/{_REST_API_VERSION}")
        result["status_code"] = resp.status_code
        content_type = (resp.headers.get("Content-Type") or "").lower()
        result["exposed"] = resp.status_code in (200, 500) and "xml" in content_type
        if result["exposed"]:
            logger.warning("SOAP API endpoint appears exposed")
        else:
            logger.info("SOAP API endpoint does not appear exposed")
    except Exception as exc:
        result["error"] = str(exc)
        logger.debug(f"SOAP check failed: {exc}")

    return result


def discover_custom_controllers(client: AuraClient, aura_url: str) -> dict[str, list[str]]:
    app_url = _infer_app_url(aura_url)
    controllers: dict[str, list[str]] = {}

    endpoint_pattern = re.compile(r'(?:src|href)=["\']([^"\']+)["\']', re.IGNORECASE)
    aura_cmd_def_pattern = re.compile(r'/auraCmdDef\?[^"\']+', re.IGNORECASE)
    controller_pattern = re.compile(r'apex://[A-Za-z0-9_-]+/ACTION\$[A-Za-z0-9_-]+')

    try:
        seed = client.get(app_url)
    except Exception as exc:
        logger.debug(f"Custom controller discovery seed failed: {exc}")
        return controllers

    text = seed.text
    endpoints = set(endpoint_pattern.findall(text))
    endpoints.update(aura_cmd_def_pattern.findall(text))

    parsed = urlparse(app_url)
    host = parsed.netloc

    checked = 0
    for endpoint in sorted(endpoints):
        if checked >= 40:
            break
        abs_url = urljoin(app_url, endpoint)
        if urlparse(abs_url).netloc != host:
            continue
        checked += 1
        try:
            resp = client.get(abs_url)
        except Exception:
            continue

        hits = sorted(set(controller_pattern.findall(resp.text)))
        if hits:
            controllers[abs_url] = hits

    count = sum(len(v) for v in controllers.values())
    if count:
        logger.warning(f"Found {count} custom Apex controller descriptor(s)")
    else:
        logger.info("No custom Apex controller descriptors found")

    return controllers


def run(client: AuraClient, session: Session, output_dir: str | None = None) -> dict:
    summary = {
        "self_registration": check_self_registration(client),
        "rest_api": check_rest_api(client, session.url),
        "soap_api": check_soap_api(client, session.url),
        "graphql": check_graphql(client),
        "custom_controllers": discover_custom_controllers(client, session.url),
    }

    if output_dir:
        path = f"{output_dir}/exposure_summary.json"
        storage.save_json(path, summary)
        logger.success(f"Saved exposure summary to {path}")

    return summary
