# Built-in imports
from pathlib import Path

# Third-party imports
from loguru import logger

# Local imports
from ..client import AuraClient


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


def fuzz(client: AuraClient, wordlist_path: str | Path,
         method: str = "invoke", stop_on_first: bool = False) -> list[str]:
    """
    Fuzz ApexController names from wordlist.
    Returns a list of descriptors that did NOT return an ACCESS_DENIED or
    NO_SUCH_ACTION error — i.e. the controller/method exists and is callable.
    """
    wordlist = Path(wordlist_path)
    if not wordlist.exists():
        raise FileNotFoundError(f"Wordlist not found: {wordlist}")

    controllers = [l.strip() for l in wordlist.read_text(encoding="utf-8").splitlines()
                   if l.strip() and not l.startswith("#")]

    hits: list[str] = []

    for i, controller in enumerate(controllers, 1):
        descriptor = _build_descriptor(controller, method)
        logger.debug(f"[{i}/{len(controllers)}] {descriptor}")

        try:
            response = client.aura_post(_payload(descriptor))
        except Exception as e:
            logger.warning(f"HTTP error on {descriptor}: {e}")
            continue

        if response.get("exceptionEvent"):
            logger.debug(f"{descriptor}: Aura exception (skip)")
            continue

        actions = response.get("actions", [])
        if not actions:
            logger.debug(f"{descriptor}: no actions in response (skip)")
            continue

        state = actions[0].get("state", "")
        errors = actions[0].get("error", [])
        error_msg = _first_error_message(errors)

        if state == "SUCCESS":
            logger.success(f"HIT (SUCCESS): {descriptor}")
            hits.append(descriptor)
        elif "ACCESS_DENIED" in error_msg or "access" in error_msg.lower():
            logger.warning(f"EXISTS — access denied (potential finding): {descriptor}")
            hits.append(descriptor)
        elif "No ACTION" in error_msg or "No such" in error_msg:
            logger.debug(f"Not found: {descriptor}")
        else:
            logger.debug(f"{descriptor}: state={state} | {error_msg[:80]}")

        if stop_on_first and hits:
            break

    return hits


def _first_error_message(errors: list) -> str:
    try:
        return errors[0]["event"]["attributes"]["values"]["message"]
    except (IndexError, KeyError):
        return ""
