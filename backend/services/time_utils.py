from datetime import datetime
from zoneinfo import ZoneInfo

def get_zurich_now() -> datetime:
    """Return current time in Europe/Zurich timezone."""
    return datetime.now(ZoneInfo("Europe/Zurich"))

def format_zurich_timestamp(dt: datetime) -> str:
    """Format a datetime object as an ISO string with timezone offset."""
    return dt.isoformat()
