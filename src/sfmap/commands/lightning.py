# sfmap/commands/lightning.py

# Built-in imports
import argparse

# Third-party imports
from loguru import logger

# Local imports
from ..core.client import AuraClient
from ..core.modules import enum, lightning_controllers
from ..core.utils.storage import OutputWriter
from ._context import _build_lightning_session, _resolve_output_dir
from ._phase_runner import run_phase_loop

# Sentinel filenames — one per phase, used by cmd_lightning_assess to detect completed work.
# Keep in sync with the actual save() calls in each cmd_* handler below.
SENTINEL_CONTROLLERS = "lightning_controller_hits.json"
SENTINEL_OBJECTS = "lightning_objects.json"

_PHASE_SENTINELS: dict[str, str] = {
    "lightning controllers": SENTINEL_CONTROLLERS,
    "lightning objects":     SENTINEL_OBJECTS,
}

_ASSESS_DEFAULTS: list[tuple[str, object]] = [
    ("wordlist", None),
]


def cmd_lightning_controllers(args: argparse.Namespace) -> int:
    session = _build_lightning_session(args)
    out = OutputWriter(_resolve_output_dir(args, session))
    with AuraClient(session) as client:
        results = lightning_controllers.fuzz(
            client, wordlist_path=getattr(args, "wordlist", None)
        )

    callable_ones = [d for d, s in results.items() if s == "callable"]
    exists_denied = [d for d, s in results.items() if s == "exists_denied"]

    if callable_ones or exists_denied:
        path = out.save(
            SENTINEL_CONTROLLERS,
            {"callable": callable_ones, "exists_denied": exists_denied},
        )
        logger.success(
            f"{len(callable_ones)} callable, {len(exists_denied)} access-denied "
            f"— saved to {path}"
        )
    else:
        logger.info("No Lightning controller hits found")

    return 1 if (callable_ones or exists_denied) else 0


def cmd_lightning_objects(args: argparse.Namespace) -> int:
    session = _build_lightning_session(args)
    out = OutputWriter(_resolve_output_dir(args, session))
    with AuraClient(session) as client:
        objects, csp_sites = enum.list_objects_with_csp(client)
        enum._print_objects_from(objects)

    if objects:
        path = out.save(SENTINEL_OBJECTS, objects)
        logger.info(f"{len(objects)} object(s) saved to {path}")

    if csp_sites:
        path = out.save("csp_trusted_sites.json", csp_sites)
        logger.info(f"CSP trusted sites saved to {path}")

    return 1 if objects else 0


def cmd_lightning_assess(args: argparse.Namespace) -> int:
    session = _build_lightning_session(args)
    out_dir = _resolve_output_dir(args, session)

    phases = [
        ("lightning controllers", cmd_lightning_controllers),
        ("lightning objects",     cmd_lightning_objects),
    ]

    return run_phase_loop(phases, _PHASE_SENTINELS, _ASSESS_DEFAULTS, out_dir, args)
