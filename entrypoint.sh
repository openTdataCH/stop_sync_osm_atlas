#!/bin/bash
set -e

# Add current directory to PYTHONPATH
export PYTHONPATH=$PYTHONPATH:/app

MODE="${1:-app}"

if [ "$MODE" = "scheduler" ]; then
    echo "Starting scheduler mode..."
    echo "Waiting for Postgres database..."
    python matching_and_import_db/database/init.py
    exec python -u -m matching_and_import_db.scheduler.service
fi


echo "Waiting for Postgres database..."
python matching_and_import_db/database/init.py

# Run database migrations are now handled by the 'migrator' container in docker-compose.
# We no longer run migrations in the app container.


# Background tasks like the data pipeline are handled by the 'scheduler' service.


echo "Starting Flask application on port 5001..."
# Start the Flask application
exec python backend/app.py