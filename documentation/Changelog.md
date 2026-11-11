# Review application changelog

This page records notable changes to the review application, its database import, browser interface and deployment. Matching releases are recorded separately in the [matching engine changelog](../engine/documentation/Changelog.md).

Changes to the [result bundle contract](../engine/documentation/Result%20bundle%20format.md) are recorded in both changelogs: here from the consumer side and in the engine changelog from the producer side.

---

## Version 0.6.0

The matching code moves to its own package, the [matching engine](../engine/documentation/Changelog.md), first released as 0.1.0. The application no longer matches: it imports the engine's result bundles and presents them.

### Architecture

- **Engine and application apart** — The application validates and imports versioned result bundles without importing engine code. The committed `engine.ref` pins the engine commit it is built and tested with. See [A1.1](1.1%20Bundle%20import%20and%20publication.md).
- **Atomic publication** — An import is built and checked in a private staging schema, then published in one transaction.
- **Not only Switzerland** — Interface features that need SLOIDs or UIC references appear only when the bundle provides them.
- **Pipeline status** — The Data page shows every phase and stage of a run live, and a run whose process died is marked failed instead of shown as running.

### Matching shown in the interface

- **New match rules** — OSM elements tagged with an ATLAS SLOID (`ref:sloid`, `railway:ref:sloid`) are matched first, as **SLOID in OSM**. Each match type names the rule that decided it, and the map's Matched filter groups them by rule.
- **New problem types** — **OSM SLOID** for a SLOID that names a distant or unknown platform, and **disused** for retired OSM elements that still look in use. Disused elements are drawn as grey rings. See [A2.4](2.4%20Problems%20page.md).
- **More routes linked** — Lines are linked when their variants have the same stops in order, also without a route ID, and variants are compared by station, so a stop at another platform of the same station counts as shared. An OSM relation without `ref_trips` is paired with a variant on its stops in order. See [A2.6](2.6%20Routes%20pages.md).
- **Several matches per line** — A line can be matched to several lines of the other side: the timetable splits one line into several routes, and OSM can hold a line twice. Each match is a route card, which names the others. See [A2.6](2.6%20Routes%20pages.md#lines-with-several-matches).
- **Route side called `gtfs` in the code** — Tables, columns, the stored `source` value, JSON fields, CSS classes and JavaScript call the timetable side `gtfs` (`gtfs_line_families`, `gtfs_line_family_id`, `gtfs_itinerary_id`, `routes_gtfs`, `route-card--gtfs_only`); ATLAS stops keep `atlas`. The internal route APIs accept the older `atlas_itinerary_id`, `source=atlas` and `{"atlas": …}` variant keys until the next release. See [A2.6](2.6%20Routes%20pages.md#names).
- **What supports a match** — Each matched route card says whether the route ID and the stops link its lines, the stops only, or the route ID alone. The import keeps the engine's `stop_score` of each line link. See [A2.6](2.6%20Routes%20pages.md#what-supports-a-match).
- **GTFS, not ATLAS, on the route side** — Routes and variants come from the timetable, so the Routes pages, route filters and popups call that side GTFS. ATLAS stays the name of the stop registry.

### Map and Problems page

- **Search by name** — The search box suggests stations and OSM elements by name or number, and identifiers match whole. See [A2.2](2.2%20Filter%20and%20search%20logic.md#names-and-suggestions).
- **Shareable filters** — The address bar keeps every map filter, and **Copy link** shares the current view. See [A2.9](2.9%20Permalinks.md#map).
- **Problems by area** — The map filters by problem type and priority, and the Problems page filters by a drawn rectangle.
- **Faster, clearer map** — Markers are drawn on a canvas, JSON answers are compressed, and a legend explains the markers and lines. Popups keep one width and compare matched stops side by side.
- **Route variants on the map** — The route filter can keep a single variant, and variant maps colour stops as the main map does.
- **Links to the documentation** — Filters, match types and problem types link to the section that explains them.

### Data, operators and exports

- **Analytics by source** — `/data/analytics` is reorganised into stop matching, unmatched, route matching, problems, ATLAS, Swiss GTFS, OSM stops and OSM routes, with plainer layouts.
- **Simpler operator cards and export form**.

### Public API

- **Stop lookup** — `/api/lookup` returns every match of a stop as JSON and is the only `/api/` endpoint with stable fields. `/llms.txt` describes it for AI agents. See [A2.10](2.10%20Public%20API.md).
- **Changed endpoints** — Exports report progress, download and cancel under `/api/exports/<task_id>/`. `/api/search`, `/api/route_stops`, `/api/docs/stats`, `/api/generate_report`, `/api/download_stats_summary_pdf` and `/api/routes/comparison/best` are removed.

### Documentation and code quality

- **User guide** — Pages for mappers and data stewards on problems, routes, links and the API, plus a [glossary](0.4%20Glossary.md). See [0. User guide](0.%20User%20guide.md).
- **New addresses** — Page files are named after their titles, so some addresses change (`/docs/intro` is now `/docs/user_guide`); old addresses are not redirected. Any page can be downloaded alone as a PDF.
- **Code quality dashboard** — `/quality` maps the modules, files and functions of both repositories and their dependencies in one style, lists what to clean up (functions nothing mentions, copied code, long files) and shows the test and coverage results that CI measured on the running commit, down to each file. The site downloads those results from GitHub by its own commit, so no report is committed any more. See [A4.3](4.3%20Code%20quality.md).


## Version 0.5

**Released:** July 30th 2026

### New features
- **Search and filters on GTFS↔SLOID map**
- **See routes on the GTFS↔SLOID map popup** — Like on the main map

### Improvements

- **Consolidated frontend code** — Unified map and popup logic across the application.
- **File-backed runtime state** — The app and scheduler default to shared JSON files in `data/runtime`; Redis remains an optional state backend.
- **Updated documentation**
