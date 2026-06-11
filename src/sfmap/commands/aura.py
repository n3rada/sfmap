# sfmap/commands/aura.py

# Built-in imports
import argparse

# Third-party imports
from loguru import logger

# Local imports
from ..core.client import AuraClient
from ..core.modules import apex, bootstrap, crud, dump, enum, flow, idor, injection, listviews, network, relatedlist
from ..core.utils.storage import OutputWriter
from ._context import _build_session, _resolve_output_dir


def cmd_list_objects(args: argparse.Namespace) -> int:
    from ..core.utils import storage
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


def cmd_list_views(args: argparse.Namespace) -> int:
    session = _build_session(args)
    out = OutputWriter(_resolve_output_dir(args, session))
    with AuraClient(session) as client:
        all_objects = enum.list_objects(client)
        urls = listviews.sweep(client, list(all_objects.keys()), out)
    return 1 if urls else 0


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


def cmd_bootstrap(args: argparse.Namespace) -> int:
    session = _build_session(args)
    out = OutputWriter(_resolve_output_dir(args, session))
    with AuraClient(session) as client:
        results = bootstrap.fetch(client, out)
    return 1 if results else 0


def cmd_aura_follow(args: argparse.Namespace) -> int:
    session = _build_session(args)
    out = OutputWriter(_resolve_output_dir(args, session))
    with AuraClient(session) as client:
        results = relatedlist.sweep(client, out)
    return 1 if results else 0


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
