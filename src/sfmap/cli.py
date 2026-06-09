# sfmap/cli.py

# Built-in imports
import argparse
import json
import os
import sys
from pathlib import Path

# Third-party imports
from loguru import logger

# Local imports
from . import __version__
from .core.client import AuraClient
from .core.session import Session
from .core.modules import apex, apexrest, bootstrap, chatter, content, crud, dump, enum, exposure, flow, graphql, idor, injection, listviews, network, relatedlist, reporter, soql, staticresource, tooling
from .core.utils import autocontext
from .core.utils import common, logbook, storage


def _resolve_output_dir(args: argparse.Namespace, session: Session | None = None) -> str:
    if args.output:
        return args.output
    base = common.default_output_dir(args.url)
    identity = getattr(args, "identity", None)
    if not identity:
        identity = "guest" if (session is None or session.is_guest) else "authenticated"
    return os.path.join(base, identity)


def _resolve_file_arg(value: str | None, default_file: str) -> str | None:
    raw = value or f"@{default_file}"
    if raw.startswith("@"):
        path = Path(raw[1:])
        if not path.exists():
            return None
        try:
            return path.read_text(encoding="utf-8-sig").strip() or None
        except OSError as exc:
            logger.exception(f"Cannot read file '{path}'")
            raise SystemExit(1) from exc
    return raw or None


def _build_session(args: argparse.Namespace) -> Session:
    url = common.resolve_url(args.url)
    if url != args.url:
        logger.debug(f"Resolved URL: {url} (from {args.url})")

    # -- context -------------------------------------------------------
    raw_context = args.context or "@ctx.json"
    extracted_token: str | None = None

    if raw_context.startswith("@"):
        path = Path(raw_context[1:])
        if not path.exists():
            logger.info(f"No context file found at '{path}', auto-extracting from target")
            try:
                context, extracted_token = autocontext.extract(url)
            except ValueError as exc:
                logger.error(str(exc))
                raise SystemExit(1) from exc
            try:
                path.write_text(json.dumps(context, indent=2), encoding="utf-8")
                logger.info(f"Context saved to {path} for future runs")
            except OSError:
                pass
        else:
            try:
                raw = path.read_text(encoding="utf-8-sig").strip()
                context = json.loads(raw)
            except OSError as exc:
                logger.exception(f"Cannot read context file '{path}'")
                raise SystemExit(1) from exc
            except json.JSONDecodeError as exc:
                logger.exception(f"Context file '{path}' is not valid JSON")
                raise SystemExit(1) from exc
    else:
        try:
            context = json.loads(raw_context)
        except json.JSONDecodeError as exc:
            logger.exception("context is not valid JSON")
            raise SystemExit(1) from exc

    # -- credentials ---------------------------------------------------
    # Resolve cookie first: auto-extracted token is only valid when a session
    # cookie is also present. Without a cookie the extracted JWT is a guest
    # CSRF token that the server rejects when no SID accompanies it.
    cookie = _resolve_file_arg(getattr(args, "cookie", None), "cookies.txt")
    bearer = _resolve_file_arg(getattr(args, "bearer", None), "bearer.txt")

    token_raw = _resolve_file_arg(getattr(args, "token", None), "token.txt")
    if token_raw is None and extracted_token and cookie:
        token = extracted_token
        logger.debug("Using auto-extracted Aura token from page HTML")
    else:
        token = token_raw or "undefined"

    return Session(
        url=url,
        context=context,
        token=token,
        cookie=cookie,
        bearer_token=bearer,
    )


def cmd_list_objects(args: argparse.Namespace) -> int:
    session = _build_session(args)
    with AuraClient(session) as client:
        objects = enum.print_objects(client)
    storage.save_config_data(session.url, objects)
    logger.success(f"Object list cached → {storage.config_data_path(session.url)}")
    return 0


