# Built-in imports
import json
import re
from pathlib import Path
from urllib.parse import urlparse

# Third-party imports
from loguru import logger

# Local imports
from ..client import AuraClient
from ..utils import storage

DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 1000
APEX_PAGE_SIZE = 25


def _payload_get_items(object_name: str, page_size: int, page: int) -> dict:
    return {
        "actions": [
            {
                "id": "mar;a",
                "descriptor": "serviceComponent://ui.force.components.controllers.lists.selectableListDataProvider.SelectableListDataProviderController/ACTION$getItems",
                "callingDescriptor": "UNKNOWN",
                "params": {
                    "entityNameOrId": object_name,
                    "layoutType": "FULL",
                    "pageSize": page_size,
                    "currentPage": page - 1,  # Salesforce is 0-indexed
                    "useTimeout": False,
                    "getCount": True,
                    "enableRowActions": False,
                },
            }
        ]
    }


def _payload_get_record(record_id: str) -> dict:
    return {
        "actions": [
            {
                "id": "mar;a",
                "descriptor": "serviceComponent://ui.force.components.controllers.detail.DetailController/ACTION$getRecord",
                "callingDescriptor": "UNKNOWN",
                "params": {
                    "recordId": record_id,
                    "record": None,
                    "inContextOfComponent": "",
                    "mode": "VIEW",
                    "layoutType": "FULL",
                    "defaultFieldValues": None,
                    "navigationLocation": "LIST_VIEW_ROW",
                },
            }
        ]
    }


def _extract_error(errors: list) -> str:
    try:
        msg = errors[0]["event"]["attributes"]["values"]["message"]
        return msg.replace("\n", " ")
    except (IndexError, KeyError):
        return "unknown error"


def get_items(
    client: AuraClient,
    object_name: str,
    page_size: int = DEFAULT_PAGE_SIZE,
    page: int = 1,
    silent: bool = False,
) -> dict | None:  # page is 1-based
    """Returns returnValue dict for a single page, or None on failure."""
    mode = "guest" if client.is_guest else "authenticated"
    payload = _payload_get_items(object_name, page_size, page)
    logger.trace(f"getItems {object_name} page={page} page_size={page_size} mode={mode}")
    try:
        response = client.aura_post(payload)
    except Exception:
        logger.exception(f"get_items {object_name} failed")
        return None

    if response.get("exceptionEvent"):
        logger.debug(f"Aura exception for {object_name} ({mode} mode)")
        return None

    actions = response.get("actions", [])
    if not actions:
        return None

    action = actions[0]
    state = action.get("state")
    logger.trace(f"getItems {object_name} page={page} → state={state}")
    if state == "ERROR":
        msg = f"{object_name}: {_extract_error(action.get('error', []))}"
        if client.is_guest or silent:
            logger.debug(msg)
        else:
            logger.warning(msg)
        return None

    return_value = action.get("returnValue", {})
    total = return_value.get("totalCount", "?")
    result_count = len(return_value.get("result", []))
    logger.trace(f"getItems {object_name} page={page} → totalCount={total} results={result_count}")
    if not return_value.get("result"):
        return None

    return return_value


def get_record(client: AuraClient, record_id: str) -> None:
    """Dumps a single record by ID and prints it."""
    logger.debug(f"Dumping record: {record_id}")
    payload = _payload_get_record(record_id)
    response = client.aura_post(payload)

    actions = response.get("actions", [{}])
    if not actions or actions[0].get("state") != "SUCCESS":
        logger.warning("Record dump failed")
        return

    rv = actions[0].get("returnValue")
    print(json.dumps(rv, ensure_ascii=False, indent=2))


def get_object_info(client: AuraClient, object_name: str) -> dict | None:
    """Fetch field-level metadata via RecordUiController/ACTION$getObjectInfo."""
    payload = {
        "actions": [{
            "id": "oi;a",
            "descriptor": "aura://RecordUiController/ACTION$getObjectInfo",
            "callingDescriptor": "UNKNOWN",
            "params": {"objectApiName": object_name},
        }]
    }
    response = client.aura_post(payload)
    actions = response.get("actions", [])
    if not actions:
        return None
    action = actions[0]
    if action.get("state") != "SUCCESS":
        msg = _extract_error(action.get("error", []))
        logger.debug(f"getObjectInfo {object_name}: {msg}")
        return None
    return action.get("returnValue")


