# Built-in imports
from urllib.parse import urlparse

_AURA_PATH = "/s/sfsites/aura"


def resolve_url(raw: str) -> str:
    """
    Accept a domain, base URL, or full Aura endpoint and always return
    the full endpoint URL ending with /s/sfsites/aura.

    Examples
    --------
    site.my.site.com                → https://site.my.site.com/s/sfsites/aura
    https://site.my.site.com        → https://site.my.site.com/s/sfsites/aura
    https://…/custom/path           → https://…/custom/path/s/sfsites/aura
    https://…/s/sfsites/aura        → unchanged
    """
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    raw = raw.rstrip("/")
    if not raw.endswith("/aura"):
        raw = raw + _AURA_PATH
    return raw


def default_output_dir(url: str) -> str:
    """Derive a filesystem-safe output directory name from a URL.

    Delegates to :func:`sfmap.core.utils.storage.output_dir` so the naming
    convention (``salesforce_<host>_<path>``) is defined in one place.
    """
    # Import here to avoid a circular dependency (storage imports resolve_url from here).
    from .storage import output_dir  # noqa: PLC0415

    return output_dir(url)
