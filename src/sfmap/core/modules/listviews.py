# Built-in imports
from urllib.parse import urlparse

# Third-party imports
from loguru import logger

# Local imports
from ..client import AuraClient
from ..utils import storage


def _chunked_post(client: AuraClient, actions: list[dict], chunk_size: int = 100) -> list[dict]:
    """Send actions in batches, return the flat list of all action response dicts."""
    results: list[dict] = []
    for i in range(0, len(actions), chunk_size):
        chunk = actions[i:i + chunk_size]
        try:
            resp = client.aura_post({"actions": chunk})
            results.extend(resp.get("actions", []))
        except Exception:
            logger.exception(f"List views: batch {i}-{i + len(chunk)} failed")
    return results


def _app_base(aura_url: str) -> str:
    """Derive the community app base from the Aura endpoint URL, e.g. https://host/s"""
    p = urlparse(aura_url)
    # strip /sfsites/aura or /aura suffix, keep the /s prefix
    path = p.path
    for suffix in ("/sfsites/aura", "/aura"):
        if path.endswith(suffix):
            path = path[: -len(suffix)]
            break
    return f"{p.scheme}://{p.netloc}{path.rstrip('/')}"


def sweep(client: AuraClient, objects: list[str], out: storage.OutputWriter) -> list[str]:
    """
    Enumerate which objects have accessible UI list views in the community.

    Two-pass approach:
    1. getInitialListViews for all objects (batched): find objects with at least one list view
    2. getItems via ListViewDataManager on each view: confirm record access and collect the UI URL

    Returns a list of browsable community UI URLs (e.g. https://host/s/recordlist/Account/Default).
    """
    if not objects:
        return []

    app_base = _app_base(client._session.url)

    # Pass 1: check which objects have list views
    actions_p1 = [
        {
            "id": obj,
            "descriptor": (
                "serviceComponent://ui.force.components.controllers.lists"
                ".listViewPickerDataProvider.ListViewPickerDataProviderController"
                "/ACTION$getInitialListViews"
            ),
            "callingDescriptor": "UNKNOWN",
            "params": {"scope": obj, "maxMruResults": 10, "maxAllResults": 20},
        }
        for obj in objects
    ]

    logger.info(f"List views: checking {len(objects)} object(s) for accessible views (2 passes)")
    responses_p1 = _chunked_post(client, actions_p1)

    objects_with_views: dict[str, list[str]] = {}
    for action in responses_p1:
        obj = action.get("id", "")
        if action.get("state") != "SUCCESS":
            continue
        views = (action.get("returnValue") or {}).get("listViews", [])
        filter_names = [v["name"] for v in views if v.get("name")]
        if filter_names:
            objects_with_views[obj] = filter_names

    if not objects_with_views:
        logger.info("List views: no objects with accessible list views")
        return []

    logger.debug(f"List views: {len(objects_with_views)} object(s) have list view definitions")

    # Pass 2: confirm actual record access via getItems
    actions_p2 = [
        {
            "id": f"{obj};{fname}",
            "descriptor": (
                "serviceComponent://ui.force.components.controllers.lists"
                ".listViewDataManager.ListViewDataManagerController/ACTION$getItems"
            ),
            "callingDescriptor": "UNKNOWN",
            "params": {
                "filterName": fname,
                "entityName": obj,
                "pageSize": 50,
                "layoutType": "LIST",
                "getCount": True,
                "enableRowActions": False,
                "offset": 0,
            },
        }
        for obj, fnames in objects_with_views.items()
        for fname in fnames
    ]

    responses_p2 = _chunked_post(client, actions_p2)

    accessible_urls: list[str] = []
    seen_objects: set[str] = set()

    for action in responses_p2:
        action_id = action.get("id", "")
        if ";" not in action_id:
            continue
        obj, fname = action_id.split(";", 1)
        if action.get("state") != "SUCCESS":
            continue
        rv = action.get("returnValue") or {}
        # recordIdActionsList is non-empty when records are actually returned
        if rv.get("recordIdActionsList"):
            url = f"{app_base}/recordlist/{obj}/Default"
            if obj not in seen_objects:
                seen_objects.add(obj)
                accessible_urls.append(url)
                logger.success(f"List view accessible: {url} ({obj}/{fname})")

    if not accessible_urls:
        logger.info("List views: no accessible record lists found")
        return []

    path = out.save("listviews.json", {"accessible_urls": accessible_urls, "objects": sorted(seen_objects)})
    logger.info(f"List views saved to {path}")

    return accessible_urls
