# **OSM & ATLAS Synchronization**


Welcome! This project provides a systematic pipeline to identify, analyze, and resolve discrepancies between public transport stop data from **ATLAS** (Swiss official data) and **OpenStreetMap (OSM)**.

It automates data download and processing (ATLAS, OSM, GTFS, HRDF), performs exact/distance-based/route-based matching, and serves an interactive web app for inspecting matches, problems, and manual fixes.

![Geneva stops](documentation/images/Geneve.png)

---

## Table of Contents

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

## Prerequisites

- **Docker Desktop** with Compose v2 (required)
- Internet connection to download datasets (ATLAS, OSM, GTFS, HRDF)
- **Optional**: Python 3.9+ and MySQL 8 for local development without Docker

## Installation & Setup (with Docker)

**Just want to run it?** Here's the fastest path:

1.  **Clone the repository**
    ```bash
    git clone https://github.com/openTdataCH/stop_sync_osm_atlas.git
    cd stop_sync_osm_atlas
    ```

2.  **Configure environment** (optional but recommended):
    - Copy `env.example` to `.env` and adjust values (DB users/passwords, URIs, flags)

3.  **Build and Run with Docker Compose** (no .env required for local):
    ```bash
    docker compose up --build
    ```
    
    **On the first run**, Docker will automatically:
    - Build the application image
    - Download and start MySQL database
    - Download ATLAS data from OpenTransportData.swiss
    - Download GTFS and HRDF data for route matching
    - Download OSM data via the Overpass API
    - Process and match all data
    - Import everything into the database
    - Start the Flask web application

    This typically takes 15 minutes. Data and database state are cached across runs (`./data` directory and the `mysql_data` volume).

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

## Pipline (Entrypoint)
![Schema pipeline](documentation/images/PipelineSchema.png)
When the `app` container starts (and data import is not skipped), the entrypoint runs:

- `get_atlas_data.py`: downloads ATLAS data and GTFS, builds optimized route/stop artifacts
- `get_osm_data.py`: fetches OSM data via Overpass and processes it

Downloads are cached under `data/raw/` and processed artifacts under `data/processed/`  See [DATA_ORGANIZATION.md](documentation/DATA_ORGANIZATION.md) for details.

**Speed up iterations**: Use `MATCH_ONLY=true` to skip downloads and data processing and only run the matching/import process using existing data files. This requires that a full pipeline has been run at least once to generate the necessary processed files.

### Data Import (Entrypoint)
After acquisition, `import_data_db.py` populates the MySQL databases (e.g., `stops`, `problems`, `persistent_data`, `atlas_stops`, `osm_nodes`, `routes_and_directions`).

Set `SKIP_DATA_IMPORT=true` (the `app-dev` service already does this) to bypass acquisition/import when you only want to run the web app against an existing database.

### Running the Web Application
The Flask server is started automatically by Docker Compose.

Access it at [http://localhost:5001/](http://localhost:5001/).

**Usage:**

- **Map View**: Browse stops by type (`matched`, `unmatched`, `osm`) and match method.
- **Filters & Search**: Filter by ATLAS SLOID, OSM Node ID, UIC reference, or route.
- **Problems**: On the problems page you can solve the problems. See [PROBLEMS_DEFINITIONS.md](documentation/PROBLEMS_DEFINITIONS.md).
- **Manage Data**: See [PERSISTENT_DATA.md](documentation/PERSISTENT_DATA.md).
- **Generating Reports:** The web app can generate CSV and PDF reports. See [GENERATE_REPORTS.md](documentation/GENERATE_REPORTS.md)

## Environment & Secrets

- This repo provides `env.example` (copy to `.env` if you want to override defaults). Key variables:
  - `MYSQL_USER`, `MYSQL_PASSWORD`: base MySQL user for `stops_db` (dev default: `stops_user`/`1234`).
  - `AUTH_DB_USER`, `AUTH_DB_PASSWORD`: optional dedicated user for `auth_db` (least privilege). If set, the entrypoint will create/grant it and revoke `stops_user` on `auth_db`.
  - `DATABASE_URI`, `AUTH_DATABASE_URI`: SQLAlchemy URIs. Override to use your chosen users.
  - `SECRET_KEY`: Flask secret key (set a strong value in production).
  - `AUTO_MIGRATE`, `MATCH_ONLY`, `SKIP_DATA_IMPORT`: control data pipeline and migrations.
  - `TURNSTILE_SITE_KEY`, `TURNSTILE_SECRET_KEY`: Cloudflare Turnstile CAPTCHA (optional locally; required to enable CAPTCHA on auth forms).
  - `AWS_REGION`, `SES_FROM_EMAIL`: Amazon SES region and a verified sender identity (only required if you want to send emails).
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

Use `manage.py` to list users, create users, and grant/revoke admin (run these inside the container). This is the simplest way to become admin locally:
```bash
# Inside the container
docker compose exec app python manage.py list-users
docker compose exec app python manage.py create-user --email you@example.com --password 'StrongPass' --admin
docker compose exec app python manage.py set-admin --email you@example.com --on
docker compose exec app python manage.py set-admin --email you@example.com --off
```

If you are running the `app-dev` service instead, replace `app` with `app-dev`:
```bash
docker compose exec app-dev python manage.py list-users
```

The project uses Alembic (via Flask‑Migrate) to manage schema for both MySQL databases (`stops_db` and `auth_db`). On startup, the application waits for MySQL and runs `flask db upgrade` to apply migrations. In development, migrations can be auto‑generated on first run.

## Production deployment (read‑only runtime)

- The web app does not write to the filesystem at runtime. For production, run with a read‑only root filesystem and no bind mounts using the prod override:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

- This enables `read_only: true`, removes volumes, and mounts a tmpfs at `/tmp`. HTTPS‑related flags are also enforced (`FORCE_HTTPS=true`, `SESSION_COOKIE_SECURE=true`).
- Use the standard compose file (without the prod override) only when running data acquisition/matching scripts that need to write under `./data/`.

## Authentication

- Authentication features: email/password (Argon2id), optional email verification, TOTP 2FA with backup codes, rate limiting and progressive lockout.

### Local auth notes
- You can log in with any account you create via the UI or `manage.py`.
- Email verification is optional locally; if SES is not configured, verification emails are skipped harmlessly.
- CAPTCHA (Turnstile) checks are skipped if keys are not set.

### Roles: what admins vs users can do
- Users (authenticated):
  - Manual match stops (`/api/manual_match`)
  - Save solutions and notes; make them persistent for specific stops
  - Generate reports
  - Bulk persist all current solutions and notes (`/api/make_all_persistent`)
- Admins (authenticated + `is_admin=true`):
  - Delete persistent entries (`DELETE /api/persistent_data/<id>`)
  - Make a specific persistent solution non‑persistent (`/api/make_non_persistent/<id>`)
  - Clear all persistent data (`/api/clear_all_persistent`)
  - Clear all non‑persistent data (`/api/clear_all_non-persistent`)




## Bachelor Project Report

Check the bachelor project report at: [ISC_SEC_memoire_diplome_GuillemMASSAGUE-OrestisMALASPINAS-2025.pdf](ISC_SEC_memoire_diplome_GuillemMASSAGUE-OrestisMALASPINAS-2025.pdf)


## Contributing and project Status

This project is a **work in progress**. Feedback and improvements are welcome!
Feel free to submit issues and pull requests. Thank you for your interest! 🚀

---

