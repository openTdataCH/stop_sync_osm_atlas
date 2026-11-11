"""
Pytest configuration and shared fixtures for stop_sync_osm_atlas tests.

This module provides:
- Independent review application fixtures
- Flask test client configuration
"""

import os
import re
import sys
import pytest

# Ensure project root is in path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Rate-limit counters stay in process memory.
os.environ['RATELIMIT_STORAGE_URI'] = 'memory://'
# The importer opens its connection at import time; never let it reach a real
# database. PostGIS tests use their own TEST_POSTGRES_URI.
os.environ['DATABASE_URI'] = 'sqlite://'


# =============================================================================
# Backend / Flask Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def _runtime_state_dir(monkeypatch, tmp_path):
    """Pipeline status, run lease and export tasks go to a fresh directory per test, never data/runtime."""
    monkeypatch.setenv('STATE_DIR', str(tmp_path / 'runtime'))


@pytest.fixture(autouse=True)
def _restore_model_indexes():
    """GeoAlchemy2's SQLite DDL removes geometry indexes from the shared tables; put them back."""
    import backend.models  # noqa: F401
    from backend.extensions import db

    saved = {table: set(table.indexes) for table in db.Model.metadata.tables.values()}
    yield
    for table, indexes in saved.items():
        table.indexes.clear()
        table.indexes.update(indexes)


@pytest.fixture(autouse=True)
def _no_quality_download(monkeypatch):
    """No test reaches GitHub for quality evidence, and none sees what another test loaded."""
    from backend.services import quality_report

    monkeypatch.setattr(quality_report, 'download', lambda revision: None)
    monkeypatch.setattr(quality_report, '_loaded', {})
    monkeypatch.setattr(quality_report, '_missed', {})


@pytest.fixture
def app():
    """Create Flask application configured for testing, on the in-memory SQLite set above."""
    # Import here to avoid circular imports and allow test isolation
    from backend.app import create_app

    app = create_app()
    app.config['TESTING'] = True

    yield app


@pytest.fixture
def client(app):
    """Create a test client for the Flask application."""
    return app.test_client()


@pytest.fixture
def postgres():
    """A disposable PostGIS database from TEST_POSTGRES_URI, with a fresh schema."""
    from sqlalchemy import create_engine, text

    import backend.models  # noqa: F401 -- registers tables used by metadata.create_all.
    from backend.extensions import db

    uri = os.getenv('TEST_POSTGRES_URI')
    if not uri:
        pytest.skip('TEST_POSTGRES_URI must identify a disposable PostGIS database')
    engine = create_engine(uri)
    with engine.begin() as connection:
        database = connection.execute(text('SELECT current_database()')).scalar()
        if not database.endswith('_test') and database != 'transport_test':
            pytest.fail('Database name must end in _test to permit resetting the test schema')
        connection.execute(text('DROP SCHEMA public CASCADE'))
        connection.execute(text('CREATE SCHEMA public'))
        connection.execute(text('CREATE EXTENSION IF NOT EXISTS postgis'))
        db.Model.metadata.create_all(connection)
    yield engine
    engine.dispose()


@pytest.fixture
def sqlite_tables(app, monkeypatch):
    """Create model tables in the app's SQLite database and return the session.

    Call it with the models a test needs. Geometry columns become text.
    """
    import sqlalchemy.dialects.sqlite.base as sqlite_base

    from backend.extensions import db

    orig_do_execute = sqlite_base.SQLiteDialect.do_execute

    def do_execute(self, cursor, statement, parameters=None, context=None):
        spatial_cmds = ('RecoverGeometryColumn', 'CreateSpatialIndex', 'CheckSpatialMetaData',
                        'InitSpatialMetaData', 'CheckSpatialIndex')
        if any(cmd in statement for cmd in spatial_cmds) or 'USING gist' in statement.lower():
            return
        if 'CREATE INDEX idx_stops_geom_gist' in statement:
            return
        if 'AddGeometryColumn' in statement:
            match = re.search(r"AddGeometryColumn\s*\('(\w+)',\s*'(\w+)'", statement)
            if match:
                try:
                    orig_do_execute(self, cursor, f'ALTER TABLE {match.group(1)} ADD COLUMN {match.group(2)} TEXT', None, context)
                except Exception:
                    pass
            return
        orig_do_execute(self, cursor, statement, parameters, context)

    monkeypatch.setattr(sqlite_base.SQLiteDialect, 'do_execute', do_execute)
    with app.app_context():
        # Geometry is written through GeomFromEWKT() and read through AsEWKB().
        connection = db.session.connection().connection.dbapi_connection
        for function in ('GeomFromEWKT', 'AsEWKB'):
            connection.create_function(function, 1, lambda value: value)

        def create(*models):
            for model in models:
                model.__table__.create(bind=db.engine, checkfirst=True)
            return db.session

        yield create
        db.session.remove()


@pytest.fixture
def problems_db(sqlite_tables):
    """SQLite stand-in for the stop, problem and snapshot tables."""
    from backend.models import AtlasStop, DatasetPublication, OsmNode, Problem, StopsMatched

    return sqlite_tables(AtlasStop, OsmNode, StopsMatched, Problem, DatasetPublication)
