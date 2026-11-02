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

## A module map, not a function diagram

Status: accepted. Owner: OSM Atlas maintainers. Reviewed: 2026-11-02.

The dashboard draws modules and the code references between them, and opens one
module at a time as files. It never draws every function: thousands of symbols
make an unreadable diagram, and the boundary is what reviewers act on. Each
module's actual interface is the set of its names used from other modules,
compared with its declared entry points. A code dependency the catalog does not
declare is shown as a finding, not a failure, because the map cannot see HTTP,
database or template dependencies and its Python call edges miss dynamic dispatch.

Criticality stays a declared judgment of the worst defect's impact, chosen with
the rubric in `documentation/4.3 Code Quality.md`. It is not derived from coverage or size, which
would let weak tests lower the bar.
