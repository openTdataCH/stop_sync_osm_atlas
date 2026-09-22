# Quality controls

This guide explains how to run, maintain and interpret the app and engine quality
checks. Start in the application repository. The [module catalog](modules.yml)
records responsibilities and invariants; the generated report connects those
modules to evidence. The [Code Quality page](../documentation/4.3%20Code%20Quality.md)
renders that evidence in the documentation portal.

## Choose a command

| Command | Purpose | Requirements |
|---|---|---|
| `make quality-fast-container` | Catalog, architecture, Python/JS/CSS lint, template/config syntax, vendor checks and focused quality/contract tests | Docker Compose and an engine checkout |
| `make quality` | Full app, browser and engine suites; PostGIS publication and producer/consumer checks; coverage sanity; structural debt; report/map generation | Docker Compose and an engine checkout |
| `make quality-fast` | Same fast checks using installed local tools | Python 3.13, Node 22.x at least 22.13, all app/test/quality dependencies |
| `make quality-ci` | Full checks with an existing disposable database and separate engine interpreter | Same supported tools, `TEST_POSTGRES_URI`, `ENGINE_PYTHON` |
| `make quality-down` | Remove the dedicated quality Compose stack and its disposable data | Docker Compose |

A fast pass does not execute the complete browser or application suite and does
not replace full verification. Dependency audits and CodeQL are separate CI
checks; `make quality` does not run those network services.

## Supported local setup

### Docker: the complete reproducible path

Keep a quality-enabled engine checkout beside the application:

```text
workspace/
  stop_sync_osm_atlas/
  engine/
    quality/modules.yml
```

From `stop_sync_osm_atlas/`:

```sh
make quality-fast-container
make quality
make quality-down
```

For another engine location, pass `ENGINE_ROOT` consistently:

```sh
make quality ENGINE_ROOT=/absolute/path/to/engine
```

[Dockerfile.quality](../Dockerfile.quality) supplies Python 3.13, Node 22,
PDF rendering libraries, app tools and an isolated engine virtual environment.
[compose.quality.yml](../compose.quality.yml) bind-mounts app source and the engine
checkout, keeps engine source read-only, and gives the runner its image's Node
dependencies. The dedicated `osm-atlas-quality` project provisions PostGIS 16/3.4
with disposable in-memory database storage. It does not share production volumes
or use the deployment's database credentials. Full publication tests can replace
test data, so this separation is essential.

Both container commands build the image. Rebuild after requirement, lockfile or
engine dependency changes; changing a bind-mounted source file does not update
installed packages. Preflight rejects a Python package version that no longer
satisfies the current requirement files.

A full run clears `quality/raw/` before collecting evidence, then writes outputs
back into the app checkout. Save any previous run you need to investigate before
starting another full run. Stop editing either repository while the final run is
in progress: source changes invalidate its fingerprints, including changes to
documentation, configuration and tests.

### Native development

Use Python **3.13** and Node **22.x, version 22.13 or later**. The runner checks
those versions; an arbitrary newer Node major is not the supported toolchain.
Native PDF tests also need the platform's Pango/Cairo libraries. Prefer the
container when those libraries are unavailable.

```sh
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-base.txt -r requirements-web.txt \
  -r requirements-scheduler.txt -r requirements-test.txt -r requirements-quality.txt
npm ci
make quality-fast PYTHON=python ENGINE_ROOT=../engine
```

`requirements-test.txt` includes Hypothesis and JSON Schema because ordinary
pytest collection includes property and quality-schema tests. Installing only
pytest, or treating those packages as optional quality extras, is insufficient.
`requirements-quality.txt` supplies the analyzer versions used by the quality
runner. See [dependency management](../documentation/3.1%20Dependency%20Management%20%26%20Build%20Strategy.md)
for the app's dependency groups.

Do not install `transport-matcher` into the app interpreter. Full verification
checks this boundary explicitly. To run the full command natively, create a
separate engine environment and supply a database dedicated to tests:

