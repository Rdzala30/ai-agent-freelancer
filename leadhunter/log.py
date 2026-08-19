"""Structured logging: console + rotating file, plus a tiny audit helper.

The audit trail of record is the `lead_events` table in SQLite (see db.py).
The log file is for operational debugging. Both are written from the same
call sites via the pipeline's event() helper.
"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

LOG_NAME = "leadhunter"


def setup_logging(level: str = "INFO", log_file: Path | None = None) -> None:
    root = logging.getLogger(LOG_NAME)
    if root.handlers:  # already configured (e.g. tests)
        return

    root.setLevel(level.upper())
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S"
    )

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    if log_file is not None:
        log_file = Path(log_file)
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)

    root.propagate = False


def get_logger(name: str = "leadhunter") -> logging.Logger:
    return logging.getLogger(f"{LOG_NAME}.{name}" if name != LOG_NAME else LOG_NAME)