def cmd_dump(args: argparse.Namespace) -> int:
    session = _build_session(args)
    output_dir = _resolve_output_dir(args, session)
    obj_type = getattr(args, "type", "both")
    display = getattr(args, "display", False)
    custom_fields = getattr(args, "custom_fields", False)
    explicit = getattr(args, "objects", None) or []

    with AuraClient(session) as client:
        if explicit:
            for i, obj in enumerate(explicit, 1):
                logger.debug(f"{i}/{len(explicit)}) Dumping '{obj}'")
                ok = dump.dump_object(client, obj, output_dir, full=True,
                                      display=display, custom_fields=custom_fields)
                if not ok:
                    logger.debug(f"No data returned for '{obj}'")
        else:
            all_objects = enum.list_objects(client)
            if obj_type == "standard":
                targets = {k: v for k, v in all_objects.items() if not k.endswith("__c")}
            elif obj_type == "custom":
                targets = {k: v for k, v in all_objects.items() if k.endswith("__c")}
            else:
                targets = all_objects
            names = list(targets.keys())
            logger.info(f"{len(names)} objects to dump")
            failed = []
            for i, obj in enumerate(names, 1):
                logger.debug(f"{i}/{len(names)}) {obj}")
                ok = dump.dump_object(client, obj, output_dir, full=True,
                                      custom_fields=custom_fields)
                if not ok:
                    failed.append(obj)
            if failed:
                logger.info(f"Failed / empty: {', '.join(failed)}")
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    session = _build_session(args)
    with AuraClient(session) as client:
        dump.get_record(client, args.record_id)
    return 0



def cmd_content_enum(args: argparse.Namespace) -> int:
    session = _build_session(args)
    output_dir = _resolve_output_dir(args, session)
    with AuraClient(session) as client:
        critical = content.run(client, session.url, output_dir)
    return 1 if critical else 0


def cmd_exposure(args: argparse.Namespace) -> int:
    session = _build_session(args)
    output_dir = _resolve_output_dir(args, session)

    with AuraClient(session) as client:
        summary = exposure.run(client, session, output_dir=output_dir)

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


def cmd_download(args: argparse.Namespace) -> int:
    session = _build_session(args)
    base_dir = _resolve_output_dir(args, session)
    downloads_dir = os.path.join(base_dir, "downloads")
    path = dump.download_file(AuraClient(session), args.sf_id, session.url, downloads_dir)
    return 0 if path else 1


def cmd_crud_probe(args: argparse.Namespace) -> int:
    session = _build_session(args)
    output_dir = _resolve_output_dir(args, session)
    with AuraClient(session) as client:
        all_objects = enum.list_objects(client)
        if args.type == "standard":
            targets = {k: v for k, v in all_objects.items() if not k.endswith("__c")}
        elif args.type == "custom":
            targets = {k: v for k, v in all_objects.items() if k.endswith("__c")}
        else:
            targets = all_objects
        findings = crud.probe(client, targets, output_dir)
    return 1 if findings else 0


def cmd_soql_inject(args: argparse.Namespace) -> int:
    session = _build_session(args)
    output_dir = _resolve_output_dir(args, session)
    apex_hits: list[str] = getattr(args, "apex_hits", None) or []
    with AuraClient(session) as client:
        all_objects = enum.list_objects(client)
        result = injection.run(client, all_objects, apex_hits, output_dir)
    return 1 if result["findings"] else 0


def cmd_chatter(args: argparse.Namespace) -> int:
    session = _build_session(args)
    output_dir = _resolve_output_dir(args, session)
    with AuraClient(session) as client:
        summary = chatter.run(client, session.url, output_dir)
    findings = bool(summary.get("file_upload") or summary.get("aura_objects") or summary.get("rest_endpoints"))
    return 1 if findings else 0


