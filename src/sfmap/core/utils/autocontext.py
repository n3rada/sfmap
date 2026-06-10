# Built-in imports
import json
import re
from urllib.parse import urlparse

# Third-party imports
import httpx
from loguru import logger

_CANDIDATE_PATHS = ["/s", "/"]

_DUMMY_CONTEXT = {
    "mode": "PROD",
    "fwuid": "INVALID",
    "app": "siteforce:loginApp2",
    "loaded": {"APPLICATION@markup://siteforce:loginApp2": "siteforce:loginApp2"},
    "dn": [],
    "globals": {},
    "uad": False,
}
_DUMMY_ACTION = {
    "id": "242;a",
    "descriptor": "serviceComponent://ui.force.components.controllers.relatedList.RelatedListContainerDataProviderController/ACTION$getRecords",
    "callingDescriptor": "UNKNOWN",
    "params": {"recordId": "Foobar"},
}

_FWUID_RE = re.compile(r'"fwuid"\s*:\s*"([^"]+)"')
_MARKUP_RE = re.compile(r'"(APPLICATION@markup://[^"]+)"\s*:\s*"([^"]+)"')
_APP_RE = re.compile(r'"app"\s*:\s*"([^"]+)"')
_TOKEN_RE = re.compile(r'eyJub[^";]+')


def _base_url(aura_url: str) -> str:
    p = urlparse(aura_url)
    return f"{p.scheme}://{p.netloc}"


def _context_from_html(text: str) -> dict | None:
    fwuid_m = _FWUID_RE.search(text)
    markup_m = _MARKUP_RE.search(text)
    app_m = _APP_RE.search(text)
    if not (fwuid_m and markup_m and app_m):
        return None
    return {
        "mode": "PROD",
        "fwuid": fwuid_m.group(1),
        "app": app_m.group(1),
        "loaded": {markup_m.group(1): markup_m.group(2)},
        "dn": [],
        "globals": {},
        "uad": False,
    }


def _token_from_response(resp: httpx.Response) -> str | None:
    if m := _TOKEN_RE.search(resp.text):
        return m.group(0)
    if m := _TOKEN_RE.search(resp.headers.get("set-cookie", "")):
        return m.group(0)
    return None


def _context_from_dummy_post(aura_url: str, http: httpx.Client) -> dict | None:
    """
    Send a malformed POST; the Aura framework error response leaks the real fwuid
    in the format "Expected: <real_fwuid> Actual: INVALID".
    """
    body = (
        "message=" + json.dumps({"actions": [_DUMMY_ACTION]})
        + "&aura.context=" + json.dumps(_DUMMY_CONTEXT)
        + "&aura.token=undefined"
    )
    try:
        resp = http.post(
            aura_url,
            content=body.encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        # Pattern 1: framework version mismatch error
        if m := re.search(r"Expected:\s*(\S+)\s+Actual", resp.text):
            fwuid = m.group(1)
            logger.debug(f"Auto-context: fwuid from framework mismatch error: {fwuid}")
            ctx = dict(_DUMMY_CONTEXT)
            ctx["fwuid"] = fwuid
            return ctx
        # Pattern 2: context embedded in JSON response
        try:
            data = resp.json()
            if fwuid := data.get("context", {}).get("fwuid"):
                logger.debug(f"Auto-context: fwuid from response context: {fwuid}")
                ctx = dict(_DUMMY_CONTEXT)
                ctx["fwuid"] = fwuid
                return ctx
        except Exception:
            pass
    except Exception:
        logger.exception("Auto-context: dummy POST failed")
    return None


def extract(aura_url: str) -> tuple[dict, str | None]:
    """
    Auto-extract the Aura context dict and optional token from the target site.

    Approach:
    1. GET /s: parse fwuid, app, APPLICATION@markup from the HTML
    2. GET /: same
    3. Dummy POST to the Aura endpoint: extract fwuid from framework error

    Returns (context_dict, token_str | None).
    token_str is only present when the HTML page contains a visible JWT (authenticated session).
    Raises ValueError if all three approaches fail.
    """
    base = _base_url(aura_url)
    http = httpx.Client(
        verify=False,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        },
        timeout=20.0,
        follow_redirects=True,
    )

    context: dict | None = None
    token: str | None = None

    try:
        for path in _CANDIDATE_PATHS:
            url = f"{base}{path}"
            try:
                resp = http.get(url)
                if resp.status_code == 200:
                    context = _context_from_html(resp.text)
                    if context:
                        logger.debug(f"Auto-context: extracted from page {url}")
                        token = _token_from_response(resp)
                        break
            except Exception:
                logger.exception(f"Auto-context: GET {url} failed")

        if context is None:
            logger.debug("Auto-context: HTML scan found nothing, trying dummy POST")
            context = _context_from_dummy_post(aura_url, http)
    finally:
        http.close()

    if context is None:
        raise ValueError(
            f"Could not auto-extract Aura context from {base}. "
            "Capture it manually from Burp and save to ctx.json, or pass it with -C."
        )

    logger.info(f"Auto-context: fwuid={context['fwuid']!r} app={context['app']!r}")
    return context, token
