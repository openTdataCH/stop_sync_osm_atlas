from datetime import datetime
from zoneinfo import ZoneInfo

def get_zurich_now() -> datetime:
    """Return current time in Europe/Zurich timezone."""
    return datetime.now(ZoneInfo("Europe/Zurich"))

def format_zurich_timestamp(dt: datetime) -> str:
    """Format a datetime object as an ISO string with timezone offset."""
    return dt.isoformat()


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
