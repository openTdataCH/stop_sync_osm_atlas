# Contributing

Choose the part you want to improve:

- **Matching rules or a new dataset:** start with [engine/CONTRIBUTING.md](../engine/CONTRIBUTING.md). New datasets normally begin as external adapters using the public adapter contract; they do not automatically become built-ins. The app and database are unnecessary.
- **Maps or popups:** use the checked-in `tests/fixtures/result-v1` bundle, adapt data in `map-entity-adapters.js`, and run `npm test -- --runInBand`. Preserve each page's viewport, ordering and focus policy.
- **API, import or reports:** work in `backend/`. Run the app suite without installing the engine. Test publication changes against a disposable PostGIS database.
- **A bad match:** include source/OSM identifiers, expected behavior and a small reproducible example. A minimal public-data fixture is more useful than a national download.

See [the walkthroughs](documentation/Contributing.md) and [result contract](../engine/RESULT_FORMAT.md). Keep source-format parsing in adapters, downloads in acquisition clients, dataset composition in integrations, matching policy in profiles, domain decisions in the core, and presentation/persistence in the app. Add a regression that captures the observed failure rather than reproducing the implementation.

The application and engine have separate repositories, installation and tests,
and communicate through a versioned file format. Keep their checkouts together
for combined verification, but do not add imports across that boundary.

Run `make quality-fast` for local correctness checks or `make quality` for the
supported Python 3.13 / Node 22 container and disposable PostGIS suite. The full
command keeps the engine in a separate interpreter and writes raw evidence,
module coverage and a code map under `quality/`. See the [quality guide](quality/README.md)
for setup, baselines and verification limits. Retrieve a module's invariants,
tests and documentation with `python scripts/quality.py context MODULE_ID`.

Before requesting review:

1. Identify the affected responsibility and invariants in the
   [module catalog](quality/modules.yml). Assign new production files to one
   owner; associate relevant tests and documentation with that module.
2. Record intended behavior, failure examples, validation and recovery impact in
   the [PR change contract](.github/pull_request_template.md).
3. Add a regression for the behavior being changed. Browser tests must load real
   production scripts through the instrumented loader and clean up their timers,
   listeners and maps; see the
   [JavaScript test guide](documentation/4.2%20JavaScript%20tests.md).
4. Update the explanation, reference or operations document that users and
   maintainers need. For a behavior change with no document update, explain why
   the existing documentation remains accurate.
5. Run focused checks while editing, then collect the full evidence appropriate
   to the change once source and documentation are stable. Report skipped,
   missing or stale evidence explicitly. A generated report is not proof that
   all measurements passed.

The [quality operating guide](quality/README.md) covers native/container setup,
all commands and artifacts, CI configuration, baseline review, temporary
exceptions and troubleshooting. Never refresh a debt baseline or suppress an
unexpected browser error merely to make the checks green.
