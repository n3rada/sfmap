# sfmap/commands/surface.py

# Built-in imports
import argparse

# Local imports
from ..core.client import AuraClient
from ..core.modules import exposure
from ..core.utils.storage import OutputWriter
from ._context import _build_session, _resolve_output_dir


def cmd_exposure(args: argparse.Namespace) -> int:
    session = _build_session(args)
    out = OutputWriter(_resolve_output_dir(args, session))

    with AuraClient(session) as client:
        summary = exposure.run(client, session, out=out)

    findings = 0
    if summary["self_registration"].get("enabled"):
        findings += 1
    if summary["rest_api"].get("version_listing_exposed"):
        findings += 1
    if summary["soap_api"].get("exposed"):
        findings += 1
    if summary["graphql"].get("enabled"):
        findings += 1
    if summary["custom_controllers"]:
        findings += 1
    if summary.get("security_headers", {}).get("weaknesses"):
        findings += 1
    if summary.get("visualforce"):
        findings += 1
    if summary.get("network_config", {}).get("self_registration_enabled"):
        findings += 1

    return 1 if findings else 0
