# Quality controls

This folder holds the inputs and outputs of the application's and engine's quality checks. The guides live in the documentation, so they read the same on the site, in the PDF and here:

- [A4.3 Code quality](../documentation/4.3%20Code%20Quality.md): the code quality dashboard, the criticality of modules, how to read the report and how it reaches the site.
- [A4.4 Running the quality checks](../documentation/4.4%20Running%20Quality%20Checks.md): commands, local and CI setup, maintaining the module catalog, baselines, exceptions and troubleshooting.

| File | Contents |
|---|---|
| [modules.yml](modules.yml) | The module catalog: every source file's owner module, with its criticality, invariants, entry points, dependencies, tests and documentation |
| [modules.schema.json](modules.schema.json), [latest.schema.json](latest.schema.json) | Structure of the catalog and of the generated report |
| [exclusions.json](exclusions.json), [baseline.json](baseline.json), [exceptions.json](exceptions.json) | Excluded sources, accepted structural findings and temporary exceptions |
| [decisions.md](decisions.md) | Why ownership, contracts, evidence and ratchets work this way |
| [published/](published/) | The CI report committed by `make deploy-report`, which the site shows |

A local run also writes `latest.json`, `report.md`, `quality-map.json`, `code-map.json` and `raw/` here; Git ignores them.
