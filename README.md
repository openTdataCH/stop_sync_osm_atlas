# **OSM & ATLAS Synchronization**


Welcome! This project provides a systematic pipeline to identify, analyze, and resolve discrepancies between public transport stop data from **ATLAS** (Swiss official data) and **OpenStreetMap (OSM)**.

It automates data download and processing (ATLAS, OSM, GTFS, HRDF), performs exact/fuzzy/route-based matching, and serves an interactive web app for inspecting matches, problems, and manual fixes.
![Geneva stops](documentation/images/Geneve.png)
---

## Quick Start

**Just want to run it?** Here's the fastest path:

1. **Clone the repository**
   ```bash
   git clone https://github.com/openTdataCH/stop_sync_osm_atlas.git
   cd bachelor-project
   ```

2. **Build and start everything**
   ```bash
   docker compose up --build
   ```
    This will:
   - Download and set up the MySQL database (persisted in a Docker **volume**)
    - Download ATLAS, OSM, and GTFS data automatically (cached under `./data`)
    - Process and match the data
    - Start the web application at [http://localhost:5001](http://localhost:5001)

    The matching process run typically takes 10–20 minutes.

3. **Development shortcut** (skip heavy data processing):
   ```bash
   docker compose up app-dev
   ```
    Use this after you've done a full run at least once. It starts the app without re-running the data pipeline.

4. **Stop & clean-up**
   ```bash
   # Stop containers
   docker compose down

   # Optional – ⚠️ wipe the database completely (destroys the Docker volume)
   docker compose down -v
   ```
    If you ever experience database corruption or want a fresh start, use the second command. It removes the `mysql_data` volume so the next run re-initializes the database.

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

This project delivers a robust methodology and tooling to match public transport stops across two datasets:

- **ATLAS**: The official Swiss traffic-points dataset (boarding platforms).
- **OSM**: OpenStreetMap public-transport nodes.

It identifies exact and fuzzy matches, computes geographic distances, performs route-based matching (GTFS/HRDF), and exposes an interactive UI to inspect and manually correct mismatches.

## Prerequisites

- **Docker Desktop** with Compose v2 (required)
- Internet connection to download datasets (ATLAS, OSM, GTFS)
- **Optional**: Python 3.9+ and MySQL 8 for local development without Docker

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

    **Development Mode (Skip Data Processing):**
    ```bash
    docker compose up app-dev
    ```
    Use this when the database is already populated and you want to iterate on the web application without re-running the pipeline.

3.  **Access the application**:
    - Web app: [http://localhost:5001](http://localhost:5001)
    - MySQL database: `localhost:3306` (user: `stops_user`, password: `1234`)

4.  **To stop the services**:
    ```bash
    docker compose down
    ```
    To remove all data: `docker compose down -v`

## Database Setup (Handled by Docker Compose)
The `docker-compose.yml` configuration initializes MySQL on the first run using `database_setup.sql` (mounted into the MySQL init directory). It creates:

- `stops_db` (analytical data)
- `auth_db` (authentication tables)
- User `stops_user` with access to both databases

Initialization scripts are executed only when the MySQL data directory is empty. Because the MySQL data lives in the `mysql_data` Docker volume, subsequent runs will reuse the existing databases without re-running the SQL.

## Data Acquisition (Handled by Docker Entrypoint)
When the `app` container starts (and data import is not skipped), the entrypoint runs:

- `get_atlas_data.py`: downloads ATLAS data and GTFS, builds optimized route/stop artifacts
- `get_osm_data.py`: fetches OSM data via Overpass and processes it

Downloads are cached under `data/raw/` and processed artifacts under `data/processed/` to avoid re-downloading and to speed up subsequent runs. See `documentation/DATA_ORGANIZATION.md` for details.

## Data Import (Handled by Docker Entrypoint)
After acquisition, `import_data_db.py` populates the MySQL databases (e.g., `stops`, `problems`, `persistent_data`, `atlas_stops`, `osm_nodes`, `routes_and_directions`).

Set `SKIP_DATA_IMPORT=true` (the `app-dev` service already does this) to bypass acquisition/import when you only want to run the web app against an existing database.

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

