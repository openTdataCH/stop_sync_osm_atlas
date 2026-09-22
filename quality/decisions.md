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
Avoid a global function diagram. Use module context and bounded symbol views.
