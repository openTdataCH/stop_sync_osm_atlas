# Quality system decisions

## Responsibility ownership and a versioned wire boundary

Status: accepted. Owner: OSM Atlas maintainers. Reviewed: 2026-09-22.

Each production file has one responsibility owner. The result bundle is a virtual
contract connecting producer and consumer, not a duplicate ownership module.
The app never imports engine code; it validates the wire contract independently.
Staging, locking, atomic publication and rollback are verified with real PostGIS.

## Evidence before thresholds

Status: accepted. Owner: OSM Atlas maintainers. Reviewed: 2026-09-22.

Use one generated file and one dashboard. Catalogs are JSON syntax in YAML
files, so they can be read without another parser. Reports are regenerated, never
hand edited. Missing or invalid measurements are explicit, and evidence measured
on other source is refused instead of shown as stale; there is no weighted
quality score, and no coverage percentage fails a run. The clone baseline
identifies findings, not merely a count, so deleting one finding cannot buy
permission for a new one; a baseline refresh is a deliberate reviewable change.

Static import edges are exact syntax evidence. Dynamic call edges are heuristic;
script ordering and declared cross-process contracts remain separate relations.

## The site shows the evidence of its own commit

Status: accepted. Owner: OSM Atlas maintainers. Reviewed: 2026-11-11.

Nothing generated is committed. CI publishes the report and the code map of each
commit of `main` as one release asset, and the site downloads the file of the
commit it runs, once. Committing the report meant a manual step before every
deployment, commits of 1.7 MB and a site that marked the map of older code as
stale. A release asset needs no token, unlike a CI artifact. The site does not
build the map itself: that needs Node, the engine checkout and the scripts, which
a server should not need. In a checkout a local run's file wins, so a change can
be seen before it is pushed.

Unused code is a marking on the map, not a gate: a function is unused when no
production code names it. Vulture at full confidence reported nothing, and the
rule by name also covers the browser scripts. Only a function or a class is
marked: the object a page script publishes on `window` for its tests holds no
code of its own.

## One map at three depths

Status: accepted. Owner: OSM Atlas maintainers. Reviewed: 2026-11-11.

The dashboard draws the code on three levels in one style: modules as circles,
files and functions as dots inside them. A module is in the same place on Modules
and Files, above the modules it depends on, so a change of level reads as opening
the same picture further. Before, there were six views in two styles; the two
that drew one module's files and one file's functions in three columns are gone,
because the side panel lists the same users and uses.

The Modules level is the boundary review tool, because the boundary is what
reviewers act on: each module's actual interface is the set of its names used
from other modules, compared with its declared entry points. A code dependency
the catalog does not declare is shown as a finding, not a failure, because the
map cannot see database dependencies or URLs built at runtime, and its Python
call edges miss dynamic dispatch. HTTP requests and templates are linked from
their URL text and names; what cannot be resolved is listed on the dashboard
instead of silently missing. A link to a page draws nothing, because following a
link does not use the page's code.

Thousands of functions cannot be read as boxes and arrows, so they are dots:
size by use, names only where they fit, and lines lit when a dot is selected.
The layout is a small deterministic force layout in the dashboard script instead
of a vendored library: it places 2,200 dots in about 0.2 seconds and gives the
same picture for the same code map.

The map also points at what to clean up: functions nothing mentions, copied
blocks and long files. These are lists and markings, never a failed check.

Criticality stays a declared judgment of the worst defect's impact, chosen with
the rubric in `documentation/4.3 Code quality.md`. It is not derived from coverage or size, which
would let weak tests lower the bar.
