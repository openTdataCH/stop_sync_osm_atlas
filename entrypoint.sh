#!/bin/bash
set -e

# Add current directory to PYTHONPATH
export PYTHONPATH=$PYTHONPATH:/app


echo "Waiting for Postgres database..."
python - <<'PY'
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

database_uri = os.environ.get('DATABASE_URI')
auth_uri = os.environ.get('AUTH_DATABASE_URI')

if not database_uri:
    raise SystemExit('DATABASE_URI is not set')

wait_for_db(database_uri, 'DATABASE_URI')
if auth_uri:
    # auth_db might not exist yet on reused volumes; try to create it, then wait.
    try:
        wait_for_db(auth_uri, 'AUTH_DATABASE_URI', attempts=3)
    except SystemExit:
        ensure_db_exists(auth_uri)
        wait_for_db(auth_uri, 'AUTH_DATABASE_URI')

print('Postgres is up and ready.')
PY

# Run database migrations
echo "Running database migrations..."
if [ "${AUTO_MIGRATE:-false}" = "true" ]; then
    if [ ! -d "migrations" ]; then
        flask db init || true
    fi
    # Autogenerate migration scripts from models (safe in dev)
    flask db migrate -m "Auto migration" || true
fi
flask db upgrade || true

# Create auth tables (quick fix for multi-database bind issue)
echo "Creating auth tables..."
python create_auth_tables.py || true

# Check if data import should be skipped
if [ "$SKIP_DATA_IMPORT" != "true" ]; then

    # Check if we should run only matching (skip data downloads)
    if [ "$MATCH_ONLY" = "true" ]; then
        echo "MATCH_ONLY mode: Skipping data downloads, running only matching and database import..."
        
        # Verify required processed files exist
        if [ ! -f "data/processed/osm_nodes_with_routes.csv" ] || [ ! -f "data/processed/atlas_routes_unified.csv" ]; then
            echo "Error: MATCH_ONLY=true but required processed files are missing."
            echo "Please run the full pipeline first (without MATCH_ONLY) to download and process data."
            exit 1
        fi
        
        # Run only the matching pipeline and database import
        echo "Running matching pipeline and database import..."
        python import_data_db.py
        echo "Finished import_data_db.py"
        
    else
        # Full pipeline: download, process, and import
        echo "Running full data preparation and import pipeline..."
        
        # Download ATLAS data
        echo "Downloading ATLAS data..."
        python -m Download_and_process_data.get_atlas_data
        echo "Finished get_atlas_data.py"

        # Download OSM data via Overpass API
        echo "Downloading OSM data via Overpass API..."
        python -c "from Download_and_process_data.get_osm_data import query_overpass; query_overpass()"
        echo "Finished OSM Overpass query"

        # Process OSM data
        echo "Processing OSM data..."
        python -m Download_and_process_data.get_osm_data
        echo "Finished get_osm_data.py processing"

        # Run the complete matching pipeline and import to database
        echo "Running complete matching pipeline and database import..."
        python import_data_db.py
        echo "Finished import_data_db.py"

        echo "All data scripts executed successfully."
    fi
else
    echo "SKIP_DATA_IMPORT is set to true. Skipping data import."
fi

echo "Starting Flask application on port 5001..."
# Start the Flask application
exec python backend/app.py