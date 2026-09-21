"""Stage snapshots away from readers, then replace app-owned tables atomically."""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import MetaData, text
from sqlalchemy.schema import CreateTable
from backend.importing.progress import progress_stage, report
from backend.importing.timing import stage
from sqlalchemy.orm import Session

from backend.extensions import db
import backend.models  # Registers the application tables.

LOGGER = logging.getLogger(__name__)


def publish_snapshot(
    engine,
    payload,
    write_rows,
    *,
    manifest=None,
    progress_callback=None,
    stage_event_callback=None,
):
    if engine.dialect.name != "postgresql":
        raise ValueError("Snapshot publication requires PostgreSQL/PostGIS")
    token = uuid.uuid4().hex
    staging, previous = f"import_{token}", f"previous_{token}"
    tables = [table for table in db.Model.metadata.sorted_tables if table.name != "dataset_publication"]
    names = [table.name for table in tables]
    stage_metadata = MetaData()
    for table in tables:
        cloned = table.to_metadata(stage_metadata, schema=staging, referred_schema_fn=lambda *args: staging)
        # SQLAlchemy regenerates names for Column(index=True) using the staging
        # schema. Preserve the public names expected by migrations and tooling.
        column_index_names = {tuple(column.name for column in index.columns): index.name
                              for index in table.indexes if index._column_flag}
        for index in cloned.indexes:
            if index._column_flag:
                index.name = column_index_names[tuple(column.name for column in index.columns)]
    created = False
    published = False
    try:
        with progress_stage('database.load', stage_event_callback):
            with engine.begin() as connection:
                connection.execute(text(f'CREATE SCHEMA "{staging}"'))
                # CreateTable includes PK/unique/FK constraints, but omits secondary
                # indexes. GeoAlchemy's spatial indexes are in table.indexes too.
                for table in stage_metadata.sorted_tables:
                    connection.execute(CreateTable(table))
            created = True
            # ORM insert statements use the same table definitions with a translated
            # schema; every foreign key in staging targets the new run's own rows.
            with engine.connect().execution_options(schema_translate_map={None: staging}) as connection:
                with Session(bind=connection) as stage_session, stage_session.begin():
                    stage_session.info['snapshot_schema'] = staging
                    with stage('import.load_tables'):
                        write_rows(stage_session, payload)
            with stage('import.indexes_and_analyze'), engine.begin() as connection:
                for table in stage_metadata.sorted_tables:
                    for index in sorted(table.indexes, key=lambda item: item.name):
                        index.create(connection)
                    # COPY and route rows supply explicit IDs. Keep future defaults
                    # above their maximum after moving the sequence into public.
                    column = table.autoincrement_column
                    if column is not None:
                        qualified = f'"{staging}"."{table.name}"'
                        connection.execute(text(f"""
                            SELECT setval(pg_get_serial_sequence(:table, :column),
                                          COALESCE(MAX("{column.name}"), 1), COUNT(*) > 0)
                            FROM {qualified}
                        """), {'table': qualified, 'column': column.name})
                    connection.execute(text(f'ANALYZE "{staging}"."{table.name}"'))
        # Keep this transaction short. A reader holds its existing locks until it
        # finishes, or bounded lock acquisition fails and the old run stays live.
        report(progress_callback, 'publish', 'Publishing the new dataset')
        with progress_stage('publish.swap', stage_event_callback):
            with stage("import.publish"), engine.begin() as connection:
                connection.execute(text("SET LOCAL lock_timeout = '3s'"))
                connection.execute(text("SET LOCAL statement_timeout = '25s'"))
                connection.execute(text("SELECT pg_advisory_xact_lock(784369152)"))
                quoted = ', '.join(f'public."{name}"' for name in sorted(names))
                connection.execute(text(f'LOCK TABLE {quoted} IN ACCESS EXCLUSIVE MODE'))
                connection.execute(text(f'CREATE SCHEMA "{previous}"'))
                for name in names:
                    connection.execute(text(f'ALTER TABLE public."{name}" SET SCHEMA "{previous}"'))
                for name in names:
                    connection.execute(text(f'ALTER TABLE "{staging}"."{name}" SET SCHEMA public'))
                if manifest is not None:
                    import json
                    connection.execute(text("""
                        INSERT INTO dataset_publication (id, run_id, manifest)
                        VALUES (1, :run_id, CAST(:manifest AS jsonb))
                        ON CONFLICT (id) DO UPDATE SET run_id = EXCLUDED.run_id, manifest = EXCLUDED.manifest
                    """), {"run_id": manifest["run_id"], "manifest": json.dumps(manifest)})
                connection.execute(text(f'DROP SCHEMA "{staging}"'))
            published = True
    finally:
        # Cleanup failure after a successful publication must not report the run
        # as rolled back. Orphaned schemas can be removed by an operator later.
        cleanup = previous if published else staging
        if created:
            try:
                with engine.begin() as connection:
                    connection.execute(text(f'DROP SCHEMA IF EXISTS "{cleanup}" CASCADE'))
            except Exception:
                LOGGER.exception("Could not remove snapshot schema %s", cleanup)
