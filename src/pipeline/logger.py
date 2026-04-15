"""
Centralized logging for the pipeline.
Writes to both console (tqdm-compatible) and logs/pipeline.log.
"""
import logging
import sys
from pathlib import Path
from datetime import datetime

from .config import LOGS_DIR

LOG_FILE = LOGS_DIR / "pipeline.log"
FAILURE_LOG = LOGS_DIR / "failures.log"


def get_logger(name: str = "pipeline") -> logging.Logger:
    """Return a configured logger that writes to file and stderr."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%H:%M:%S"
    )

    # File handler — full debug log
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    # Console handler — INFO+ only, tqdm-compatible
    ch = logging.StreamHandler(sys.stderr)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)

    logger.addHandler(fh)
    logger.addHandler(ch)

    return logger


def log_failure(company: str, stage: str, error: str) -> None:
    """Append a failure record to the failures log."""
    with open(FAILURE_LOG, "a", encoding="utf-8") as f:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        f.write(f"{ts} | {company} | {stage} | {error}\n")
