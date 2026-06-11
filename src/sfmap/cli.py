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
from .core.client import AuraClient, AuraSessionExpired
from .core.session import Session
from .core.modules import apex, apexrest, bootstrap, chatter, content, crud, dump, enum, exposure, flow, graphql, idor, injection, listviews, network, relatedlist, reporter, soql, staticresource, tooling
from .core.utils import autocontext, identity as identity_mod
from .core.utils import burp as burp_mod, common, logbook, storage
from .core.utils.storage import OutputWriter


def _resolve_output_dir(args: argparse.Namespace, session: Session | None = None) -> str:
    if args.output:
        return args.output
    if not args.url:
        logger.error("URL is required when --output is not specified")
        raise SystemExit(1)
    base = common.default_output_dir(args.url)
    label = getattr(args, "identity", None)
    display: str | None = None
    if not label:
        if session is None or session.is_guest:
            label = "guest"
        else:
            with AuraClient(session) as tmp:
                label, display = identity_mod.resolve_with_display(tmp)
    output_dir = os.path.join(base, label)
    if display and display != label:
        identity_mod.save_display_name(output_dir, display)
    return output_dir


def _resolve_file_arg(value: str | None, default_file: str, label: str = "") -> str | None:
    raw = value or f"@{default_file}"
    if raw.startswith("@"):
        path = Path(raw[1:])
        if not path.exists():
            if value:
                logger.error(f"{label}: file not found: {path}")
                raise SystemExit(1)
            logger.debug(f"{label}: {path} not found, skipping")
            return None
        try:
            content = path.read_text(encoding="utf-8-sig").strip() or None
        except OSError as exc:
            logger.error(f"{label}: cannot read {path}: {exc}")
            raise SystemExit(1) from exc
        if content:
            logger.info(f"{label}: loaded from {path} ({len(content)} chars)")
        else:
            logger.warning(f"{label}: {path} exists but is empty")
        return content
    logger.info(f"{label}: loaded from command-line argument")
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
                logger.info(f"context: loaded from {path}")
            except OSError as exc:
                logger.error(f"context: cannot read {path}: {exc}")
                raise SystemExit(1) from exc
            except json.JSONDecodeError as exc:
                logger.error(f"context: {path} is not valid JSON: {exc}")
                raise SystemExit(1) from exc
    else:
        try:
            context = json.loads(raw_context)
            logger.info("context: loaded from command-line argument")
        except json.JSONDecodeError as exc:
            logger.error(f"context: not valid JSON: {exc}")
            raise SystemExit(1) from exc

    # -- credentials ---------------------------------------------------
    # burp.txt is the primary credential source. When present, delete cookies.txt
    # and token.txt so stale files cannot interfere with subsequent runs.
    burp_cookie: str | None = None
    burp_token: str | None = None
    burp_path = Path("burp.txt")
    if burp_path.exists():
        burp_cookie, burp_token = burp_mod.parse_burp_request(burp_path)
        if burp_cookie:
            logger.info(f"burp: loaded cookie from {burp_path} ({len(burp_cookie)} chars)")
        if burp_token:
            logger.info(f"burp: loaded aura.token from {burp_path} ({len(burp_token)} chars)")
        for stale in ("cookies.txt", "token.txt"):
            p = Path(stale)
            if p.exists():
                p.unlink()
                logger.info(f"burp: removed stale {stale}")

    cookie_cli = getattr(args, "cookie", None)
    if cookie_cli:
        cookie = _resolve_file_arg(cookie_cli, "cookies.txt", "cookie")
    elif burp_cookie:
        cookie = burp_cookie
    else:
        cookie = _resolve_file_arg(None, "cookies.txt", "cookie")

    bearer = _resolve_file_arg(getattr(args, "bearer", None), "bearer.txt", "bearer")

    token_cli = getattr(args, "token", None)
    if token_cli:
        token_raw = _resolve_file_arg(token_cli, "token.txt", "token")
    elif burp_token:
        token_raw = burp_token
    else:
        token_raw = _resolve_file_arg(None, "token.txt", "token")

    if token_raw is None and extracted_token and cookie:
        token = extracted_token
        logger.info("token: using auto-extracted value from page HTML")
    elif token_raw is None:
        token = "undefined"
        logger.info("token: none found, using 'undefined' (guest mode)")
    else:
        token = token_raw

    session = Session(
        url=url,
        context=context,
        token=token,
        cookie=cookie,
        bearer_token=bearer,
    )

    if not session.is_guest:
        try:
            with AuraClient(session) as client:
                identity_mod.verify(client)
            logger.info("Auth: session credentials accepted")
        except AuraSessionExpired as exc:
            logger.error(f"Auth: {exc}")
            raise SystemExit(1) from exc

    return session


