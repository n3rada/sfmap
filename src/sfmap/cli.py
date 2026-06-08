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
from .core.modules import apex, apexrest, chatter, content, crud, dump, enum, exposure, graphql, idor, injection, soql
from .core.utils import common, logbook, storage


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
    raw = args.context or "@ctx.json"
    if raw.startswith("@"):
        path = Path(raw[1:])
        try:
            raw = path.read_text(encoding="utf-8-sig").strip()
        except OSError as exc:
            logger.exception(f"Cannot read context file '{path}'")
            raise SystemExit(1) from exc
    try:
        context = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.exception("context is not valid JSON")
        raise SystemExit(1) from exc

    url = common.resolve_url(args.url)
    if url != args.url:
        logger.debug(f"Resolved URL: {url} (from {args.url})")

    token = _resolve_file_arg(getattr(args, "token", None), "token.txt") or "undefined"
    cookie = _resolve_file_arg(getattr(args, "cookie", None), "cookies.txt")

    return Session(
        url=url,
        context=context,
        token=token,
        cookie=cookie,
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
    output_dir = args.output or common.default_output_dir(args.url)
    with AuraClient(session) as client:
        for i, obj in enumerate(args.objects, 1):
            logger.info(f"{i}/{len(args.objects)}) Dumping '{obj}'")
            ok = dump.dump_object(
                client, obj, output_dir,
                full=True,
                display=args.display,
                custom_fields=args.custom_fields,
            )
            if not ok:
                logger.warning(f"No data returned for '{obj}'")
    return 0


def cmd_dump_all(args: argparse.Namespace) -> int:
    session = _build_session(args)
    output_dir = args.output or common.default_output_dir(args.url)
    with AuraClient(session) as client:
        all_objects = enum.list_objects(client)

        if args.type == "standard":
            targets = {k: v for k, v in all_objects.items() if not k.endswith("__c")}
        elif args.type == "custom":
            targets = {k: v for k, v in all_objects.items() if k.endswith("__c")}
        else:
            targets = all_objects

        names = list(targets.keys())
        logger.info(f"{len(names)} objects to dump (type={args.type})")
        failed = []

        for i, obj in enumerate(names, 1):
            logger.info(f"{i}/{len(names)}) {obj}")
            ok = dump.dump_object(client, obj, output_dir,
                                  full=True,
                                  custom_fields=args.custom_fields)
            if not ok:
                failed.append(obj)

        if failed:
            logger.warning(f"Failed / empty: {', '.join(failed)}")
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    session = _build_session(args)
    with AuraClient(session) as client:
        dump.get_record(client, args.record_id)
    return 0


def cmd_guest(args: argparse.Namespace) -> int:
    session = _build_session(args)
    base_dir = args.output or common.default_output_dir(args.url)
    guest_dir = os.path.join(base_dir, "guest")

    if session.token != "undefined" or session.cookie:
        logger.warning(
            "guest runs unauthenticated — any -T / --cookie passed here are ignored"
        )
    # Always strip credentials for the guest run
    session = Session(
        url=session.url,
        context=session.context,
        token="undefined",
        cookie=None,
        guest_mode=True,
    )

    cached = storage.load_config_data(session.url)
    if cached:
        objects: dict[str, str] = cached
        logger.info(
            f"Using cached object list ({len(objects)} objects — "
            "run 'aura list-objects' first to refresh)"
        )
    else:
        logger.info(
            "No cache — enumerating objects as guest "
            "(run 'aura list-objects' with credentials for wider coverage)"
        )
        try:
            with AuraClient(session, authenticated=False) as c:
                objects = enum.list_objects(c)
        except RuntimeError as exc:
            logger.error(f"Guest enumeration failed: {exc}")
            return 1

    logger.info(f"Probing {len(objects)} objects via Aura guest mode")
    aura_readable: dict[str, int] = {}

    with AuraClient(session, authenticated=False) as client:
        for i, obj_name in enumerate(objects, 1):
            logger.debug(f"[{i}/{len(objects)}] {obj_name}")
            rv = dump.get_items(client, obj_name, page_size=100, page=1)
            if rv is None:
                continue
            results = rv.get("result", [])
            if results:
                total = rv.get("totalCount", len(results))
                logger.warning(
                    f"GUEST HIT — {obj_name}: {len(results)} record(s) (total: {total})"
                )
                aura_readable[obj_name] = total
                dump.write_page(guest_dir, obj_name, 1, rv)

    if aura_readable:
        logger.warning(f"{len(aura_readable)} Aura-readable object(s) found")
        return 1
    logger.success("No guest-accessible objects or files found.")
    return 0


def cmd_content_enum(args: argparse.Namespace) -> int:
    session = _build_session(args)
    output_dir = args.output or common.default_output_dir(args.url)
    with AuraClient(session) as client:
        critical = content.run(client, session.url, output_dir)
    return 1 if critical else 0


def cmd_exposure(args: argparse.Namespace) -> int:
    session = _build_session(args)
    output_dir = args.output or common.default_output_dir(args.url)

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
    base_dir = args.output or common.default_output_dir(args.url)
    downloads_dir = os.path.join(base_dir, "downloads")
    path = dump.download_file(AuraClient(session), args.sf_id, session.url, downloads_dir)
    return 0 if path else 1


def cmd_crud_probe(args: argparse.Namespace) -> int:
    session = _build_session(args)
    output_dir = args.output or common.default_output_dir(args.url)
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
    output_dir = args.output or common.default_output_dir(args.url)
    apex_hits: list[str] = getattr(args, "apex_hits", None) or []
    with AuraClient(session) as client:
        all_objects = enum.list_objects(client)
        result = injection.run(client, all_objects, apex_hits, output_dir)
    return 1 if result["findings"] else 0


def cmd_chatter(args: argparse.Namespace) -> int:
    session = _build_session(args)
    output_dir = args.output or common.default_output_dir(args.url)
    with AuraClient(session) as client:
        summary = chatter.run(client, session.url, output_dir)
    findings = bool(summary.get("file_upload") or summary.get("aura_objects") or summary.get("rest_endpoints"))
    return 1 if findings else 0


def cmd_graphql_query(args: argparse.Namespace) -> int:
    session = _build_session(args)
    output_dir = args.output or common.default_output_dir(args.url)
    with AuraClient(session) as client:
        all_objects = enum.list_objects(client)
        results = graphql.query_objects(client, list(all_objects.keys()), output_dir)
    return 1 if any(v > 0 for v in results.values()) else 0


def cmd_content_download(args: argparse.Namespace) -> int:
    session = _build_session(args)
    base_dir = args.output or common.default_output_dir(args.url)
    downloads_dir = os.path.join(base_dir, "downloads")
    with AuraClient(session) as client:
        downloaded = content.download_all(client, session.url, base_dir, downloads_dir)
    return 0 if downloaded else 1


def cmd_graphql_introspect(args: argparse.Namespace) -> int:
    session = _build_session(args)
    output_dir = args.output or common.default_output_dir(args.url)
    with AuraClient(session) as client:
        ok = graphql.introspect(client, session.url, output_dir)
    return 0 if ok else 1


def cmd_apex_fuzz(args: argparse.Namespace) -> int:
    session = _build_session(args)
    with AuraClient(session) as client:
        hits = apex.fuzz(client, args.wordlist, method=args.method)
    if hits:
        logger.success(f"{len(hits)} callable descriptor(s) found:")
        for h in hits:
            logger.success(f"  {h}")
    else:
        logger.info("No callable Apex descriptors found.")
    return 0 if not hits else 1


def cmd_object_info(args: argparse.Namespace) -> int:
    session = _build_session(args)
    output_dir = args.output or common.default_output_dir(args.url)
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
                logger.info(f"{obj}: {len(fields)} field(s) — saved to {path}")
            else:
                logger.debug(f"{obj}: getObjectInfo returned nothing")
    return 0


def cmd_idor_probe(args: argparse.Namespace) -> int:
    session = _build_session(args)
    output_dir = args.output or common.default_output_dir(args.url)
    record_ids = idor.collect_ids_from_directory(output_dir)
    if not record_ids:
        logger.warning(
            "No record IDs found in output directory — run 'aura dump-all' first"
        )
        return 1
    logger.info(f"Collected {len(record_ids)} unique record ID(s) from {output_dir}")
    findings = idor.probe_guest(session, record_ids, output_dir)
    return 1 if findings else 0


def cmd_content_distribution(args: argparse.Namespace) -> int:
    session = _build_session(args)
    output_dir = args.output or common.default_output_dir(args.url)
    with AuraClient(session) as client:
        hits = content.check_content_distribution(client, session.url, output_dir)
    return 1 if hits else 0


def cmd_apexrest_fuzz(args: argparse.Namespace) -> int:
    session = _build_session(args)
    output_dir = args.output or common.default_output_dir(args.url)
    with AuraClient(session) as client:
        hits = apexrest.fuzz(client, session.url, output_dir, wordlist_path=args.wordlist)
    return 1 if hits else 0


def cmd_soql_query(args: argparse.Namespace) -> int:
    session = _build_session(args)
    output_dir = args.output or common.default_output_dir(args.url)
    soql_dir = os.path.join(output_dir, "soql")
    with AuraClient(session) as client:
        results = soql.run(client, session.url, soql_dir)
    return 1 if results else 0


def _add_common_args(parser: argparse.ArgumentParser) -> None:
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sfmap",
        description="Salesforce surface-centric security assessment toolkit.",
        epilog="For more information, visit: https://github.com/n3rada/sfmap",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        allow_abbrev=True,
        exit_on_error=True,
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
        help="Show version and exit.",
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging.",
    )

    parser.add_argument(
        "--trace",
        action="store_true",
        help="Enable trace logging (most verbose).",
    )

    parser.add_argument(
        "--log-level",
        type=str,
        choices=["TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default=None,
        help="Set logging level explicitly (overrides --debug).",
    )

    parser.add_argument(
        "--proxy",
        nargs="?",
        const="http://127.0.0.1:8080",
        metavar="URL",
        help="Proxy URL. Bare flag defaults to http://127.0.0.1:8080 (Burp).",
    )

    parser.add_argument(
        "url",
        metavar="URL",
        help="Target domain or base URL (e.g. site.my.site.com). /s/sfsites/aura is appended automatically.",
    )

    parser.add_argument(
        "-C",
        "--context",
        default=None,
        metavar="VALUE|@FILE",
        help="aura.context as a JSON string or @path/to/file.json. Defaults to @ctx.json in the current directory.",
    )

    surfaces = parser.add_subparsers(dest="surface", required=True)

    # -- aura group ----------------------------------------------------------
    p_aura = surfaces.add_parser("aura", help="Aura surface operations")
    aura_sub = p_aura.add_subparsers(dest="aura_command", required=True)

    p_list = aura_sub.add_parser("list-objects", help="Enumerate all visible objects")
    _add_common_args(p_list)
    p_list.set_defaults(func=cmd_list_objects)

    p_dump = aura_sub.add_parser("dump", help="Dump records for specified object(s)")
    _add_common_args(p_dump)
    p_dump.add_argument(
        "objects",
        nargs="+",
        metavar="OBJECT",
        help="Object name(s) to dump  (e.g. User Account)",
    )
    p_dump.add_argument(
        "--display",
        action="store_true",
        help="Print results to stdout as well as saving",
    )
    p_dump.add_argument(
        "--custom-fields",
        action="store_true",
        help="Extract __c field names from each dumped record and write custom_fields_summary.txt",
    )
    p_dump.set_defaults(func=cmd_dump)

    p_all = aura_sub.add_parser("dump-all", help="Dump all visible objects to files")
    _add_common_args(p_all)
    p_all.add_argument(
        "--type",
        choices=["standard", "custom", "both"],
        default="both",
        help="Which object types to dump (default: both)",
    )
    p_all.add_argument(
        "--custom-fields",
        action="store_true",
        help="Extract __c field names from each dumped record and write custom_fields_summary.txt",
    )
    p_all.set_defaults(func=cmd_dump_all)

    p_rec = aura_sub.add_parser("record", help="Dump a single record by Salesforce ID")
    _add_common_args(p_rec)
    p_rec.add_argument("record_id", metavar="RECORD_ID")
    p_rec.set_defaults(func=cmd_record)

    p_apex = aura_sub.add_parser(
        "apex-fuzz", help="Wordlist-fuzz ApexController ACTION methods"
    )
    _add_common_args(p_apex)
    p_apex.add_argument(
        "-w",
        "--wordlist",
        required=False,
        default=None,
        metavar="FILE",
        help="Optional custom controller wordlist path (default: bundled sfmap list)",
    )
    p_apex.add_argument(
        "--method",
        default="invoke",
        metavar="METHOD",
        help="Apex method name to fuzz (default: invoke)",
    )
    p_apex.set_defaults(func=cmd_apex_fuzz)

    p_oi = aura_sub.add_parser(
        "object-info",
        help="Fetch field-level metadata (getObjectInfo) for one or more objects",
    )
    _add_common_args(p_oi)
    p_oi.add_argument(
        "objects",
        nargs="*",
        metavar="OBJECT",
        help="Object name(s) to inspect (default: all visible objects)",
    )
    p_oi.set_defaults(func=cmd_object_info)

    p_idor = aura_sub.add_parser(
        "idor-probe",
        help="Test getRecord access as unauthenticated guest for all IDs in the output directory",
    )
    _add_common_args(p_idor)
    p_idor.set_defaults(func=cmd_idor_probe)

    p_crud = aura_sub.add_parser(
        "crud-probe",
        help="Probe create/delete access on visible objects (auto-cleans created records)",
    )
    _add_common_args(p_crud)
    p_crud.add_argument(
        "--type",
        choices=["standard", "custom", "both"],
        default="custom",
        help="Which object types to probe (default: custom)",
    )
    p_crud.set_defaults(func=cmd_crud_probe)

    p_inj = aura_sub.add_parser(
        "soql-inject",
        help="Test SOQL injection via getItems where clause and Apex method parameters",
    )
    _add_common_args(p_inj)
    p_inj.add_argument(
        "--apex-hits",
        nargs="*",
        metavar="DESCRIPTOR",
        default=[],
        help="Apex descriptors to test (from apex-fuzz output)",
    )
    p_inj.set_defaults(func=cmd_soql_inject)

    # -- guest group ---------------------------------------------------------
    p_guest = surfaces.add_parser("guest", help="Guest/unauthenticated operations")
    guest_sub = p_guest.add_subparsers(dest="guest_command", required=True)

    p_guest_aura = guest_sub.add_parser(
        "aura", help="Unauthenticated Aura object visibility scan"
    )
    p_guest_aura.add_argument(
        "--output",
        "-o",
        metavar="DIR",
        help="Output directory (default: derived from URL)",
    )
    p_guest_aura.set_defaults(func=cmd_guest, token=None, cookie=None)

    # -- rest group ----------------------------------------------------------
    p_rest = surfaces.add_parser("rest", help="REST surface operations")
    rest_sub = p_rest.add_subparsers(dest="rest_command", required=True)

    p_ce = rest_sub.add_parser(
        "content-enum",
        help="Enumerate Content* and probe unauthenticated VersionData access",
        description=(
            "Dumps ContentDocument (069) and ContentVersion (068) records via Aura, "
            "then probes each ContentVersion ID against "
            "/services/data/v59.0/sobjects/ContentVersion/{Id}/VersionData "
            "without any credentials. A 200 response means the Guest profile has "
            '"API Enabled" and files are downloadable without authentication '
            "(critical finding)."
        ),
    )
    _add_common_args(p_ce)
    p_ce.set_defaults(func=cmd_content_enum)

    p_cd = rest_sub.add_parser(
        "content-download",
        help="Enumerate and download all ContentDocument/ContentVersion files",
    )
    _add_common_args(p_cd)
    p_cd.set_defaults(func=cmd_content_download)

    p_gql = rest_sub.add_parser(
        "graphql-introspect",
        help="Run GraphQL introspection and save schema to output directory",
    )
    _add_common_args(p_gql)
    p_gql.set_defaults(func=cmd_graphql_introspect)

    p_gql_q = rest_sub.add_parser(
        "graphql-query",
        help="Query all known objects via GraphQL uiapi and record accessible record counts",
    )
    _add_common_args(p_gql_q)
    p_gql_q.set_defaults(func=cmd_graphql_query)

    p_chat = rest_sub.add_parser(
        "chatter",
        help="Enumerate Chatter feeds and probe IP leak via /chatter/handlers/file/body",
    )
    _add_common_args(p_chat)
    p_chat.set_defaults(func=cmd_chatter)

    p_cdist = rest_sub.add_parser(
        "content-distribution",
        help="Enumerate ContentDistribution records and probe public file URLs without authentication",
    )
    _add_common_args(p_cdist)
    p_cdist.set_defaults(func=cmd_content_distribution)

    p_ar = rest_sub.add_parser(
        "apexrest-fuzz",
        help="Wordlist-fuzz /services/apexrest/ custom REST endpoints",
    )
    _add_common_args(p_ar)
    p_ar.add_argument(
        "-w",
        "--wordlist",
        default=None,
        metavar="FILE",
        help="Custom endpoint wordlist (default: bundled sfmap list)",
    )
    p_ar.set_defaults(func=cmd_apexrest_fuzz)

    p_soql = rest_sub.add_parser(
        "soql-query",
        help="Run probe SOQL queries via /services/data/{v}/query (requires REST API access)",
    )
    _add_common_args(p_soql)
    p_soql.set_defaults(func=cmd_soql_query)

    # -- surface group -------------------------------------------------------
    p_surface = surfaces.add_parser("surface", help="Cross-surface mapping")
    surface_sub = p_surface.add_subparsers(dest="surface_command", required=True)

    p_exp = surface_sub.add_parser(
        "exposure",
        help="Run REST/SOAP/GraphQL/self-reg/controller checks",
    )
    _add_common_args(p_exp)
    p_exp.set_defaults(func=cmd_exposure)

    # -- files group ---------------------------------------------------------
    p_files = surfaces.add_parser("files", help="File/object download operations")
    files_sub = p_files.add_subparsers(dest="files_command", required=True)

    p_dl = files_sub.add_parser(
        "download",
        help="Download by ContentDocument/ContentVersion ID",
    )
    _add_common_args(p_dl)
    p_dl.add_argument(
        "sf_id",
        metavar="ID",
        help="Salesforce record ID (069 ContentDocument or 068 ContentVersion)",
    )
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