def cmd_graphql_dump(args: argparse.Namespace) -> int:
    session = _build_session(args)
    output_dir = _resolve_output_dir(args, session)
    obj = getattr(args, "object", None)
    fields = getattr(args, "fields", None) or []
    with AuraClient(session) as client:
        if obj and fields:
            # Explicit: one object with named fields
            result = graphql.dump_object(client, obj, fields, output_dir)
            return 1 if result else 0
        elif obj:
            # Auto-discover fields for one object
            result = graphql.autodump(client, output_dir, object_names=[obj])
        else:
            # Full sweep: discover all accessible objects + fields
            result = graphql.autodump(client, output_dir, object_names=None)
    return 1 if result else 0


def cmd_graphql_query(args: argparse.Namespace) -> int:
    session = _build_session(args)
    output_dir = _resolve_output_dir(args, session)
    with AuraClient(session) as client:
        all_objects = enum.list_objects(client)
        results = graphql.query_objects(client, list(all_objects.keys()), output_dir)
    return 1 if any(v > 0 for v in results.values()) else 0


def cmd_content_download(args: argparse.Namespace) -> int:
    session = _build_session(args)
    base_dir = _resolve_output_dir(args, session)
    downloads_dir = os.path.join(base_dir, "downloads")
    with AuraClient(session) as client:
        downloaded = content.download_all(client, session.url, base_dir, downloads_dir)
    return 0 if downloaded else 1


def cmd_graphql_introspect(args: argparse.Namespace) -> int:
    session = _build_session(args)
    output_dir = _resolve_output_dir(args, session)
    with AuraClient(session) as client:
        ok = graphql.introspect(client, session.url, output_dir)
    return 0 if ok else 1


def cmd_apex_fuzz(args: argparse.Namespace) -> int:
    session = _build_session(args)
    with AuraClient(session) as client:
        hits = apex.fuzz(client, args.wordlist, method=args.method)
    if hits:
        logger.warning(f"{len(hits)} callable descriptor(s) found:")
        for h in hits:
            logger.info(f"  {h}")
    else:
        logger.info("No callable Apex descriptors found.")
    return 0 if not hits else 1


def cmd_object_info(args: argparse.Namespace) -> int:
    session = _build_session(args)
    output_dir = _resolve_output_dir(args, session)
    os.makedirs(output_dir, exist_ok=True)
    with AuraClient(session) as client:
        objects = args.objects or list(enum.list_objects(client).keys())
        for obj in objects:
            info = dump.get_object_info(client, obj)
            if info:
                path = os.path.join(output_dir, f"objectinfo_{obj}.json")
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(json.dumps(info, ensure_ascii=False, indent=2))
                fields = info.get("fields", {})
                logger.info(f"{obj}: {len(fields)} field(s), saved to {path}")
            else:
                logger.debug(f"{obj}: getObjectInfo returned nothing")
    return 0


def cmd_related_lists(args: argparse.Namespace) -> int:
    session = _build_session(args)
    output_dir = _resolve_output_dir(args, session)
    with AuraClient(session) as client:
        results = relatedlist.probe(
            client,
            args.record_id,
            output_dir,
            object_api_name=getattr(args, "object", None),
        )
    return 1 if any(v > 0 for v in results.values()) else 0


def cmd_flow_fuzz(args: argparse.Namespace) -> int:
    session = _build_session(args)
    output_dir = _resolve_output_dir(args, session)
    with AuraClient(session) as client:
        hits = flow.fuzz(client, output_dir, wordlist_path=getattr(args, "wordlist", None))
    return 1 if hits else 0


def cmd_network_access(args: argparse.Namespace) -> int:
    session = _build_session(args)
    output_dir = _resolve_output_dir(args, session)
    with AuraClient(session) as client:
        results = network.fetch(client, output_dir)
    return 1 if results else 0


