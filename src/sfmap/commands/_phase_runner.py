# sfmap/commands/_phase_runner

# Built-in imports
import argparse
import time
from pathlib import Path
from typing import Callable

# Third-party imports
from loguru import logger

type Phase = tuple[str, Callable[[argparse.Namespace], int]]


def run_phase_loop(
    phases: list[Phase],
    sentinels: dict[str, str],
    defaults: list[tuple[str, object]],
    out_dir: str,
    args: argparse.Namespace,
) -> int:
    """Execute a list of assessment phases with sentinel-based skip and result tracking.

    Each phase receives a cloned namespace with `output` set to `out_dir` and any
    missing attributes from `defaults` filled in. A phase is skipped when its sentinel
    file already exists under `out_dir`. The return value is 1 if any phase errored, 0
    otherwise (skips and findings do not count as errors).
    """
    out_path = Path(out_dir)
    results: list[tuple[str, str, float]] = []

    for name, fn in phases:
        sentinel = sentinels.get(name)
        if sentinel and (out_path / sentinel).exists():
            logger.info(f"assess: {name} already done, skipping")
            results.append((name, "skip", 0.0))
            continue

        phase_args = argparse.Namespace(**vars(args))
        phase_args.output = out_dir
        for attr, val in defaults:
            if not hasattr(phase_args, attr):
                setattr(phase_args, attr, val)

        t0 = time.monotonic()
        try:
            fn(phase_args)
            elapsed = time.monotonic() - t0
            results.append((name, "ok", elapsed))
        except SystemExit:
            elapsed = time.monotonic() - t0
            results.append((name, "fatal", elapsed))
            logger.error(f"assess: {name} aborted session, stopping")
            break
        except Exception:
            elapsed = time.monotonic() - t0
            results.append((name, "error", elapsed))
            logger.exception(f"assess: {name} failed, continuing")

    logger.info("─" * 55)
    for name, status, elapsed in results:
        if status == "ok":
            logger.success(f"  {name:<32} {elapsed:>6.1f}s")
        elif status == "skip":
            logger.info(f"  {name:<32}  skipped")
        else:
            logger.error(f"  {name:<32} {elapsed:>6.1f}s")
    logger.info("─" * 55)

    return 1 if any(s == "error" for _, s, _ in results) else 0