def dump_object(
    client: AuraClient,
    object_name: str,
    out: storage.OutputWriter,
    full: bool = False,
    display: bool = False,
    custom_fields: bool = False,
) -> bool:
    """
    Dumps all pages of object_name to JSON files under output_dir.
    Returns True if at least one page was written, False on total failure.
    """
    page_size = (
        APEX_PAGE_SIZE
        if object_name == "ApexClass"
        else (MAX_PAGE_SIZE if full else DEFAULT_PAGE_SIZE)
    )
    page = 1
    wrote_any = False
    found_fields: set[str] = set()

    while True:
        rv = get_items(client, object_name, page_size, page)
        if rv is None:
            break

        write_page(out, object_name, page, rv)
        wrote_any = True

        if custom_fields and not object_name.endswith("__c"):
            found_fields.update(identify_custom_fields(rv))

        if display:
            print(json.dumps(rv, ensure_ascii=False, indent=2))

        results = rv.get("result", [])

        page += 1
        if not full or len(results) < page_size:
            break

    if custom_fields and found_fields:
        write_custom_fields_summary(out, object_name, found_fields)
        logger.info(f"{object_name}: {len(found_fields)} custom field(s) found")

    return wrote_any


def write_page(out: storage.OutputWriter, object_name: str, page: int, value: dict) -> None:
    path = out.save(f"{object_name}__page{page}.json", value)
    logger.debug(f"Saved {path}")


def identify_custom_fields(return_value: dict) -> set[str]:
    """Recursively walk a getItems returnValue and collect every __c field name."""
    custom_fields: set[str] = set()

    def _walk(obj: object) -> None:
        if not isinstance(obj, dict):
            return
        for key, value in obj.items():
            if key.endswith("__c"):
                custom_fields.add(key)
            if isinstance(value, dict) and value.get("sobjectType") is None:
                _walk(value)
            elif isinstance(value, list):
                for item in value:
                    _walk(item)

    for result in return_value.get("result", []):
        _walk(result.get("record", result))

    return custom_fields


def write_custom_fields_summary(out: storage.OutputWriter, object_name: str, fields: set[str]) -> None:
    """Append custom field names for object_name to custom_fields_summary.txt."""
    filename = "custom_fields_summary.txt"
    header = not (out.path / filename).exists()
    lines: list[str] = []
    if header:
        lines += ["Custom Fields Summary\n", "===================\n\n"]
    lines += [f"Object: {object_name}\n", "Custom Fields:\n"]
    lines += [f"  - {field}\n" for field in sorted(fields)]
    lines.append("\n")
    out.append_text(filename, "".join(lines))
    logger.debug(f"Custom fields for {object_name} appended to {out / filename}")


def download_file(
    client: "AuraClient", sf_id: str, aura_url: str, out: storage.OutputWriter
) -> Path | None:
    """
    Download a Salesforce file by ContentDocument (069) or ContentVersion (068) ID.
    Uses the servlet.shepherd download endpoint, not the Aura API.
    """
    parsed = urlparse(aura_url)
    base = f"{parsed.scheme}://{parsed.netloc}"

    if sf_id.startswith("069"):
        url = f"{base}/sfc/servlet.shepherd/document/download/{sf_id}"
    elif sf_id.startswith("068"):
        url = f"{base}/sfc/servlet.shepherd/version/download/{sf_id}"
    else:
        logger.warning(
            f"Unrecognised Salesforce ID prefix: {sf_id} (expected 069 or 068)"
        )
        return None

    logger.debug(f"GET {url}")
    resp = client.get(url)

    if resp.status_code != 200:
        logger.warning(f"Download failed: HTTP {resp.status_code}")
        return None

    # Try to extract filename from Content-Disposition
    filename: str | None = None
    cd = resp.headers.get("Content-Disposition", "")
    m = re.search(r'filename\*?=[\'"]?(?:UTF-8\'\')?([^\'"\s;]+)', cd, re.IGNORECASE)
    if m:
        filename = m.group(1)

    if not filename:
        filename = sf_id

    dest = out.save_bytes(filename, resp.content)
    logger.info(f"Saved {dest} ({len(resp.content):,} bytes)")
    return dest
