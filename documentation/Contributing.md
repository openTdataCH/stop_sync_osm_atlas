# Contributing

Work on the smallest part your change needs: the matching engine can be improved without starting the website, and the website with an existing result bundle. No national download is needed to begin. The [glossary](0.4%20Glossary.md) defines the terms used below.

| Contribution | Start here | Verify |
|---|---|---|
| A matching rule or [dataset profile](../engine/documentation/2.%20Matching%20process.md#dataset-profiles) | The engine's contributor guide, `CONTRIBUTING.md` in the engine repository | Engine offline tests |
| GTFS, ATLAS or OSM parsing | `src/osm_public_transport_matcher/adapters/` in the engine repository | Adapter fixtures and regression tests |
| Another dataset | Your own adapter that implements the public adapter contract; [what belongs in the engine](../engine/documentation/1.%20Input%20integrations%20%26%20acquisition.md#what-belongs-in-this-distribution) says when one becomes built in | Small offline test cases |
| A map component | `static/js/components/` and the page adapters | Jest tests; all map pages share the same entity model |
| Import, API or reports | `backend/` | Application tests, which run without the engine, and the PostGIS publication tests when publication is affected |
| A reproducible bad match | Report the source and OSM IDs, the expected result and a minimal public example | Add it as a small engine fixture |
| Documentation | `documentation/` and `documentation/diagrams/catalog.py` | `python -m pytest tests/test_docs_links.py tests/test_docs_diagrams.py tests/test_docs_rendering.py -q` |

In the engine, format parsing belongs in adapters, matching policy in profiles and matching decisions in the core ([E1 Code structure](../engine/documentation/1.%20Input%20integrations%20%26%20acquisition.md#code-structure)). Presentation and persistence belong in the review application.

## Run only the UI

A small synthetic bundle runs the website without the engine: follow [Try it with the example bundle](1.1%20Bundle%20import%20and%20publication.md#try-it-with-the-example-bundle). For day-to-day work, `make dev` starts the website with automatic reloading.

## Add a map feature

Adapt page data in `static/js/components/map-entity-adapters.js`, and keep the extraction of domain fields there. Renderers consume unchanged source coordinates, canonical entity keys, status, emphasis and popup references. Keep page-specific query, ordering and focus rules in the page's controller. Add a regression test for the behaviour you change and run `npm test -- --runInBand`.

## Work across the boundary

Read the [result bundle format](../engine/documentation/Result%20bundle%20format.md). A change that affects both the engine (producer) and the application (consumer) needs updated fixtures and contract tests. An internal Python refactoring or an SQL migration alone does not need a new schema version. Never import code across the boundary.

The engine and the review application are separate repositories, each with its own release version, immutable Git tags and commits. Application builds also pin the engine's full commit SHA. The result schema version changes independently of both and needs coordinated support on both sides. [A3.1 Dependencies and builds](3.1%20Dependencies%20and%20builds.md) describes both release procedures.

## Improve the documentation

Use the terms of the [glossary](0.4%20Glossary.md), British spelling, one line per paragraph, and code paths in backticks. End each page with `## Related pages`. `tests/test_docs_style.py`, `tests/test_docs_links.py` and `tests/test_docs_rendering.py` check these rules and every link.

## Before requesting review

1. Find the module your change affects in the module catalog, `quality/modules.yml`, and keep its invariants. A new file belongs to the module that owns its directory; name it in the catalog only when that owner is wrong, and associate the relevant tests and documentation with its module ([A4.4](4.4%20Running%20the%20quality%20checks.md#maintain-the-module-catalog)). The [code quality dashboard](/quality) shows a module's invariants, tests and documentation when it is selected.
2. Fill in the change contract of the pull request template, `.github/pull_request_template.md`: the behaviour change and affected modules, acceptance and failure examples, preserved invariants, verification, the documentation decision and the recovery impact.
3. Add a regression test that captures the observed failure rather than restating the implementation. Browser tests load the real production scripts through `tests/js/load-browser-script.js` and clean up their timers, listeners and maps ([A4.2](4.2%20JavaScript%20tests.md)).
4. Update the pages that users and maintainers need. When a behaviour change needs no documentation update, say why in the pull request.
5. Run focused checks while editing, and the full checks once code and documentation are stable ([A4.4](4.4%20Running%20the%20quality%20checks.md)). Report skipped or missing evidence: a generated report is not proof that every measurement passed. Never refresh the clone baseline or silence an unexpected browser error only to make the checks pass.
