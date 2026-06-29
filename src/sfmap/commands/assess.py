# sfmap/commands/assess.py

# Built-in imports
import argparse

# Third-party imports
from loguru import logger

# Local imports
from ._context import _build_session, _resolve_output_dir
from ._phase_runner import run_phase_loop
from .detect import load_surface_profile
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
    profile = load_surface_profile(args.url)
    if profile:
        surfaces = profile.get("surfaces", [])
        if "lightning" in surfaces and "experience_cloud" not in surfaces:
            logger.info("assess: surface profile says Lightning only, routing to lightning assess")
            from .lightning import cmd_lightning_assess
            return cmd_lightning_assess(args)

    session = _build_session(args)
    out_dir = _resolve_output_dir(args, session)

    phases = [
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

    rc = run_phase_loop(phases, _PHASE_SENTINELS, _ASSESS_DEFAULTS, out_dir, args)

    report_args = argparse.Namespace(output=out_dir)
    try:
        cmd_report(report_args)
    except Exception:
        logger.exception("assess: report generation failed")

    return rc
