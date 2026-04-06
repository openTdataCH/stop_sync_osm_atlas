import math
import pandas as pd
from sqlalchemy import func
from backend.models import Problem

def make_point_geom(lat, lon):
    """Create a PostGIS POINT geometry (SRID 4326) from lat/lon, or None if missing."""
    if lat is None or lon is None:
        return None
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except Exception:
        return None
    return func.ST_SetSRID(func.ST_MakePoint(lon_f, lat_f), 4326)

def safe_value(val, default=None):
    """Safely handle NaN, None, and other problematic values for DB inserts"""
    if val is None:
        return default
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return default
    if pd.isna(val):
        return default
    return val

def get_osm_node_type(rec, is_osm_unmatched=False):
    """Determine the osm_node_type based on OSM tags or ORM-like dict fields."""
    if not isinstance(rec, dict):
        return None

    # Accept both shapes:
    # 1) {'tags': {...}} (nested)
    # 2) {...} where keys are already OSM tag names (flat)
    tags = rec.get('tags') if isinstance(rec.get('tags'), dict) else rec

    if is_osm_unmatched:
        osm_public_transport = tags.get('public_transport')
        osm_railway = tags.get('railway')
        osm_amenity = tags.get('amenity')
        osm_aerialway = tags.get('aerialway')
    else:
        osm_public_transport = rec.get('osm_public_transport')
        osm_railway = rec.get('osm_railway')
        osm_amenity = rec.get('osm_amenity')
        osm_aerialway = rec.get('osm_aerialway')

    if osm_public_transport == 'stop_position':
        return 'stop_position'
    if (osm_public_transport == 'station' or osm_railway == 'station') and osm_public_transport != 'stop_position':
        return 'railway_station'
    if osm_amenity == 'ferry_terminal':
        return 'ferry_terminal'
    if osm_aerialway and osm_aerialway != '':
        return 'aerialway'
    if osm_public_transport == 'platform':
        return 'platform'
    return None

