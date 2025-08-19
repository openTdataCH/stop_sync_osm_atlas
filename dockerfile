# Use an official Python runtime as a parent image
# Use Debian bookworm to keep wkhtmltopdf available in apt
FROM python:3.9-slim-bookworm

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV FLASK_APP=backend/app.py
ENV FLASK_RUN_HOST=0.0.0.0
ENV FLASK_RUN_PORT=5001

# GDAL environment variables for GeoPandas installation
ENV CPLUS_INCLUDE_PATH=/usr/include/gdal
ENV C_INCLUDE_PATH=/usr/include/gdal

# Install system dependencies
# wkhtmltopdf for PDF generation
# mysql-client for mysqladmin in entrypoint script
# dos2unix to handle line ending issues
# GDAL and geospatial libraries for GeoPandas
RUN apt-get update && apt-get install -y --no-install-recommends \
    wkhtmltopdf \
    default-mysql-client \
    dos2unix \
    gdal-bin \
    libgdal-dev \
    libgeos-dev \
    libproj-dev \
    proj-data \
    proj-bin \
    libspatialindex-dev \
    libspatialindex6 \
    build-essential \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user and group to run the app (configurable at build time)
ARG APP_UID=1000
ARG APP_GID=1000
RUN groupadd -g ${APP_GID} app && \
    useradd -m -u ${APP_UID} -g ${APP_GID} -s /bin/bash app

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container at /app
COPY requirements.txt /app/

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entrypoint script first and fix it
COPY entrypoint.sh /app/entrypoint.sh
RUN dos2unix /app/entrypoint.sh && chmod +x /app/entrypoint.sh

# Copy the rest of the application code into the container at /app
COPY . /app/

# Tighten default permissions and prepare writable runtime dirs
RUN find /app -type d -exec chmod 755 {} \; && \
    find /app -type f -exec chmod 644 {} \; && \
    chmod 755 /app/entrypoint.sh && \
    mkdir -p /app/data /app/.cache && \
    chown -R app:app /app && \
    chmod 775 /app/data /app/.cache

# Drop privileges: run as non-root user
USER app

# Expose port 5001 for the Flask app
EXPOSE 5001

# Use the entrypoint script directly
ENTRYPOINT ["/bin/bash", "/app/entrypoint.sh"]