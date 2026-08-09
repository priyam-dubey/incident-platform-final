"""
Structured (JSON) logging. Plain-text logs are unqueryable at production log
volume - every log line here is a JSON object so it can be shipped straight
to ClickHouse/ELK/Datadog without a fragile regex parser in front of it.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from typing import Any


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Extra structured fields attached via logger.info(..., extra={"foo": "bar"})
        reserved = set(vars(logging.LogRecord("", 0, "", 0, "", (), None)).keys()) | {
            "message",
            "asctime",
        }
        for key, value in vars(record).items():
            if key not in reserved:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "info") -> None:
    root = logging.getLogger()
    root.setLevel(level.upper())
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)

    # Quiet down noisy third-party loggers at info level; we care about our own.
    logging.getLogger("aiokafka").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
