# Built-in imports
import json
from pathlib import Path
from urllib.parse import urlparse

# Local imports
from .common import resolve_url


class OutputWriter:
    """Owns a directory and provides typed methods for writing assessment output."""

    def __init__(self, path: str | Path):
        self._path = Path(path)
        self._path.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self._path

    def __str__(self) -> str:
        return str(self._path)

    def __truediv__(self, name: str) -> Path:
        return self._path / name

    def save(self, filename: str, data: dict | list) -> Path:
        p = self._path / filename
        save_json(p, data)
        return p

    def save_bytes(self, filename: str, data: bytes) -> Path:
        p = self._path / filename
        p.write_bytes(data)
        return p

    def append_text(self, filename: str, text: str) -> None:
        with (self._path / filename).open("a", encoding="utf-8") as fh:
            fh.write(text)

    def subdir(self, name: str) -> "OutputWriter":
        return OutputWriter(self._path / name)


def output_dir(url: str) -> str:
    """Derive a filesystem-safe target root directory name from a URL."""
    parsed = urlparse(resolve_url(url))
    safe_host = parsed.netloc.replace(":", "_")
    return f"salesforce_{safe_host}"


def init_target_dirs(url: str) -> Path:
    """Create the target root and its guest/ and users/ subdirectories. Returns the root path."""
    root = Path(output_dir(url))
    (root / "guest").mkdir(parents=True, exist_ok=True)
    (root / "users").mkdir(parents=True, exist_ok=True)
    return root


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
