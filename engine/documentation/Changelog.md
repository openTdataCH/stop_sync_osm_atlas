# Matching Engine Changelog

This page records notable changes to the standalone `transport-matcher` package,
its adapters, matching behavior, result production and command-line interface.
Review-application releases are recorded separately in the
[review application changelog](../../documentation/Changelog.md).

Changes to the [result bundle contract](../RESULT_FORMAT.md) are recorded in both
changelogs: here from the producer side and in the application changelog from the
consumer side.

---

## Version 0.1.0

Initial independent release extracted from the original Stop Sync OSM Atlas
pipeline.

### Added

- **Standalone package and CLI** — Added an installable Python package with source adapters, dataset profiles, offline tests and the `transport-matcher` command.
- **Generic GTFS workflow** — Added namespaced source identities and matching profiles so feeds can be processed without SLOID or UIC identifiers.
- **Independent result production** — Matching runs now write complete, validated result bundles without Flask, SQLAlchemy, PostGIS or review-application imports.
- **Explicit integration boundary** — Added a public external-adapter contract and a first-party Swiss integration entry point. Generic GTFS route products now use `source_*` names internally while schema 1 retains its deprecated legacy field names at the serialization boundary.
- **Separated OSM acquisition and parsing** — Overpass network access, normalized OSM element parsing and PTv2 route-product parsing now live in separate modules; the former combined module remains as a compatibility shim.

### Performance

- **Staged source caching** — ATLAS filtering, GTFS download and parsing, and GTFS-to-ATLAS mapping invalidate independently; full Swiss runs continue to refresh OSM.
- **Large-feed GTFS processing** — The Swiss adapter uses DuckDB and reduced trip patterns before constructing Python itineraries.

### Compatibility

- **Versioned result contract** — Version 1 bundles carry manifests, checksums and explicit source identities for independent consumers. The corresponding application-side change is recorded in the [review application changelog](../../documentation/Changelog.md).
