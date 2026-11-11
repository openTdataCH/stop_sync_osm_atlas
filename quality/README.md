# Quality controls

This folder holds the inputs of the application's and engine's quality checks. The guides live in the documentation, so they read the same on the site, in the PDF and here:

- [A4.3 Code quality](../documentation/4.3%20Code%20quality.md): the code quality dashboard, the criticality of modules and how to read the evidence.
- [A4.4 Running the quality checks](../documentation/4.4%20Running%20the%20quality%20checks.md): commands, local and CI setup, how the evidence reaches the site, maintaining the module catalog, the baseline and troubleshooting.

| File | Contents |
|---|---|
| [modules.yml](modules.yml) | The module catalog: every source file's owner module, with its criticality, invariants, entry points, dependencies, tests and documentation |
| [modules.schema.json](modules.schema.json), [report.schema.json](report.schema.json) | Structure of the catalog and of the generated report |
| [exclusions.json](exclusions.json), [baseline.json](baseline.json) | Excluded sources and the accepted duplicated blocks |
| [decisions.md](decisions.md) | Why ownership, contracts, evidence and the baseline work this way |

A run writes `evidence.json` (the report and the code map the dashboard shows) and `raw/` here; Git ignores them. Nothing generated is committed: CI publishes each commit's `evidence.json` as a release asset, and the site downloads the file of the commit it runs.
