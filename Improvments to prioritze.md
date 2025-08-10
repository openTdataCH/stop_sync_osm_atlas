## Improvements to prioritize

This document lists the most important issues to address in the app, why they matter, and what to do about them. It focuses on security, correctness, performance, and maintainability. Explanations are kept clear and non‑technical where possible.

### 1) Secrets and configuration (security)
- What: Database usernames/passwords are hardcoded in code and docker files (e.g., `stops_user:1234`), and the database port is exposed.
- Why it’s a problem: Anyone who gets access to the repo or network can use those credentials. Hardcoded secrets tend to leak. Exposed DB ports are reachable and invite brute‑force attempts.
- What to do:
  - Use environment variables or a secrets manager for DB credentials and other secrets.
  - Use strong passwords. Don’t expose DB ports in production (no `ports: 3306:3306`).
  - Separate dev and prod configurations so dev convenience does not affect prod security.

### 2) Debug server enabled (security & stability)
- What: The Flask app runs with `debug=True` and binds to all interfaces.
- Why it’s a problem: The debugger can expose internals and even allow code execution if reachable. Also, the dev server isn’t designed for production.
- What to do:
  - Turn off debug in production and run behind a production WSGI server (e.g., gunicorn or uWSGI).

### 3) No authentication/authorization on write endpoints (security)
- What: Endpoints that change data (saving solutions/notes, clearing data, making everything persistent) are open to anyone.
- Why it’s a problem: Unauthenticated users can modify or delete data.
- What to do:
  - Require authentication (e.g., login, API keys) and restrict actions to authorized roles.
  - Add CSRF protection for browser‑based POST requests.

### 4) Cross‑site scripting (XSS) risks in the frontend (security)
- What: Popup HTML is built by concatenating strings and injected via `innerHTML`, with inline `onclick` handlers.
- Why it’s a problem: If a name/operator/ID contains HTML, it can execute scripts in the user’s browser.
- What to do:
  - Escape all dynamic text before injecting into the DOM.
  - Avoid inline `onclick`. Use `addEventListener` bindings.
  - Prefer building DOM nodes with `document.createElement` instead of big HTML strings.
  - Add a Content Security Policy (CSP) that disallows inline scripts.

### 5) Model ↔ schema drift (correctness)
- What: The code expected a `manual_is_persistent` column on `stops` but it wasn’t in the SQL schema.
- Why it’s a problem: Mismatches cause runtime errors and data not being saved/loaded as expected.
- What to do:
  - Keep models and schema in sync. We added the missing column in `database_setup.sql`.
  - Introduce database migrations (Alembic) to manage changes safely over time.

### 6) Conflicting database URI configuration (correctness)
- What: `backend/app.py` sets a database URI, then `init_db` in `backend/models.py` overwrites it from env again.
- Why it’s a problem: Confusing and error‑prone; you may connect to a different DB than you think.
- What to do:
  - Remove the override in `init_db` and trust the app’s config. Have one source of truth for configuration.

### 7) Inefficient random selection (performance)
- What: Random stop used `ORDER BY RAND()`, which forces the database to sort many rows.
- Why it’s a problem: Slow on large tables and wastes resources.
- What we changed:
  - Use a simple approach: count rows, pick a random offset, fetch one row.

### 8) N+1 query patterns (performance)
- What: Some code fetches related rows in loops (e.g., per‑item queries in `Problem.to_dict`).
- Why it’s a problem: Many small queries are slower than one properly joined query.
- What to do:
  - Use eager loading (`joinedload`) to pull related data in one go, or restructure serialization to use already joined data.

### 9) Heavy in‑memory grouping for duplicates (performance)
- What: Duplicates are grouped in Python after loading many rows.
- Why it’s a problem: High memory and CPU usage, harder to paginate.
- What to do:
  - Move grouping into SQL (e.g., `GROUP BY uic_ref, local_ref`), or precompute and store duplicate groups during import so the API can read them quickly.

### 10) Text search with multiple `%LIKE%` filters (performance & UX)
- What: Free‑text search matches across many columns using wildcard patterns.
- Why it’s a problem: Such queries don’t use indexes well and can be slow.
- What to do:
  - Add full‑text indexes or use a lightweight search service. If staying in MySQL, consider full‑text indexes on relevant columns and adjust queries.

### 11) JSON fields queried with functions (performance)
- What: Queries like `json_search` over JSON columns for routes.
- Why it’s a problem: JSON function scans are slow and not easily indexable.
- What to do:
  - Normalize frequently queried JSON into relational tables with proper indexes (e.g., a table for route membership per stop and direction).

### 12) Caching hot reads (performance)
- What: Endpoints like `/api/operators`, route lookups, and popups are read often.
- Why it’s a problem: Recomputing results on every request adds latency and DB load.
- What to do:
  - Add short‑TTL caching (in‑memory or Redis) for common queries.

### 13) Report generation safety (security)
- What: `pdfkit` runs a headless browser to render HTML to PDF.
- Why it’s a problem: If untrusted data reaches the template, scripts or external requests could run during PDF rendering.
- What to do:
  - Sanitize template data. Use wkhtmltopdf flags to disable JavaScript and network access where possible.

### 14) Observability (operational)
- What: Limited structured logs and metrics.
- Why it’s a problem: Hard to troubleshoot and measure performance.
- What to do:
  - Add structured logging (JSON), request IDs, timing logs, and basic metrics for query times and cache hit rates.

### 15) Tests and CI
- What: There aren’t automated tests/linting in CI.
- Why it’s a problem: Changes can break features without early detection; style drifts.
- What to do:
  - Add unit tests for endpoints and query building. Use a seed DB for tests. Add lint (ruff/flake8) and type checks (mypy) in CI.

### 16) Production deployment hygiene
- What: Dev settings in Docker compose, DB port exposed, no WSGI server.
- Why it’s a problem: Security and performance risk in prod.
- What to do:
  - Create separate compose files/profiles for prod; remove DB port publishing; run gunicorn; use non‑root DB users; enforce least privilege.

### 17) Duplicates computation alignment (roadmap)
- What: Duplicates are computed at request time.
- Why it’s a problem: Slower responses and inconsistent grouping.
- What to do:
  - Compute duplicates during data import and persist them, then expose via API/UI. This matches the planned work and scales better.


