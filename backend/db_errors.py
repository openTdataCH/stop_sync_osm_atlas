DATABASE_TIMEOUT_SQLSTATES = {
    "55P03",  # lock_not_available / lock_timeout
    "57014",  # query_canceled / statement_timeout
}


def _exception_chain(exc):
    pending = [exc]
    seen = set()
    while pending:
        current = pending.pop()
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        yield current
        pending.extend([
            getattr(current, "orig", None),
            getattr(current, "__cause__", None),
            getattr(current, "__context__", None),
        ])


def is_database_timeout_error(exc):
    """Return True for PostgreSQL lock and statement timeout failures."""
    for current in _exception_chain(exc):
        sqlstate = (
            getattr(current, "sqlstate", None)
            or getattr(current, "pgcode", None)
        )
        if sqlstate in DATABASE_TIMEOUT_SQLSTATES:
            return True

        message = str(current).lower()
        if (
            "canceling statement due to lock timeout" in message
            or "canceling statement due to statement timeout" in message
            or "statement timeout" in message
            or "lock timeout" in message
        ):
            return True
    return False
