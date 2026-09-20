#!/bin/bash
set -e

# Add current directory to PYTHONPATH
export PYTHONPATH=$PYTHONPATH:/app

MODE="${1:-app}"

if [ "$MODE" = "scheduler" ]; then
    echo "Starting scheduler mode..."
    echo "Waiting for Postgres database..."
    python backend/importing/init.py
    exec python -u -m backend.jobs.service
fi


echo "Waiting for Postgres database..."
python backend/importing/init.py

# Run database migrations are now handled by the 'migrator' container in docker-compose.
# We no longer run migrations in the app container.


# Background tasks like the data pipeline are handled by the 'scheduler' service.


echo "Starting Flask application on port 5001..."
# Start the Flask application
if [ "$FLASK_DEBUG" = "1" ]; then
    exec python backend/app.py
else
    exec gunicorn -w 2 -b 0.0.0.0:5001 backend.app:app
fi