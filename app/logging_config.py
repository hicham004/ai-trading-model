"""Structured (JSON) logging setup.

We emit one JSON object per log line. JSON logs are easy for both humans and
tools to read, and they keep a consistent shape across the whole project.

No secrets are ever logged: Phase 1 only handles public market data, and the
configuration layer never stores credentials.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

# Standard ``LogRecord`` attributes. Anything a caller adds via ``extra=...``
# that is NOT in this set gets included in the JSON output as a custom field.
_RESERVED_LOG_RECORD_KEYS = set(
    logging.makeLogRecord({}).__dict__.keys()
) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    """Format log records as single-line JSON objects with UTC timestamps."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Include any structured context passed via logger.info(..., extra={...}).
        for key, value in record.__dict__.items():
            if key not in _RESERVED_LOG_RECORD_KEYS and not key.startswith("_"):
                payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    """Configure root logging to emit structured JSON to stdout.

    Safe to call more than once; it replaces existing handlers so we do not
    accumulate duplicate log lines.
    """
    root = logging.getLogger()
    root.setLevel(level.upper())

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(JsonFormatter())

    root.handlers.clear()
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger. Use the module ``__name__`` as the name."""
    return logging.getLogger(name)
