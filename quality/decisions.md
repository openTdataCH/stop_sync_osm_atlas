# Quality system decisions

## Responsibility ownership and a versioned wire boundary

Status: accepted. Owner: OSM Atlas maintainers. Reviewed: 2026-09-22.

Each production file has one responsibility owner. The result bundle is a virtual
contract connecting producer and consumer, not a duplicate ownership module.
The app never imports engine code; it validates the wire contract independently.
Staging, locking, atomic publication and rollback are verified with real PostGIS.

## Evidence before thresholds

Status: accepted. Owner: OSM Atlas maintainers. Reviewed: 2026-09-22.

Use one local artifact and the existing documentation portal. Catalogs are JSON
syntax in YAML files, so they can be read without another parser. Reports are
regenerated, never hand edited. Missing, invalid or stale reports are explicit;
there is no weighted quality score. Coverage and changed-line targets start as
advisories until a representative supported run establishes a reviewed baseline.
Clone/dead-code baselines identify findings, not merely a count, so deleting one
finding cannot buy permission for a new one. Exceptions need an owner, reason,
module and expiry; baseline refreshes are deliberate reviewable changes.

Static import edges are exact syntax evidence. Dynamic call edges are heuristic;
script ordering and declared cross-process contracts remain separate relations.

## A module map for boundaries, a functions map for exploring

Status: accepted. Owner: OSM Atlas maintainers. Reviewed: 2026-11-04.

The dashboard draws modules and the code references between them, and opens one
module at a time as files and one file at a time as functions. That module map is
the boundary review tool, because the boundary is what reviewers act on: each
module's actual interface is the set of its names used from other modules,
compared with its declared entry points. A code dependency the catalog does not
declare is shown as a finding, not a failure, because the map cannot see database
dependencies or URLs built at runtime, and its Python call edges miss dynamic dispatch.
HTTP requests and templates are linked from their URL text and names; what cannot
be resolved is listed on the dashboard instead of silently missing. A link to a page
draws no arrow, because following a link does not use the page's code.

The dashboard also offers a functions map with every function and class of both
repositories, for exploring the code rather than reviewing it. Thousands of
symbols cannot be read as a diagram of boxes and arrows, so that map is a cloud of
dots: one region per module, dot size by use, names only where they fit, and the
lines of a function shown when it is selected. Its layout is a small deterministic
force layout in the dashboard script instead of a vendored library: it places the
2,200 dots in about 0.2 seconds, faster than d3-force did in measurement, and gives
the same picture for the same code map. Findings are never read from it.

Criticality stays a declared judgment of the worst defect's impact, chosen with
the rubric in `documentation/4.3 Code quality.md`. It is not derived from coverage or size, which
would let weak tests lower the bar.
