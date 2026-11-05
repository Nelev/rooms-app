"""Structured JSON logs, each line with the ID of the request it was logged in."""

import json
import logging
from contextvars import ContextVar
from datetime import UTC, datetime

request_id: ContextVar[str | None] = ContextVar("request_id", default=None)

_RECORD_KEYS = set(vars(logging.makeLogRecord({}))) | {"message", "asctime", "color_message"}  # color_message: uvicorn's console copy


class JsonFormatter(logging.Formatter):
    """One JSON object per line: time, level, logger, message, request_id, the record's `extra` fields and any exception."""

    def format(self, record: logging.LogRecord) -> str:
        line = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id.get(),
            **{k: v for k, v in vars(record).items() if k not in _RECORD_KEYS},
        }
        if record.exc_info:
            line["exception"] = self.formatException(record.exc_info)
        return json.dumps(line, default=str)


def configure_logging(level: str = "INFO") -> None:
    """Log JSON to stderr from the root logger; uvicorn's loggers propagate to it, and its access log gives way to RequestId's."""
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=level, handlers=[handler], force=True)
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers.clear()
        logging.getLogger(name).propagate = True
    logging.getLogger("uvicorn.access").disabled = True