def cmd_idor_probe(args: argparse.Namespace) -> int:
    session = _build_session(args)
    output_dir = _resolve_output_dir(args, session)
    record_ids = idor.collect_ids_from_directory(output_dir)
    if not record_ids:
        logger.warning("No record IDs found in output directory, run 'aura dump' first")
        return 1
    logger.info(f"Collected {len(record_ids)} unique record ID(s) from {output_dir}")
    findings = idor.probe_guest(session, record_ids, output_dir)
    return 1 if findings else 0


def cmd_content_distribution(args: argparse.Namespace) -> int:
    session = _build_session(args)
    output_dir = _resolve_output_dir(args, session)
    with AuraClient(session) as client:
        hits = content.check_content_distribution(client, session.url, output_dir)
    return 1 if hits else 0


def cmd_apexrest_fuzz(args: argparse.Namespace) -> int:
    session = _build_session(args)
    output_dir = _resolve_output_dir(args, session)
    with AuraClient(session) as client:
        hits = apexrest.fuzz(client, session.url, output_dir, wordlist_path=args.wordlist)
    return 1 if hits else 0


def cmd_static_resources(args: argparse.Namespace) -> int:
    session = _build_session(args)
    output_dir = _resolve_output_dir(args, session)
    with AuraClient(session) as client:
        hits = staticresource.fuzz(client, session.url, output_dir, wordlist_path=args.wordlist)
    return 1 if hits else 0


def cmd_soql_query(args: argparse.Namespace) -> int:
    session = _build_session(args)
    output_dir = _resolve_output_dir(args, session)
    soql_dir = os.path.join(output_dir, "soql")
    with AuraClient(session) as client:
        results = soql.run(client, session.url, soql_dir)
    return 1 if results else 0


def cmd_bootstrap(args: argparse.Namespace) -> int:
    session = _build_session(args)
    output_dir = _resolve_output_dir(args, session)
    with AuraClient(session) as client:
        results = bootstrap.fetch(client, output_dir)
    return 1 if results else 0


def cmd_list_views(args: argparse.Namespace) -> int:
    session = _build_session(args)
    output_dir = _resolve_output_dir(args, session)
    with AuraClient(session) as client:
        all_objects = enum.list_objects(client)
        urls = listviews.sweep(client, list(all_objects.keys()), output_dir)
    return 1 if urls else 0


def cmd_report(args: argparse.Namespace) -> int:
    output_dir = _resolve_output_dir(args)
    if not os.path.isdir(output_dir):
        logger.error(f"Output directory not found: {output_dir}")
        return 1
    reporter.generate(output_dir, target=args.url)
    return 0


def cmd_tooling_query(args: argparse.Namespace) -> int:
    session = _build_session(args)
    output_dir = _resolve_output_dir(args, session)
    with AuraClient(session) as client:
        results = tooling.run(client, session.url, output_dir)
    return 1 if results else 0


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

    surfaces = parser.add_subparsers(dest="surface", required=True)

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
        help="Fetch CMCAppController bootstrap data — object home URLs accessible in the community UI",
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

    # rest graphql (subgroup)
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

    # rest content (subgroup)
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

    # rest flat commands
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

    # -- report --------------------------------------------------------------
    p_report = surfaces.add_parser(
        "report",
        help="Generate a self-contained HTML report from an existing output directory",
    )
    p_report.add_argument(
        "--output", "-o", metavar="DIR",
        help="Output directory to read (default: derived from URL + identity)",
    )
    p_report.add_argument(
        "-I", "--identity", default=None, metavar="LABEL",
        help="Identity label to read (e.g. guest, alice). Defaults to 'guest'.",
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


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    # Show help if no cli args provided
    if len(sys.argv) <= 1:
        parser.print_help()
        return 1

    # Determine log level: --log-level takes precedence, then --debug, then --trace, then default INFO
    if args.log_level:
        log_level = args.log_level
    elif args.trace:
        log_level = "TRACE"
    elif args.debug:
        log_level = "DEBUG"
    else:
        log_level = "INFO"

    logbook.setup_logging(level=log_level)

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

    return args.func(args)