def ensure_schema_updated():
    """Run Alembic migrations to ensure the DB schema is up to date."""
    try:
        import os
        from flask import Flask
        from flask_migrate import upgrade
        from backend.extensions import db, migrate
        import backend.models  # noqa: F401 - Ensure models are registered for Alembic
        from sqlalchemy import text

        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv(
            'DATABASE_URI',
            'postgresql+psycopg://stops_user:1234@localhost:5432/import_db',
        )
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(app)
        migrate.init_app(app, db)

        known_revisions = {
            'b5fa82492b15',
            '0fd9b8d7a1c4',
            '34cb04acd397',
            '647fb683a8d3',
        }

        def _repair_unknown_revision_if_needed() -> None:
            """Reset stale local Alembic revision metadata when history was rewritten."""
            try:
                current_revision = db.session.execute(text("SELECT version_num FROM alembic_version")).scalar()
            except Exception:
                # A failed probe can leave the session transaction aborted.
                db.session.rollback()
                return

            if current_revision and current_revision not in known_revisions:
                print(
                    "Warning: Unknown Alembic revision "
                    f"'{current_revision}' detected. Resetting to current head."
                )
                db.session.execute(text("DROP TABLE IF EXISTS alembic_version"))
                db.session.commit()
                from flask_migrate import stamp
                stamp(revision='head')

        def _upgrade_with_recovery():
            """Upgrade schema and recover from stale local Alembic revision references.

            Development setups may contain an alembic_version pointing to a removed
            revision after migration history cleanup. In that case, reset version
            metadata and stamp the current head before continuing.
            """
            _repair_unknown_revision_if_needed()
            try:
                upgrade()
            except BaseException as exc:
                message = str(exc)
                if "Can't locate revision identified by" not in message:
                    raise
                print(f"Warning: Alembic revision drift detected ({message}). Resetting alembic_version to head.")
                db.session.execute(text("DROP TABLE IF EXISTS alembic_version"))
                db.session.commit()
                from flask_migrate import stamp
                stamp(revision='head')

        with app.app_context():
            _upgrade_with_recovery()
            # Ensure cleanup statements run in a fresh transaction even if previous
            # revision-probe logic encountered and handled SQL errors.
            db.session.rollback()
            # Development cleanup: remove deprecated duplicate flags from stops_matched
            # while keeping a single migration history file.
            db.session.execute(text("ALTER TABLE stops_matched DROP COLUMN IF EXISTS has_atlas_duplicate"))
            db.session.execute(text("ALTER TABLE stops_matched DROP COLUMN IF EXISTS has_osm_duplicate"))

            # Ensure stop-unit tables exist for local databases with older revisions.
            db.session.execute(text(
                """
                CREATE TABLE IF NOT EXISTS osm_stops (
                    id SERIAL PRIMARY KEY,
                    stop_kind VARCHAR(20) NOT NULL,
                    group_kind VARCHAR(50),
                    representative_node_id VARCHAR(100) NOT NULL REFERENCES osm_nodes(osm_node_id) ON DELETE CASCADE,
                    CONSTRAINT ck_osm_stops_stop_kind CHECK (stop_kind IN ('single', 'pair', 'trio')),
                    CONSTRAINT ck_osm_stops_group_kind CHECK (
                        group_kind IS NULL OR group_kind IN (
                            'osm_pair_uic',
                            'osm_pair_name',
                            'osm_pair_tram',
                            'osm_pair_uic_equal_15m',
                            'osm_pair_name_equal_15m',
                            'osm_pair_tram_equal_15m',
                            'osm_trio'
                        )
                    )
                )
                """
            ))
            db.session.execute(text("CREATE INDEX IF NOT EXISTS idx_osm_stops_stop_kind ON osm_stops(stop_kind)"))
            db.session.execute(text("CREATE INDEX IF NOT EXISTS idx_osm_stops_group_kind ON osm_stops(group_kind)"))
            db.session.execute(text("CREATE INDEX IF NOT EXISTS idx_osm_stops_representative_node_id ON osm_stops(representative_node_id)"))

            db.session.execute(text(
                """
                CREATE TABLE IF NOT EXISTS osm_stop_members (
                    osm_stop_id INTEGER NOT NULL REFERENCES osm_stops(id) ON DELETE CASCADE,
                    node_id VARCHAR(100) NOT NULL REFERENCES osm_nodes(osm_node_id) ON DELETE CASCADE,
                    member_role VARCHAR(20) NOT NULL,
                    PRIMARY KEY (osm_stop_id, node_id),
                    CONSTRAINT uq_osm_stop_members_node_id UNIQUE (node_id),
                    CONSTRAINT ck_osm_stop_members_member_role CHECK (
                        member_role IN ('single', 'pair_a', 'pair_b', 'trio_middle', 'trio_side')
                    )
                )
                """
            ))
            db.session.commit()
        print("Database schema migrated to latest revision.")
    except Exception as e:
        print(f"Error running migrations: {e}")
        raise

def validate_coordinates(rec, lat_key, lon_key, id_key, id_value, record_type):
    """Validate and extract coordinates from a record."""
    try:
        lat = safe_value(rec.get(lat_key))
        lon = safe_value(rec.get(lon_key))
        
        if lat is None or lon is None:
            print(f"Warning: Missing coordinates for {record_type} {id_key}={id_value}")
            return None, None
        
        lat_float = float(lat)
        lon_float = float(lon)
        
        if math.isnan(lat_float) or math.isinf(lat_float) or math.isnan(lon_float) or math.isinf(lon_float):
            print(f"Warning: Invalid coordinates (NaN/Inf) for {record_type} {id_key}={id_value}")
            return None, None
        
        if not (-90 <= lat_float <= 90) or not (-180 <= lon_float <= 180):
            print(f"Warning: Coordinates out of range for {record_type} {id_key}={id_value}: lat={lat_float}, lon={lon_float}")
            return None, None
        
        return lat_float, lon_float
    except (ValueError, TypeError) as e:
        print(f"Warning: Error parsing coordinates for {record_type} {id_key}={id_value}: {e}")
        return None, None

def get_from_tags(rec, tag_key, default=None):
    """Extract a value from OSM tags dictionary."""
    if tag_key in rec:
        return safe_value(rec[tag_key], default)
    tags = rec.get('tags', {})
    if isinstance(tags, dict) and tag_key in tags:
        return safe_value(tags[tag_key], default)
    return default

def apply_problem_results(stop_record, results: list):
    """Convert ProblemResult objects into ORM Problem records on a Stop."""
    for r in results:
        stop_record.problems.append(Problem(
            problem_type=r.problem_type,
            priority=r.priority,
        ))
