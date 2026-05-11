import os
import importlib
import math
import pytest
from backend.models import StopsMatched, AtlasStop, OsmNode, Problem

@pytest.fixture
def setup_test_env_and_db(monkeypatch):
    """
    Overrides environment variables to point to the subsetted data in tests/data.
    Uses the in-memory SQLite database automatically configured by the docker 
    test runner (DATABASE_URI=sqlite://) and creates the schema.
    """
    # Point to the sample subset dataset
    os.environ['ATLAS_STOPS_CSV'] = 'tests/data/sample_atlas.csv'
    os.environ['OSM_XML_FILE'] = 'tests/data/sample_osm.xml'
    # Ensure both DBs use SQLite for this test regardless of outer environment.
    os.environ['DATABASE_URI'] = 'sqlite://'
    
    # Initialize DB Schema for the test
    from backend.extensions import db
    import matching_and_import_db.database.session as session_module
    session_module = importlib.reload(session_module)
    engine = session_module.engine
    session = session_module.session

    # Reload orchestrator and importer to ensure they pick up the new session and mocks
    import matching_and_import_db.orchestrator as orchestrator_mod
    importlib.reload(orchestrator_mod)
    import matching_and_import_db.database.importer as importer_mod
    importlib.reload(importer_mod)
    import matching_and_import_db.database.helpers as db_helpers
    importlib.reload(db_helpers)

    from sqlalchemy.ext.compiler import compiles
    from sqlalchemy.dialects.postgresql import JSONB

    @compiles(JSONB, 'sqlite')
    def compile_jsonb_sqlite(type_, compiler, **kw):
        return 'JSON'
    
    # Mock SpatiaLite functions since they crash vanilla SQLite
    import sqlalchemy.dialects.sqlite.base as sqlite_base
    orig_do_execute = sqlite_base.SQLiteDialect.do_execute
    
    import re
    def mock_do_execute(self, cursor, statement, parameters=None, context=None):
        spatial_cmds = ["RecoverGeometryColumn", "CreateSpatialIndex",
                       "CheckSpatialMetaData", "InitSpatialMetaData", "CheckSpatialIndex"]
        if any(cmd in statement for cmd in spatial_cmds) or statement.startswith("TRUNCATE TABLE"):
            return
        
        # Intercept AddGeometryColumn and turn it into a regular ALTER TABLE ADD COLUMN
        if "AddGeometryColumn" in statement:
            m = re.search(r"AddGeometryColumn\s*\('(\w+)',\s*'(\w+)'", statement)
            if m:
                table, col = m.groups()
                # Run a plain ALTER TABLE to create the column as TEXT so INSERTs work
                try:
                    orig_do_execute(self, cursor, f"ALTER TABLE {table} ADD COLUMN {col} TEXT", None, context)
                except Exception:
                    pass # Table might already have it or other issue
            return

        orig_do_execute(self, cursor, statement, parameters, context)
        
    sqlite_base.SQLiteDialect.do_execute = mock_do_execute

    
    # Mock PostGIS/EWKT geometry generation in the importer
    orig_make_point_wkt = getattr(importer_mod, '_make_point_wkt', None)
    importer_mod._make_point_wkt = lambda lat, lon: None

    # Keep this test hermetic: CI does not ship GTFS cache artifacts or raw GTFS files.
    monkeypatch.setattr(importer_mod, '_build_gtfs_insert_payloads', lambda: ([], []))

    # Mock PostGIS make_point_geom (legacy/helpers)
    orig_make_point_geom = db_helpers.make_point_geom
    db_helpers.make_point_geom = lambda lat, lon: None

    # Older tests mocked a user-input persistence hook here. Keep the fixture
    # tolerant if that optional integration is absent in the current importer.
    orig_apply_persistent = getattr(importer_mod, 'apply_persistent_solutions_service', None)
    if orig_apply_persistent is not None:
        importer_mod.apply_persistent_solutions_service = lambda *args, **kwargs: None
    
    db.Model.metadata.create_all(engine)

    yield

    session.rollback()
    # Drop tables while mocks are still active (spatial DDL needs the mock)
    try:
        db.Model.metadata.drop_all(engine)
    except Exception:
        pass
    # Now restore all mocks
    sqlite_base.SQLiteDialect.do_execute = orig_do_execute
    db_helpers.make_point_geom = orig_make_point_geom
    if orig_make_point_wkt is not None:
        importer_mod._make_point_wkt = orig_make_point_wkt
    if orig_apply_persistent is not None:
        importer_mod.apply_persistent_solutions_service = orig_apply_persistent



def test_small_pipeline_end_to_end(setup_test_env_and_db):
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
    from matching_and_import_db.database.importer import (
        build_fast_insert_payloads,
        import_to_database,
        precompute_problem_artifacts,
        precompute_route_artifacts,
    )
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

    # 2. Database Insertion (Execute the payload-first importer)
    problem_artifacts = precompute_problem_artifacts(result)
    route_artifacts = precompute_route_artifacts(result)
    db_payloads = build_fast_insert_payloads(result, problem_artifacts, route_artifacts)
    no_nearby_sloids = import_to_database(db_payloads=db_payloads)
    
    # 3. Verify Database State
    matched_db_count = session.query(StopsMatched).filter(StopsMatched.stop_type == 'matched').count()
    atlas_db_count = session.query(AtlasStop).count()
    osm_db_count = session.query(OsmNode).count()
    
    assert matched_db_count > 0, "Expected StopsMatched records in DB."
    assert atlas_db_count > 0, "Expected AtlasStop records in DB."
    assert osm_db_count > 0, "Expected OsmNode records in DB."


def test_load_gtfs_insert_payload_cache_normalizes_nan_values(tmp_path, monkeypatch):
    import matching_and_import_db.database.importer as importer_mod

    stops_cache = tmp_path / 'gtfs_stops.csv'
    state_cache = tmp_path / 'gtfs_atlas_stop_matches.csv'

    stops_cache.write_text(
        "stop_id,stop_name,uic_number,local_ref,normalized_local_ref,stop_lat,stop_lon\n"
        "stop-1,Main Stop,8500,,,46.1,7.1\n",
        encoding='utf-8',
    )
    state_cache.write_text(
        "stop_id,sloid,stop_type,match_method,distance_m,gtfs_stop_lat,gtfs_stop_lon,atlas_lat,atlas_lon\n"
        "stop-1,sloid-1,matched,,NaN,46.1,7.1,46.2,7.2\n"
        ",,atlas_unmatched,,NaN,,,46.3,7.3\n",
        encoding='utf-8',
    )

    monkeypatch.setattr(importer_mod, 'GTFS_DB_STOPS_CACHE_PATH', str(stops_cache))
    monkeypatch.setattr(importer_mod, 'GTFS_DB_STATE_CACHE_PATH', str(state_cache))

    gtfs_stop_rows, gtfs_state_rows = importer_mod._load_gtfs_insert_payload_cache()

    assert gtfs_stop_rows[0]['local_ref'] is None
    assert gtfs_stop_rows[0]['normalized_local_ref'] is None
    assert gtfs_state_rows[0]['match_method'] is None
    assert gtfs_state_rows[0]['distance_m'] is None
    assert gtfs_state_rows[1]['stop_id'] is None
    assert gtfs_state_rows[1]['sloid'] is None
    assert not math.isnan(gtfs_state_rows[0]['gtfs_stop_lat'])
