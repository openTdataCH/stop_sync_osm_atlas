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
- **Disused OSM elements** — The bundle reader accepts the optional `disused` flag on OSM `unmatched` rows and checks it against `lifecycle`, the unmatched-problem coverage and `disused` problems. The importer stores disused elements as `osm_disused` map entries outside the stop units and counts, and keeps every tag of each OSM element in `osm_nodes.osm_tags`. The map has an "OSM disused" filter and draws them as grey hollow rings with a `U`; the Problems page, problem statistics and exports gain the `disused` type; OSM popups list all tags. Migration `20261030_000008` adds `osm_lifecycle` and `osm_tags`; run migrations, then import a bundle to fill them. See [A1.1 Bundle import and publication](1.1%20Import%20Process.md#disused-osm-elements).

### Operators

- **Simpler operator cards** — Each card now stacks the ATLAS operator above a breakdown of its matched OSM stops by `operator` value: a stacked bar plus one row per value, including a "Not tagged" row, so the counts add up to the total. `operator:wikidata` uses the same rows. A status pill (Consistent, Partly tagged, N different values, Not tagged) summarises each operator. The connector arrows, nested boxes and repeated labels are gone, and "See on map" buttons are now compact "Map" links.
- **Distinct stop counts** — "Matched" in the card header now counts distinct ATLAS stops, and the tag breakdown counts distinct OSM stops. Before, both counted match pairs, so an ATLAS stop matched to several OSM stops could make "matched" exceed the operator's stop total. See [A2.7 Colours and styles](2.7%20Colours%20and%20styles.md).

### Routes

- **Stored highest overlap for unmatched variants** — The import now computes, for every ATLAS and OSM itinerary, the itinerary of the other source sharing the most stops in order, and publishes it with the snapshot in the new `itinerary_best_overlaps` table. Route cards render the "Highest overlap" figure directly instead of scanning every itinerary after each page load (previously about 9 seconds for 20 unmatched OSM variants on the Swiss dataset). Variants without any shared stop now say so instead of showing an arbitrary 0% route. The batch endpoint `/api/routes/comparison/best` and the `best` field of `/api/routes/comparison/options` are removed. Run migrations, then import a bundle to fill the table. See [A2.6 Routes pages](2.6%20Routes%20Pages.md).
- **Paired route details** — On a matched route, opening the ATLAS or the OSM details card opens the other one too, so both attribute lists sit side by side for comparison. The two cards keep the same height. Cards of unmatched routes still open on their own.

### Public API

- **Stop lookup for scripts and AI agents** — `/api/lookup` returns every match of a stop as JSON, with distances, match types, problems, OSM tags and the snapshot's attribution. It takes the permalink identifiers (`osm=node/<id>`, `osm=way/<id>`, `sloid=`) plus `uic_ref=` for a whole station, never database row numbers, and it is the only `/api/` endpoint whose fields are kept stable. See [A2.10 Public API](2.10%20Public%20API.md).
- **Stop links readable without JavaScript** — Map and Problems links with `sloid` or `osm` name the stop in their title, description and `og:` tags, link to its lookup and carry a visually hidden summary, so link previews and fetch tools see the stop.
- **`/llms.txt` and `robots.txt`** — A new `/llms.txt` explains the site and the lookup to AI agents. `robots.txt` allows `/api/lookup` and puts its most specific rule first, so parsers that apply the first matching rule no longer read `Allow: /` as permission for every `/api/` path.

### Reliability and interface

- **Clearer analytics sections** — The sections after the pipeline on `/data/analytics` lose their nested cards and coloured tile borders: each topic is one block with uncoloured key figures, compact tables and label/value lists. Bars use ATLAS navy and OSM green, and only priorities use red, orange and grey. Percentages and distances have one decimal, and repeated headings are gone. The section menu now follows jumps such as the End key, the scrollbar or a reload part-way down the page. The statistics PDF uses the same layout, and its problem table now shows the counts per priority instead of zeros. Route contradictions get their own row, so the rows of each priority add up to its total. See [A2.7](2.7%20Colours%20and%20styles.md#analytics).
- **Analytics by source** — `/data/analytics` has the sections Stop matching, Unmatched, Route matching, Problems, ATLAS stops, Swiss GTFS, OSM stops and OSM routes, and every figure names its unit: OSM elements, stop units, lines or itineraries. OSM stops covers geometry (element types, nodes and ways, stop units), groups by type with their match state, and tag coverage for identifiers, operator and network, and amenities, per platform and stop position. Route matching shows the link count once, since lines and itineraries are linked one to one, then the coverage of each side by mode, why GTFS and OSM lines stay unlinked, and itinerary links within linked lines. Swiss GTFS splits stop ID resolution into platforms, stops and parent stations, and reports the stop IDs that trips use. ATLAS stops shows the filter steps from the download to the platforms and counts duplicates in SLOIDs. Unmatched OSM elements leave out trio middles, which count as matched. `backend/services/dataset_stats.py` computes the per-source sections from the published tables, so `scripts/regenerate_stats.py` refreshes them too. See [A1.2](1.2%20Stats%20and%20timestamps.md#the-sections-of-statsjson).
- **SQL NULL for absent JSON values** — `duplicate_group_sloids`, `duplicate_group_node_ids`, `osm_tags` and `details_json` store an absent value as SQL `NULL`, on both the COPY and the insert path, so `IS NOT NULL` selects exactly the rows with a value. See [A1](1.%20Database.md#stops-and-identities).
- **Simpler export form** — `/data/export` is one form that fits a desktop screen without scrolling. The three export types are cards on the left, and the chosen one shows its own options (sources, problem types, priorities), so switching type does not move the rest of the form. ATLAS operators and the output settings sit on the right, and the operator list opens over the form. The summary and the download button sit in a bar that stays in view, and the daily limit is a note beside the button instead of a banner. The page heading and the "Stats computed" time are gone: the Export tab already names the page, and the time belongs to `/data/analytics`.
- **Race-safe pipeline status** — Scheduler startup no longer resets an active manual run, and shared status fields are patched atomically for both file and Redis backends.
- **Heartbeat recovery** — A live pipeline lease can recover the web view from an unfinished legacy status record incorrectly marked idle.
- **Orphaned-run recovery** — Pipeline leases now record process/container ownership and heartbeat time. A scheduler watchdog marks killed runners failed and releases their stale locks at startup or within the configured heartbeat grace period, so restarting services cannot leave the UI claiming a nonexistent background run.
- **Detailed live pipeline timeline** — The Data page always shows the eight workflow phases, including before the first analytics snapshot exists. Engine events distinguish source preparation, stop and route matching, bundle creation, database staging and the actual atomic publication; reused or skipped work is explicit, elapsed bars resize every second, and truncated labels expose their full text on hover or keyboard focus.
- **Self-describing pipeline substages** — A versioned stage plan now combines engine-owned matching work with app-owned database/publication work. The analytics UI generically renders persistent color-coded substage lists, preserves selection during polling, and accepts future engine stages without a frontend mapping change.
- **Complete stage timing records** — Reused and skipped stages now write timestamped, zero-duration history events, and compact UI timestamps explain whether they represent a stage start, reuse decision or skip decision. Legacy gaps remain unknown instead of being filled with fabricated times.
- **Engine pinned in the repository** — The committed `engine.ref` holds the engine commit the app is built and tested with. CI, `scripts/verify_engine_checkout.sh` and the documentation's engine source links read it, so upgrading the engine is a one-line commit. `ENGINE_REPO`, `ENGINE_REF` and `DOCS_ENGINE_BLOB_BASE` in `.env`, and the CI variable and token, are no longer used; remove them.

### Code quality

- **Code quality dashboard** — `/quality` draws the module map of both repositories: how the modules' code depends on each other, which dependencies the module catalog does not declare, which modules depend on each other both ways and which private names cross a module border. Opening a module shows its files, with the modules that use it on one side and the modules it uses on the other. The evidence table and required checks follow. `make deploy-report` now also publishes the code map the dashboard draws. See [A4.3](4.3%20Code%20Quality.md#read-the-dashboard).
- **Calls between files in the code map** — The map resolves Python calls through imports and re-exports, and counts a browser script's top-level names used by other scripts. Importing a submodule no longer counts as importing its package's `__init__.py`.
- **Clearer report columns** — "Risk" is now "Criticality", defined by a [rubric](4.3%20Code%20Quality.md#criticality) on the impact of a module's worst defect. "Clones" is now "Duplicated blocks". The "Trend" column, which had no data, is removed.

### Documentation

- **Quality guide in the documentation** — The quality guide moved from `quality/README.md` into [A4.3 Code quality](4.3%20Code%20Quality.md), for reading the results, and [A4.4 Running the quality checks](4.4%20Running%20Quality%20Checks.md), for running and maintaining them. Links no longer send readers to GitHub.
- **Easier portal navigation** — The sidebar shows page numbers as plain grey text instead of coloured pills and collection headings in small capitals with their version, and highlights only the page being read. A faint colour marks each page's owner: a dot beside collections and page headers and the tint of the highlighted page, green for the engine, navy for the review application and purple for the shared overview. Long titles wrap instead of being cut off. Collection descriptions no longer appear on hover; the [project overview](0.%20Intro.md#how-to-read-this-documentation) describes the collections. A filter box (press `/`) narrows the sidebar. Each page opens with its collection and number above a plain title. "On this page" lists the page's sections beside the article on wide screens and above it on narrow ones. Inline code across the site takes the colour of its text instead of red. See [A2.8](2.8%20Documentation%20Page%20Delivery.md#full-pages-and-partial-updates).
- **PDF of a single page** — The PDF dialog offers this page, the whole documentation or chosen sections. A page's "Download PDF" link opens it on that page, which downloads alone as `<address>.pdf`; the link at the bottom of the sidebar opens it on the whole documentation. The dialog replaces the "All Sections" checklist and its red button.
- **Rewritten overview** — The introduction, architecture, import and scheduler pages are rewritten around a new [glossary](0.1%20Glossary.md), and every page now follows the [documentation style guide](Documentation%20style%20guide.md).
- **Generated diagrams** — Overview, architecture, deployment, publication and pipeline figures are SVGs generated from `documentation/diagrams/` with one shared visual vocabulary. `python3 documentation/diagrams/build.py` regenerates them, and the engine's figures as well.
- **Clickable diagram links** — The portal inlines kit diagrams instead of showing them through `<img>`, so links drawn in them work, such as the repository links in the project overview. Each diagram's element IDs now start with its name, so several diagrams can share a page. Hand-drawn SVGs and other images are still shown as images, and GitHub and the PDF show every diagram as a static image. See [A2.8](2.8%20Documentation%20Page%20Delivery.md#diagrams).
- **Portal rendering fixes** — Automatic code links no longer alter code blocks, inline code or existing links; placeholders inside code stay literal; file names such as `build.py` no longer become `http://` links; wrapped source lines no longer break sentences; headings have stable anchors; navigation titles come from each page's heading. Links to engine source files point at the engine commit pinned in `engine.ref` instead of producing 404s.
- **PDF fixes** — Links to sections of other pages resolve inside the PDF, section numbers are no longer doubled, and `#` comments in code blocks are no longer read as headings.
- **Numeric page order** — The portal and the PDF sort pages by section number, so A2.10 follows A2.9 instead of A2.1.

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
