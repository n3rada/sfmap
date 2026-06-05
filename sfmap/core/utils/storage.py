# Built-in imports
import json
from pathlib import Path
from urllib.parse import urlparse

# Local imports
from .common import resolve_url


def output_dir(url: str) -> str:
    """Derive a filesystem-safe output directory name from a URL.

    Always uses the ``aura_`` prefix regardless of scheme.
    """
    parsed = urlparse(resolve_url(url))
    safe_host = parsed.netloc.replace(":", "_")
    safe_path = parsed.path.strip("/").replace("/", "_") or "root"
    return f"aura_{safe_host}_{safe_path}"


def save_json(path: str | Path, data: dict | list) -> None:
    """Write *data* to *path* as pretty-printed JSON, creating parent dirs."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_json(path: str | Path) -> dict | list | None:
    """Load JSON from *path*. Returns None if the file does not exist or is malformed."""
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

def config_data_path(url: str) -> Path:
    """Return the Path where a target's getConfigData response is cached."""
    return Path(output_dir(url)) / "config_data.json"


def save_config_data(url: str, data: dict) -> None:
    """Persist the ``apiNamesToKeyPrefixes`` map returned by getConfigData."""
    save_json(config_data_path(url), data)


def load_config_data(url: str) -> dict | None:
    result = load_json(config_data_path(url))
    return result if isinstance(result, dict) else None
