# Contributing

Work on the smallest part your change needs: the matching engine can be improved without starting the website, and the website with an existing result bundle. The [glossary](0.1%20Glossary.md) defines the terms used below.

| Contribution | Start here | Verify |
|---|---|---|
| A matching rule or [dataset profile](../engine/documentation/2.%20Matching%20process.md#dataset-profiles) | The engine's contributor guide, `CONTRIBUTING.md` in the engine repository | Engine offline tests |
| GTFS, ATLAS or OSM parsing | `src/public_transport_matcher/adapters/` in the engine repository | Adapter fixtures and regression tests |
| A map component | `static/js/components/` and the page adapters | Jest tests; all map pages share the same entity model |
| Import, API or reports | `backend/` | Application tests, and the PostGIS publication tests when publication is affected |
| A reproducible bad match | Report the source and OSM IDs, the expected result and a minimal public example | Add it as a small engine fixture |
| Documentation | The [documentation style guide](Documentation%20style%20guide.md) | `python -m pytest tests/test_docs_links.py tests/test_docs_diagrams.py tests/test_docs_rendering.py -q` |

## Run only the UI

Start the local database and the migrator, import the example bundle with `python -m backend.importing.importer tests/fixtures/result-v1`, then start the app ([A1.1](1.1%20Import%20Process.md#try-it-with-the-example-bundle)). The bundle contains synthetic matches and unmatched records. Set `REVIEW_CONFIG=config/gtfs-example.json` for a presentation without Swiss specifics.

## Add a map feature

Adapt page data in `static/js/components/map-entity-adapters.js`, and keep the extraction of domain fields there. Renderers consume unchanged source coordinates, canonical entity keys, status, emphasis and popup references. Keep page-specific query, ordering and focus rules in the page's controller. Add a regression test for the behaviour you change and run `npm test -- --runInBand`.

## Work across the boundary

Read the [result bundle format](../engine/documentation/Result%20bundle%20format.md). A change that affects both the engine (producer) and the application (consumer) needs updated fixtures and contract tests. An internal Python refactoring or an SQL migration alone does not need a new schema version.

The engine and the review application are separate repositories, each with its own release version, immutable Git tags and commits. Application builds also pin the engine's full commit SHA. The result schema version changes independently of both and needs coordinated support on both sides. [A3.1 Dependencies and builds](3.1%20Dependency%20Management%20&%20Build%20Strategy.md) describes both release procedures.

## Improve the documentation

Follow the [documentation style guide](Documentation%20style%20guide.md): it defines the page structure, the terms, the link conventions and the diagram kit. Regenerate the diagrams with `python3 documentation/diagrams/build.py` after changing their source, and commit the generated SVGs.

## Related projects

For possible work with neighbouring projects, see [related projects and collaboration opportunities](../engine/documentation/Related%20projects.md).
