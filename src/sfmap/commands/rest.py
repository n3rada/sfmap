# sfmap/commands/rest.py

# Built-in imports
import argparse

# Third-party imports
from loguru import logger

# Local imports
from ..core.client import AuraClient
from ..core.modules import apexrest, chatter, config, content, dump, enum, graphql, soql, staticresource, tooling
from ..core.utils.storage import OutputWriter
from ._context import _build_session, _resolve_output_dir


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


def cmd_graphql_introspect(args: argparse.Namespace) -> int:
    session = _build_session(args)
    out = OutputWriter(_resolve_output_dir(args, session))
    with AuraClient(session) as client:
        ok = graphql.introspect(client, session.url, out)
    return 0 if ok else 1


def cmd_chatter(args: argparse.Namespace) -> int:
    session = _build_session(args)
    out = OutputWriter(_resolve_output_dir(args, session))
    with AuraClient(session) as client:
        summary = chatter.run(client, session.url, out)
    findings = bool(summary.get("file_upload") or summary.get("aura_objects") or summary.get("rest_endpoints"))
    return 1 if findings else 0


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


def cmd_tooling_query(args: argparse.Namespace) -> int:
    session = _build_session(args)
    out = OutputWriter(_resolve_output_dir(args, session))
    with AuraClient(session) as client:
        results = tooling.run(client, session.url, out)
    return 1 if results else 0


def cmd_config_review(args: argparse.Namespace) -> int:
    session = _build_session(args)
    out = OutputWriter(_resolve_output_dir(args, session))
    with AuraClient(session) as client:
        results = config.run(client, session.url, out)
    return 1 if any(v > 0 for v in results.values()) else 0


def cmd_content_enum(args: argparse.Namespace) -> int:
    session = _build_session(args)
    out = OutputWriter(_resolve_output_dir(args, session))
    with AuraClient(session) as client:
        critical = content.run(client, session.url, out)
    return 1 if critical else 0


def cmd_content_download(args: argparse.Namespace) -> int:
    session = _build_session(args)
    out = OutputWriter(_resolve_output_dir(args, session))
    with AuraClient(session) as client:
        downloaded = content.download_all(client, session.url, out, out.subdir("downloads"))
    return 0 if downloaded else 1


def cmd_content_distribution(args: argparse.Namespace) -> int:
    session = _build_session(args)
    out = OutputWriter(_resolve_output_dir(args, session))
    with AuraClient(session) as client:
        hits = content.check_content_distribution(client, session.url, out)
    return 1 if hits else 0