```sh
python3.13 -m venv ../engine/.venv
../engine/.venv/bin/python -m pip install '../engine[swiss,gtfs,quality]'
TEST_POSTGRES_URI=postgresql+psycopg://test:test@localhost:5432/transport_test \
  make quality-ci PYTHON=python ENGINE_ROOT=../engine \
  ENGINE_PYTHON=../engine/.venv/bin/python
```

The example assumes that disposable PostGIS database already exists. It is not a
command for connecting to a production database. For engine-only work, use the
[engine quality guide](../../engine/quality/README.md).

## CI and repository setup

[Required quality](../.github/workflows/tests.yml) runs on pull requests and
selected branch pushes. It checks out the engine separately, installs matching
toolchains, supplies a disposable PostGIS service, and invokes `make quality-ci`.
The app suite runs without an engine installation; the engine suite and explicit
producer/consumer check use the separate engine interpreter.

Repository administrators must configure:

- `ENGINE_REPOSITORY`: the engine repository in `owner/repository` form.
- `ENGINE_REF`: a reviewed engine revision containing its quality catalog and
  commands. A commit SHA gives an immutable producer/consumer test pairing.
- `ENGINE_REPOSITORY_TOKEN`: credentials with read access for the engine
  checkout used by the workflows.
- Branch protection or rulesets requiring **Required quality**, **Dependency
  security audit**, and the applicable **Security analysis** checks for Python
  and JavaScript/TypeScript. Confirm the exact check names after the first run.

Committing workflow files does not configure repository protection, grant access
to another repository, or publish engine changes. Update the engine revision as
part of a reviewed cross-repository contract change.

The required workflow always uploads `quality-<app SHA>` evidence, including
failed-run outputs, with 30-day retention. Inspect job output alongside the
artifact: missing outputs may indicate that collection itself failed.

[Periodic quality](../.github/workflows/deep-quality.yml) runs production Python
dependency auditing and an npm audit on pull requests, weekly and on manual
invocation. The npm audit fails at high severity; the Python audit fails on its
reported vulnerabilities. Its `dependency-security-<app SHA>` artifact preserves
both audit reports. Dependency changes must update the corresponding requirement
or lockfile and any vendored assets, then rerun behavioral tests. For example,
the WeasyPrint 70 security upgrade is protected by PDF layout/rendering tests and
a regression proving stylesheet arguments respect the document URL fetcher.

[CodeQL](../.github/workflows/codeql.yml) analyzes app Python and first-party
browser JavaScript on pull requests, selected pushes and its weekly schedule.
Vendor files are excluded. Findings are available through GitHub code scanning;
a successful job is not itself a per-module security score.

The standalone engine has its own production dependency audit and Python CodeQL
workflow. Configure its required branch checks independently; see the
[engine quality guide](../../engine/quality/README.md). An app audit does not
establish that the engine's separate dependency closure was scanned.

The periodic mutation job runs on the weekly/manual paths, not every pull
request. It targets the engine's result-position validator and publishes a
`result-validation-mutation-<app SHA>` artifact. Survivors remain advisory during
baseline collection; failed execution is still a failed workflow.

## Manual inputs and ownership

| File | Who maintains it | Meaning |
|---|---|---|
| [modules.yml](modules.yml) | Maintainers | Module responsibility, risk, owner, invariants, source/test paths, entry points, documentation and declared dependencies/contracts |
| [modules.schema.json](modules.schema.json) | Quality maintainers | Validated catalog structure; the catalog uses JSON-compatible YAML |
| [exclusions.json](exclusions.json) | Maintainers, with reasons | Shared source exclusions and additional clone exclusions |
| [baseline.json](baseline.json) | Reviewed changes | Accepted structural findings and optional advisory module branch floors |
| [exceptions.json](exceptions.json) | Named owners | Exact, temporary structural finding exceptions with expiry |
| [latest.schema.json](latest.schema.json) | Quality maintainers | Versioned aggregate evidence structure |
| [decisions.md](decisions.md) | Maintainers | Why ownership, contracts, evidence and ratchets work this way |

