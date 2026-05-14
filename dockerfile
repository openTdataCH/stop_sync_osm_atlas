# syntax=docker/dockerfile:1
# Use an official Python runtime as a parent image
FROM python:3.13-slim-bookworm AS base

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install system dependencies shared by both
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-pip \
    dos2unix \
    graphviz \
    libgraphviz-dev \
    build-essential \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Create a non-root user and group
ARG APP_UID=1000
ARG APP_GID=1000
RUN groupadd -g ${APP_GID} app && \
    useradd -m -u ${APP_UID} -g ${APP_GID} -s /bin/bash app

WORKDIR /app

# Copy base requirements
COPY requirements-base.txt /app/
RUN pip install --no-cache-dir -r requirements-base.txt

# Base permissions helper
RUN mkdir -p /app/data /app/.cache && \
    chown -R app:app /app && \
    chmod 775 /app/data /app/.cache

# ==========================================
# WEB APP STAGE
# ==========================================
FROM base AS app-stage

# Web system dependencies (weasyprint, cairo, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-cffi libcairo2 libpango-1.0-0 libpangocairo-1.0-0 \
    libgdk-pixbuf2.0-0 libffi-dev shared-mime-info \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY requirements-web.txt /app/
RUN pip install --no-cache-dir -r requirements-web.txt

ENV FLASK_APP=backend/app.py \
    FLASK_RUN_HOST=0.0.0.0 \
    FLASK_RUN_PORT=5001

COPY entrypoint.sh /app/entrypoint.sh
RUN dos2unix /app/entrypoint.sh && chmod +x /app/entrypoint.sh

# Copy code
COPY . /app/
# Ensure permissions are correct and app user owns it
RUN find /app -type d -exec chmod 755 {} \; && \
    find /app -type f -exec chmod 644 {} \; && \
    chmod 755 /app/entrypoint.sh && \
    chown -R app:app /app

USER app
EXPOSE 5001
ENTRYPOINT ["/bin/bash", "/app/entrypoint.sh"]

# ==========================================
# TEST STAGE
# ==========================================
FROM app-stage AS test-stage

USER root

# Include scheduler geospatial stack so pipeline tests can run in one image.
ENV CPLUS_INCLUDE_PATH=/usr/include/gdal
ENV C_INCLUDE_PATH=/usr/include/gdal

RUN apt-get update && apt-get install -y --no-install-recommends \
    gdal-bin libgdal-dev libgeos-dev libproj-dev \
    proj-data proj-bin libspatialindex-dev \
    libspatialindex6 build-essential \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY requirements-scheduler.txt /app/
COPY requirements-test.txt /app/
RUN pip install --no-cache-dir -r requirements-scheduler.txt -r requirements-test.txt

USER app

# ==========================================
# SCHEDULER STAGE
# ==========================================
FROM base AS scheduler-stage

# GDAL environment variables for GeoPandas
ENV CPLUS_INCLUDE_PATH=/usr/include/gdal
ENV C_INCLUDE_PATH=/usr/include/gdal

# Scheduler system dependencies (GDAL, Geos, Proj)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gdal-bin libgdal-dev libgeos-dev libproj-dev \
    proj-data proj-bin libspatialindex-dev \
    libspatialindex6 build-essential \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY requirements-scheduler.txt /app/
RUN pip install --no-cache-dir -r requirements-scheduler.txt

COPY entrypoint.sh /app/entrypoint.sh
RUN dos2unix /app/entrypoint.sh && chmod +x /app/entrypoint.sh

# Copy code
COPY . /app/
# Ensure permissions are correct and app user owns it
RUN find /app -type d -exec chmod 755 {} \; && \
    find /app -type f -exec chmod 644 {} \; && \
    chmod 755 /app/entrypoint.sh && \
    chown -R app:app /app

USER app
ENTRYPOINT ["/bin/bash", "/app/entrypoint.sh"]