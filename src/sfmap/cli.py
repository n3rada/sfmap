# sfmap/cli.py

# Built-in imports
import argparse
import os
import sys

# Third-party imports
from loguru import logger

# Local imports
from . import __version__
from .commands.aura import (
    cmd_apex_controllers, cmd_apex_fuzz, cmd_aura_follow, cmd_bootstrap,
    cmd_crud_probe, cmd_dump, cmd_flow_fuzz, cmd_idor_probe, cmd_list_objects,
    cmd_list_views, cmd_network_access, cmd_object_info, cmd_record,
    cmd_related_lists, cmd_soql_inject,
)
from .commands.rest import (
    cmd_apexrest_fuzz, cmd_chatter, cmd_content_distribution, cmd_content_download,
    cmd_content_enum, cmd_graphql_dump, cmd_graphql_introspect, cmd_graphql_query,
    cmd_soql_query, cmd_sosl_query, cmd_static_resources, cmd_tooling_query,
)
from .commands.surface import cmd_exposure
from .commands.files import cmd_download
from .commands.assess import cmd_assess
from .commands.report import cmd_report
from .commands.lightning import cmd_lightning_assess, cmd_lightning_controllers, cmd_lightning_objects
from .commands.detect import cmd_detect
from .core.utils import logbook


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-I",
        "--identity",
        default=None,
        metavar="LABEL",
        help=(
            "Identity label used as output subdirectory (e.g. alice, admin, guest). "
            "Defaults to 'guest' when unauthenticated, 'authenticated' otherwise."
        ),
    )
    parser.add_argument(
        "-T",
        "--token",
        default=None,
        metavar="VALUE|@FILE",
        help="aura.token value or @path/to/file. Defaults to @token.txt in the current directory.",
    )
    parser.add_argument(
        "--cookie",
        default=None,
        metavar="VALUE|@FILE",
        help="Raw Cookie header or @path/to/file. Defaults to @cookies.txt in the current directory.",
    )
    parser.add_argument(
        "--output",
        "-o",
        metavar="DIR",
        help="Output directory (default: derived from URL)",
    )
    parser.add_argument(
        "--bearer",
        default=None,
        metavar="VALUE|@FILE",
        help=(
            "OAuth Bearer token for REST API access (internal user session). "
            "Defaults to @bearer.txt if present. Required for soql-query, "
            "tooling, and bulk API surfaces."
        ),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sfmap",
        description="Salesforce surface-centric security assessment toolkit.",
        epilog="For more information, visit: https://github.com/n3rada/sfmap",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        allow_abbrev=True,
        exit_on_error=True,
    )

    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging.")
    parser.add_argument("--trace", action="store_true", help="Enable trace logging (most verbose).")
    parser.add_argument(
        "--log-level",
        choices=["TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default=None,
    )
    parser.add_argument(
        "--proxy",
        nargs="?",
        const="http://127.0.0.1:8080",
        metavar="URL",
        help="Proxy URL (bare flag defaults to Burp at 127.0.0.1:8080).",
    )
    parser.add_argument(
        "url",
        metavar="URL",
        help="Target domain or base URL. /s/sfsites/aura is appended automatically.",
    )
    parser.add_argument(
        "-C", "--context",
        default=None,
        metavar="VALUE|@FILE",
        help="aura.context JSON string or @file. Default: @ctx.json.",
    )

    surfaces = parser.add_subparsers(dest="surface", required=False)

    # -- detect --------------------------------------------------------------
    p_detect = surfaces.add_parser(
        "detect",
        help="Probe all Aura surfaces without credentials and print next steps (default when no surface given)",
    )
    p_detect.set_defaults(func=cmd_detect)

    # -- aura ----------------------------------------------------------------
    p_aura = surfaces.add_parser("aura", help="Aura surface operations")
    aura_sub = p_aura.add_subparsers(dest="aura_command", required=True)

    p_objects = aura_sub.add_parser("objects", help="Enumerate all visible objects and cache the list")
    _add_common_args(p_objects)
    p_objects.set_defaults(func=cmd_list_objects)

    p_dump = aura_sub.add_parser(
        "dump",
        help="Dump records. With OBJECT(s): dump those. Without: dump all visible objects.",
    )
    _add_common_args(p_dump)
    p_dump.add_argument("objects", nargs="*", metavar="OBJECT",
                        help="Object(s) to dump (omit for all)")
    p_dump.add_argument("--display", action="store_true",
                        help="Print records to stdout in addition to saving")
    p_dump.add_argument("--custom-fields", action="store_true",
                        help="Extract __c field names into custom_fields_summary.txt")
    p_dump.add_argument(
        "--type", choices=["standard", "custom", "both"], default="both",
        help="Filter by object type when dumping all (default: both)",
    )
    p_dump.set_defaults(func=cmd_dump)

    p_rec = aura_sub.add_parser("record", help="Fetch and print a single record by ID")
    _add_common_args(p_rec)
    p_rec.add_argument("record_id", metavar="RECORD_ID")
    p_rec.set_defaults(func=cmd_record)

    p_info = aura_sub.add_parser(
        "info",
        help="Fetch field-level metadata (getObjectInfo) for one or more objects",
    )
    _add_common_args(p_info)
    p_info.add_argument("objects", nargs="*", metavar="OBJECT",
                        help="Object(s) to inspect (omit for all visible)")
    p_info.set_defaults(func=cmd_object_info)

    p_related = aura_sub.add_parser(
        "related",
        help="Enumerate child relationships on a record via getRecords",
    )
    _add_common_args(p_related)
    p_related.add_argument("record_id", metavar="RECORD_ID")
    p_related.add_argument("--object", default=None, metavar="OBJECT_API_NAME",
                           help="Object API name (resolved automatically if omitted)")
    p_related.set_defaults(func=cmd_related_lists)

    p_follow = aura_sub.add_parser(
        "follow",
        help="Follow child relations from existing dump records to discover reachable objects",
    )
    _add_common_args(p_follow)
    p_follow.set_defaults(func=cmd_aura_follow)

    p_idor = aura_sub.add_parser(
        "idor",
        help="Test unauthenticated getRecord access for all IDs in the output directory",
    )
    _add_common_args(p_idor)
    p_idor.set_defaults(func=cmd_idor_probe)

    p_crud = aura_sub.add_parser(
        "crud",
        help="Probe CREATE/DELETE access on visible objects",
    )
    _add_common_args(p_crud)
    p_crud.add_argument("--type", choices=["standard", "custom", "both"], default="custom",
                        help="Object type filter (default: custom)")
    p_crud.set_defaults(func=cmd_crud_probe)

    p_inject = aura_sub.add_parser(
        "inject",
        help="Test SOQL injection via getItems where-clause and Apex method parameters",
    )
    _add_common_args(p_inject)
    p_inject.add_argument("--apex-hits", nargs="*", metavar="DESCRIPTOR", default=[],
                          help="Apex descriptors to test (from aura apex output)")
    p_inject.set_defaults(func=cmd_soql_inject)

    p_apex = aura_sub.add_parser("apex", help="Wordlist-fuzz Apex controller ACTION descriptors")
    _add_common_args(p_apex)
    p_apex.add_argument("-w", "--wordlist", default=None, metavar="FILE",
                        help="Custom controller wordlist (default: built-in)")
    p_apex.add_argument("--method", default="invoke", metavar="METHOD",
                        help="Apex method name to fuzz (default: invoke)")
    p_apex.set_defaults(func=cmd_apex_fuzz)

    p_controllers = aura_sub.add_parser(
        "controllers",
        help="Discover Apex ACTION descriptors from JS bundles and local files, then probe each",
    )
    _add_common_args(p_controllers)
    p_controllers.set_defaults(func=cmd_apex_controllers)

    p_flow = aura_sub.add_parser("flow", help="Wordlist-fuzz Flow API names via InterviewController")
    _add_common_args(p_flow)
    p_flow.add_argument("-w", "--wordlist", default=None, metavar="FILE",
                        help="Custom flow name wordlist (default: built-in)")
    p_flow.set_defaults(func=cmd_flow_fuzz)

    p_network = aura_sub.add_parser(
        "network",
        help="Enumerate Experience Cloud network config (Network, NetworkMemberGroup, self-registration)",
    )
    _add_common_args(p_network)
    p_network.set_defaults(func=cmd_network_access)

    p_bootstrap = aura_sub.add_parser(
        "bootstrap",
        help="Fetch CMCAppController bootstrap data (object home URLs accessible in the community UI)",
    )
    _add_common_args(p_bootstrap)
    p_bootstrap.set_defaults(func=cmd_bootstrap)

    p_views = aura_sub.add_parser(
        "views",
        help="Enumerate accessible UI list views (ListViewPickerDataProvider + ListViewDataManager)",
    )
    _add_common_args(p_views)
    p_views.set_defaults(func=cmd_list_views)

    # -- rest ----------------------------------------------------------------
    p_rest = surfaces.add_parser("rest", help="REST surface operations")
    rest_sub = p_rest.add_subparsers(dest="rest_command", required=True)

    p_gql_grp = rest_sub.add_parser("graphql", help="GraphQL uiapi operations")
    gql_sub = p_gql_grp.add_subparsers(dest="graphql_command", required=True)

    p_gql_dump = gql_sub.add_parser(
        "dump",
        help="Dump records. No args: full sweep. OBJECT: auto-discover fields. OBJECT --fields: explicit.",
    )
    _add_common_args(p_gql_dump)
    p_gql_dump.add_argument("object", nargs="?", default=None, metavar="OBJECT",
                            help="Object API name (omit for full sweep)")
    p_gql_dump.add_argument("--fields", nargs="+", default=None, metavar="FIELD",
                            help="Fields in dot notation (auto-discovered if omitted)")
    p_gql_dump.set_defaults(func=cmd_graphql_dump)

    p_gql_query = gql_sub.add_parser(
        "query",
        help="Sweep all visible objects via GraphQL and record accessible record counts",
    )
    _add_common_args(p_gql_query)
    p_gql_query.set_defaults(func=cmd_graphql_query)

    p_gql_intro = gql_sub.add_parser("introspect", help="Run GraphQL introspection and save schema")
    _add_common_args(p_gql_intro)
    p_gql_intro.set_defaults(func=cmd_graphql_introspect)

    p_content_grp = rest_sub.add_parser("content", help="ContentDocument/ContentVersion operations")
    content_sub = p_content_grp.add_subparsers(dest="content_command", required=True)

    p_cenum = content_sub.add_parser(
        "enum",
        help="Enumerate Content* records and probe unauthenticated VersionData access",
    )
    _add_common_args(p_cenum)
    p_cenum.set_defaults(func=cmd_content_enum)

    p_cdl = content_sub.add_parser("download", help="Download all ContentDocument/ContentVersion files")
    _add_common_args(p_cdl)
    p_cdl.set_defaults(func=cmd_content_download)

    p_cdist = content_sub.add_parser(
        "distribution",
        help="Enumerate ContentDistribution records and probe public file URLs without authentication",
    )
    _add_common_args(p_cdist)
    p_cdist.set_defaults(func=cmd_content_distribution)

    p_static = rest_sub.add_parser("static", help="Enumerate and download static resources")
    _add_common_args(p_static)
    p_static.add_argument("-w", "--wordlist", default=None, metavar="FILE",
                          help="Custom resource name wordlist (default: built-in)")
    p_static.set_defaults(func=cmd_static_resources)

    p_apexrest = rest_sub.add_parser("apexrest", help="Wordlist-fuzz /services/apexrest/ endpoints")
    _add_common_args(p_apexrest)
    p_apexrest.add_argument("-w", "--wordlist", default=None, metavar="FILE",
                            help="Custom endpoint wordlist (default: built-in)")
    p_apexrest.set_defaults(func=cmd_apexrest_fuzz)

    p_soql = rest_sub.add_parser("soql", help="Run probe SOQL queries (requires Bearer token)")
    _add_common_args(p_soql)
    p_soql.set_defaults(func=cmd_soql_query)

    p_sosl = rest_sub.add_parser("sosl", help="Run probe SOSL searches (requires Bearer token)")
    _add_common_args(p_sosl)
    p_sosl.set_defaults(func=cmd_sosl_query)

    p_tooling = rest_sub.add_parser(
        "tooling", help="Dump Apex source via Tooling API (requires Bearer token)"
    )
    _add_common_args(p_tooling)
    p_tooling.set_defaults(func=cmd_tooling_query)

    p_chatter = rest_sub.add_parser(
        "chatter", help="Enumerate Chatter feeds and probe IP leak endpoint"
    )
    _add_common_args(p_chatter)
    p_chatter.set_defaults(func=cmd_chatter)

    # -- lightning -----------------------------------------------------------
    p_lightning = surfaces.add_parser(
        "lightning",
        help="Lightning Aura surface (one:one app — always authenticated, no guest mode)",
    )
    lightning_sub = p_lightning.add_subparsers(dest="lightning_command", required=True)

    p_lc = lightning_sub.add_parser(
        "controllers",
        help="Probe Lightning Aura framework controller descriptors (aura://)",
    )
    _add_common_args(p_lc)
    p_lc.add_argument(
        "-w", "--wordlist", default=None, metavar="FILE",
        help="Custom descriptor wordlist (default: built-in lightning_controllers.txt)",
    )
    p_lc.set_defaults(func=cmd_lightning_controllers)

    p_lo = lightning_sub.add_parser(
        "objects",
        help="Enumerate visible objects via getConfigData in Lightning context (experimental)",
    )
    _add_common_args(p_lo)
    p_lo.set_defaults(func=cmd_lightning_objects)

    p_la = lightning_sub.add_parser(
        "assess",
        help="Run all Lightning phases in sequence, skipping completed ones",
    )
    _add_common_args(p_la)
    p_la.set_defaults(func=cmd_lightning_assess)

    # -- assess --------------------------------------------------------------
    p_assess = surfaces.add_parser(
        "assess",
        help="Run full assessment: all phases in dependency order",
    )
    _add_common_args(p_assess)
    p_assess.set_defaults(func=cmd_assess)

    # -- report --------------------------------------------------------------
    p_report = surfaces.add_parser(
        "report",
        help="Generate a self-contained HTML report from an existing output directory",
    )
    p_report.add_argument(
        "--output", "-o", metavar="DIR", required=False, default=None,
        help="Output directory to read (default: derived from URL)",
    )
    p_report.set_defaults(func=cmd_report)

    # -- surface -------------------------------------------------------------
    p_surface = surfaces.add_parser("surface", help="Cross-surface exposure mapping")
    surface_sub = p_surface.add_subparsers(dest="surface_command", required=True)
    p_exp = surface_sub.add_parser("exposure", help="Full exposure check across all surfaces")
    _add_common_args(p_exp)
    p_exp.set_defaults(func=cmd_exposure)

    # -- files ---------------------------------------------------------------
    p_files = surfaces.add_parser("files", help="File download by ID")
    files_sub = p_files.add_subparsers(dest="files_command", required=True)
    p_dl = files_sub.add_parser("download", help="Download by ContentDocument/ContentVersion ID")
    _add_common_args(p_dl)
    p_dl.add_argument("sf_id", metavar="ID",
                      help="Salesforce record ID (069 ContentDocument or 068 ContentVersion)")
    p_dl.set_defaults(func=cmd_download)

    return parser


_SURFACES_NO_URL: frozenset[str] = frozenset({"report"})
_FLAGS_WITH_VALUE: frozenset[str] = frozenset({"--log-level", "-C", "--context"})


def main() -> int:
    if len(sys.argv) <= 1:
        build_parser().print_help()
        return 1

    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--debug", action="store_true")
    pre.add_argument("--trace", action="store_true")
    pre.add_argument("--log-level", dest="log_level", default=None,
                     choices=["TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
    pre.add_argument("--proxy", nargs="?", const="http://127.0.0.1:8080", default=None)
    pre_args, argv = pre.parse_known_args(sys.argv[1:])

    if pre_args.log_level:
        log_level = pre_args.log_level
    elif pre_args.trace:
        log_level = "TRACE"
    elif pre_args.debug:
        log_level = "DEBUG"
    else:
        log_level = "INFO"

    logbook.setup_logging(level=log_level)

    url_patched = False
    skip_next = False
    for i, arg in enumerate(argv):
        if skip_next:
            skip_next = False
            continue
        if arg.startswith("-"):
            if arg in _FLAGS_WITH_VALUE:
                skip_next = True
            continue
        if arg in _SURFACES_NO_URL:
            argv = argv[:i] + ["_"] + argv[i:]
            url_patched = True
        break

    parser = build_parser()
    args = parser.parse_args(argv)
    if url_patched:
        args.url = None

    if args.proxy:
        if not args.proxy.startswith(("http://", "https://")):
            logger.error("Invalid proxy format.")
            return 1

        for key in (
            "http_proxy",
            "https_proxy",
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "all_proxy",
        ):
            os.environ[key] = args.proxy

        logger.info(f"Proxy set to {args.proxy}")

    from .core.client import AuraSessionExpired
    try:
        fn = getattr(args, "func", None)
        if fn is None:
            if getattr(args, "url", None):
                return cmd_detect(args)
            build_parser().print_help()
            return 1
        return fn(args)
    except AuraSessionExpired as exc:
        logger.error(str(exc))
        return 1
