# Changelog

All notable changes to this project will be documented in this page.

---

## Version 0.6

### Architecture

- **Independent matching engine** — Added the installable `engine/` package with source adapters, dataset profiles, offline tests, and a standalone CLI.
- **Versioned result boundary** — The engine now publishes validated result bundles; the review app imports them without importing engine code.
- **Atomic snapshot publication** — Imports build and validate a private PostGIS staging schema before switching the public snapshot transactionally.

### Performance and portability

- **Staged source caching** — ATLAS filtering, GTFS download/parsing, and GTFS-to-ATLAS mapping now invalidate independently; full runs continue to refresh OSM.
- **Large-feed GTFS processing** — The Swiss adapter uses DuckDB and reduced trip patterns before constructing Python itineraries.
- **Generic GTFS workflow** — Namespaced source identities and capability-driven review configuration support non-Swiss feeds without requiring SLOID or UIC identifiers.

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
