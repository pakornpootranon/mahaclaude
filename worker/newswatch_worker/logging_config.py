"""Structured logging (docs/02-architecture.md §8: 'Worker logs: structured
JSON lines to stdout; errors also land in cycles.error').
One JSON object per line, easy to grep/parse or pipe through `tail -f
| jq`. Any `extra={...}` fields a log call passes through are included
verbatim alongside the standard timestamp/level/logger/message fields.
"""

from __future__ import annotations

import json
import logging
import sys

_STANDARD_RECORD_FIELDS = set(
    logging.LogRecord(name="", level=0, pathname="", lineno=0, msg="", args=(), exc_info=None).__dict__.keys()
) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_RECORD_FIELDS:
                payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
