# sfmap/commands/_context.py

# Built-in imports
import argparse
import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse

# Third-party imports
import httpx
from loguru import logger

# Local imports
from ..core.client import AuraClient, AuraSessionExpired, USER_AGENT
from ..core.session import Session
from ..core.utils import autocontext, detect as detect_mod, identity as identity_mod
from ..core.utils import burp as burp_mod, common, storage
from ..core.utils.common import resolve_lightning_url


def _sid_from_cookie(cookie: str) -> str | None:
    for part in cookie.split(";"):
        k, _, v = part.strip().partition("=")
        if k.strip().lower() == "sid":
            return v.strip() or None
    return None


def _resolve_file_arg(value: str | None, default_file: str, label: str = "") -> str | None:
    raw = value or f"@{default_file}"
    if raw.startswith("@"):
        path = Path(raw[1:])
        if not path.exists():
            if value:
                logger.error(f"{label}: file not found: {path}")
                raise SystemExit(1)
            logger.debug(f"{label}: {path} not found, skipping")
            return None
        try:
            content = path.read_text(encoding="utf-8-sig").strip() or None
        except OSError as exc:
            logger.error(f"{label}: cannot read {path}: {exc}")
            raise SystemExit(1) from exc
        if content:
            logger.info(f"{label}: loaded from {path} ({len(content)} chars)")
        else:
            logger.warning(f"{label}: {path} exists but is empty")
        return content
    logger.info(f"{label}: loaded from command-line argument")
    return raw or None


def _resolve_output_dir(
    args: argparse.Namespace,
    session: Session | None = None,
    surface: str = "experience_cloud",
) -> str:
    if args.output:
        return args.output
    if not args.url:
        logger.error("URL is required when --output is not specified")
        raise SystemExit(1)
    target_root = str(storage.init_target_dirs(args.url, surface=surface))
    label = getattr(args, "identity", None)
    display: str | None = None
    is_guest = session is None or session.is_guest
    if not label:
        if is_guest:
            label = "guest"
        else:
            with AuraClient(session) as tmp:
                label, display = identity_mod.resolve_with_display(tmp)
            if re.search(r"guest", label, re.IGNORECASE):
                label = "guest"
                display = None
                is_guest = True
    if is_guest or label == "guest":
        output_dir = os.path.join(target_root, "guest")
    else:
        output_dir = os.path.join(target_root, "users", label)
    identity_mod.save_identity_json(output_dir, label, display, session)
    return output_dir


def _build_session(args: argparse.Namespace) -> Session:
    from .detect import ensure_surface_profile
    url = common.resolve_url(args.url)
    logger.info(f"Surface: Experience Cloud Aura: {url}")
    ensure_surface_profile(args.url, "experience_cloud")

    raw_context = args.context or "@ctx.json"
    extracted_token: str | None = None
    burp_context_str: str | None = None

    burp_path_early = Path("burp.txt")
    if burp_path_early.exists() and not args.context:
        _, _, burp_context_str = burp_mod.parse_burp_request(burp_path_early)
        if burp_context_str:
            try:
                context = json.loads(burp_context_str)
                ctx_path = Path("ctx.json")
                ctx_path.write_text(json.dumps(context, indent=2), encoding="utf-8")
                logger.info(f"burp: aura.context updated ctx.json (fwuid={context.get('fwuid', '?')!r})")
            except (json.JSONDecodeError, OSError):
                burp_context_str = None

    if not burp_context_str:
        if raw_context.startswith("@"):
            path = Path(raw_context[1:])
            if not path.exists():
                logger.info(f"No context file found at '{path}', auto-extracting from target")
                try:
                    context, extracted_token = autocontext.extract(url)
                except ValueError as exc:
                    logger.error(str(exc))
                    raise SystemExit(1) from exc
                try:
                    path.write_text(json.dumps(context, indent=2), encoding="utf-8")
                    logger.info(f"Context saved to {path} for future runs")
                except OSError:
                    pass
            else:
                try:
                    raw = path.read_text(encoding="utf-8-sig").strip()
                    context = json.loads(raw)
                    logger.info(f"context: loaded from {path}")
                except OSError as exc:
                    logger.error(f"context: cannot read {path}: {exc}")
                    raise SystemExit(1) from exc
                except json.JSONDecodeError as exc:
                    logger.error(f"context: {path} is not valid JSON: {exc}")
                    raise SystemExit(1) from exc
        else:
            try:
                context = json.loads(raw_context)
                logger.info("context: loaded from command-line argument")
            except json.JSONDecodeError as exc:
                logger.error(f"context: not valid JSON: {exc}")
                raise SystemExit(1) from exc

    burp_cookie: str | None = None
    burp_token: str | None = None
    burp_path = Path("burp.txt")
    if burp_path.exists():
        burp_cookie, burp_token, burp_context_str = burp_mod.parse_burp_request(burp_path)
        if burp_cookie:
            logger.info(f"burp: loaded cookie from {burp_path} ({len(burp_cookie)} chars)")
        if burp_token:
            logger.info(f"burp: loaded aura.token from {burp_path} ({len(burp_token)} chars)")
        if burp_context_str:
            logger.info(f"burp: loaded aura.context from {burp_path}")
        for stale in ("cookies.txt", "token.txt"):
            p = Path(stale)
            if p.exists():
                p.unlink()
                logger.info(f"burp: removed stale {stale}")

    cookie_cli = getattr(args, "cookie", None)
    if cookie_cli:
        cookie = _resolve_file_arg(cookie_cli, "cookies.txt", "cookie")
    elif burp_cookie:
        cookie = burp_cookie
    else:
        cookie = _resolve_file_arg(None, "cookies.txt", "cookie")

    bearer = _resolve_file_arg(getattr(args, "bearer", None), "bearer.txt", "bearer")

    token_cli = getattr(args, "token", None)
    if token_cli:
        token_raw = _resolve_file_arg(token_cli, "token.txt", "token")
    elif burp_token:
        token_raw = burp_token
    else:
        token_raw = _resolve_file_arg(None, "token.txt", "token")

    if token_raw is None and extracted_token and cookie:
        token = extracted_token
        logger.info("token: using auto-extracted value from page HTML")
    elif token_raw is None:
        token = "undefined"
        logger.info("token: none found, using 'undefined' (guest mode)")
    else:
        token = token_raw

    session = Session(
        url=url,
        context=context,
        token=token,
        cookie=cookie,
        bearer_token=bearer,
    )

    if not session.is_guest:
        try:
            with AuraClient(session) as client:
                identity_mod.verify(client)
            logger.info("Auth: session credentials accepted")
        except AuraSessionExpired as exc:
            logger.error(f"Auth: {exc}")
            raise SystemExit(1) from exc

    return session


