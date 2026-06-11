# sfmap/commands/assess.py

# Built-in imports
import argparse
import time
from pathlib import Path
from typing import Callable

# Third-party imports
from loguru import logger

# Local imports
from ._context import _build_session, _resolve_output_dir
from .aura import (
    cmd_apex_controllers, cmd_aura_follow, cmd_bootstrap, cmd_crud_probe,
    cmd_dump, cmd_flow_fuzz, cmd_idor_probe, cmd_list_objects, cmd_list_views,
    cmd_network_access, cmd_soql_inject,
)
from .rest import (
    cmd_apexrest_fuzz, cmd_chatter, cmd_content_enum, cmd_graphql_dump,
    cmd_graphql_introspect, cmd_graphql_query, cmd_soql_query, cmd_sosl_query,
    cmd_static_resources, cmd_tooling_query,
)
from .surface import cmd_exposure
from .report import cmd_report


_PHASE_SENTINELS: dict[str, str] = {
    "surface exposure":        "exposure_summary.json",
    "aura network":            "network_config.json",
    "aura bootstrap":          "csp_trusted_sites.json",
    "aura objects":            "../config_data.json",
    "aura dump":               "ContentDocument__page1.json",
    "aura crud":               "crud_probe.json",
    "aura inject":             "injection_findings.json",
    "aura views":              "listviews.json",
    "aura flow":               "flow_hits.json",
    "aura controllers":        "apex_descriptors.json",
    "aura follow":             "relatedlists_sentinel.json",
    "aura idor":               "idor_findings.json",
    "rest graphql introspect": "graphql/graphql_introspection_status.json",
    "rest graphql query":      "graphql/graphql_User.json",
    "rest graphql dump":       "graphql_dump_User.json",
    "rest static":             "staticresource_summary.json",
    "rest apexrest":           "apexrest_hits.json",
    "rest chatter":            "chatter/chatter_summary.json",
    "rest soql":               "soql/soql_summary.json",
    "rest sosl":               "sosl/sosl_summary.json",
    "rest content enum":       "ContentDocument__page1.json",
    "rest tooling":            "tooling",
}

_ASSESS_DEFAULTS: list[tuple[str, object]] = [
    ("objects", []), ("display", False), ("custom_fields", False),
    ("type", "custom"), ("wordlist", None), ("method", "invoke"),
    ("apex_hits", []), ("object", None), ("fields", None),
    ("record_id", None), ("soql", None), ("sosl", None),
]


def cmd_assess(args: argparse.Namespace) -> int:
    session = _build_session(args)
    out_dir = _resolve_output_dir(args, session)
    out_path = Path(out_dir)

    phases: list[tuple[str, Callable[[argparse.Namespace], int]]] = [
        ("surface exposure",        cmd_exposure),
        ("aura network",            cmd_network_access),
        ("aura bootstrap",          cmd_bootstrap),
        ("aura objects",            cmd_list_objects),
        ("aura dump",               cmd_dump),
        ("aura crud",               cmd_crud_probe),
        ("aura inject",             cmd_soql_inject),
        ("aura views",              cmd_list_views),
        ("aura flow",               cmd_flow_fuzz),
        ("aura controllers",        cmd_apex_controllers),
        ("aura follow",             cmd_aura_follow),
        ("aura idor",               cmd_idor_probe),
        ("rest graphql introspect", cmd_graphql_introspect),
        ("rest graphql query",      cmd_graphql_query),
        ("rest graphql dump",       cmd_graphql_dump),
        ("rest static",             cmd_static_resources),
        ("rest apexrest",           cmd_apexrest_fuzz),
        ("rest chatter",            cmd_chatter),
        ("rest soql",               cmd_soql_query),
        ("rest sosl",               cmd_sosl_query),
        ("rest content enum",       cmd_content_enum),
        ("rest tooling",            cmd_tooling_query),
    ]

    results: list[tuple[str, str, float]] = []

    for name, fn in phases:
        sentinel = _PHASE_SENTINELS.get(name)
        if sentinel and (out_path / sentinel).exists():
            logger.info(f"assess: {name} already done, skipping")
            results.append((name, "skip", 0.0))
            continue

        phase_args = argparse.Namespace(**vars(args))
        phase_args.output = out_dir
        for attr, val in _ASSESS_DEFAULTS:
            if not hasattr(phase_args, attr):
                setattr(phase_args, attr, val)

        t0 = time.monotonic()
        try:
            fn(phase_args)
            elapsed = time.monotonic() - t0
            results.append((name, "ok", elapsed))
        except SystemExit:
            elapsed = time.monotonic() - t0
            results.append((name, "fatal", elapsed))
            logger.error(f"assess: {name} aborted session, stopping")
            break
        except Exception:
            elapsed = time.monotonic() - t0
            results.append((name, "error", elapsed))
            logger.exception(f"assess: {name} failed, continuing")

    report_args = argparse.Namespace(output=out_dir)
    try:
        cmd_report(report_args)
    except Exception:
        logger.exception("assess: report generation failed")

    logger.info("─" * 55)
    for name, status, elapsed in results:
        if status == "ok":
            logger.success(f"  {name:<32} {elapsed:>6.1f}s")
        elif status == "skip":
            logger.info(f"  {name:<32}  skipped")
        else:
            logger.error(f"  {name:<32} {elapsed:>6.1f}s")
    logger.info("─" * 55)

    failed = sum(1 for _, s, _ in results if s == "error")
    return 1 if failed else 0
