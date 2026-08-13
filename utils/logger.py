import sys
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from config.settings import LOG_DIR

try:
    from loguru import logger as _loguru_logger
    _loguru_logger.remove()
    _loguru_logger.add(
        sys.stdout,
        format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level="INFO",
        colorize=True,
    )
    _loguru_logger.add(
        LOG_DIR / "hubt_framework.json.log",
        rotation="10 MB",
        retention="7 days",
        serialize=True,
        level="DEBUG",
    )
    logger = _loguru_logger
except ImportError:
    # Standard Logging Fallback if loguru is not yet installed in local python env
    logger = logging.getLogger("HUBT_Framework")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s - %(name)s: %(message)s"))
        logger.addHandler(ch)
        fh = RotatingFileHandler(LOG_DIR / "hubt_framework.log", maxBytes=5*1024*1024, backupCount=3, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"))
        logger.addHandler(fh)

__all__ = ["logger"]
