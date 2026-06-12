# sfmap/commands/report.py

# Built-in imports
import argparse
import os

# Third-party imports
from loguru import logger

# Local imports
from ..core.modules import reporter
from ..core.utils import storage


def cmd_report(args: argparse.Namespace) -> int:
    if args.output:
        output_dir = args.output
    elif getattr(args, "url", None):
        output_dir = storage.output_dir(args.url)
    else:
        logger.error("--output DIR is required when no URL is given")
        return 1
    if not os.path.isdir(output_dir):
        logger.error(f"Output directory not found: {output_dir}")
        return 1
    reporter.generate(output_dir)
    return 0