Every inventoried production source has exactly one ownership module. Source
inventory combines tracked and new nonignored Git files, configured source roots
and explicit files. It recognizes Python, JS/MJS/CJS, CSS, templates, SQL, shell,
YAML, JSON and TOML; explicit catalog entries include extensionless deployment
files and requirement lists. New files outside an established directory must
still be assigned an owner. Symlinks are not followed as source files.

Tests may support multiple modules and are associated through each module's test
patterns. Contract nodes connect producer and consumer owners; a contract does
not assign a second owner to their implementation files. Documentation paths are
obligations, not an instruction to document every private helper.

The source exclusions cover generated evidence and diagrams, the built CSS
bundle, vendored/installed dependencies, runtime data, bytecode, mutation
worktrees, and tests/fixtures that are modeled as evidence. Historical migrations
remain owned source but are excluded from clone budgets. Each repository can add
explicit exclusions to its catalog; always explain the category being excluded.

Runtime coverage denominators are narrower than source ownership: app
`backend/**/*.py`, engine `src/**/*.py`, and every first-party
`static/js/**/*.js`. CSS, templates, deployment files and build tooling remain
owned and checked, but are not assigned runtime coverage percentages.

When adding or moving code:

1. Choose the existing responsibility owner, or add a module with a coherent
   responsibility and failure boundary.
2. Update source/test patterns and required explanation/reference/operations
   documents. Keep criticality based on failure impact.
3. Declare stable entry points, dependencies and cross-repository contracts.
4. Run `check`, relevant focused tests and `make quality-fast`; finish with full
   evidence appropriate to the change.

## CLI reference

Run `python scripts/quality.py --help` for the parser's current options. Examples
below assume the supported environment and a sibling engine checkout.

| Command | Result |
|---|---|
| `python scripts/quality.py check --engine-root ../engine` | Validates catalog schemas, single ownership, documentation/test references, entry points, exceptions and enforced architecture boundaries |
| `python scripts/quality.py coverage --engine-root ../engine` | Validates current raw coverage against source fingerprints and all expected runtime files; does not execute tests |
| `python scripts/quality.py debt --engine-root ../engine` | Runs jscpd and Vulture, writes raw findings and fails on new unexcepted structural debt |
| `python scripts/quality.py report --engine-root ../engine` | Reads existing evidence and writes `latest.json`, `report.md` and the code map; does not recollect tests |
| `python scripts/quality.py map --engine-root ../engine` | Generates the complete machine-readable module/file/symbol map |
| `python scripts/quality.py context app.snapshot-publication --engine-root ../engine` | Prints that module's responsibility, invariants, entry points, dependencies, tests, docs and verification commands |
| `python scripts/quality.py impact backend/importing/publication.py --depth 1 --engine-root ../engine` | Prints a bounded JSON neighborhood for matching module/file IDs |
| `python scripts/quality.py symbol publish_snapshot --depth 2 --engine-root ../engine` | Prints matching symbols and their bounded graph neighborhood |

`--engine-root` supplies the engine checkout. Without it, this CLI uses
`ENGINE_DIR` if set, then searches `engine/` within the app and `../engine/` for a
catalog. Make targets use `ENGINE_ROOT`; these are deliberately different
interfaces, so explicit paths are easiest when using both.

`--depth` accepts only `1` or `2` for `impact` and `symbol`. Matching is
case-insensitive substring matching over node IDs; a broad search term can match
several symbols or files. Use a more specific path/name to narrow the result.
These commands also refresh the complete map before printing the selected view.

`report --base origin/main` enables advisory changed-line coverage for the app.
The comparison revision must exist locally. New untracked code is included in
local comparisons; CI supplies the pull request base through `QUALITY_BASE`.
This option does not currently compute an independent engine diff. Without a
base, changed coverage is `not_measured`.

`debt --write-baseline` is an explicit baseline-maintenance operation, described
below. It must not be added to CI or to an automatic fix command.

