PYTHON ?= python3
QUALITY_COMPOSE = docker compose -p osm-atlas-quality -f compose.quality.yml

.PHONY: dev quality-fast quality quality-fast-container quality-down

# Reconcile bind mounts with this checkout and enable Flask's source reloader.
dev:
	FLASK_DEBUG=1 docker compose up --build -d db migrator app

# Set ENGINE_DIR for an external engine checkout (`make quality ENGINE_DIR=path`);
# Docker targets also read .env and default to ../engine on the host, while native tools default to engine/.

# Native fast checks use Python 3.13, Node 22, requirements.txt, requirements-dev.txt and npm ci.
quality-fast:
	$(PYTHON) scripts/run_quality.py fast

# The complete checks, locally and in CI: Python 3.13, Node 22 and a disposable PostGIS database in Docker.
quality:
	$(QUALITY_COMPOSE) run --build --rm quality

quality-fast-container:
	$(QUALITY_COMPOSE) run --build --rm --no-deps quality python scripts/run_quality.py fast --engine-dir /workspace/engine

quality-down:
	$(QUALITY_COMPOSE) down --volumes
