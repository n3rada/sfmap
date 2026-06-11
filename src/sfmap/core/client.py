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


class AuraClient:
    def __init__(
        self, session: Session, authenticated: bool | None = None, verify_ssl: bool = False
    ):
        self._session = session
        # If caller doesn't specify, derive from session: guest session → unauthenticated
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
        resp = self._http.post(
            self._session.url,
            content=body.encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        text = resp.text.lstrip("/*").lstrip()
        return json.loads(text)

    def aura_post(self, message: dict) -> dict:
        token = self._session.token if self._authenticated else "undefined"
        return self._post(message, token)

    def get(self, url: str, follow_redirects: bool = True) -> "httpx.Response":
        return self._http.get(url, follow_redirects=follow_redirects)

    def rest_get(self, url: str) -> "httpx.Response":
        """GET with OAuth Bearer header when a bearer_token is configured."""
        headers = {}
        if self._session.bearer_token:
            headers["Authorization"] = f"Bearer {self._session.bearer_token}"
        return self._http.get(url, headers=headers)

    def rest_post(self, url: str, **kwargs) -> "httpx.Response":
        """POST with OAuth Bearer header when a bearer_token is configured."""
        headers = kwargs.pop("headers", {})
        if self._session.bearer_token:
            headers["Authorization"] = f"Bearer {self._session.bearer_token}"
        return self._http.post(url, headers=headers, **kwargs)

    @property
    def has_bearer(self) -> bool:
        return bool(self._session.bearer_token)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "AuraClient":
        return self

    def __exit__(self, *_) -> None:
        self.close()
