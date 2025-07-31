# Use an official Python runtime as a parent image
FROM python:3.9-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV FLASK_APP=backend/app.py
ENV FLASK_RUN_HOST=0.0.0.0
ENV FLASK_RUN_PORT=5001

# Install system dependencies
# wkhtmltopdf for PDF generation
# mysql-client for mysqladmin in entrypoint script
# dos2unix to handle line ending issues
RUN apt-get update && apt-get install -y --no-install-recommends \
    wkhtmltopdf \
    default-mysql-client \
    dos2unix \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

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

# Expose port 5001 for the Flask app
EXPOSE 5001

# Use the entrypoint script directly
ENTRYPOINT ["/bin/bash", "/app/entrypoint.sh"]