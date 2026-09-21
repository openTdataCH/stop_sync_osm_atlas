# Review Application Changelog

This page records notable changes to the review application, its database import,
browser interface and deployment. Matching releases are recorded separately in
the [matching engine changelog](../engine/documentation/Changelog.md).

Changes to the [result bundle contract](../engine/RESULT_FORMAT.md) are recorded
in both changelogs: here from the consumer side and in the engine changelog from
the producer side.

---

## Unreleased

### Reliability and interface

- **Race-safe pipeline status** — Scheduler startup no longer resets an active manual run, and shared status fields are patched atomically for both file and Redis backends.
- **Heartbeat recovery** — A live pipeline lease can recover the web view from an unfinished legacy status record incorrectly marked idle.
- **Orphaned-run recovery** — Pipeline leases now record process/container ownership and heartbeat time. A scheduler watchdog marks killed runners failed and releases their stale locks at startup or within the configured heartbeat grace period, so restarting services cannot leave the UI claiming a nonexistent background run.
- **Detailed live pipeline timeline** — The Data page always shows nine real workflow stages, including before the first analytics snapshot exists. Engine events distinguish source preparation, stop and route matching, bundle creation, database staging and the actual atomic publication; reused or skipped work is explicit, elapsed bars resize every second, and truncated labels expose their full text on hover or keyboard focus.
- **Self-describing pipeline substages** — A versioned stage plan now combines engine-owned matching work with app-owned database/publication work. The analytics UI generically renders persistent color-coded substage lists, preserves selection during polling, and accepts future engine stages without a frontend mapping change.
- **Complete stage timing records** — Reused and skipped stages now write timestamped, zero-duration history events, and compact UI timestamps explain whether they represent a stage start, reuse decision or skip decision. Legacy gaps remain unknown instead of being filled with fabricated times.

## Version 0.6.0

### Architecture

- **Versioned result consumption** — The application validates and imports versioned result bundles without importing matching-engine code.
- **Atomic snapshot publication** — Imports build and validate a private PostGIS staging schema before switching the public snapshot transactionally.

### Portability

- **Capability-driven review configuration** — Deployments can present non-Swiss result bundles without requiring SLOID- or UIC-specific interface features.

### Review application

- **Canonical documentation routes** — In-app documentation links use stable slugs instead of legacy filename URLs.
- **Local frontend assets** — Browser libraries are vendored under `static/vendor/` rather than loaded from public CDNs.

## Version 0.5

**Released:** July 30th 2026

### New Features
- **Search and filters on GTFS↔SLOID map**
- **See routes on the GTFS↔SLOID map popup** — Like on the main map

### Improvements

- **Consolidated frontend code** — Unified map and popup logic across the application.
- **File-backed runtime state** — The app and scheduler default to shared JSON files in `data/runtime`; Redis remains an optional state backend.
- **Updated documentation**
