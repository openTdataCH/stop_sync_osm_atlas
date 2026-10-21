# Review application changelog

This page records notable changes to the review application, its database import,
browser interface and deployment. Matching releases are recorded separately in
the [matching engine changelog](../engine/documentation/Changelog.md).

Changes to the [result bundle contract](../engine/documentation/Result%20bundle%20format.md) are recorded
in both changelogs: here from the consumer side and in the engine changelog from
the producer side.

---

## Unreleased

### Result bundle

- **Source-neutral route records** — The importer reads the engine 0.2.0 bundle: `source_routes`, a `side` and stable `key` on families and itineraries, `source_stop_key`, `osm_node_id` and `station_ref` on stop calls, `source_line_family_id` and `source_itinerary_id` on matches, and the `unknown_source_stop_references` counter. `projection.py` maps them onto the existing tables, so no migration is needed. The `quality_metrics` many-to-one block (`source_to_multiple_osm`, `osm_to_multiple_source`) and the GTFS coverage counter `atlas.resolved_by_gtfs` use the engine's new names. Import a new bundle after upgrading.
- **Engine package renamed** — The engine is now the `public-transport-matcher` package and command. The default `MATCHER_COMMAND` follows; a deployment that sets `MATCHER_COMMAND=transport-matcher` in its `.env` must update it, together with `ENGINE_REF`.

### Operators

- **Simpler operator cards** — Each card now stacks the ATLAS operator above a breakdown of its matched OSM stops by `operator` value: a stacked bar plus one row per value, including a "Not tagged" row, so the counts add up to the total. `operator:wikidata` uses the same rows. A status pill (Consistent, Partly tagged, N different values, Not tagged) summarises each operator. The connector arrows, nested boxes and repeated labels are gone, and "See on map" buttons are now compact "Map" links.
- **Distinct stop counts** — "Matched" in the card header now counts distinct ATLAS stops, and the tag breakdown counts distinct OSM stops. Before, both counted match pairs, so an ATLAS stop matched to several OSM stops could make "matched" exceed the operator's stop total. See [A2.7 Colours and styles](2.7%20Colours%20and%20styles.md).

### Routes

- **Stored highest overlap for unmatched variants** — The import now computes, for every ATLAS and OSM itinerary, the itinerary of the other source sharing the most stops in order, and publishes it with the snapshot in the new `itinerary_best_overlaps` table. Route cards render the "Highest overlap" figure directly instead of scanning every itinerary after each page load (previously about 9 seconds for 20 unmatched OSM variants on the Swiss dataset). Variants without any shared stop now say so instead of showing an arbitrary 0% route. The batch endpoint `/api/routes/comparison/best` and the `best` field of `/api/routes/comparison/options` are removed. Run migrations, then import a bundle to fill the table. See [A2.6 Routes pages](2.6%20Routes%20Pages.md).

### Reliability and interface

- **Race-safe pipeline status** — Scheduler startup no longer resets an active manual run, and shared status fields are patched atomically for both file and Redis backends.
- **Heartbeat recovery** — A live pipeline lease can recover the web view from an unfinished legacy status record incorrectly marked idle.
- **Orphaned-run recovery** — Pipeline leases now record process/container ownership and heartbeat time. A scheduler watchdog marks killed runners failed and releases their stale locks at startup or within the configured heartbeat grace period, so restarting services cannot leave the UI claiming a nonexistent background run.
- **Detailed live pipeline timeline** — The Data page always shows the eight workflow phases, including before the first analytics snapshot exists. Engine events distinguish source preparation, stop and route matching, bundle creation, database staging and the actual atomic publication; reused or skipped work is explicit, elapsed bars resize every second, and truncated labels expose their full text on hover or keyboard focus.
- **Self-describing pipeline substages** — A versioned stage plan now combines engine-owned matching work with app-owned database/publication work. The analytics UI generically renders persistent color-coded substage lists, preserves selection during polling, and accepts future engine stages without a frontend mapping change.
- **Complete stage timing records** — Reused and skipped stages now write timestamped, zero-duration history events, and compact UI timestamps explain whether they represent a stage start, reuse decision or skip decision. Legacy gaps remain unknown instead of being filled with fabricated times.

### Documentation

- **Rewritten overview** — The introduction, architecture, import and scheduler pages are rewritten around a new [glossary](0.1%20Glossary.md), and every page now follows the [documentation style guide](Documentation%20style%20guide.md).
- **Generated diagrams** — Overview, architecture, deployment, publication and pipeline figures are SVGs generated from `documentation/diagrams/` with one shared visual vocabulary. `python3 documentation/diagrams/build.py` regenerates them, and the engine's figures as well.
- **Portal rendering fixes** — Automatic code links no longer alter code blocks, inline code or existing links; placeholders inside code stay literal; file names such as `build.py` no longer become `http://` links; wrapped source lines no longer break sentences; headings have stable anchors; navigation titles come from each page's heading. Links to engine source files need `DOCS_ENGINE_BLOB_BASE`, which Compose now passes to the web service, instead of producing 404s.
- **PDF fixes** — Links to sections of other pages resolve inside the PDF, section numbers are no longer doubled, and `#` comments in code blocks are no longer read as headings.

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
