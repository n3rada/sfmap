# Built-in imports
import os
import sys
from pathlib import Path

# Third-party imports
from loguru import logger


def _format_message(record):
    level_name = record["level"].name

    trace_brown = "#8b7355"
    debug_blue = "#6c9bd1"
    info_white = "#ecf0f1"
    success_green = "#52c88a"
    warning_orange = "#f39c12"
    error_red = "#e74c3c"
    critical_mag = "#c71585"
    time_gray = "#a5a5a5"

    symbols = {
        "TRACE": (f"<fg {trace_brown}>[*]</fg {trace_brown}>", trace_brown),
        "DEBUG": (f"<fg {debug_blue}>[•]</fg {debug_blue}>", debug_blue),
        "INFO": (f"<fg {info_white}>[i]</fg {info_white}>", info_white),
        "SUCCESS": (f"<fg {success_green}>[✓]</fg {success_green}>", success_green),
        "WARNING": (f"<fg {warning_orange}>[!]</fg {warning_orange}>", warning_orange),
        "ERROR": (f"<fg {error_red}>[✗]</fg {error_red}>", error_red),
        "CRITICAL": (
            f"<fg {critical_mag}><bold>[⚠]</bold></fg {critical_mag}>",
            critical_mag,
        ),
    }

    symbol, color = symbols.get(level_name, ("[?]", "white"))

    return (
        f"<fg {time_gray}>{{time:YYYY-MM-DD HH:mm:ss.SSS!UTC}} (UTC)</fg {time_gray}> "
        f"{symbol} "
        f"<fg {color}>{{message}}</fg {color}>"
        "\n{exception}"
    )


def _log_dir() -> Path:
    override = os.getenv("sfmap_LOG_DIR")
    if override:
        return Path(override).expanduser().resolve()

    if os.name == "nt":
        base = Path(os.getenv("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
        return (base / "sfmap" / "logs").resolve()

    base = os.getenv("XDG_STATE_HOME")
    if base:
        return Path(base).expanduser().resolve() / "sfmap" / "logs"

    return Path.home() / ".local" / "state" / "sfmap" / "logs"


def setup_logging(level: str = "INFO") -> None:
    level = level.upper()
    valid = {"TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"}
    if level not in valid:
        level = "INFO"

    logger.remove()

    logger.add(
        sys.stderr,
        enqueue=False,
        backtrace=True,
        diagnose=True,
        level=level,
        format=_format_message,
        colorize=True,
    )

    log_dir = _log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)

    logger.add(
        log_dir / "sfmap.log",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS!UTC} (UTC) [{level:7}] {message}\n{exception}",
        level=level,
        rotation=os.getenv("sfmap_LOG_MAX_BYTES", "10 MB"),
        retention=f"{int(os.getenv('sfmap_LOG_RETENTION_DAYS', '14'))} days",
        compression="zip",
        encoding="utf-8",
        enqueue=True,
    )

    logger.trace(f"Logger initialised at level {level}")
