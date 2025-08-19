# **OSM & ATLAS Synchronization**


Welcome! This project provides a systematic pipeline to identify, analyze, and resolve discrepancies between public transport stop data from **ATLAS** (Swiss official data) and **OpenStreetMap (OSM)**.

It automates data download and processing (ATLAS, OSM, GTFS, HRDF), performs exact/fuzzy/route-based matching, and serves an interactive web app for inspecting matches, problems, and manual fixes.

![Geneva stops](documentation/images/Geneve.png)

---

## Table of Contents

- [Overview](#overview)
- [Prerequisites](#prerequisites)
- [Installation & Setup (with Docker)](#installation--setup-with-docker)
- [Database Setup (Migrations)](#database-setup-migrations)
- [Data Acquisition (Entrypoint)](#data-acquisition-entrypoint)
- [Data Import (Entrypoint)](#data-import-entrypoint)
- [Running the Web Application](#running-the-web-application)
- [Usage](#usage)
- [Generating Reports](#generating-reports)
- [Project Report](#project-report)
- [Project Status](#project-status)
- [Contributing](#contributing)

---

## Overview

This project delivers a robust methodology and tooling to match public transport stops across two datasets:

- **ATLAS**: The official Swiss traffic-points dataset (boarding platforms).
- **OSM**: OpenStreetMap public-transport nodes.

It identifies exact and fuzzy matches, computes geographic distances, performs route-based matching (GTFS/HRDF), and exposes an interactive UI to inspect and manually correct mismatches.

## Prerequisites

- **Docker Desktop** with Compose v2 (required)
- Internet connection to download datasets (ATLAS, OSM, GTFS)
- **Optional**: Python 3.9+ and MySQL 8 for local development without Docker

## Installation & Setup (with Docker)

**Just want to run it?** Here's the fastest path:

1.  **Clone the repository**
    ```bash
    git clone https://githepia.hesge.ch/guillem.massague/bachelor-project.git
    cd bachelor-project
    ```

2.  **Configure environment** (optional but recommended):
    - Copy `env.example` to `.env` and adjust values (DB users/passwords, URIs, flags)

3.  **Build and Run with Docker Compose**:
    ```bash
    docker compose up --build
    ```
    
    **On the first run**, Docker will automatically:
    - Build the application image
    - Download and start MySQL database
    - Download ATLAS data from OpenTransportData.swiss
    - Download OSM data via the Overpass API
    - Download GTFS data for route matching
    - Process and match all data
    - Import everything into the database
    - Start the Flask web application

    This typically takes 10 minutes. Data and database state are cached across runs (`./data` directory and the `mysql_data` volume).

    **Match-Only Mode (Skip Data Downloads):**
    ```bash
    MATCH_ONLY=true docker compose up --build
    ```
    Use this when you want to re-run only the matching and database import using previously downloaded data. This is much faster than the full pipeline.

    **Development Mode (Skip Data Processing Entirely):**
    ```bash
    docker compose up app-dev
    ```
    Use this when the database is already populated and you want to iterate on the web application without re-running any data pipeline.

4.  **Access the application**:
    - Web app: [http://localhost:5001](http://localhost:5001)
    - MySQL database: `localhost:3306` (user: `stops_user`, password: `1234`)

    For better security, you can enable a dedicated auth DB user by creating a `.env` from `.env.example` and setting:
    - `AUTH_DB_USER`
    - `AUTH_DB_PASSWORD`
    Optionally override `AUTH_DATABASE_URI` to use this user.

5.  **To stop the services**:
    ```bash
    docker compose down
    ```
    To remove all data: `docker compose down -v`

## Database Setup (Migrations)
## Environment & Secrets

- Never commit real secrets. Use a local `.env` (ignored by git) or environment variables in your runtime.
- This repo provides `env.example` (copy to `.env`). Key variables:
  - `MYSQL_USER`, `MYSQL_PASSWORD`: base MySQL user for `stops_db` (dev default: `stops_user`/`1234`).
  - `AUTH_DB_USER`, `AUTH_DB_PASSWORD`: optional dedicated user for `auth_db` (least privilege). If set, the entrypoint will create/grant it and revoke `stops_user` on `auth_db`.
  - `DATABASE_URI`, `AUTH_DATABASE_URI`: SQLAlchemy URIs. Override to use your chosen users.
  - `SECRET_KEY`: Flask secret key (set a strong value in production).
  - `AUTO_MIGRATE`, `MATCH_ONLY`, `SKIP_DATA_IMPORT`: control data pipeline and migrations.
  - `TURNSTILE_SITE_KEY`, `TURNSTILE_SECRET_KEY`: Cloudflare Turnstile CAPTCHA (optional locally; required to enable CAPTCHA on auth forms).
  - `AWS_REGION`, `SES_FROM_EMAIL`: Amazon SES region and a verified sender identity (required to send emails).
  - `SES_CONFIGURATION_SET` (optional): existing SES configuration set name.
  - `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` (optional): AWS credentials if not using instance/task roles.

Example `.env` snippet:
```env
MYSQL_USER=stops_user
MYSQL_PASSWORD=1234
AUTH_DB_USER=auth_user
AUTH_DB_PASSWORD=change-me-strong
DATABASE_URI=mysql+pymysql://stops_user:1234@db/stops_db
AUTH_DATABASE_URI=mysql+pymysql://auth_user:change-me-strong@db/auth_db
SECRET_KEY=dev-insecure
AUTO_MIGRATE=true
# CAPTCHA (Cloudflare Turnstile)
TURNSTILE_SITE_KEY=your-turnstile-site-key
TURNSTILE_SECRET_KEY=your-turnstile-secret-key
# Email (Amazon SES)
AWS_REGION=eu-west-1
SES_FROM_EMAIL=no-reply@example.com
# SES_CONFIGURATION_SET=your-config-set
# If not using roles, provide AWS credentials via env
# AWS_ACCESS_KEY_ID=...
# AWS_SECRET_ACCESS_KEY=...
```

## Admin Management CLI

Use `manage.py` to list users, create users, and grant/revoke admin:
```bash
# Inside the container
docker compose exec app python manage.py list-users
docker compose exec app python manage.py create-user --email you@example.com --password 'StrongPass' --admin
docker compose exec app python manage.py set-admin --email you@example.com --on
docker compose exec app python manage.py set-admin --email you@example.com --off
```

The project uses Alembic (via Flask‑Migrate) to manage schema for both MySQL databases (`stops_db` and `auth_db`). On startup, the application waits for MySQL and runs `flask db upgrade` to apply migrations. In development, migrations can be auto‑generated on first run.

## Security & Permissions

- The application container now runs as a non‑root user (`app`) with minimal permissions in `/app`.
- Writable directories are restricted to what is needed at runtime (e.g., `/app/data`, `/app/.cache`).
- You can align the container user with your host UID/GID to avoid permission issues on bind mounts:

```bash
docker compose build --build-arg APP_UID=$(id -u) --build-arg APP_GID=$(id -g) app
```

If you see permission errors when the container tries to write into the bind‑mounted project directory, rebuild with the UID/GID args above.

## Authentication & Audit

- Authentication features: email/password (Argon2id), optional email verification, TOTP 2FA with backup codes, rate limiting and progressive lockout.
- Audit logging is enabled: all auth events are stored in `auth_db.auth_events` and also emitted as structured JSON to stdout.

Quick ways to inspect events:

```bash
# From your host, open a MySQL shell and query recent failed logins
docker compose exec db mysql -u stops_user -p1234 -e "USE auth_db; SELECT occurred_at, email_attempted, ip_address FROM auth_events WHERE event_type='login_failure' ORDER BY occurred_at DESC LIMIT 20;"

# Tail only auth events from app logs
docker compose logs -f app | grep auth_event | cat
```

## Data Acquisition (Entrypoint)
When the `app` container starts (and data import is not skipped), the entrypoint runs:

- `get_atlas_data.py`: downloads ATLAS data and GTFS, builds optimized route/stop artifacts
- `get_osm_data.py`: fetches OSM data via Overpass and processes it

Downloads are cached under `data/raw/` and processed artifacts under `data/processed/` to avoid re-downloading and to speed up subsequent runs. See `documentation/DATA_ORGANIZATION.md` for details.

**Speed up iterations**: Use `MATCH_ONLY=true` to skip downloads and only run the matching/import process using existing data files. This requires that a full pipeline has been run at least once to generate the necessary processed files.

## Data Import (Entrypoint)
After acquisition, `import_data_db.py` populates the MySQL databases (e.g., `stops`, `problems`, `persistent_data`, `atlas_stops`, `osm_nodes`, `routes_and_directions`).

Set `SKIP_DATA_IMPORT=true` (the `app-dev` service already does this) to bypass acquisition/import when you only want to run the web app against an existing database.

## Running the Web Application
The Flask server is started automatically by Docker Compose.

- **For full setup (including data processing):**
  ```bash
  docker compose up
  ```

- **For development (skipping data processing):**
  ```bash
  docker compose up app-dev
  ```

Access it at [http://localhost:5001/](http://localhost:5001/).

## Usage

- **Map View**: Browse stops by type (`matched`, `unmatched`, `osm`) and match method.
- **Filters & Search**: Filter by ATLAS SLOID, OSM Node ID, UIC reference, or route.
- **Manual Matching**: On the Problems page, use the Manual match action, select the opposite dataset entry on the map, and the system will save the pair. You can auto‑persist from the side panel.
- **Problems**:
  
- **Manage Data**:

## Generating Reports

The web app can generate CSV and PDF reports (still work in progress).

## Project Report

Work in progress.

## Project Status

This project is a **work in progress**. Feedback and improvements are welcome!

## Contributing

Feel free to submit issues and pull requests. Thank you for your interest! 🚀

---

