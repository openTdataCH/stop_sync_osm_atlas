#!/bin/bash
set -e

# Add current directory to PYTHONPATH
export PYTHONPATH=$PYTHONPATH:/app

MODE="${1:-app}"

if [ "$MODE" = "scheduler" ]; then
    echo "Starting scheduler mode..."
    echo "Waiting for Postgres database..."
    python matching_and_import_db/database/init.py
    exec python -m matching_and_import_db.scheduler.service
fi


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
else
    flask db upgrade
fi

if [ "${RUN_STARTUP_PIPELINE:-false}" = "true" ]; then
    echo "RUN_STARTUP_PIPELINE=true -> running one full pipeline before app start"
    python -m matching_and_import_db.scheduler.job_runner --mode full --trigger manual
fi

echo "Starting Flask application on port 5001..."
# Start the Flask application
exec python backend/app.py