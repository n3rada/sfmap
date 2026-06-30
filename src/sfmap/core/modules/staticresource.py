# Built-in imports
from importlib.resources import files as resource_files
from urllib.parse import urlparse

# Third-party imports
from loguru import logger

# Local imports
from ..client import AuraClient
from ..utils import storage
from . import dump


def _base_url(aura_url: str) -> str:
    parsed = urlparse(aura_url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _load_wordlist(custom_path: str | None) -> list[str]:
    if custom_path:
        with open(custom_path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    else:
        text = resource_files("sfmap.data").joinpath("static_resources.txt").read_text(encoding="utf-8")
        lines = text.splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]


def _enumerate_via_aura(client: AuraClient) -> list[str]:
    rv = dump.get_items(client, "StaticResource", page_size=500, page=1, silent=True)
    if rv is None:
        return []
    names: list[str] = []
    for item in rv.get("result", []):
        record = item.get("record", item)
        fields = record.get("fields", {})
        name_field = fields.get("Name", {})
        name = name_field.get("value") if isinstance(name_field, dict) else name_field
        if name:
            names.append(name)
    return names


def _fetch(client: AuraClient, base: str, name: str) -> tuple[int, bytes]:
    for url in (f"{base}/resource/{name}", f"{base}/s/resource/{name}"):
        try:
            resp = client.get(url)
            if resp.status_code == 200:
                return 200, resp.content
        except Exception:
            logger.exception(f"StaticResource fetch error {name}")
    return 404, b""


def fuzz(
    client: AuraClient,
    aura_url: str,
    out: storage.OutputWriter,
    wordlist_path: str | None = None,
) -> list[dict]:
    base = _base_url(aura_url)
    hits: list[dict] = []

    aura_names = _enumerate_via_aura(client)
    if aura_names:
        logger.info(f"StaticResource: {len(aura_names)} name(s) enumerated via Aura")
        names = aura_names
    else:
        logger.info("StaticResource: not accessible via Aura, using wordlist")
        names = _load_wordlist(wordlist_path)
        logger.info(f"StaticResource: {len(names)} name(s) to probe")

    for name in names:
        sc, data = _fetch(client, base, name)
        if sc != 200:
            logger.debug(f"StaticResource {name}: not accessible")
            continue

        safe = name.replace("/", "_").replace("\\", "_")
        bin_path = out.save_bytes(f"staticresource_{safe}.bin", data)
        logger.success(f"StaticResource accessible: /resource/{name} ({len(data):,} bytes) → {bin_path}")
        hits.append({"name": name, "url": f"{base}/resource/{name}", "size": len(data)})

    out.save("staticresource_summary.json", hits)

    if hits:
        logger.success(f"StaticResource: {len(hits)} resource(s) downloaded to {out}")
    else:
        logger.info("StaticResource: no accessible resources found")

    return hits
