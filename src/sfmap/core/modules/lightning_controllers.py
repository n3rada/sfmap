# sfmap/core/modules/lightning_controllers

# Built-in imports
from importlib import resources
from pathlib import Path

# Third-party imports
from loguru import logger

# Local imports
from ..client import AuraClient
from . import apex


def _load_descriptors(wordlist_path: str | Path | None) -> list[str]:
    if wordlist_path is not None:
        p = Path(wordlist_path)
        if not p.exists():
            raise FileNotFoundError(f"Wordlist not found: {p}")
        content = p.read_text(encoding="utf-8")
    else:
        resource = resources.files("sfmap").joinpath("data/lightning_controllers.txt")
        content = resource.read_text(encoding="utf-8")
    return [
        line.strip()
        for line in content.splitlines()
        if line.strip() and not line.startswith("#")
    ]


def fuzz(client: AuraClient, wordlist_path: str | Path | None = None) -> dict[str, str]:
    """Probe Lightning Aura framework controller descriptors.

    Returns a dict mapping each descriptor to its probe result category:
    callable | exists_denied | not_found | error
    """
    descriptors = _load_descriptors(wordlist_path)
    logger.info(f"Probing {len(descriptors)} Lightning controller descriptor(s)")
    return apex.probe(client, descriptors)
