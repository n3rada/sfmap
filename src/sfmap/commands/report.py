# sfmap/commands/report.py

# Built-in imports
import argparse
import os

# Third-party imports
from loguru import logger

# Local imports
from ..core.modules import reporter


def cmd_report(args: argparse.Namespace) -> int:
    if not args.output:
        logger.error("--output DIR is required")
        return 1
    output_dir = args.output
    if not os.path.isdir(output_dir):
        logger.error(f"Output directory not found: {output_dir}")
        return 1
    reporter.generate(output_dir)
    return 0
