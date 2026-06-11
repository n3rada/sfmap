# sfmap/commands/files.py

# Built-in imports
import argparse

# Local imports
from ..core.client import AuraClient
from ..core.modules import dump
from ..core.utils.storage import OutputWriter
from ._context import _build_session, _resolve_output_dir


def cmd_download(args: argparse.Namespace) -> int:
    session = _build_session(args)
    out = OutputWriter(_resolve_output_dir(args, session))
    path = dump.download_file(AuraClient(session), args.sf_id, session.url, out.subdir("downloads"))
    return 0 if path else 1
