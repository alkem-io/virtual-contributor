from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone


class JSONFormatter(logging.Formatter):
    """JSON log formatter with structured fields."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, object] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }
        # Add extra fields if present
        for key in ("plugin_type", "correlation_id"):
            value = getattr(record, key, None)
            if value is not None:
                log_entry[key] = value
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry)


def setup_logging(level: str = "INFO", plugin_type: str = "") -> None:
    """Configure JSON structured logging for the process.

    All existing handlers on the root logger are removed and replaced with a
    single ``StreamHandler`` writing JSON lines to *stdout*.  When
    *plugin_type* is provided it is automatically injected into every log
    record via a filter.
    """
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove existing handlers
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    root.addHandler(handler)

    if plugin_type:

        class PluginTypeFilter(logging.Filter):
            def filter(self, record: logging.LogRecord) -> bool:
                record.plugin_type = plugin_type  # type: ignore[attr-defined]
                return True

        root.addFilter(PluginTypeFilter())
