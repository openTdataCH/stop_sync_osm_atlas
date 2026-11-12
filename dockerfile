# syntax=docker/dockerfile:1
FROM node:22-bookworm-slim AS docs-diagram-stage
ENV PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends chromium \
    && rm -rf /var/lib/apt/lists/*
COPY package.json package-lock.json ./
RUN npm ci
COPY scripts/render_docs_mermaid.mjs ./scripts/render_docs_mermaid.mjs
COPY documentation ./documentation
# ``engine`` is a named build context supplied by Compose (or with
# ``docker build --build-context engine=...``). The review app never vendors
# or imports the engine package, but publishes the docs from the same checkout
# that is installed in the scheduler image.
COPY --from=engine /documentation ./engine/documentation
COPY --from=engine /pyproject.toml ./engine/pyproject.toml
RUN npm run docs:render-mermaid

FROM python:3.13-slim-bookworm AS app-stage
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
ARG APP_UID=1000
ARG APP_GID=1000
RUN groupadd -g ${APP_GID} app && useradd -m -u ${APP_UID} -g ${APP_GID} -s /bin/bash app
# Pango and HarfBuzz are the system libraries WeasyPrint draws the PDFs with (its own Debian list).
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
ENV FLASK_APP=backend/app.py FLASK_RUN_HOST=0.0.0.0 FLASK_RUN_PORT=5001
# Web image contains no engine source or engine dependencies. It includes the
# engine-owned Markdown so the site can present one unified documentation portal.
COPY --chown=app:app backend ./backend
COPY --chown=app:app templates ./templates
COPY --chown=app:app static ./static
COPY --chown=app:app migrations ./migrations
COPY --chown=app:app config ./config
COPY --chown=app:app documentation ./documentation
COPY --from=engine --chown=app:app /documentation ./engine/documentation
COPY --from=engine --chown=app:app /pyproject.toml ./engine/pyproject.toml
COPY --from=docs-diagram-stage --chown=app:app /app/documentation/generated/diagrams ./documentation/generated/diagrams
COPY --chown=app:app README.md LICENSE entrypoint.sh engine.ref ./
RUN mkdir -p data .cache && chown app:app data .cache && chmod +x entrypoint.sh
USER app
EXPOSE 5001
ENTRYPOINT ["/bin/bash", "/app/entrypoint.sh"]

# Deployment composition: jobs invoke a separately installed engine executable.
# No Python imports connect the app to the engine.
FROM app-stage AS scheduler-stage
USER root
COPY --from=engine / /opt/osm-public-transport-matcher
RUN pip install --no-cache-dir '/opt/osm-public-transport-matcher[swiss,acquisition]' \
    && osm-public-transport-matcher --help > /dev/null
USER app
