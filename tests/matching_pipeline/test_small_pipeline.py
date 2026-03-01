import os
import pytest
from backend.models import StopsMatched, AtlasStop, OsmNode, Problem

@pytest.fixture(autouse=True)
def setup_test_env_and_db():
    """
    Overrides environment variables to point to the subsetted data in tests/data.
    Uses the in-memory SQLite database automatically configured by the docker 
    test runner (DATABASE_URI=sqlite://) and creates the schema.
    """
    # Point to the sample subset dataset
    os.environ['ATLAS_STOPS_CSV'] = 'tests/data/sample_atlas.csv'
    os.environ['OSM_XML_FILE'] = 'tests/data/sample_osm.xml'
    
    # Initialize DB Schema for the test
    from backend.extensions import db
    from matching_and_import_db.database.session import engine, session, user_input_engine
    from sqlalchemy.ext.compiler import compiles
    from sqlalchemy.dialects.postgresql import JSONB

    @compiles(JSONB, 'sqlite')
    def compile_jsonb_sqlite(type_, compiler, **kw):
        return 'JSON'
    
    
    # Mock SpatiaLite functions since they crash vanilla SQLite
    import sqlalchemy.dialects.sqlite.base as sqlite_base
    orig_do_execute = sqlite_base.SQLiteDialect.do_execute
    
    def mock_do_execute(self, cursor, statement, parameters=None, context=None):
        spatial_cmds = ["RecoverGeometryColumn", "AddGeometryColumn", "CreateSpatialIndex",
                       "CheckSpatialMetaData", "InitSpatialMetaData", "CheckSpatialIndex"]
        if any(cmd in statement for cmd in spatial_cmds) or statement.startswith("TRUNCATE TABLE"):
            return
        # Strip PostGIS function calls so INSERTs work on vanilla SQLite.
        # GeomFromEWKT(?) consumes 1 param; ST_SetSRID(ST_MakePoint(?, ?), ?) consumes 3.
        import re
        if parameters is not None:
            params = list(parameters)
        else:
            params = None
        # Count ? placeholders before the spatial expr to find the param index to remove
        for pattern, n_params in [
            (r'GeomFromEWKT\(\?\)', 1),
            (r'ST_SetSRID\(ST_MakePoint\(\?,\s*\?\),\s*\?\)', 3),
        ]:
            m = re.search(pattern, statement)
            if m and params is not None:
                # Count how many ? appear before this match
                before = statement[:m.start()].count('?')
                for _ in range(n_params):
                    if before < len(params):
                        params.pop(before)
                statement = statement[:m.start()] + 'NULL' + statement[m.end():]
        orig_do_execute(self, cursor, statement, params, context)
        
    sqlite_base.SQLiteDialect.do_execute = mock_do_execute
    
    # Mock Alembic schema updater
    import matching_and_import_db.database.helpers as db_helpers
    orig_ensure_schema_updated = db_helpers.ensure_schema_updated
    db_helpers.ensure_schema_updated = lambda: None

    # Mock PostGIS make_point_geom since SQLite has no ST_MakePoint/ST_SetSRID
    import matching_and_import_db.database.importer as importer_mod
    orig_make_point_geom = db_helpers.make_point_geom
    noop_geom = lambda lat, lon: None
    db_helpers.make_point_geom = noop_geom
    importer_mod.make_point_geom = noop_geom

    # Mock apply_persistent_solutions since user_input DB is a separate in-memory SQLite
    orig_apply_persistent = importer_mod.apply_persistent_solutions_service
    importer_mod.apply_persistent_solutions_service = lambda *args, **kwargs: None
    
    db.Model.metadata.create_all(engine)
    db.Model.metadata.create_all(user_input_engine)

    yield

    session.rollback()
    # Drop tables while mocks are still active (spatial DDL needs the mock)
    try:
        db.Model.metadata.drop_all(engine)
    except Exception:
        pass
    try:
        db.Model.metadata.drop_all(user_input_engine)
    except Exception:
        pass
    # Now restore all mocks
    sqlite_base.SQLiteDialect.do_execute = orig_do_execute
    db_helpers.ensure_schema_updated = orig_ensure_schema_updated
    db_helpers.make_point_geom = orig_make_point_geom
    importer_mod.make_point_geom = orig_make_point_geom
    importer_mod.apply_persistent_solutions_service = orig_apply_persistent


def test_small_pipeline_end_to_end():
    """
    End-to-End Test (Small Pipeline)
    
    Ensures that the entire matching and import process runs seamlessly 
    from the entrypoint logic down to database insertion, using a very small 
    data payload to execute quickly.
    
    This validates:
    - Domain Models Initialization
    - The Pipeline Heuristics
    - Problem Detection
    - Database Hydration (importer.py)
    """
    from matching_and_import_db.orchestrator import run_matching
    from matching_and_import_db.database.importer import import_to_database
    from matching_and_import_db.database.session import session
    
    # 1. Run the heuristics engine on the sample data
    result = run_matching()
    
    # Basic assertions on the raw output
    assert result is not None
    assert len(result.matched) > 0, "Expected matches from the small pipeline."
    
    # The current tests/data produces a match rate > 50% for unique atlas sloids
    matched_sloids = {m.atlas_node.sloid for m in result.matched}
    total_atlas = len(result.matched) + len(result.unmatched_atlas)  # Roughly speaking
    unique_atlas = len(set(m.atlas_node.sloid for m in result.matched) | {m.sloid for m in result.unmatched_atlas})
    
    match_rate = len(matched_sloids) / unique_atlas if unique_atlas > 0 else 0
    assert match_rate >= 0.50, f"Match rate too low: {match_rate:.0%}"
    assert match_rate <= 1.00, f"Match rate too high: {match_rate:.0%}"

    # 2. Database Insertion (Execute the data-first importer)
    no_nearby_sloids = import_to_database(
        result,
        result.duplicate_sloid_map
    )
    
    # 3. Verify Database State
    matched_db_count = session.query(StopsMatched).filter(StopsMatched.stop_type == 'matched').count()
    atlas_db_count = session.query(AtlasStop).count()
    osm_db_count = session.query(OsmNode).count()
    
    assert matched_db_count > 0, "Expected StopsMatched records in DB."
    assert atlas_db_count > 0, "Expected AtlasStop records in DB."
    assert osm_db_count > 0, "Expected OsmNode records in DB."
