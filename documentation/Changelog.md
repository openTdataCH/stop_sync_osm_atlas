# Review application changelog

Here you can find notable changes to this review web application, its database import, browser interface and deployment. Matching releases are recorded separately in the [matching engine changelog](../engine/documentation/Changelog.md).

Changes to the [result bundle contract](../engine/documentation/Result%20bundle%20format.md) are recorded in both changelogs: here from the consumer side and in the engine changelog from the producer side.

---

## Version 0.6.0

The matching code moves to its own package, the [matching engine](../engine/documentation/Changelog.md), first released as 0.1.0. The application no longer matches: it imports the engine's result bundles and presents them.

### Architecture

- **Engine and application apart** — The application validates and imports versioned result bundles without importing engine code. The committed `engine.ref` pins the engine commit it is built and tested with. See [A1.1](1.1%20Bundle%20import%20and%20publication.md).
- **Atomic publication** — An import is built and checked in a private staging schema, then published in one transaction.
- **Not only Switzerland** — Interface features that need SLOIDs or UIC references appear only when the bundle provides them.
- **Pipeline status** — The Data page shows every phase and stage of a run live, and a run whose process died is marked failed instead of shown as running.
- **Installation without Docker** — `scripts/install_server.sh` checks out the pinned engine, installs the application and the engine into one virtualenv and applies the migrations; the scheduler finds the engine command in that virtualenv. The database schema starts again from one migration, so a database from an earlier version is recreated once. See [A3](3.%20Application%20architecture%20%26%20deployment.md#deployment-without-docker).
- **Documentation PDF without Node** — CI renders the documentation's Mermaid diagrams for each commit of `main` and publishes them next to the quality evidence; a site that cannot render them downloads the set of its commit for the PDF. A diagram nobody rendered becomes a note pointing to the online page instead of failing the export. See [A2.5](2.5%20Reports%20and%20PDFs.md#documentation-pdf).

### Matching shown in the interface

- **New match rules** — OSM elements tagged with an ATLAS SLOID (`ref:sloid`, `railway:ref:sloid`) are matched first, as **SLOID in OSM**. Each match type names the rule that decided it, and the map's Matched filter groups them by rule.
- **New problem types** — **OSM SLOID** for a SLOID that names a distant or unknown platform, and **disused** for retired OSM elements that still look in use. Disused elements are drawn as grey rings. See [A2.4](2.4%20Problems%20page.md).
- **More routes linked** — Lines are linked when their variants have the same stops in order, also without a route ID, and variants are compared by station, so a stop at another platform of the same station counts as shared. An OSM relation without `ref_trips` is paired with a variant on its stops in order. See [A2.6](2.6%20Routes%20pages.md).
- **Several matches per line** — A line can be matched to several lines of the other side: the timetable splits one line into several routes, and OSM can hold a line twice. Each match is a route card, which names the others. See [A2.6](2.6%20Routes%20pages.md#lines-with-several-matches).

- **GTFS, not ATLAS, on the route side** — Routes and variants come from the timetable, so the Routes pages, route filters and popups call that side GTFS. ATLAS stays the name of the stop registry.

### Map and Problems page

- **Search by name** — The search box suggests stations and OSM elements by name or number, and identifiers match whole. See [A2.2](2.2%20Filter%20and%20search%20logic.md#names-and-suggestions).
- **Shareable filters** — The address bar keeps every map filter, and **Copy link** shares the current view. See [A2.9](2.9%20Permalinks.md#map).
- **Problems by area** — The map filters by problem type and priority, and the Problems page filters by a drawn rectangle.
- **Faster, clearer map** — Markers are drawn on a canvas, JSON answers are compressed, and a legend explains the markers and lines. Popups keep one width and compare matched stops side by side.
- **Route variants on the map** — The route filter can keep a single variant, and variant maps colour stops as the main map does.
- **Problems page counts** — The summary names problems and stops apart ("43,103 problems at 38,177 stops", or groups in the Duplicates view), and an entry is one stop with all its problems, its duplicate problem included, so "Entry N of M" counts what the list holds. It called 38,177 stops "problems", and the type counts said 43,103. See [A2.4](2.4%20Problems%20page.md#entries).
- **A duplicate reported once per stop** — Engine `8f19dc7` reports a duplicate on one pair of its stop: the closest that a rule matched, never a propagated one. An ATLAS duplicate matched to a PTv2 platform and its stop position showed the same Duplicate Entry card in two entries, and the type count included each repeat (67 on the Swiss data). See [E4.1](../engine/documentation/4.1%20Stop%20problems.md#duplicate-problems).
- **Propagated pairs in the Matched filter** — A pair matched by propagation (OSM pair partner, ATLAS duplicate) is selected with the rule of the match it was propagated from. No rule selected these 14,327 pairs, so leaving out one rule hid all of them. See [A2.2](2.2%20Filter%20and%20search%20logic.md#matched-branch).
- **Problems page on phones** — Copy link and the summary no longer cover the problem card, the keyboard shortcuts hint is hidden, and the filter menus of the map and the Problems page open in full.

### Data, operators and exports

- **Analytics by source** — `/data/analytics` is reorganised into stop matching, unmatched, route matching, problems, ATLAS, Swiss GTFS, OSM stops and OSM routes, with plainer layouts.
- **Simpler operator cards and export form**.
- **Problems export by priority** — "Priority, highest first" starts with the P1 problems; it started with P3.

### Public API

- **Stop lookup** — `/api/lookup` returns every match of a stop as JSON and is the only `/api/` endpoint with stable fields. `/llms.txt` describes it for AI agents. See [A2.10](2.10%20Public%20API.md).
- **Changed endpoints** — Exports report progress, download and cancel under `/api/exports/<task_id>/`. `/api/search`, `/api/route_stops`, `/api/docs/stats`, `/api/generate_report`, `/api/download_stats_summary_pdf` and `/api/routes/comparison/best` are removed.

### Documentation and code quality

- **User guide** — Pages for mappers and data stewards on problems, routes, links and the API, plus a [glossary](0.4%20Glossary.md) in plain words. The terms of the code, the engine and the deployment are in a separate [developer glossary](Developer%20glossary.md). See [0. User guide](0.%20User%20guide.md).
- Any page can be downloaded alone as a PDF.
- **Code quality dashboard** — `/quality` maps the modules, files and functions of both repositories and their dependencies, lists what to clean up (functions nothing mentions, copied code, long files) and shows the test and coverage results that CI measured on the running commit, down to each file. The site downloads those results from GitHub by its own commit, so no report is committed any more. See [A4.3](4.3%20Code%20quality.md).


## Version 0.5

**Released:** July 30th 2026

### New features
- **Search and filters on GTFS↔SLOID map**
- **See routes on the GTFS↔SLOID map popup** — Like on the main map

### Improvements

- **Consolidated frontend code** — Unified map and popup logic across the application.
- **File-backed runtime state** — The app and scheduler default to shared JSON files in `data/runtime`; Redis remains an optional state backend.
- **Updated documentation**
