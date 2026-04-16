import logging
import os
from pathlib import Path
from logging.handlers import RotatingFileHandler

LOG_FILE = os.environ.get("MITOCLIPPER_LOG_FILE", "data/logs/mitoclipper.log")
LOG_LEVEL = os.environ.get("MITOCLIPPER_LOG_LEVEL", "INFO").upper()


def setup_logging():
    log_path = Path(LOG_FILE)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("mitoclipper")
    if logger.handlers:
        return logger

    logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    logger.addHandler(console)

    # Use RotatingFileHandler: 10MB max per file, keep 5 backups
    file_handler = RotatingFileHandler(
        log_path, maxBytes=10*1024*1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    logger.propagate = False
    logger.debug("Logger initialized at %s with rotation", log_path)

    return logger


logger = setup_logging()