The lower-level runner is `python scripts/run_quality.py fast|full|syntax`.
`fast` and `full` accept `--engine-root`; `full` also uses `--engine-python`
(defaulting to `ENGINE_PYTHON` or `/opt/engine-venv/bin/python`). `syntax` parses
Jinja templates and configured YAML/JSON without importing the app. Prefer the
Make targets for ordinary use.

## Evidence files and freshness

The full runner records each check's command, exit status and duration, continues
collecting independent checks after failures, and returns nonzero if any required
check failed. Report generation is useful even after a test failure; producing a
report is not equivalent to passing the run.

| Artifact, relative to `quality/` | Contents |
|---|---|
| `latest.json` | Schema-validated aggregate: app/engine revisions, fingerprints, generation time, completeness, tools, checks, module measurements and raw-artifact references |
| `report.md` | Generated Markdown projection of the same aggregate |
| `quality-map.json` | Typed nodes/edges, provenance and graph limitations |
| `raw/checks.json` | Full-run manifest and check results |
| `raw/fast-checks.json` | Fast-run manifest; does not certify earlier full-run evidence |
| `raw/app-tests.xml`, `raw/engine-tests.xml` | Pytest JUnit test outcomes |
| `raw/contract-tests.xml` | Explicit producer/consumer progress contract outcomes |
| `raw/app-python-coverage.json`, `raw/app-python-coverage.xml` | App line/branch coverage in JSON and XML |
| `raw/engine-python-coverage.json`, `raw/engine-python-coverage.xml` | Engine line/branch coverage in JSON and XML |
| `raw/javascript-tests.json` | Jest test outcomes |
| `raw/javascript-coverage.json`, `raw/lcov.info` | Browser production coverage in Istanbul JSON and LCOV |
| `raw/jscpd/jscpd-report.json` | Original clone-detector output |
| `raw/vulture.txt`, `raw/debt.json` | Certain dead-code output and normalized structural findings |
| `raw/python-audit.json`, `raw/npm-audit.json` | Separate dependency-audit workflow outputs, when copied/published with the evidence |
| `raw/engine-python-audit.json` | Standalone engine production dependency audit, when copied/published with the evidence |
| `raw/engine-mutation.json`, `raw/engine-mutation.txt` | Optional scoped mutation evidence, originally produced in the engine's output directory |

Analyzer formats retain their own details; the aggregate is not a replacement
for their raw reports. Coverage paths from another checkout are normalized for
module association, and pytest class-based test names are attributed to their
source test file. A shared test can count as evidence for multiple modules;
module counts are not additive suite totals.

The three producer/consumer cases skipped in the engine-free app suite are
matched by file and test identity to their separately executed contract results.
A real contract result replaces the matching skip; any recorded failure is
retained. An unrelated passing test cannot cancel a skipped or failing case.

Freshness requires a recent full-run manifest, matching app/engine Git revisions,
and matching source fingerprints. Fingerprints hash tracked and new nonignored
inputs while excluding generated quality/documentation outputs. The accepted
age is seven days, with a five-minute tolerance for future clock skew. Running
`report` again does not make an old raw run fresh. Editing a document or test
after collection also makes the earlier evidence stale.

The portal rechecks available app and engine checkout fingerprints and report
age. When a deployed image has no usable Git checkout, it explicitly says the
inputs cannot be verified. That warning must not be interpreted as verification
against the deployment. Publish matching raw evidence and revisions when
shipping a measured dashboard.

### How to read statuses

| Status | Interpretation |
|---|---|
| `pass` | The recorded check or applicable comparison passed |
| `fail` | Executed tests or an enforced rule failed; inspect the check/raw result |
| `measured` | A valid measurement is available; the percentage is not itself a success threshold |
| `attention` | Review is needed, such as skipped/missing declared tests, new structural findings or an advisory regression |
| `not_measured` | Required input for this measurement was not collected or is absent |
| `not_applicable` | There is no applicable denominator, for example no runtime source in a styles module |
| `invalid` | Evidence cannot be trusted, such as incomplete coverage or malformed mutation totals |
| `stale` | Evidence does not match current inputs or its accepted time window |

