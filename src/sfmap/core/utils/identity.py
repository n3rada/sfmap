# Built-in imports
import re
from urllib.parse import urlparse

# Third-party imports
from loguru import logger

# Local imports
from ..client import AuraClient, REST_API_VERSION


def _base_url(aura_url: str) -> str:
    p = urlparse(aura_url)
    return f"{p.scheme}://{p.netloc}"


def _safe(label: str) -> str:
    label = re.sub(r"<[^>]+>", "", label)  # strip HTML tags (Name field comes wrapped)
    label = label.lower().strip()
    label = re.sub(r"[^a-z0-9._@-]", "_", label)
    label = re.sub(r"_+", "_", label).strip("_")
    return label or "authenticated"


def _via_rest(client: AuraClient) -> str | None:
    """GET /services/data/.../chatter/users/me (works when bearer token or REST is enabled)."""
    base = _base_url(client._session.url)
    url = f"{base}/services/data/{REST_API_VERSION}/chatter/users/me"
    try:
        resp = client.rest_get(url) if client.has_bearer else client.get(url)
        if resp.status_code == 200:
            data = resp.json()
            username = data.get("username") or data.get("Username")
            if username:
                logger.debug(f"Identity: resolved via REST /chatter/users/me: {username!r}")
                return username
    except Exception:
        logger.exception("Identity: REST /chatter/users/me failed")
    return None


def _via_lightning_user(client: AuraClient) -> str | None:
    """Call aura://UserController/ACTION$getUserInfoMap (Lightning one:one surface only)."""
    payload = {
        "actions": [{
            "id": "identity;a",
            "descriptor": "aura://UserController/ACTION$getUserInfoMap",
            "callingDescriptor": "UNKNOWN",
            "params": {},
        }]
    }
    try:
        resp = client.aura_post(payload)
        actions = resp.get("actions", [])
        if not actions or actions[0].get("state") != "SUCCESS":
            return None
        rv = actions[0].get("returnValue") or {}
        username = rv.get("userName") or rv.get("username")
        if username:
            logger.debug(f"Identity: resolved via Lightning UserController: {username!r}")
            return username
    except Exception:
        logger.debug("Identity: Lightning UserController not available on this surface")
    return None


def _via_aura_user(client: AuraClient) -> str | None:
    """
    Call SelectableListDataProvider/getItems on the User object.
    In community context this returns only the current user's own record.
    The Name field is HTML-wrapped; _safe() strips the tags.
    """
    payload = {
        "actions": [{
            "id": "identity;a",
            "descriptor": (
                "serviceComponent://ui.force.components.controllers.lists"
                ".selectableListDataProvider.SelectableListDataProviderController/ACTION$getItems"
            ),
            "callingDescriptor": "UNKNOWN",
            "params": {
                "entityNameOrId": "User",
                "layoutType": "FULL",
                "pageSize": 1,
                "currentPage": 0,
                "useTimeout": False,
                "getCount": False,
                "enableRowActions": False,
            },
        }]
    }
    try:
        resp = client.aura_post(payload)
        actions = resp.get("actions", [])
        if not actions or actions[0].get("state") != "SUCCESS":
            return None
        rv = actions[0].get("returnValue") or {}
        result = (rv.get("result") or [{}])[0]
        rec = result.get("record", result)
        fields = rec.get("fields", rec)

        def _field(name: str) -> str | None:
            val = fields.get(name)
            if isinstance(val, dict):
                val = val.get("value")
            return str(val).strip() if val else None

        name = _field("Name")
        if name:
            logger.debug(f"Identity: resolved via User.getItems Name: {name!r}")
            return name
    except Exception:
        logger.debug("Identity: User.getItems not available on this surface")
    return None


def resolve(client: AuraClient) -> str:
    """
    Resolve the current authenticated session to a filesystem-safe identity label.

    Resolution order:
    1. REST /chatter/users/me (bearer or session cookie, works on both surfaces)
    2. Lightning: aura://UserController/ACTION$getUserInfoMap (one:one surface)
    3. EC: SelectableListDataProvider/getItems on User (community surface)
    4. Fallback: "authenticated"
    """
    label = _via_rest(client)
    if label:
        return _safe(label)

    label = _via_lightning_user(client) or _via_aura_user(client)
    if label:
        return _safe(label)

    logger.debug("Identity: could not resolve, using 'authenticated'")
    return "authenticated"


def resolve_with_display(client: AuraClient) -> tuple[str, str]:
    """Return (safe_dir_name, display_name). Display name preserves original casing."""
    raw = _via_rest(client) or _via_lightning_user(client) or _via_aura_user(client)
    if raw:
        display = re.sub(r"<[^>]+>", "", raw).strip()
        return _safe(raw), display
    return "authenticated", "authenticated"


def verify(client: AuraClient) -> None:
    """Make a minimal Aura call to confirm the session token is accepted.
    Raises AuraSessionExpired if the server rejects the token.
    Any non-auth error in the response (permission denied, object not found, etc.)
    is ignored: the token was accepted, which is all we need to know.
    """
    payload = {
        "actions": [{
            "id": "auth;a",
            "descriptor": (
                "serviceComponent://ui.force.components.controllers.lists"
                ".selectableListDataProvider.SelectableListDataProviderController/ACTION$getItems"
            ),
            "callingDescriptor": "UNKNOWN",
            "params": {
                "entityNameOrId": "User",
                "layoutType": "FULL",
                "pageSize": 1,
                "currentPage": 0,
                "useTimeout": False,
                "getCount": False,
                "enableRowActions": False,
            },
        }]
    }
    client.aura_post(payload)


def save_identity_json(
    output_dir: str,
    label: str,
    display: str | None,
    session: "object | None" = None,
) -> None:
    """Write identity.json into the session directory."""
    import json as _json
    from datetime import datetime, timezone
    from pathlib import Path

    data: dict = {
        "label": label,
        "display_name": display or label,
        "type": "guest" if label == "guest" else "authenticated",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    if session is not None:
        if getattr(session, "cookie", None):
            data["has_cookie"] = True
        if getattr(session, "bearer_token", None):
            data["has_bearer"] = True
        url = getattr(session, "url", None)
        if url:
            data["aura_url"] = url

    try:
        p = Path(output_dir)
        p.mkdir(parents=True, exist_ok=True)
        identity_path = p / "identity.json"
        if not identity_path.exists():
            identity_path.write_text(
                _json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
    except Exception:
        logger.exception(f"Could not write identity.json to {output_dir}")
