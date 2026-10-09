"""Optional local startup trace for diagnosing packaged builds."""

from __future__ import annotations

import os
from datetime import datetime
from .paths import CACHE

def report_error(stage: str, error: object) -> None:
    """Bounded error log, available in the windowed executable."""
    import logging
    from logging.handlers import RotatingFileHandler
    from .paths import DATA
    logger = logging.getLogger('triloa.errors')
    try:
        if not logger.handlers:
            DATA.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(DATA / 'errors.log', maxBytes=512_000, backupCount=1, encoding='utf-8')
            handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
            logger.addHandler(handler)
            logger.propagate = False
        logger.error('%s: %s', stage, error)
    except OSError:
        pass


def trace(stage: str) -> None:
    if os.environ.get("TRILOA_STARTUP_TRACE") != "1":
        return
    CACHE.mkdir(parents=True, exist_ok=True)
    with (CACHE / "startup.log").open("a", encoding="utf-8") as stream:
        stream.write(f"{datetime.now().isoformat(timespec='seconds')} {stage}\n")