def cmd_list_objects(args: argparse.Namespace) -> int:
    session = _build_session(args)
    out = OutputWriter(_resolve_output_dir(args, session))
    with AuraClient(session) as client:
        objects, csp_sites = enum.list_objects_with_csp(client)
        enum._print_objects_from(objects)
    storage.save_config_data(session.url, objects)
    logger.info(f"Object list cached → {storage.config_data_path(session.url)}")
    if csp_sites:
        path = out.save("csp_trusted_sites.json", csp_sites)
        logger.info(f"CSP trusted sites saved → {path}")
    return 0


def cmd_dump(args: argparse.Namespace) -> int:
    session = _build_session(args)
    out = OutputWriter(_resolve_output_dir(args, session))
    obj_type = getattr(args, "type", "both")
    display = getattr(args, "display", False)
    custom_fields = getattr(args, "custom_fields", False)
    explicit = getattr(args, "objects", None) or []

    with AuraClient(session) as client:
        if explicit:
            for i, obj in enumerate(explicit, 1):
                logger.debug(f"{i}/{len(explicit)}) Dumping '{obj}'")
                ok = dump.dump_object(client, obj, out, full=True,
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
                ok = dump.dump_object(client, obj, out, full=True,
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
    out = OutputWriter(_resolve_output_dir(args, session))
    with AuraClient(session) as client:
        critical = content.run(client, session.url, out)
    return 1 if critical else 0


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


def cmd_download(args: argparse.Namespace) -> int:
    session = _build_session(args)
    out = OutputWriter(_resolve_output_dir(args, session))
    path = dump.download_file(AuraClient(session), args.sf_id, session.url, out.subdir("downloads"))
    return 0 if path else 1


def cmd_crud_probe(args: argparse.Namespace) -> int:
    session = _build_session(args)
    out = OutputWriter(_resolve_output_dir(args, session))
    with AuraClient(session) as client:
        all_objects = enum.list_objects(client)
        if args.type == "standard":
            targets = {k: v for k, v in all_objects.items() if not k.endswith("__c")}
        elif args.type == "custom":
            targets = {k: v for k, v in all_objects.items() if k.endswith("__c")}
        else:
            targets = all_objects
        findings = crud.probe(client, targets, out)
    return 1 if findings else 0


def cmd_soql_inject(args: argparse.Namespace) -> int:
    session = _build_session(args)
    out = OutputWriter(_resolve_output_dir(args, session))
    apex_hits: list[str] = getattr(args, "apex_hits", None) or []
    with AuraClient(session) as client:
        all_objects = enum.list_objects(client)
        result = injection.run(client, all_objects, apex_hits, out)
    return 1 if result["findings"] else 0


def cmd_chatter(args: argparse.Namespace) -> int:
    session = _build_session(args)
    out = OutputWriter(_resolve_output_dir(args, session))
    with AuraClient(session) as client:
        summary = chatter.run(client, session.url, out)
    findings = bool(summary.get("file_upload") or summary.get("aura_objects") or summary.get("rest_endpoints"))
    return 1 if findings else 0


def cmd_graphql_dump(args: argparse.Namespace) -> int:
    session = _build_session(args)
    out = OutputWriter(_resolve_output_dir(args, session))
    obj = getattr(args, "object", None)
    fields = getattr(args, "fields", None) or []
    with AuraClient(session) as client:
        if obj and fields:
            result = graphql.dump_object(client, obj, fields, out)
            return 1 if result else 0
        elif obj:
            result = graphql.autodump(client, out, object_names=[obj])
        else:
            result = graphql.autodump(client, out, object_names=None)
    return 1 if result else 0


def cmd_graphql_query(args: argparse.Namespace) -> int:
    session = _build_session(args)
    out = OutputWriter(_resolve_output_dir(args, session))
    with AuraClient(session) as client:
        all_objects = enum.list_objects(client)
        object_names = list(all_objects.keys())
        schema_path = out / "graphql" / "graphql_schema.json"
        if schema_path.is_file():
            schema_names = graphql.schema_object_names(schema_path)
            extra = [n for n in schema_names if n not in all_objects]
            if extra:
                logger.info(f"Schema expands sweep by {len(extra)} type(s) not in getConfigData")
                object_names.extend(extra)
        results = graphql.query_objects(client, object_names, out)
    return 1 if any(v > 0 for v in results.values()) else 0


def cmd_content_download(args: argparse.Namespace) -> int:
    session = _build_session(args)
    out = OutputWriter(_resolve_output_dir(args, session))
    with AuraClient(session) as client:
        downloaded = content.download_all(client, session.url, out, out.subdir("downloads"))
    return 0 if downloaded else 1


def cmd_graphql_introspect(args: argparse.Namespace) -> int:
    session = _build_session(args)
    out = OutputWriter(_resolve_output_dir(args, session))
    with AuraClient(session) as client:
        ok = graphql.introspect(client, session.url, out)
    return 0 if ok else 1


def cmd_apex_fuzz(args: argparse.Namespace) -> int:
    session = _build_session(args)
    with AuraClient(session) as client:
        hits = apex.fuzz(client, args.wordlist, method=args.method)
    if hits:
        logger.success(f"{len(hits)} callable descriptor(s) found:")
        for h in hits:
            logger.info(f"  {h}")
    else:
        logger.info("No callable Apex descriptors found.")
    return 0 if not hits else 1


def cmd_apex_controllers(args: argparse.Namespace) -> int:
    session = _build_session(args)
    out = OutputWriter(_resolve_output_dir(args, session))

    with AuraClient(session) as client:
        descriptors = apex.discover(client, session.url, str(out))

    if not descriptors:
        logger.info("No Apex ACTION descriptors discovered")
        return 0

    disc_path = out.save("apex_descriptors.json", descriptors)
    logger.info(f"Saved {len(descriptors)} descriptor(s) to {disc_path}")

    with AuraClient(session) as client:
        results = apex.probe(client, descriptors)

    callable_ones = [d for d, s in results.items() if s == "callable"]
    exists_denied = [d for d, s in results.items() if s == "exists_denied"]

    out.save("apex_hits.json", {"callable": callable_ones, "exists_denied": exists_denied})

    logger.info(f"Probe complete: {len(callable_ones)} callable, {len(exists_denied)} access-denied")
    return 1 if callable_ones or exists_denied else 0


def cmd_object_info(args: argparse.Namespace) -> int:
    session = _build_session(args)
    out = OutputWriter(_resolve_output_dir(args, session))
    with AuraClient(session) as client:
        objects = args.objects or list(enum.list_objects(client).keys())
        for obj in objects:
            info = dump.get_object_info(client, obj)
            if info:
                path = out.save(f"objectinfo_{obj}.json", info)
                fields = info.get("fields", {})
                logger.info(f"{obj}: {len(fields)} field(s), saved to {path}")
            else:
                logger.debug(f"{obj}: getObjectInfo returned nothing")
    return 0


def cmd_related_lists(args: argparse.Namespace) -> int:
    session = _build_session(args)
    out = OutputWriter(_resolve_output_dir(args, session))
    with AuraClient(session) as client:
        results = relatedlist.probe(
            client,
            args.record_id,
            out,
            object_api_name=getattr(args, "object", None),
        )
    return 1 if any(v > 0 for v in results.values()) else 0


def cmd_aura_follow(args: argparse.Namespace) -> int:
    session = _build_session(args)
    out = OutputWriter(_resolve_output_dir(args, session))
    with AuraClient(session) as client:
        results = relatedlist.sweep(client, out)
    return 1 if results else 0


def cmd_flow_fuzz(args: argparse.Namespace) -> int:
    session = _build_session(args)
    out = OutputWriter(_resolve_output_dir(args, session))
    with AuraClient(session) as client:
        hits = flow.fuzz(client, out, wordlist_path=getattr(args, "wordlist", None))
    return 1 if hits else 0


def cmd_network_access(args: argparse.Namespace) -> int:
    session = _build_session(args)
    out = OutputWriter(_resolve_output_dir(args, session))
    with AuraClient(session) as client:
        results = network.fetch(client, out)
    return 1 if results else 0


def cmd_idor_probe(args: argparse.Namespace) -> int:
    session = _build_session(args)
    out = OutputWriter(_resolve_output_dir(args, session))
    record_ids = idor.collect_ids_from_directory(out.path)
    if not record_ids:
        logger.warning("No record IDs found in output directory, run 'aura dump' first")
        return 1
    logger.info(f"Collected {len(record_ids)} unique record ID(s) from {out}")
    findings = idor.probe_guest(session, record_ids, out)
    return 1 if findings else 0


def cmd_content_distribution(args: argparse.Namespace) -> int:
    session = _build_session(args)
    out = OutputWriter(_resolve_output_dir(args, session))
    with AuraClient(session) as client:
        hits = content.check_content_distribution(client, session.url, out)
    return 1 if hits else 0


def cmd_apexrest_fuzz(args: argparse.Namespace) -> int:
    session = _build_session(args)
    out = OutputWriter(_resolve_output_dir(args, session))
    with AuraClient(session) as client:
        hits = apexrest.fuzz(client, session.url, out, wordlist_path=args.wordlist)
    return 1 if hits else 0


def cmd_static_resources(args: argparse.Namespace) -> int:
    session = _build_session(args)
    out = OutputWriter(_resolve_output_dir(args, session))
    with AuraClient(session) as client:
        hits = staticresource.fuzz(client, session.url, out, wordlist_path=args.wordlist)
    return 1 if hits else 0


def cmd_soql_query(args: argparse.Namespace) -> int:
    session = _build_session(args)
    out = OutputWriter(_resolve_output_dir(args, session))
    with AuraClient(session) as client:
        results = soql.run(client, session.url, out.subdir("soql"))
    return 1 if results else 0


def cmd_sosl_query(args: argparse.Namespace) -> int:
    session = _build_session(args)
    out = OutputWriter(_resolve_output_dir(args, session))
    with AuraClient(session) as client:
        results = soql.run_sosl(client, session.url, out.subdir("sosl"))
    return 1 if results else 0


def cmd_bootstrap(args: argparse.Namespace) -> int:
    session = _build_session(args)
    out = OutputWriter(_resolve_output_dir(args, session))
    with AuraClient(session) as client:
        results = bootstrap.fetch(client, out)
    return 1 if results else 0


def cmd_list_views(args: argparse.Namespace) -> int:
    session = _build_session(args)
    out = OutputWriter(_resolve_output_dir(args, session))
    with AuraClient(session) as client:
        all_objects = enum.list_objects(client)
        urls = listviews.sweep(client, list(all_objects.keys()), out)
    return 1 if urls else 0


def cmd_report(args: argparse.Namespace) -> int:
    if not args.output:
        logger.error("--output DIR is required")
        return 1
    output_dir = args.output
    if not os.path.isdir(output_dir):
        logger.error(f"Output directory not found: {output_dir}")
        return 1
    reporter.generate(output_dir)
    return 0



def cmd_tooling_query(args: argparse.Namespace) -> int:
    session = _build_session(args)
    out = OutputWriter(_resolve_output_dir(args, session))
    with AuraClient(session) as client:
        results = tooling.run(client, session.url, out)
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

    # -- report --------------------------------------------------------------
    p_report = surfaces.add_parser(
        "report",
        help="Generate a self-contained HTML report from an existing output directory",
    )
    p_report.add_argument(
        "--output", "-o", metavar="DIR", required=True,
        help="Output directory to read",
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
    # Show help if no cli args provided
    if len(sys.argv) <= 1:
        build_parser().print_help()
        return 1

    # When a no-URL surface (e.g. "report") appears before any URL argument,
    # inject a placeholder so argparse can still parse the positional structure.
    argv = sys.argv[1:]
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

    from .core.client import AuraSessionExpired
    try:
        return args.func(args)
    except AuraSessionExpired as exc:
        logger.error(str(exc))
        return 1
