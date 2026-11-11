from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from zoneinfo import ZoneInfo

def get_zurich_now() -> datetime:
    """Return current time in Europe/Zurich timezone."""
    return datetime.now(ZoneInfo("Europe/Zurich"))

def format_zurich_timestamp(dt: datetime) -> str:
    """Format a datetime object as an ISO string with timezone offset."""
    return dt.isoformat()


def parse_utc_timestamp(value: Any) -> datetime | None:
    """A stored timestamp as an aware UTC datetime, or None when it is missing or unreadable.

    Reads datetimes, ISO 8601 strings and RFC 2822 dates. A timestamp without a
    zone is taken as UTC.
    """
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            try:
                parsed = parsedate_to_datetime(value)
            except (TypeError, ValueError):
                return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def format_zurich_display_timestamp(value: datetime | str | None, include_seconds: bool = False) -> str | None:
    """Format a datetime or ISO timestamp for user-facing display in Zurich time."""
    if value in (None, ""):
        return value
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            return value
    else:
        return value

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("Europe/Zurich"))
    else:
        dt = dt.astimezone(ZoneInfo("Europe/Zurich"))
    
    format_str = '%Y-%m-%d %H:%M:%S' if include_seconds else '%Y-%m-%d %H:%M'
    return dt.strftime(format_str)
