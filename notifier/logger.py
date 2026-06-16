# notifier/logger.py
import json
import logging
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "module": record.name,
            "message": record.getMessage(),
        }
        # Attach any extra fields passed via `extra={}`
        for key, val in record.__dict__.items():
            if key not in logging.LogRecord.__dict__ and not key.startswith("_"):
                payload[key] = val
        return json.dumps(payload)


def get_logger(name: str, log_file: str, max_bytes: int = 10_485_760, backup_count: int = 7) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # already configured

    logger.setLevel(logging.DEBUG)
    handler = RotatingFileHandler(log_file, maxBytes=max_bytes, backupCount=backup_count)
    handler.setFormatter(_JsonFormatter())
    logger.addHandler(handler)

    # Also emit to stdout so container platforms (Fly `fly logs`, Docker) capture
    # logs without shelling in. ponytail: stdout JSON mirrors the file; drop this
    # handler if you ever want file-only logging.
    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(_JsonFormatter())
    logger.addHandler(stream)
    return logger
