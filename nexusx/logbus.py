# -*- coding: utf-8 -*-
"""
Logging: file (rotating) + console + an in-memory queue that the GUI Log tab pumps.
Same idea as UCeX v6.7 (_QueueHandler), extended with rotation and a tag helper.
"""
from __future__ import annotations

import logging
import queue
import sys
from logging.handlers import RotatingFileHandler

from .paths import LOG_FILE, ensure_app_dir

log_queue: "queue.Queue[str]" = queue.Queue()
_FMT = "%(asctime)s [%(levelname)s] %(message)s"
_configured = False


class _QueueHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            log_queue.put_nowait(self.format(record))
        except Exception:
            pass


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    global _configured
    logger = logging.getLogger("NexusX")
    if _configured:
        return logger
    ensure_app_dir()
    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter(_FMT)
    try:
        fh = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
        fh.setFormatter(fmt)
        fh.setLevel(logging.DEBUG)
        logger.addHandler(fh)
    except Exception:
        pass
    if sys.stdout is not None:  # pythonw has no stdout
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        sh.setLevel(level)
        logger.addHandler(sh)
    qh = _QueueHandler()
    qh.setFormatter(fmt)
    qh.setLevel(logging.DEBUG)
    logger.addHandler(qh)
    logger.propagate = False
    _configured = True
    return logger


def get_logger() -> logging.Logger:
    return setup_logging()


def tag_for(message: str) -> str:
    """Map a formatted log line to a GUI colour tag."""
    if "[ERROR]" in message or "[CRITICAL]" in message:
        return "error"
    if "[WARNING]" in message:
        return "warn"
    if "[DEBUG]" in message:
        return "debug"
    if "✅" in message or "[OK]" in message:
        return "ok"
    return "info"
