#!/bin/bash
# Local test runner that mirrors the GitHub Actions workflow
# This script runs the same tests that run in CI/CD using Docker

set -e  # Exit on error

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Running Tests Locally (Docker-based)${NC}"
echo -e "${BLUE}========================================${NC}\n"

# Build the Docker image first
echo -e "${GREEN}Building Docker image...${NC}"
docker-compose build app-dev

# Function to run tests in container
run_in_container() {
    docker-compose run --rm app-dev bash -c "$1"
}

# 1. JavaScript Tests
echo -e "\n${GREEN}========================================${NC}"
echo -e "${GREEN}Running JavaScript Tests...${NC}"
echo -e "${GREEN}========================================${NC}"
run_in_container "npm ci && npm test -- --coverage --ci"

# 2. Python Lint
echo -e "\n${GREEN}========================================${NC}"
echo -e "${GREEN}Running Python Lint...${NC}"
echo -e "${GREEN}========================================${NC}"

# Install linting tools and run checks
run_in_container "pip install flake8 black isort && \
    echo 'Running flake8 (critical errors)...' && \
    flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics && \
    echo 'Running flake8 (all checks)...' && \
    flake8 . --count --exit-zero --max-complexity=10 --max-line-length=120 --statistics && \
    echo 'Checking formatting with black...' && \
    black --check --diff . ; \
    echo 'Checking import sorting with isort...' && \
    isort --check-only --diff ."

# 3. Python Tests
echo -e "\n${GREEN}========================================${NC}"
echo -e "${GREEN}Running Python Tests...${NC}"
echo -e "${GREEN}========================================${NC}"

# Set up environment and run pytest
run_in_container "pip install pytest pytest-cov && \
    FLASK_ENV=testing \
    TESTING=true \
    DATABASE_URI='sqlite:///:memory:' \
    AUTH_DATABASE_URI='sqlite:///:memory:' \
    SECRET_KEY='test-secret-key' \
    pytest tests/ --cov=matching_process --cov=backend --cov-report=xml --cov-report=html -v"

echo -e "\n${GREEN}========================================${NC}"
echo -e "${GREEN}All tests completed successfully! ✓${NC}"
echo -e "${GREEN}========================================${NC}"
echo -e "\nCoverage reports available:"
echo -e "  - JavaScript: ./coverage/"
echo -e "  - Python: ./htmlcov/"
