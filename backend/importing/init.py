import os
import time

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

if __name__ == "__main__":
    database_uri = os.environ.get('DATABASE_URI')

    if not database_uri:
        raise SystemExit('DATABASE_URI is not set')

    wait_for_db(database_uri, 'DATABASE_URI')

    print('Postgres is up and ready.')
