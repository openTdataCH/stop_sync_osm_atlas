import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _get_application_tables() -> list[str]:
    import backend.models  # noqa: F401
    from backend.extensions import db

    return [table.name for table in db.Model.metadata.sorted_tables]


def reset_import_db(database_uri: str) -> None:
    engine = create_engine(database_uri, pool_pre_ping=True)
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    application_tables = set(_get_application_tables())
    tables = [table for table in application_tables if table in existing_tables]
    if not tables:
        print('Import DB reset: no application tables to drop.')
    else:
        quoted_tables = ', '.join(f'"{table}"' for table in tables)
        with engine.begin() as conn:
            conn.execute(text(f'DROP TABLE IF EXISTS {quoted_tables} CASCADE'))
        print(f'Import DB reset: dropped {len(tables)} application tables.')

    if 'alembic_version' in existing_tables:
        with engine.begin() as conn:
            conn.execute(text('DROP TABLE IF EXISTS alembic_version'))
        print('Import DB reset: dropped alembic_version.')


if __name__ == '__main__':
    database_uri = os.environ.get('DATABASE_URI')
    if not database_uri:
        raise SystemExit('DATABASE_URI is not set')
    reset_import_db(database_uri)