#!/usr/bin/env bash

# Dispatches the action selected by a VS Code task input. Keeping the commands
# here makes the task picker a small, two-level menu without changing the
# commands developers already use.
set -euo pipefail

action="${1:?Expected a VS Code task action}"

case "$action" in
  web-debug) FLASK_DEBUG=1 docker compose up --build app ;;
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
  pipeline-scheduled-now)
    docker compose build migrator scheduler
    docker compose up -d db
    docker compose up -d --force-recreate migrator
    test "$(docker wait stop_sync_osm_atlas_migrator)" = "0"
    docker compose up -d scheduler
    docker exec stop_sync_osm_atlas_scheduler python -m backend.jobs.job_runner --mode full --trigger manual
    ;;
  test-all)
    docker compose build test
    docker compose run --rm --no-deps --entrypoint '' -e DATABASE_URI=sqlite:// -e USER_INPUT_DATABASE_URI=sqlite:// test python -m pytest tests/
    ;;
  test-result-contract)
    docker compose build test
    docker compose run --rm --no-deps --entrypoint '' -e DATABASE_URI=sqlite:// -e USER_INPUT_DATABASE_URI=sqlite:// test python -m pytest tests/test_result_bundle.py -v
    ;;
  docs-pdf) npm run docs:build-pdf ;;
  docs-er-diagram) docker exec stop_sync_osm_atlas_app python3 documentation/print_er_diagram/generate_er.py ;;
  sync-vendor-libraries) npm run vendor:sync ;;
  *)
    printf 'Unknown VS Code task action: %s\n' "$action" >&2
    exit 2
    ;;
esac
