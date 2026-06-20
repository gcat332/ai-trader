import json
from datetime import datetime, timezone


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def load_blackout(path: str) -> list[tuple[datetime, datetime]]:
    """Load UTC blackout windows from a JSON list of {start, end, label} rows."""
    try:
        with open(path, encoding="utf-8") as f:
            rows = json.load(f)
        windows = []
        for row in rows:
            windows.append((_parse_utc(row["start"]), _parse_utc(row["end"])))
        return windows
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return []


def in_blackout(windows: list[tuple[datetime, datetime]], now: datetime) -> bool:
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)
    return any(start <= now < end for start, end in windows)
