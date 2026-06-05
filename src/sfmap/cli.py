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
from .core.modules import apex, content, dump, enum, exposure
from .core.utils import common, logbook, storage


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

    return Session(
        url=url,
        context=context,
        token=args.token or "undefined",
        cookie=getattr(args, "cookie", None),
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
                full=args.full,
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
                                  full=args.full,
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

    return 1 if findings else 0


def cmd_download(args: argparse.Namespace) -> int:
    session = _build_session(args)
    output_dir = args.output or common.default_output_dir(args.url)
    path = dump.download_file(AuraClient(session), args.sf_id, session.url, output_dir)
    return 0 if path else 1


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


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-T",
        "--token",
        default=None,
        help="aura.token value (omit for unauthenticated/guest access)",
    )
    parser.add_argument("--cookie", help="Raw Cookie header for authentication")
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
        "context",
        metavar="CONTEXT",
        nargs="?",
        default=None,
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
        "-f",
        "--full",
        action="store_true",
        help="Dump all pages (default: first page only)",
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
        "-f", "--full", action="store_true", help="Dump all pages per object"
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


if __name__ == "__main__":
    sys.exit(main())
