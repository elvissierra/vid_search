"""Structured logging: one JSON object per line on stderr.

configure() is called once by each entry point (the API and the worker). Any
`extra={...}` fields passed to a logging call become keys in the line, so log
aggregators can filter on `job_id`, `status` and so on without parsing text.
Set LOG_LEVEL (default INFO) to change verbosity.
"""
import json
import logging
import os
import sys
from datetime import datetime, timezone

# Attributes every LogRecord has; anything else came from `extra=`.
_STANDARD = frozenset(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {
    "message", "asctime", "taskName",
}
_HANDLER_MARK = "_vid_search_json"


class JsonFormatter(logging.Formatter):
    def __init__(self, service):
        super().__init__()
        self.service = service

    def format(self, record):
        entry = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "service": self.service,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in vars(record).items():
            if key not in _STANDARD and not key.startswith("_"):
                entry[key] = value
        if record.exc_info:
            entry["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def configure(service):
    """Send all logging to stderr as JSON, tagged with `service`. Idempotent."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, _HANDLER_MARK, False):
            root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter(service))
    setattr(handler, _HANDLER_MARK, True)
    root.addHandler(handler)
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    root.setLevel(level if level in logging.getLevelNamesMapping() else "INFO")
