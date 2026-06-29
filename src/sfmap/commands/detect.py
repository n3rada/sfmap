# sfmap/commands/detect.py

# Built-in imports
import argparse

# Third-party imports
import httpx
from loguru import logger

# Local imports
from ..core.client import USER_AGENT
from ..core.utils import detect as detect_mod
from ..core.utils.storage import output_dir, save_json
from pathlib import Path

SURFACE_PROFILE_FILE = "surface_profile.json"


def load_surface_profile(url: str) -> dict | None:
    import json
    p = Path(output_dir(url)) / SURFACE_PROFILE_FILE
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def ensure_surface_profile(url: str, surface: str) -> None:
    """Write a minimal surface profile for url if none exists yet.

    Explicit surface commands call this so that assess routing works
    even when detect was never run.
    """
    p = Path(output_dir(url)) / SURFACE_PROFILE_FILE
    if p.exists():
        return
    save_json(p, {"target": url, "surfaces": [surface]})
    logger.debug(f"Surface profile created from explicit surface: {surface}")


def cmd_detect(args: argparse.Namespace) -> int:
    raw = args.url or ""
    if not raw:
        logger.error("URL is required for surface detection")
        return 1

    http = httpx.Client(
        verify=False,
        timeout=20.0,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    )
    try:
        logger.info(f"Detecting surfaces on {raw}")
        ec = detect_mod.probe_experience_cloud(raw, http)
        lt = detect_mod.probe_lightning(raw, http)
    finally:
        http.close()

    _report_ec(ec, raw)
    _report_lightning(lt, raw)

    surfaces = []
    if ec["found"]:
        surfaces.append("experience_cloud")
    if lt["found"]:
        surfaces.append("lightning")

    profile: dict = {"target": raw, "surfaces": surfaces}
    if ec["found"] and ec.get("guest_objects") is not None:
        profile["guest_objects"] = ec["guest_objects"]

    root = output_dir(raw)
    profile_path = Path(root) / SURFACE_PROFILE_FILE
    save_json(profile_path, profile)
    logger.info(f"Surface profile saved to {profile_path}")

    return 0 if (ec["found"] or lt["found"]) else 1


def _report_ec(result: dict, target: str) -> None:
    if not result["found"]:
        logger.info(f"Experience Cloud: not detected ({result['endpoint']})")
        return

    fwuid = result["fwuid"][:32] if result["fwuid"] else "unknown"
    logger.success(f"Experience Cloud: detected at {result['endpoint']}")
    logger.info(f"Experience Cloud: app={result['app']} fwuid={fwuid}")

    guest = result.get("guest_objects")
    if guest is not None and guest > 0:
        logger.success(f"Experience Cloud: guest access active, {guest} object(s) visible")
    elif guest == 0:
        logger.info("Experience Cloud: guest access enabled but no objects exposed")
    else:
        logger.info("Experience Cloud: guest access unknown")

    logger.info(f"Experience Cloud: run sfmap {target} assess")


def _report_lightning(result: dict, target: str) -> None:
    if not result["found"]:
        logger.info(f"Lightning: not detected ({result['endpoint']})")
        return

    fwuid = result["fwuid"][:32] if result["fwuid"] != "unknown" else "unknown"
    logger.success(f"Lightning: detected at {result['endpoint']}")
    logger.info(f"Lightning: app={result['app']} fwuid={fwuid}")
    logger.info("Lightning: always authenticated, no guest access")
    logger.info(f"Lightning: run sfmap {target} lightning assess")
