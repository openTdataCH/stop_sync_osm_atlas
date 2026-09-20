# Review Application Changelog

This page records notable changes to the review application, its database import,
browser interface and deployment. Matching releases are recorded separately in
the [matching engine changelog](../engine/documentation/Changelog.md).

Changes to the [result bundle contract](../engine/RESULT_FORMAT.md) are recorded
in both changelogs: here from the consumer side and in the engine changelog from
the producer side.

---

## Version 0.6

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
