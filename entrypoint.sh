#!/bin/bash
set -e

# Add current directory to PYTHONPATH
export PYTHONPATH=$PYTHONPATH:/app


# Check if data import should be skipped
if [ "$SKIP_DATA_IMPORT" != "true" ]; then
    # Wait for the database to be ready
    echo "Waiting for MySQL database at db:3306..."
    while ! mysqladmin ping -h"db" -P3306 --silent --user=${MYSQL_USER} --password=${MYSQL_PASSWORD}; do
        sleep 1
    done
    echo "MySQL is up and ready."

    # Ensure the authentication database exists even on existing volumes
    if [ -n "$MYSQL_ROOT_PASSWORD" ]; then
        echo "Ensuring auth_db exists..."
        mysql -h db -uroot -p"${MYSQL_ROOT_PASSWORD}" -e "CREATE DATABASE IF NOT EXISTS auth_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci; GRANT ALL PRIVILEGES ON auth_db.* TO 'stops_user'@'%'; FLUSH PRIVILEGES;" || true
    fi

    # Check if data needs to be imported.
    # A simple flag file can be used to ensure scripts run only once if desired,
    # or run them every time if the data needs to be fresh on each start.
    # For this setup, we'll run them every time to ensure data is populated.

    echo "Running data preparation and import scripts..."
    
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
else
    echo "SKIP_DATA_IMPORT is set to true. Skipping data import."
fi

echo "Starting Flask application on port 5001..."
# Start the Flask application
exec python backend/app.py