#!/bin/bash
set -e

# Add current directory to PYTHONPATH
export PYTHONPATH=$PYTHONPATH:/app


echo "Waiting for MySQL database at db:3306..."
while ! mysqladmin ping -h"db" -P3306 --silent --user=${MYSQL_USER} --password=${MYSQL_PASSWORD}; do
    sleep 1
done
echo "MySQL is up and ready."

# Ensure the authentication database exists even on existing volumes (dev convenience)
if [ -n "$MYSQL_ROOT_PASSWORD" ]; then
    echo "Ensuring auth_db exists..."
    mysql -h db -uroot -p"${MYSQL_ROOT_PASSWORD}" -e "CREATE DATABASE IF NOT EXISTS auth_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci; GRANT ALL PRIVILEGES ON auth_db.* TO 'stops_user'@'%'; FLUSH PRIVILEGES;" || true

    # Optionally create a dedicated auth user with least-privilege grants if env vars are provided
    if [ -n "$AUTH_DB_USER" ] && [ -n "$AUTH_DB_PASSWORD" ]; then
        echo "Ensuring dedicated user '$AUTH_DB_USER' has privileges on auth_db..."
        mysql -h db -uroot -p"${MYSQL_ROOT_PASSWORD}" -e "CREATE USER IF NOT EXISTS '${AUTH_DB_USER}'@'%' IDENTIFIED BY '${AUTH_DB_PASSWORD}'; GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX ON auth_db.* TO '${AUTH_DB_USER}'@'%'; FLUSH PRIVILEGES;" || true
        echo "Revoking 'stops_user' privileges on auth_db (keeping its stops_db access)..."
        mysql -h db -uroot -p"${MYSQL_ROOT_PASSWORD}" -e "REVOKE ALL PRIVILEGES ON auth_db.* FROM 'stops_user'@'%'; FLUSH PRIVILEGES;" || true
    fi
fi

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
        python get_atlas_data.py
        echo "Finished get_atlas_data.py"

        # Download OSM data via Overpass API
        echo "Downloading OSM data via Overpass API..."
        python -c "from get_osm_data import query_overpass; query_overpass()"
        echo "Finished OSM Overpass query"

        # Process OSM data
        echo "Processing OSM data..."
        python get_osm_data.py
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