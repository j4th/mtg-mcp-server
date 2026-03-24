"""Structured logging configuration for MTG MCP server.

All logging goes to stderr — stdout is reserved for MCP transport in stdio mode.
Call configure_logging() once at startup from server.py:main().
"""

from __future__ import annotations

import logging
import sys

import structlog

_VALID_LEVELS = frozenset(logging.getLevelNamesMapping())


def configure_logging(level: str = "INFO") -> None:
    """Configure structlog with JSON output to stderr.

    Args:
        level: Log level name (DEBUG, INFO, WARNING, ERROR, CRITICAL).

    Raises:
        ValueError: If level is not a recognized log level name.
    """
    level_upper = level.upper()
    if level_upper not in _VALID_LEVELS:
        raise ValueError(
            f"Invalid log level '{level}'. Must be one of: {', '.join(sorted(_VALID_LEVELS))}"
        )
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(level_upper),
        ),
    )


def get_logger(service: str) -> structlog.stdlib.BoundLogger:
    """Return a structlog logger bound with the given service name."""
    return structlog.get_logger(service=service)
