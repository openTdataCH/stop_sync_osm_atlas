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

# The 'migrator' service runs the migrations and the 'scheduler' service the
# data pipeline; this container only serves the application.
echo "Starting Flask application on port 5001..."
# Start the Flask application
if [ "$FLASK_DEBUG" = "1" ]; then
    # The CLI keeps the reloader alive if an edit introduces an import/syntax
    # error, so fixing the file recovers without restarting the container.
    exec flask --app backend.app:app run --debug --host=0.0.0.0 --port=5001
else
    exec gunicorn -w 2 -b 0.0.0.0:5001 backend.app:app
fi
