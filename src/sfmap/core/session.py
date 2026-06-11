# sfmap/core/session

# Built-in imports
import json
from dataclasses import dataclass


@dataclass
class Session:
    url: str  # Full Aura endpoint, e.g. https://host/s/sfsites/aura
    context: dict  # aura.context as a dict (will be JSON-serialised on send)
    token: str = "undefined"  # aura.token raw string; "undefined" = unauthenticated
    cookie: str | None = None  # Raw Cookie header value
    guest_mode: bool = False  # Explicit guest assessment mode flag
    bearer_token: str | None = None  # OAuth Bearer token for REST API access

    @property
    def is_guest(self) -> bool:
        # A session cookie is what authenticates a Salesforce session.
        # The aura.token is only a CSRF token — Salesforce issues one even to
        # unauthenticated visitors. Without a cookie (and without an OAuth
        # bearer token for REST-only flows), the session is effectively guest.
        return self.guest_mode or (not self.cookie and not self.bearer_token)

    @property
    def context_str(self) -> str:
        return json.dumps(self.context)

    @staticmethod
    def parse_cookies(raw: str) -> dict:
        """Parse a raw Cookie header string into a dict for requests."""
        cookies: dict = {}
        for part in raw.split(";"):
            part = part.strip()
            if "=" in part:
                k, v = part.split("=", 1)
                cookies[k.strip()] = v.strip()
        return cookies

    @property
    def cookies_dict(self) -> dict:
        if self.cookie:
            return self.parse_cookies(self.cookie)
        return {}
