from sqlalchemy.exc import ProgrammingError


def is_missing_table_error(exc):
    """Return True when the database reports a missing table/relation."""
    if isinstance(exc, ProgrammingError):
        orig = getattr(exc, "orig", None)
        if getattr(orig, "sqlstate", None) == "42P01":
            return True

    message = str(exc).lower()
    if "does not exist" in message:
        return True
    if "no such table" in message:
        return True
    return False
