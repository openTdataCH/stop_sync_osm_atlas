#!/usr/bin/env bash

# Dispatches the action selected by a VS Code task input. Keeping the commands
# here makes the task picker a small, two-level menu without changing the
# commands developers already use.
set -euo pipefail

# Resolve Compose and bind mounts from this checkout, including when the task
# is launched from the parent multi-repository workspace.
app_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$app_root"

action="${1:?Expected a VS Code task action}"

case "$action" in
  web-debug) make dev ;;
  web-gunicorn) FLASK_DEBUG=0 docker compose up --build app ;;
  web-db-upgrade)
    docker compose build migrator app
    docker compose up -d db
    docker compose up -d --force-recreate migrator
    test "$(docker wait stop_sync_osm_atlas_migrator)" = "0"
    docker compose up -d app
    ;;
  web-regenerate-stats) docker exec stop_sync_osm_atlas_app python scripts/regenerate_stats.py ;;
  pipeline-existing-data)
    docker compose build migrator app scheduler
    docker compose up -d db
    docker compose up -d --force-recreate migrator
    test "$(docker wait stop_sync_osm_atlas_migrator)" = "0"
    docker compose up -d app scheduler
    docker exec stop_sync_osm_atlas_scheduler python -m backend.jobs.job_runner --mode match-import --trigger manual
    ;;
  pipeline-full)
    docker compose build migrator app scheduler
    docker compose up -d db
    docker compose up -d --force-recreate migrator
    test "$(docker wait stop_sync_osm_atlas_migrator)" = "0"
    docker compose up -d app scheduler
    docker exec stop_sync_osm_atlas_scheduler python -m backend.jobs.job_runner --mode full --trigger manual
    ;;
  pipeline-force-refresh)
    docker compose build migrator app scheduler
    docker compose up -d db
    docker compose up -d --force-recreate migrator
    test "$(docker wait stop_sync_osm_atlas_migrator)" = "0"
    docker compose up -d app scheduler
    docker exec -e PIPELINE_FORCE_FULL_REFRESH=true stop_sync_osm_atlas_scheduler python -m backend.jobs.job_runner --mode full --trigger manual
    ;;
  quality-fast) make quality-fast-container ;;
  quality) make quality ;;
  docs-pdf) npm run docs:build-pdf ;;
  docs-diagrams) npm run docs:diagrams ;;
  sync-vendor-libraries) npm run vendor:sync ;;
  *)
    printf 'Unknown VS Code task action: %s\n' "$action" >&2
    exit 2
    ;;
esac
