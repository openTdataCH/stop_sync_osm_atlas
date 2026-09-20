# Contributing

Choose the smallest part needed for your contribution. You can improve the matching engine without starting the website, and improve the website using an existing result bundle.

| Contribution | Start here | Verify |
|---|---|---|
| A matching predicate or dataset profile | Engine repository contributor guide | Engine offline tests. |
| GTFS/ATLAS/OSM parsing | `engine/src/transport_matcher/adapters/` | Adapter fixtures and regression tests. |
| A map component | `static/js/components/` and page adapters | Jest tests; the four pages share canonical entities. |
| Import, API or reports | `backend/` | App tests and real PostGIS publication checks when relevant. |
| A reproducible bad match | Supply source/OSM IDs, expected result and a minimal public example. | Add it as a small engine fixture. |

## Run only the UI

Start the local database and migrator, import `tests/fixtures/result-v1` with `python -m backend.importing.importer`, then start the app. The fixture contains synthetic matches and unmatched records. Set `REVIEW_CONFIG=config/gtfs-example.json` for a generic presentation.

## Add a map feature

Adapt page data in `static/js/components/map-entity-adapters.js`; keep domain field extraction there. Renderers consume immutable source coordinates, canonical entity keys, status, emphasis and popup references. Keep page-specific query/order/focus policy in the relevant controller. Add a regression for the behavior being changed and run `npm test -- --runInBand`.

## Work across the boundary

Read [the result contract](../engine/RESULT_FORMAT.md). Changes that affect both producer and consumer need fixture updates and contract tests. An internal Python refactor or SQL migration alone should not require a new wire format version.

The engine and review application are separate sibling repositories, and each has its own release version, immutable Git tag and commit SHA. Review-app builds additionally pin the engine full commit SHA. Result-schema versions change independently and require coordinated producer/consumer support. See [Dependency Management & Build Strategy](3.1%20Dependency%20Management%20&%20Build%20Strategy.md) for both release procedures.

For possible work with neighboring projects, see [related projects and collaboration opportunities](../engine/documentation/Related%20projects.md).
