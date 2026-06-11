# Built-in imports
import json
import os
import re
from pathlib import Path

# Third-party imports
from loguru import logger

# Local imports
from ..client import AuraClient
from ..session import Session
from . import dump

_SF_ID_RE = re.compile(r'\b([0-9A-Za-z]{15}|[0-9A-Za-z]{18})\b')

_OBJECT_PREFIXES = {
    "001": "Account",
    "003": "Contact",
    "005": "User",
    "006": "Opportunity",
    "00Q": "Lead",
    "00T": "Task",
    "00U": "Event",
    "069": "ContentDocument",
    "068": "ContentVersion",
    "500": "Case",
    "0F9": "ContentDistribution",
}

# Only probe these prefixes + anything that looks like a custom object ID.
# System/infrastructure prefixes (Group, Profile, RecordType, Layout, etc.)
# are excluded to avoid noise; those are expected to be semi-public.
_SENSITIVE_PREFIXES = frozenset({
    "001",  # Account
    "003",  # Contact
    "005",  # User
    "006",  # Opportunity
    "00Q",  # Lead
    "500",  # Case
    "069",  # ContentDocument
    "068",  # ContentVersion
    "0F9",  # ContentDistribution
})


def _plausible_sf_id(fid: str) -> bool:
    prefix = fid[:3]
    return bool(re.match(r'^[0-9]{3}|[0-9]{2}[A-Za-z]|[A-Za-z][0-9]{2}', prefix))


_SKIP_SUBDIRS = frozenset({"graphql", "soql", "chatter", "downloads"})


def _collect_ids_from_files(files: list[Path]) -> set[str]:
    ids: set[str] = set()
    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
            for fid in _SF_ID_RE.findall(text):
                if _plausible_sf_id(fid):
                    ids.add(fid)
        except Exception:
            pass
    return ids


def _is_custom_object_id(fid: str) -> bool:
    """Heuristic: custom object IDs typically start with a lowercase letter followed by digits."""
    return bool(re.match(r'^[a-z][0-9A-Za-z]{2}', fid))


def collect_ids_from_directory(directory: str) -> list[str]:
    """
    Collect candidate IDs for IDOR testing from root-level authenticated dumps.
    Only sensitive standard object prefixes and custom object IDs are included.
    Guest-accessible IDs (from guest/ subdir) are subtracted to avoid false positives.
    """
    root = Path(directory)
    all_ids = _collect_ids_from_files(list(root.glob("*.json")))

    guest_dir = root / "guest"
    guest_ids: set[str] = set()
    if guest_dir.is_dir():
        guest_ids = _collect_ids_from_files(list(guest_dir.glob("*.json")))

    candidates: list[str] = []
    for fid in all_ids - guest_ids:
        prefix = fid[:3]
        if prefix in _SENSITIVE_PREFIXES or _is_custom_object_id(fid):
            candidates.append(fid)

    return candidates


def probe_guest(
    session: Session,
    record_ids: list[str],
    output_dir: str,
) -> list[dict]:
    """
    Try getRecord for each ID via an unauthenticated guest session.
    Findings: records that were returned in SUCCESS state without credentials.
    This indicates the Aura guest profile has read access to individual records
    by ID even when list-view sharing prevents enumeration.
    """
    if not record_ids:
        logger.info("IDOR probe: no record IDs to test")
        return []

    guest_session = Session(
        url=session.url,
        context=session.context,
        token="undefined",
        cookie=None,
        guest_mode=True,
    )

    findings: list[dict] = []
    logger.info(f"IDOR probe: testing {len(record_ids)} record IDs as unauthenticated guest")

    with AuraClient(guest_session) as guest_client:
        for i, record_id in enumerate(record_ids, 1):
            logger.debug(f"[{i}/{len(record_ids)}] getRecord {record_id}")
            logger.trace(f"IDOR getRecord {record_id} (prefix={record_id[:3]})")
            try:
                payload = dump._payload_get_record(record_id)
                resp = guest_client.aura_post(payload)
                actions = resp.get("actions", [])
                state = actions[0].get("state") if actions else "no-actions"
                logger.trace(f"IDOR getRecord {record_id} → state={state}")
                if actions and state == "SUCCESS":
                    rv = actions[0].get("returnValue", {})
                    rv_keys = list(rv.keys()) if isinstance(rv, dict) else []
                    logger.trace(f"IDOR getRecord {record_id} returnValue keys={rv_keys}")
                    if rv_keys == ["onLoadErrorMessage"] or not rv_keys:
                        logger.debug(f"Record {record_id}: exists but data blocked (guest denied)")
                        continue
                    logger.success(
                        f"IDOR: record {record_id} data accessible as guest "
                        f"(prefix={record_id[:3]}, fields={rv_keys[:5]})"
                    )
                    record_obj = rv.get("record", {}) if isinstance(rv, dict) else {}
                    fields = record_obj.get("fields", {}) if isinstance(record_obj, dict) else {}
                    name = None
                    for fname in ("PathOnClient", "Title", "Name"):
                        fval = fields.get(fname)
                        if isinstance(fval, dict) and fval.get("value"):
                            name = fval["value"]
                            break
                    findings.append({
                        "id": record_id,
                        "prefix": record_id[:3],
                        "object_type": _OBJECT_PREFIXES.get(record_id[:3]),
                        "return_value_keys": rv_keys,
                        "record_name": name,
                    })
            except Exception:
                logger.exception(f"IDOR probe error for {record_id}")

    if findings:
        os.makedirs(output_dir, exist_ok=True)
        path = os.path.join(output_dir, "idor_findings.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(findings, ensure_ascii=False, indent=2))
        logger.success(
            f"IDOR: {len(findings)} record(s) accessible as unauthenticated guest, "
            f"see {path}"
        )
    else:
        logger.info("IDOR: no unauthenticated record access found")

    return findings
