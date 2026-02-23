-- Create the secondary user-input database on first container initialization.
-- Note: docker-entrypoint-initdb.d scripts run only when the data directory is empty.

CREATE DATABASE user_input_db;

-- Grant access to the main app user (POSTGRES_USER).
-- This assumes POSTGRES_USER is the same principal used by the app URIs.
GRANT ALL PRIVILEGES ON DATABASE user_input_db TO CURRENT_USER;
