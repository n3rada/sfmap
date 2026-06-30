# Built-in imports
from urllib.parse import urlparse

_AURA_PATH = "/s/sfsites/aura"
_LIGHTNING_AURA_PATH = "/aura"


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


def resolve_lightning_url(raw: str) -> str:
    """
    Accept a domain or URL and return the Lightning Aura endpoint (always /aura).

    Works for both Lightning Experience (my.salesforce.com) and
    Setup Lightning (my.salesforce-setup.com).
    """
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    parsed = urlparse(raw)
    return f"{parsed.scheme}://{parsed.netloc}{_LIGHTNING_AURA_PATH}"


def resolve_rest_base_url(aura_url: str) -> str:
    """Return the REST API base URL for any Salesforce Aura endpoint URL.

    lightning.force.com and my.salesforce.com both serve /services/data/ natively.
    Only my.salesforce-setup.com is a UI-only domain that needs to be mapped to
    the org's my.salesforce.com for REST API access.
    """
    parsed = urlparse(aura_url)
    host = parsed.netloc
    if host.endswith(".my.salesforce-setup.com"):
        prefix = host[: -len(".my.salesforce-setup.com")]
        host = f"{prefix}.my.salesforce.com"
    return f"{parsed.scheme}://{host}"


def default_output_dir(url: str) -> str:
    """Derive a filesystem-safe output directory name from a URL.

    Delegates to :func:`sfmap.core.utils.storage.output_dir` so the naming
    convention (``salesforce_<host>_<path>``) is defined in one place.
    """
    # Import here to avoid a circular dependency (storage imports resolve_url from here).
    from .storage import output_dir  # noqa: PLC0415

    return output_dir(url)
