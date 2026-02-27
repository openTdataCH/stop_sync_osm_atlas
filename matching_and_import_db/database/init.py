import os
import time
from urllib.parse import urlparse, urlunparse

from sqlalchemy import create_engine, text

def wait_for_db(uri: str, name: str, attempts: int = 60) -> None:
    engine = create_engine(uri, pool_pre_ping=True)
    last_err = None
    for _ in range(attempts):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return
        except Exception as e:
            last_err = e
            time.sleep(1)
    raise SystemExit(f"Database not ready: {name}: {last_err}")

def ensure_db_exists(target_uri: str) -> None:
    """Ensure the database referenced by target_uri exists.

    For Postgres, CREATE DATABASE cannot run inside a transaction.
    """
    parsed = urlparse(target_uri)
    dbname = (parsed.path or '').lstrip('/')
    if not dbname:
        return

    # Connect to the server default 'postgres' database
    server_uri = urlunparse(parsed._replace(path='/postgres'))
    engine = create_engine(server_uri, pool_pre_ping=True)
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :d"),
            {"d": dbname},
        ).scalar()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{dbname}"'))

if __name__ == "__main__":
    database_uri = os.environ.get('DATABASE_URI')
    auth_uri = os.environ.get('USER_INPUT_DATABASE_URI')

    if not database_uri:
        raise SystemExit('DATABASE_URI is not set')

    wait_for_db(database_uri, 'DATABASE_URI')
    if auth_uri:
        # user_input_db might not exist yet on reused volumes; try to create it, then wait.
        try:
            wait_for_db(auth_uri, 'USER_INPUT_DATABASE_URI', attempts=3)
        except SystemExit:
            ensure_db_exists(auth_uri)
            wait_for_db(auth_uri, 'USER_INPUT_DATABASE_URI')

    print('Postgres is up and ready.')