def _build_lightning_session(args: argparse.Namespace) -> Session:
    """Build a Session for the Lightning Aura surface (one:one app, always authenticated).

    Lightning has no guest mode: cookie and token are both required. Context defaults
    to lightning_ctx.json and is never auto-extracted (requires a live sid session).
    Burp export (burp.txt) is supported as a primary credential source.
    """
    from .detect import ensure_surface_profile

    url = resolve_lightning_url(args.url)
    logger.info(f"Surface: Lightning Aura: {url}")

    storage.init_target_dirs(args.url, surface="lightning")
    profile_path = Path(storage.output_dir(args.url)) / "surface_profile.json"
    if not profile_path.exists():
        http = httpx.Client(verify=False, timeout=10.0, follow_redirects=True, headers={"User-Agent": USER_AGENT})
        try:
            result = detect_mod.probe_lightning(args.url, http)
        finally:
            http.close()
        if not result["found"]:
            logger.error(f"Lightning Aura endpoint not found at {url}, is this the right surface?")
            raise SystemExit(1)
        ensure_surface_profile(args.url, "lightning")

    # Burp: validate domain before loading, then parse
    burp_cookie: str | None = None
    burp_token: str | None = None
    burp_context_str: str | None = None
    burp_path = Path("burp.txt")
    if burp_path.exists():
        burp_host = burp_mod.parse_burp_host(burp_path)
        target_host = urlparse(url).netloc
        if burp_host and burp_host != target_host:
            logger.error(
                f"burp.txt was captured from {burp_host!r} but target is {target_host!r}. "
                "Capture a fresh request from the correct domain and save it as burp.txt."
            )
            raise SystemExit(1)
        burp_cookie, burp_token, burp_context_str = burp_mod.parse_burp_request(burp_path)
        if burp_cookie:
            logger.info(f"burp: loaded cookie ({len(burp_cookie)} chars)")
        if burp_token:
            logger.info("burp: loaded aura.token")
        if burp_context_str:
            logger.info("burp: loaded aura.context")

    # Context: defaults to lightning_ctx.json, never auto-extracted
    # Auto-persist from burp.txt so future runs don't need burp.txt
    raw_context = args.context or "@lightning_ctx.json"
    if burp_context_str and not args.context:
        try:
            context = json.loads(burp_context_str)
            logger.info("context: loaded from burp.txt")
            ctx_path = Path("lightning_ctx.json")
            if not ctx_path.exists():
                ctx_path.write_text(json.dumps(context, indent=2), encoding="utf-8")
                logger.info("burp: context persisted to lightning_ctx.json")
        except json.JSONDecodeError:
            burp_context_str = None

    if burp_token and not Path("token.txt").exists():
        Path("token.txt").write_text(burp_token, encoding="utf-8")
        logger.info("burp: token persisted to token.txt")

    if not burp_context_str or args.context:
        if raw_context.startswith("@"):
            path = Path(raw_context[1:])
            if not path.exists():
                logger.error(
                    f"Lightning context not found at '{path}'. "
                    "Capture aura.context from a POST to /aura in DevTools "
                    "and save it as lightning_ctx.json (or pass it with -C)."
                )
                raise SystemExit(1)
            try:
                context = json.loads(path.read_text(encoding="utf-8-sig").strip())
                logger.info(f"context: loaded from {path}")
            except json.JSONDecodeError as exc:
                logger.error(f"context: {path} is not valid JSON: {exc}")
                raise SystemExit(1) from exc
            except OSError as exc:
                logger.error(f"context: cannot read {path}: {exc}")
                raise SystemExit(1) from exc
        else:
            try:
                context = json.loads(raw_context)
                logger.info("context: loaded from command-line argument")
            except json.JSONDecodeError as exc:
                logger.error(f"context: not valid JSON: {exc}")
                raise SystemExit(1) from exc

    # Cookie: required, Lightning has no guest surface
    cookie_cli = getattr(args, "cookie", None)
    if cookie_cli:
        cookie = _resolve_file_arg(cookie_cli, "cookies.txt", "cookie")
    elif burp_cookie:
        cookie = burp_cookie
    else:
        cookie = _resolve_file_arg(None, "cookies.txt", "cookie")

    if not cookie:
        logger.error(
            "Cookie is required for the lightning surface. Lightning has no guest access. "
            "Capture the Cookie header from a Lightning session and save to cookies.txt, "
            "or drop a Burp capture as burp.txt."
        )
        raise SystemExit(1)

    # Token: required, Lightning never sends 'undefined'
    token_cli = getattr(args, "token", None)
    if token_cli:
        token_raw = _resolve_file_arg(token_cli, "token.txt", "token")
    elif burp_token:
        token_raw = burp_token
    else:
        token_raw = _resolve_file_arg(None, "token.txt", "token")

    if not token_raw:
        logger.error(
            "aura.token is required for the lightning surface. "
            "Capture the aura.token field from a POST to /aura and save to token.txt, "
            "or drop a Burp capture as burp.txt."
        )
        raise SystemExit(1)

    bearer = _resolve_file_arg(getattr(args, "bearer", None), "bearer.txt", "bearer")
    if not bearer and cookie:
        sid = _sid_from_cookie(cookie)
        if sid:
            bearer = sid
            logger.info("bearer: derived from sid cookie (Salesforce session ID is the OAuth access token)")

    return Session(
        url=url,
        context=context,
        token=token_raw,
        cookie=cookie,
        bearer_token=bearer,
    )


