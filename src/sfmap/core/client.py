# sfmap/core/client

# Built-in imports
import json

# Third-party imports
import httpx
from loguru import logger

# Local imports
from .session import Session

REST_API_VERSION = "v59.0"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/148.0.0.0 Safari/537.36 Edg/148.0.0.0"
)


class AuraSessionExpired(RuntimeError):
    def __init__(self, new_token: str = ""):
        self.new_token = new_token
        msg = "Aura session expired (aura:invalidSession)"
        if new_token == "invalid_csrf":
            msg += ": CSRF token rejected by server, refresh token.txt"
        elif new_token:
            msg += f": server sent new token hint '{new_token}', refresh token.txt"
        super().__init__(msg)


class AuraClient:
    def __init__(
        self, session: Session, authenticated: bool | None = None, verify_ssl: bool = False
    ):
        self._session = session
        if authenticated is None:
            authenticated = not session.is_guest
        self._authenticated = authenticated
        self._guest_mode = not authenticated
        if self._guest_mode:
            logger.debug("AuraClient: running as unauthenticated guest (no credentials)")
        self._http = httpx.Client(
            verify=verify_ssl,
            cookies=session.cookies_dict if authenticated else {},
            headers={"User-Agent": USER_AGENT},
            timeout=30.0,
        )

    @property
    def is_guest(self) -> bool:
        return self._guest_mode

    def _post(self, message: dict, token: str) -> dict:
        body = (
            "message="
            + json.dumps(message)
            + "&aura.context="
            + self._session.context_str
            + "&aura.token="
            + token
        )
        logger.trace(f"Aura POST → {self._session.url}\n{json.dumps(message, indent=2)}")
        resp = self._http.post(
            self._session.url,
            content=body.encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        text = resp.text.lstrip("/*").lstrip()
        logger.trace(f"Aura response HTTP {resp.status_code}: {text[:2000]}")
        obj, _ = json.JSONDecoder().raw_decode(text)
        return obj

    def aura_post(self, message: dict) -> dict:
        token = self._session.token if self._authenticated else "undefined"
        resp = self._post(message, token)
        if resp.get("exceptionEvent") and resp.get("event", {}).get("descriptor") == "markup://aura:invalidSession":
            new_token = resp.get("event", {}).get("attributes", {}).get("values", {}).get("newToken", "")
            raise AuraSessionExpired(new_token)
        return resp

    def get(self, url: str, follow_redirects: bool = True) -> "httpx.Response":
        logger.trace(f"GET {url}")
        resp = self._http.get(url, follow_redirects=follow_redirects)
        logger.trace(f"GET {url} → HTTP {resp.status_code} ({len(resp.content)} bytes)")
        return resp

    def rest_get(self, url: str) -> "httpx.Response":
        headers = {}
        if self._session.bearer_token:
            headers["Authorization"] = f"Bearer {self._session.bearer_token}"
        logger.trace(f"REST GET {url}")
        resp = self._http.get(url, headers=headers)
        logger.trace(f"REST GET {url} → HTTP {resp.status_code}")
        return resp

    def rest_post(self, url: str, **kwargs) -> "httpx.Response":
        headers = kwargs.pop("headers", {})
        if self._session.bearer_token:
            headers["Authorization"] = f"Bearer {self._session.bearer_token}"
        logger.trace(f"REST POST {url}")
        resp = self._http.post(url, headers=headers, **kwargs)
        logger.trace(f"REST POST {url} → HTTP {resp.status_code}")
        return resp

    @property
    def has_bearer(self) -> bool:
        return bool(self._session.bearer_token)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "AuraClient":
        return self

    def __exit__(self, *_) -> None:
        self.close()
