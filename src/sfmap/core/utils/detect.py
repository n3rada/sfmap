# sfmap/core/utils/detect

# Built-in imports
import json
import re
from urllib.parse import urlparse

# Third-party imports
import httpx
from loguru import logger

# Local imports
from . import autocontext

_LIGHTNING_DUMMY_CONTEXT = {
    "mode": "PROD",
    "fwuid": "INVALID",
    "app": "one:one",
    "loaded": {"APPLICATION@markup://one:one": "INVALID"},
    "dn": [],
    "globals": {},
    "uad": True,
}
_LIGHTNING_DUMMY_ACTION = {
    "id": "1;a",
    "descriptor": "aura://RecordUiController/ACTION$getObjectInfo",
    "callingDescriptor": "UNKNOWN",
    "params": {"objectApiName": "Account"},
}
_GUEST_CONFIGDATA_ACTION = {
    "id": "1;a",
    "descriptor": (
        "serviceComponent://ui.force.components.controllers.lists"
        ".selectableListDataProvider.SelectableListDataProviderController/ACTION$getConfigData"
    ),
    "callingDescriptor": "UNKNOWN",
    "params": {},
}


def _base_url(raw: str) -> str:
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    p = urlparse(raw)
    return f"{p.scheme}://{p.netloc}"


def _aura_post(url: str, context: dict, action: dict, http: httpx.Client) -> httpx.Response | None:
    body = (
        "message=" + json.dumps({"actions": [action]})
        + "&aura.context=" + json.dumps(context)
        + "&aura.token=undefined"
    )
    try:
        return http.post(
            url,
            content=body.encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    except Exception:
        logger.exception(f"detect: POST {url} failed")
        return None


def _fwuid_from_response(text: str) -> str | None:
    if m := re.search(r"Expected:\s*(\S+)\s+Actual", text):
        return m.group(1)
    try:
        obj, _ = json.JSONDecoder().raw_decode(text.lstrip("/*").lstrip())
        if fwuid := obj.get("context", {}).get("fwuid"):
            return fwuid
    except Exception:
        pass
    return None


def _guest_object_count(ec_url: str, context: dict, http: httpx.Client) -> int | None:
    resp = _aura_post(ec_url, context, _GUEST_CONFIGDATA_ACTION, http)
    if not resp:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(resp.text.lstrip("/*").lstrip())
        actions = obj.get("actions", [])
        if actions and actions[0].get("state") == "SUCCESS":
            prefixes = (actions[0].get("returnValue") or {}).get("apiNamesToKeyPrefixes") or {}
            return len(prefixes)
    except Exception:
        pass
    return None


def probe_experience_cloud(raw_url: str, http: httpx.Client) -> dict:
    """Probe the Experience Cloud Aura surface without credentials.

    Returns a dict with keys: found, endpoint, fwuid, app, guest_objects.
    guest_objects is the number of Aura objects visible without authentication,
    or None when the guest probe itself failed.
    """
    base = _base_url(raw_url)
    ec_url = base + "/s/sfsites/aura"
    context: dict | None = None

    for path in ("/s", "/"):
        try:
            resp = http.get(base + path)
            if resp.status_code == 200:
                context = autocontext._context_from_html(resp.text)
                if context:
                    logger.debug(f"detect: EC context from GET {base}{path}")
                    break
        except Exception:
            logger.exception(f"detect: GET {base}{path} failed")

    if not context:
        context = autocontext._context_from_dummy_post(ec_url, http)

    if not context:
        return {"found": False, "endpoint": ec_url}

    return {
        "found": True,
        "endpoint": ec_url,
        "fwuid": context.get("fwuid", ""),
        "app": context.get("app", ""),
        "guest_objects": _guest_object_count(ec_url, context, http),
        "context": context,
    }


def probe_lightning(raw_url: str, http: httpx.Client) -> dict:
    """Probe the Lightning Aura surface without credentials.

    Any non-404 Aura response confirms Lightning is present.
    Returns a dict with keys: found, endpoint, fwuid, app.
    """
    base = _base_url(raw_url)
    lightning_url = base + "/aura"
    resp = _aura_post(lightning_url, _LIGHTNING_DUMMY_CONTEXT, _LIGHTNING_DUMMY_ACTION, http)

    if resp is None or resp.status_code in (404, 410, 503):
        return {"found": False, "endpoint": lightning_url}

    fwuid = _fwuid_from_response(resp.text) or "unknown"
    return {
        "found": True,
        "endpoint": lightning_url,
        "fwuid": fwuid,
        "app": "one:one",
    }