The report's overall `completeness` is separate from a check outcome. `partial`
means some measurements are absent or invalid; it can be the honest result of a
passing required run while security/mutation measurements are not integrated for
every module. `complete` describes available measurements and is not a combined
quality score. `stale` means the recorded run does not establish current quality.
Missing or unreadable deployed reports are shown as **unavailable**.

Missing declared test files or skipped scenarios never become a clean module
pass. The docs count measures required catalog slots, not the editorial quality
or exhaustive correctness of those documents. Read the source documents when
reviewing behavior and invariants.

### Publish or inspect the report

Open `quality/report.md` locally, or retrieve the matching CI artifact. To deploy
it, copy `latest.json`, `quality-map.json`, `report.md` and the required `raw/`
files into the app's `quality/` directory. The portal reads the JSON aggregate;
do not hand-edit the rendered table. Its `/docs/quality-artifacts/` endpoint
serves allowed generated evidence, and rejects manual catalog and hidden files.
Copy evidence from one identifiable run, not a mixture of unrelated revisions.
Copying coverage files alone does not establish a matching full-run manifest.
Never manufacture or edit `checks.json` to endorse a manually assembled run;
collect a supported full run when valid provenance is missing.

## Coverage sanity and advisory targets

JavaScript tests use an instrumented browser-script loader. Coverage includes
shared scripts and never-loaded first-party files, which correctly contribute
zero hits. `npm run test:coverage` runs Jest and then
`scripts/check-js-coverage.cjs`; that check requires every production JS file and
actual executed statements/branches. Use the
[JavaScript test guide](../documentation/4.2%20JavaScript%20tests.md) when adding tests.

The full `coverage` sanity gate additionally requires all three app/engine/JS
reports, matching source fingerprints, Python branch coverage, complete runtime
file denominators and valid count bounds. A green test process with broken
instrumentation or missing files must fail this gate.

These are correctness checks on evidence. There is no arbitrary repository-wide
coverage floor. `baseline.json` may store module branch percentages in its
`coverage` mapping; branch deltas and the 90% changed-line target are advisory
until maintainers review representative runs. A high percentage does not replace
publication rollback, invalid-input, concurrency or contract scenarios.

For optional engine mutation evidence, run its documented `quality-mutation`
command, retain the selected target/provenance and copy `engine-mutation.json`
into app `quality/raw/` after the full run, then regenerate the report. The sample
is checked against its source and test hashes and seven-day age limit. Only
`engine.result-producer` consumes this scoped report; it must not be presented as
mutation coverage of the entire engine. A subsequent full run clears the copied
raw file, so archive it before rerunning.

## Structural debt and exceptions

The clone gate uses jscpd at a minimum of 10 lines and 70 tokens. Vulture reports
only 100%-confidence Python findings. These tools identify duplication and
certain unused/unreachable candidates; unexecuted coverage is not proof of dead
code, and broad browser-global reachability is not currently measured.
The report's **Python dead code** column uses the analyzed Python file inventory
recorded in `raw/debt.json`. Modules with no analyzed Python files are **not
applicable**, without a zero-findings claim; older artifacts without that
inventory are **not measured**. Each measured lane identifies Vulture and its
100% minimum confidence, so this column makes no JavaScript or CSS reachability
claim.

Baseline identities include content and participating files. Distinct physical
occurrences are counted: adding another identical copy within an already
baselined file pair still creates a new finding. Ordinary line movement does not
change the content identity. Deleting one clone does not buy permission for a
different new clone.

When removing existing debt, run:

```sh
python scripts/quality.py debt --engine-root ../engine
python scripts/quality.py debt --engine-root ../engine --write-baseline
git diff -- quality/baseline.json
```

Review the resulting JSON, confirm it reflects intended removals, and rerun the
normal `debt` command. Do not refresh the baseline merely to make an unexpected
failure disappear. Producer/consumer validation can intentionally duplicate a
wire contract across independent repositories; sharing app/engine implementation
imports would violate the boundary. Review the responsibility before extracting
an abstraction.

