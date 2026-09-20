# syntax=docker/dockerfile:1
FROM python:3.13-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
ARG APP_UID=1000
ARG APP_GID=1000
RUN groupadd -g ${APP_GID} app && useradd -m -u ${APP_UID} -g ${APP_GID} -s /bin/bash app
COPY requirements-base.txt ./
RUN pip install --no-cache-dir -r requirements-base.txt

FROM base AS app-stage
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 libpangocairo-1.0-0 libcairo2 libgdk-pixbuf2.0-0 \
    shared-mime-info graphviz && rm -rf /var/lib/apt/lists/*
COPY requirements-web.txt ./
RUN pip install --no-cache-dir -r requirements-web.txt
ENV FLASK_APP=backend/app.py FLASK_RUN_HOST=0.0.0.0 FLASK_RUN_PORT=5001
# Web image contains no engine source or engine dependencies.
COPY --chown=app:app backend ./backend
COPY --chown=app:app templates ./templates
COPY --chown=app:app static ./static
COPY --chown=app:app migrations ./migrations
COPY --chown=app:app config ./config
COPY --chown=app:app documentation ./documentation
COPY --chown=app:app README.md LICENSE entrypoint.sh ./
RUN mkdir -p data .cache && chown app:app data .cache && chmod +x entrypoint.sh
USER app
EXPOSE 5001
ENTRYPOINT ["/bin/bash", "/app/entrypoint.sh"]

FROM app-stage AS test-stage
USER root
COPY requirements-test.txt requirements-scheduler.txt ./
RUN pip install --no-cache-dir -r requirements-test.txt -r requirements-scheduler.txt
COPY --chown=app:app tests ./tests
COPY requirements-base.txt requirements-web.txt ./
USER app

# Deployment composition: jobs invoke a separately installed engine executable.
# No Python imports connect the app to the engine.
FROM app-stage AS scheduler-stage
USER root
COPY requirements-scheduler.txt ./
RUN pip install --no-cache-dir -r requirements-scheduler.txt
COPY engine /opt/transport-matcher
RUN pip install --no-cache-dir '/opt/transport-matcher[swiss,acquisition]' \
    && transport-matcher --help > /dev/null
USER app
