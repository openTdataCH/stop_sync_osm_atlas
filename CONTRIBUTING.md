# Contributing

Choose the part you want to improve:

- **Matching rules or a new dataset:** start with [engine/CONTRIBUTING.md](engine/CONTRIBUTING.md). New datasets normally begin as external adapters using the public adapter contract; they do not automatically become built-ins. The app and database are unnecessary.
- **Maps or popups:** use the checked-in `tests/fixtures/result-v1` bundle, adapt data in `map-entity-adapters.js`, and run `npm test -- --runInBand`. Preserve each page's viewport, ordering and focus policy.
- **API, import or reports:** work in `backend/`. Run the app suite without installing the engine. Test publication changes against a disposable PostGIS database.
- **A bad match:** include source/OSM identifiers, expected behavior and a small reproducible example. A minimal public-data fixture is more useful than a national download.

See [the walkthroughs](documentation/Contributing.md) and [result contract](engine/RESULT_FORMAT.md). Keep source-format parsing in adapters, downloads in acquisition clients, dataset composition in integrations, matching policy in profiles, domain decisions in the core, and presentation/persistence in the app. Add a regression that captures the observed failure rather than reproducing the implementation.

Both projects currently share a checkout for the extraction review. They have independent installation and tests, and communicate through a versioned file format. Do not add imports across that boundary.
