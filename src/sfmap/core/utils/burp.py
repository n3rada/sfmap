# sfmap/core/utils/burp.py

# Built-in imports
import base64
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote_plus

# Third-party imports
from loguru import logger


def _extract_host(text: str) -> str | None:
    line_sep = "\r\n" if "\r\n" in text else "\n"
    for line in text.split(line_sep)[1:]:
        low = line.lower()
        if low.startswith("host:"):
            return line[5:].strip() or None
        if not line.strip():
            break
    return None


def parse_burp_host(path: Path) -> str | None:
    """Return the Host header value from a Burp export or raw HTTP request."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return None

    stripped = text.lstrip()
    if stripped.startswith("<?xml") or stripped.startswith("<items"):
        try:
            root = ET.fromstring(text)
            item = root.find("item")
            req_elem = item.find("request") if item is not None else None
            if req_elem is None:
                return None
            raw_bytes = req_elem.text or ""
            http_text = (
                base64.b64decode(raw_bytes).decode("utf-8", errors="replace")
                if req_elem.get("base64") == "true"
                else raw_bytes
            )
        except ET.ParseError:
            return None
        return _extract_host(http_text)

    return _extract_host(text)


def _parse_raw_http(text: str) -> tuple[str | None, str | None, str | None]:
    line_sep = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(line_sep)

    # Scan all lines for the Cookie header (handles HTTP/2 captures where
    # blank lines appear between headers, pushing Cookie past the first double-CRLF).
    cookie: str | None = None
    for line in lines[1:]:
        low = line.lower()
        if low.startswith("cookie:"):
            cookie = line[7:].strip() or None
            break
        if "aura.context=" in line or "aura.token=" in line:
            break

    aura_token: str | None = None
    aura_context: str | None = None
    for part in text.split("&"):
        part = part.strip()
        if part.startswith("aura.token="):
            aura_token = unquote_plus(part[len("aura.token="):]) or None
        elif part.startswith("aura.context="):
            aura_context = unquote_plus(part[len("aura.context="):]) or None

    return cookie, aura_token, aura_context


def parse_burp_request(path: Path) -> tuple[str | None, str | None, str | None]:
    """Return (cookie_header_value, aura_token) from a Burp export file.

    Handles both raw HTTP request text and Burp XML exports (base64-encoded).
    Returns (cookie, aura_token, aura_context_json_str).
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
