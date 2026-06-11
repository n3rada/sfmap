# sfmap/core/utils/burp.py

# Built-in imports
import base64
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote_plus

# Third-party imports
from loguru import logger


def _parse_raw_http(text: str) -> tuple[str | None, str | None]:
    sep = "\r\n\r\n" if "\r\n\r\n" in text else "\n\n"
    parts = text.split(sep, 1)
    header_section = parts[0]
    body = parts[1] if len(parts) > 1 else ""

    line_sep = "\r\n" if "\r\n" in header_section else "\n"
    header_lines = header_section.split(line_sep)

    cookie: str | None = None
    for line in header_lines[1:]:
        if line.lower().startswith("cookie:"):
            cookie = line[7:].strip() or None
            break

    aura_token: str | None = None
    for part in body.split("&"):
        if part.startswith("aura.token="):
            raw = part[len("aura.token="):]
            aura_token = unquote_plus(raw) or None
            break

    return cookie, aura_token


def parse_burp_request(path: Path) -> tuple[str | None, str | None]:
    """Return (cookie_header_value, aura_token) from a Burp export file.

    Handles both raw HTTP request text and Burp XML exports (base64-encoded).
    """
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        logger.exception(f"burp: cannot read {path}")
        return None, None

    stripped = text.lstrip()
    if stripped.startswith("<?xml") or stripped.startswith("<items"):
        try:
            root = ET.fromstring(text)
            item = root.find("item")
            if item is None:
                logger.warning("burp: XML export has no <item> elements")
                return None, None
            req_elem = item.find("request")
            if req_elem is None:
                logger.warning("burp: XML <item> has no <request> element")
                return None, None
            raw_bytes = req_elem.text or ""
            if req_elem.get("base64") == "true":
                http_text = base64.b64decode(raw_bytes).decode("utf-8", errors="replace")
            else:
                http_text = raw_bytes
        except ET.ParseError:
            logger.exception("burp: failed to parse XML export")
            return None, None
        return _parse_raw_http(http_text)

    return _parse_raw_http(text)