If a specific new finding must temporarily remain, append an entry to
`exceptions.json` using its exact ID from `raw/debt.json`:

```json
{
  "module": "app.snapshot-publication",
  "finding": "REPLACE_WITH_EXACT_FINDING_ID",
  "owner": "Maintainer responsible for the follow-up",
  "reason": "Concrete reason and link/reference to the removal work",
  "expires": "YYYY-MM-DD"
}
```

The example is a template, not valid dates/IDs to copy unchanged. The actual file
is a JSON array. Supply a real future ISO date and an affected module; validation
rejects unknown modules and expired entries, and the debt gate requires the
exception's module to participate in that finding. Exceptions are visible in
the aggregate. They do not waive tests, coverage collection, syntax or security
checks. An excepted structural finding may still need attention in the module
table; the exception records why it is temporarily permitted.

## Code maps and context packets

The map joins module ownership, files, tests, documents, Python import syntax,
local symbols, template script order and declared contracts. Use `context` before
changing a critical module, then `impact` or `symbol` to inspect a small
neighborhood. The JSON is generated on demand; there is no permanent diagram of
every function.

Edges carry provenance. `static-exact` describes parsed ownership/import/script
syntax; it is not a promise about all runtime resolution. `static-heuristic`
marks inferred local calls and JavaScript symbols. `declared` relationships come
from catalog dependencies, documentation/test associations and contracts. The
current builder does not generate runtime-observed call graphs, complete dynamic
dispatch, or every cross-language fetch/database relation. Test associations are
catalog declarations, not proof that every test executes every owned symbol.

## Troubleshooting and review workflow

| Symptom | What to check |
|---|---|
| Unsupported Python/Node or missing package | Use the supported versions and all requirement files, or rebuild/run the container |
| Engine catalog missing | Set `ENGINE_ROOT`/`--engine-root` to a quality-enabled checkout and update CI's pinned `ENGINE_REF` |
| App interpreter contains `transport_matcher` | Recreate an isolated app environment; use `ENGINE_PYTHON` for engine tests |
| PostGIS test missing/skipped | Use `make quality` or provide a dedicated `TEST_POSTGRES_URI`; SQLite does not establish publication safety |
| Coverage all zero or missing JS files | Use `load-browser-script`, keep production roots included in Jest, and run the coverage sanity command |
| Unexpected console/error or leaked timer | Fix the cause or lifecycle cleanup; assert expected errors only within their test, as shown in the JS guide |
| New clone/dead-code finding | Inspect `raw/debt.json` and analyzer locations before considering a reviewed baseline/exception change |
| Report remains partial after passing tests | Inspect which measurements are unavailable; unimplemented security/mutation aggregation is not a failed test |
| Report is stale immediately after collection | Check concurrent edits, engine revision and dependency/image changes; rerun once inputs are stable |

For medium/high-risk changes, use the
[PR change contract](../.github/pull_request_template.md): intended behavior,
affected modules/contracts, invariants, acceptance/failure examples, validation,
documentation decision and recovery impact. Add meaningful regressions, update
the relevant explanation/reference pages, run focused checks while editing, and
finish with the supported complete run. Keep its verification limitations in the
review description.

## Remaining rollout work

Implemented foundations include catalogs and ownership, branch evidence from
both repositories, trustworthy browser instrumentation, clean asynchronous test
runs, correctness/style gates, executable Python boundaries, structural ratchets,
plain module reporting, bounded navigation, property examples and a scoped
mutation workflow.

Per-module security attribution is still `not_measured`; inspect audit and
CodeQL outputs directly. Mutation is measured only when the scoped artifact is
available and validated. Coverage floors, changed-line targets and mutation
survivors remain advisory.

Type checking, Knip/browser-global reachability, pinned-browser E2E/visual
snapshots, importer/query performance budgets, runtime call observations, richer
trend history and repository-specific historical agent evaluations are separate
follow-ups. Curate historical evaluation tasks from real defects with their
failing revisions and independent acceptance tests; do not fabricate evidence.
Introduce stronger gates after their inputs and operational cost are understood.