def _build_rest_only_lightning_session(args: argparse.Namespace) -> Session:
    """Build a minimal Session for REST-only Lightning operations (no Aura calls).

    Requires only a cookie with a sid value; Aura context and token are not needed.
    The sid is used directly as the OAuth Bearer token for REST API access.
    """
    url = resolve_lightning_url(args.url)
    logger.info(f"Surface: Lightning REST (no Aura): {url}")

    storage.init_target_dirs(args.url, surface="lightning")

    burp_cookie: str | None = None
    burp_path = Path("burp.txt")
    if burp_path.exists():
        burp_host = burp_mod.parse_burp_host(burp_path)
        target_host = urlparse(url).netloc
        if burp_host and burp_host != target_host:
            logger.error(
                f"burp.txt was captured from {burp_host!r} but target is {target_host!r}. "
                "Capture a fresh request from the correct domain."
            )
            raise SystemExit(1)
        burp_cookie, _, _ = burp_mod.parse_burp_request(burp_path)
        if burp_cookie:
            logger.info(f"burp: loaded cookie ({len(burp_cookie)} chars)")

    cookie_cli = getattr(args, "cookie", None)
    if cookie_cli:
        cookie = _resolve_file_arg(cookie_cli, "cookies.txt", "cookie")
    elif burp_cookie:
        cookie = burp_cookie
    else:
        cookie = _resolve_file_arg(None, "cookies.txt", "cookie")

    if not cookie:
        logger.error(
            "Cookie required. Pass --cookie 'sid=VALUE' or save to cookies.txt."
        )
        raise SystemExit(1)

    bearer = _resolve_file_arg(getattr(args, "bearer", None), "bearer.txt", "bearer")
    if not bearer:
        sid = _sid_from_cookie(cookie)
        if sid:
            bearer = sid
            logger.info("bearer: derived from sid cookie")
        else:
            logger.error("No 'sid' key found in cookie; cannot derive Bearer token.")
            raise SystemExit(1)

    dummy_context: dict = {
        "mode": "PROD",
        "fwuid": "0",
        "app": "one:one",
        "loaded": {},
        "dn": [],
        "globals": {},
        "uad": True,
    }

    return Session(
        url=url,
        context=dummy_context,
        token="rest-only",
        cookie=cookie,
        bearer_token=bearer,
    )
