PYTHON ?= python3
ENGINE_ROOT ?= ../engine
ENGINE_PYTHON ?= /opt/engine-venv/bin/python
QUALITY_COMPOSE = docker compose -p osm-atlas-quality -f compose.quality.yml

.PHONY: dev quality-fast quality quality-ci quality-fast-container quality-down deploy-report

# Reconcile bind mounts with this checkout and enable Flask's source reloader.
dev:
	FLASK_DEBUG=1 docker compose up --build -d db migrator app

# Native fast checks use Python 3.13, Node 22, requirements-quality.txt and npm ci.
quality-fast:
	$(PYTHON) scripts/run_quality.py fast --engine-root "$(ENGINE_ROOT)"

# The supported complete local path includes a disposable PostGIS database.
quality:
	ENGINE_ROOT="$(ENGINE_ROOT)" $(QUALITY_COMPOSE) run --build --rm quality

quality-fast-container:
	ENGINE_ROOT="$(ENGINE_ROOT)" $(QUALITY_COMPOSE) run --build --rm --no-deps quality python scripts/run_quality.py fast --engine-root /workspace/engine

# CI supplies the same versions and disposable database without nesting Docker.
quality-ci:
	$(PYTHON) scripts/run_quality.py full --engine-root "$(ENGINE_ROOT)" --engine-python "$(ENGINE_PYTHON)"

quality-down:
	$(QUALITY_COMPOSE) down --volumes

# Before asking for a deployment: commit and push the passing CI report of the pushed HEAD.
deploy-report:
	$(PYTHON) scripts/deploy_report.py
