"""Minimal logging helpers for World-Sim."""

from __future__ import annotations

import logging
import sys

_LOGGER_NAME = "world_sim"
_CONFIGURED = False


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a logger under the world_sim namespace."""
    if name is None or name == _LOGGER_NAME:
        return logging.getLogger(_LOGGER_NAME)
    if name.startswith(f"{_LOGGER_NAME}."):
        return logging.getLogger(name)
    return logging.getLogger(f"{_LOGGER_NAME}.{name}")


def setup_logging(level: str = "INFO") -> logging.Logger:
    """Configure root world_sim logging once and return the package logger."""
    global _CONFIGURED

    logger = get_logger()
    resolved_level = getattr(logging, level.upper(), logging.INFO)

    if not _CONFIGURED:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        logger.addHandler(handler)
        logger.propagate = False
        _CONFIGURED = True

    logger.setLevel(resolved_level)
    for handler in logger.handlers:
        handler.setLevel(resolved_level)
    return logger


def reset_logging_for_tests() -> None:
    """Clear logging configuration. Intended for tests only."""
    global _CONFIGURED

    logger = get_logger()
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    _CONFIGURED = False
