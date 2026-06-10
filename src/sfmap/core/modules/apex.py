# Built-in imports
import re
from importlib import resources
from pathlib import Path
from urllib.parse import urljoin, urlparse

# Third-party imports
from loguru import logger

# Local imports
from ..client import AuraClient

_APEX_RE = re.compile(r'apex://[A-Za-z0-9_.]+/ACTION\$[A-Za-z0-9_]+')


def _build_descriptor(controller: str, method: str = "invoke") -> str:
    if controller.startswith("apex://"):
        return controller
    return f"apex://{controller}/ACTION${method}"


def _payload(descriptor: str, params: dict | None = None) -> dict:
    return {
        "actions": [{
            "id": "mar;a",
            "descriptor": descriptor,
            "callingDescriptor": "UNKNOWN",
            "params": params or {},
        }]
    }


def _load_controllers(wordlist_path: str | Path | None) -> list[str]:
    if wordlist_path is not None:
        wordlist = Path(wordlist_path)
        if not wordlist.exists():
            raise FileNotFoundError(f"Wordlist not found: {wordlist}")
        content = wordlist.read_text(encoding="utf-8")
    else:
        resource = resources.files("sfmap").joinpath("data/apex_controllers.txt")
        content = resource.read_text(encoding="utf-8")

    return [
        line.strip()
        for line in content.splitlines()
        if line.strip() and not line.startswith("#")
    ]


def _first_error_message(errors: list) -> str:
    try:
        return errors[0]["event"]["attributes"]["values"]["message"]
    except (IndexError, KeyError):
        return ""


def _extract_from_text(text: str) -> set[str]:
    return set(_APEX_RE.findall(text))


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


def discover(client: AuraClient, aura_url: str, output_dir: str | None = None) -> list[str]:
    """
    Multi-source Apex ACTION descriptor discovery.

    Sources:
      1. App HTML page and all linked JS bundles (no endpoint cap)
      2. Any *.js files already downloaded under output_dir (static resources, etc.)

    Returns sorted, deduplicated list of apex:// descriptors.
    """
    found: set[str] = set()
    app_url = _infer_app_url(aura_url)
    host = urlparse(app_url).netloc

    # Source 1: app HTML + all linked JS files
    try:
        seed = client.get(app_url)
        found.update(_extract_from_text(seed.text))

        src_re = re.compile(r'(?:src|href)=["\']([^"\']+)["\']', re.IGNORECASE)
        for raw in src_re.findall(seed.text):
            abs_url = urljoin(app_url, raw)
            if urlparse(abs_url).netloc != host:
                continue
            try:
                resp = client.get(abs_url)
                hits = _extract_from_text(resp.text)
                if hits:
                    logger.debug(f"JS bundle {abs_url}: {len(hits)} descriptor(s)")
                    found.update(hits)
            except Exception:
                logger.exception(f"Failed to fetch JS bundle: {abs_url}")
    except Exception:
        logger.exception("App page fetch failed")

    # Source 2: local JS files already on disk
    if output_dir:
        for js_file in Path(output_dir).rglob("*.js"):
            try:
                text = js_file.read_text(encoding="utf-8", errors="ignore")
                hits = _extract_from_text(text)
                if hits:
                    logger.debug(f"Local file {js_file.name}: {len(hits)} descriptor(s)")
                    found.update(hits)
            except Exception:
                logger.exception(f"Failed to read local JS file: {js_file}")

    result = sorted(found)
    logger.info(f"Discovered {len(result)} unique Apex ACTION descriptor(s) across all sources")
    return result


def probe(client: AuraClient, descriptors: list[str]) -> dict[str, str]:
    """
    Call each descriptor with empty params and categorize the server response.

    Categories:
      callable      - server returned SUCCESS
      exists_denied - server returned ACCESS_DENIED (confirms existence)
      not_found     - no such controller or action
      error         - HTTP or parse failure
    """
    results: dict[str, str] = {}

    for i, descriptor in enumerate(descriptors, 1):
        logger.debug(f"[{i}/{len(descriptors)}] {descriptor}")
        try:
            response = client.aura_post(_payload(descriptor))
        except Exception:
            logger.exception(f"HTTP error probing {descriptor}")
            results[descriptor] = "error"
            continue

        if response.get("exceptionEvent"):
            results[descriptor] = "error"
            continue

        actions = response.get("actions", [])
        if not actions:
            results[descriptor] = "error"
            continue

        state = actions[0].get("state", "")
        msg = _first_error_message(actions[0].get("error", []))

        if state == "SUCCESS":
            logger.success(f"Callable: {descriptor}")
            results[descriptor] = "callable"
        elif "ACCESS_DENIED" in msg or "access" in msg.lower():
            logger.info(f"Exists (access denied): {descriptor}")
            results[descriptor] = "exists_denied"
        elif "No ACTION" in msg or "No such" in msg or "No COMPONENT" in msg:
            results[descriptor] = "not_found"
        else:
            logger.debug(f"Unknown: state={state} msg={msg[:80]}")
            results[descriptor] = "error"

    return results


def fuzz(client: AuraClient, wordlist_path: str | Path | None,
         method: str = "invoke", stop_on_first: bool = False) -> list[str]:
    """
    Fuzz ApexController names from wordlist.
    Returns descriptors that exist (callable or access-denied).
    """
    controllers = _load_controllers(wordlist_path)
    hits: list[str] = []

    for i, controller in enumerate(controllers, 1):
        descriptor = _build_descriptor(controller, method)
        logger.debug(f"[{i}/{len(controllers)}] {descriptor}")

        try:
            response = client.aura_post(_payload(descriptor))
        except Exception:
            logger.exception(f"HTTP error on {descriptor}")
            continue

        if response.get("exceptionEvent"):
            logger.debug(f"{descriptor}: Aura exception (skip)")
            continue

        actions = response.get("actions", [])
        if not actions:
            logger.debug(f"{descriptor}: no actions in response (skip)")
            continue

        state = actions[0].get("state", "")
        error_msg = _first_error_message(actions[0].get("error", []))

        if state == "SUCCESS":
            logger.success(f"Callable descriptor: {descriptor}")
            hits.append(descriptor)
        elif "ACCESS_DENIED" in error_msg or "access" in error_msg.lower():
            logger.info(f"{descriptor}: exists, access denied")
            hits.append(descriptor)
        elif "No ACTION" in error_msg or "No such" in error_msg:
            logger.debug(f"Not found: {descriptor}")
        else:
            logger.debug(f"{descriptor}: state={state} | {error_msg[:80]}")

        if stop_on_first and hits:
            break

    return hits
