from importlib.metadata import version, PackageNotFoundError
from pathlib import Path
import tomllib

try:
    __version__ = version("sfmap")
except PackageNotFoundError:
    try:
        pyproject_path = Path(__file__).parent.parent.parent / "pyproject.toml"
        with open(pyproject_path, "rb") as f:
            __version__ = tomllib.load(f)["project"]["version"] + "-dev"
    except (FileNotFoundError, KeyError):
        __version__ = "unknown"

__all__ = ["__version__"]
