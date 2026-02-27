#!/bin/bash
set -e

# Add current directory to PYTHONPATH
export PYTHONPATH=$PYTHONPATH:/app


echo "Waiting for Postgres database..."
python matching_and_import_db/database/init.py

# Run database migrations
echo "Running database migrations..."
if [ "${AUTO_MIGRATE:-false}" = "true" ]; then
    if [ ! -d "migrations" ]; then
        flask db init || true
    fi
    # Ensure DB is at current head before trying to autogenerate migrations.
    # If upgrade fails (transient DB/network), skip migrate to avoid confusing
    # "Target database is not up to date" errors.
    if flask db upgrade; then
        # Autogenerate migration scripts from models (safe in dev)
        flask db migrate -m "Auto migration" || true
    else
        echo "WARN: flask db upgrade failed; skipping flask db migrate"
    fi
fi
flask db upgrade

# Check if data import should be skipped
if [ "$SKIP_DATA_IMPORT" != "true" ]; then


        # Run the complete matching pipeline and import to database
        echo "🔄 Running matching pipeline and importing to database..."
        python matching_and_import_db/database/importer.py
        echo "Finished importer.py"

        echo "All data scripts executed successfully."
else
    echo "SKIP_DATA_IMPORT is set to true. Skipping data import."
fi

echo "Starting Flask application on port 5001..."
# Start the Flask application
exec python backend/app.py