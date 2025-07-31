# **Bachelor Project**

Welcome to the **Bachelor Project** repository. This project provides a systematic pipeline to identify, analyze, and resolve discrepancies between public transport stop data from **ATLAS** (Swiss official data) and **OpenStreetMap (OSM)**.

---

## Quick Start

**Just want to run it?** Here's how:

1. **Clone the repository**
   ```bash
   git clone https://githepia.hesge.ch/guillem.massague/bachelor-project.git
   cd bachelor-project
   ```

2. **Build & start everything**
   ```bash
   docker compose up --build
   ```
   This will:
   - Download and set up the MySQL database (persisted in a Docker **volume**)
   - Download ATLAS and OSM data automatically
   - Process and match the data
   - Start the web application at [http://localhost:5001](http://localhost:5001)

   **First run takes 10-15 minutes** to download and process all data. Subsequent runs are much faster.

3. **Development shortcut** (skip heavy data processing):
   ```bash
   docker compose up app-dev
   ```

4. **Stop & clean-up**
   ```bash
   # Stop containers
   docker compose down

   # Optional – ⚠️ wipe the database completely (destroys the Docker volume)
   docker compose down -v
   ```
   If you ever experience database corruption or simply want a fresh start, use the second command. It removes the `mysql_data` volume created by Docker Compose so the next run starts from a clean slate.

---

## Table of Contents

- [Overview](#overview)
- [Prerequisites](#prerequisites)
- [Installation & Setup (with Docker)](#installation--setup-with-docker)
- [Database Setup (Handled by Docker Compose)](#database-setup-handled-by-docker-compose)
- [Data Acquisition (Handled by Docker Entrypoint)](#data-acquisition-handled-by-docker-entrypoint)
- [Data Import (Handled by Docker Entrypoint)](#data-import-handled-by-docker-entrypoint)
- [Running the Web Application (Handled by Docker Compose)](#running-the-web-application-handled-by-docker-compose)
- [Usage](#usage)
- [Generating Reports](#generating-reports)
- [Project Report](#project-report)
- [Project Status](#project-status)
- [Contributing](#contributing)

---

## Overview

This project aims to build a robust methodology for matching public transport stops between two datasets:

- **ATLAS**: The official Swiss traffic-points dataset (boarding platforms).
- **OSM**: OpenStreetMap public-transport nodes.

We identify exact and fuzzy matches, compute geographic distances, and provide tools to inspect and manually correct mismatches.

## Prerequisites

- **Docker and Docker Compose** (required)
- Internet connection to download data
- **Optional**: Python 3.9+ and MySQL for local development

## Installation & Setup (with Docker)

1.  **Clone the repository**
    ```bash
    git clone https://githepia.hesge.ch/guillem.massague/bachelor-project.git
    cd bachelor-project
    ```

2.  **Build and Run with Docker Compose**:
    ```bash
    docker compose up --build
    ```
    
    **First run**: Docker will automatically:
    - Build the application image
    - Download and start MySQL database
    - Download ATLAS data from Swiss Open Transport Data
    - Download OSM data via Overpass API
    - Download GTFS data for route matching
    - Process and match all data
    - Import everything into the database
    - Start the Flask web application

    **This takes 10-15 minutes on first run**.

    **Development Mode (Skip Data Processing):**
    ```bash
    docker compose up app-dev
    ```
    Use this when the database is already populated and you want to work on the web application.

3.  **Access the application**:
    - Web app: [http://localhost:5001](http://localhost:5001)
    - MySQL database: `localhost:3306` (user: `stops_user`, password: `1234`)

4.  **To stop the services**:
    ```bash
    docker compose down
    ```
    To remove all data: `docker compose down -v`

## Database Setup (Handled by Docker Compose)
The `docker-compose.yml` configuration handles the database creation (`stops_db`) and initialization using `database_setup.sql`.

## Data Acquisition (Handled by Docker Entrypoint)
The data acquisition scripts (`get_atlas_data.py`, `get_osm_data.py`) are run automatically when the `app` container starts. This includes downloading the necessary ATLAS, OSM, and GTFS datasets. The downloaded data is stored in the project directory to avoid re-downloading on subsequent runs.

## Data Import (Handled by Docker Entrypoint)
The `import_data_db.py` script is run automatically after data acquisition to populate the database, unless `SKIP_DATA_IMPORT=true` is set (e.g., when using `docker compose up app-dev`).

## Running the Web Application (Handled by Docker Compose)
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
- **Manual Matching**: Select ATLAS & OSM pairs and click **Save** to record adjustments in `changes.json`.
- **API Endpoints**:
  - `GET /api/data` – viewport + filter parameters
  - `POST /api/save` – save manual matches
  - `GET /api/search` – keyword search
  - `GET /api/generate_report` – PDF report
  - `GET /api/route_stops` – stops for a route

## Generating Reports

The web app can generate CSV and PDF reports (still work in progress).

## Project Report

A draft of the project report is available [here](https://gitedu.hesge.ch/guillem.massague/bachelor-project/-/blob/main/DRAFT_projet_bachelor.pdf).

## Project Status

This project is a **work in progress**. Feedback and improvements are welcome!

## Contributing

Feel free to submit issues and pull requests. Thank you for your interest! 🚀

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| "TemplateNotFound" errors | Make sure you pulled the latest code: the Flask app is now configured to look for `templates/` at the repo root. Simply rebuilding the container (`docker compose build app-dev && docker compose up app-dev`) resolves this. |
| "Ports are not available" (`bind: address already in use`) | Another instance of the app is still running. Run `docker compose down` first or free port **5001**. |
| "Compromised" or inconsistent database | Run `docker compose down -v` to destroy the `mysql_data` volume and rebuild from scratch. |

### Line-ending issues on Windows
If you work on Windows, ensure that **shell scripts (`*.sh`) use LF line endings**.
The repo contains a `.gitattributes` file that enforces this, and the Docker build also runs `dos2unix` on every script just in case.
