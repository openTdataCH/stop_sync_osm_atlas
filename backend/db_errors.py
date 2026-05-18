from sqlalchemy.exc import ProgrammingError


def is_missing_table_error(exc):
    """Return True when the database reports a missing table/relation."""
    if isinstance(exc, ProgrammingError):
        orig = getattr(exc, "orig", None)
        if getattr(orig, "sqlstate", None) == "42P01":
            return True
        if getattr(orig, "sqlstate", None) == "42703":
            return False

    message = str(exc).lower()
    if "no such table" in message:
        return True
    if "does not exist" in message and (" relation " in message or " table " in message):
        return True
    return False


def is_missing_column_error(exc):
    """Return True when the database reports an undefined column."""
    if isinstance(exc, ProgrammingError):
        orig = getattr(exc, "orig", None)
        if getattr(orig, "sqlstate", None) == "42703":
            return True

    message = str(exc).lower()
    if "no such column" in message:
        return True
    if "does not exist" in message and " column " in message:
        return True
    return False
