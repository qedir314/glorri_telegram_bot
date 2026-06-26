"""
Centralized configuration and logging setup for Glorri Jobs Bot.

This module:
  - Locates the project root and loads .env with an explicit path
  - Configures structured logging (console + rotating file)
  - Exports PROJECT_ROOT for path resolution elsewhere

Import this module first in any entry point (scheduler.py, main.py)
to ensure .env is loaded and logging is configured before other imports.
"""

import os
import logging
import logging.handlers
from pathlib import Path
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Project root detection
# ---------------------------------------------------------------------------
# __file__ lives at  src/config.py  →  parent is  src/  →  parent is project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Load .env  (explicit path – no more relying on CWD)
# ---------------------------------------------------------------------------
_env_path = PROJECT_ROOT / ".env"
if _env_path.exists():
    load_dotenv(_env_path)
else:
    # Fallback: try to load anyway (useful when env vars are set externally, e.g. Docker)
    load_dotenv()

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Ensure data directory exists for log files
_data_dir = PROJECT_ROOT / "data"
_data_dir.mkdir(parents=True, exist_ok=True)

_LOG_FILE = _data_dir / "bot.log"


def setup_logging(
    console_level: int = logging.INFO,
    file_level: int = logging.DEBUG,
    max_bytes: int = 5 * 1024 * 1024,  # 5 MB
    backup_count: int = 3,
) -> None:
    """
    Configure the root logger with console and rotating-file handlers.

    Args:
        console_level: Log level for stderr output.
        file_level:   Log level for the rotating log file.
        max_bytes:    Max size per log file before rotation.
        backup_count: Number of backup files to keep.
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)  # capture everything; handlers filter

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(console_level)
    console_handler.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT))
    root_logger.addHandler(console_handler)

    # Rotating file handler
    file_handler = logging.handlers.RotatingFileHandler(
        str(_LOG_FILE),
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(file_level)
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT))
    root_logger.addHandler(file_handler)

    # Quiet down noisy third-party loggers
    for noisy in ("selenium", "urllib3", "apscheduler", "telegram", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    logging.getLogger(__name__).info("Logging configured (console=%s, file=%s)",
                                     logging.getLevelName(console_level),
                                     logging.getLevelName(file_level))


# ---------------------------------------------------------------------------
# Auto-setup on first import (convenient for entry points)
# ---------------------------------------------------------------------------
setup_logging()
