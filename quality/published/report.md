Evidence: **partial**. Generated: 2026-11-09T14:26:40.212492+00:00.

App revision: `a5f12afb2655fecbcc016f8ba5a662d7b58c7567`. Engine revision: `8f892597ae04c5e72c9d87c8effb4fde0681dae3`.

Tools: coverage 7.17.2, eslint 10.11.0, hypothesis 6.168.0, jest 29.7.0, jscpd 4.3.0, jsonschema 4.26.0, node v22.23.4, pytest 9.2.0, pytest-cov 7.1.0, python 3.13.18, ruff 0.15.7, stylelint 16.26.1, vulture 2.15.

Missing measurements are explicit. Criticality is declared in the module catalog from the impact of a failure, not measured. Duplicated blocks counts code clones of at least 10 lines; "pass" means none is new since the reviewed baseline. There is no combined quality score.

| Module | Criticality | Tests | Branch coverage | Mutation | Duplicated blocks | Python dead code | Docs | Architecture |
|---|---|---|---|---|---|---|---|---|
| app.docs-delivery | medium | pass | 65.0% | not measured | 0 (pass) | 0 (pass) | 4/4 | pass |
| app.pipeline-orchestration | high | pass | 58.73% | not measured | 3 (pass) | 0 (pass) | 5/5 | pass |
| app.query-api | high | pass | 53.37% | not measured | 6 (pass) | 0 (pass) | 4/4 | pass |
| app.review-ui | high | pass | 58.12% | not measured | 1 (pass) | 0 (pass) | 4/4 | pass |
| app.snapshot-publication | critical | pass | 74.7% | not measured | 7 (pass) | 0 (pass) | 7/7 | pass |
| engine.core-matching | critical | pass | 84.83% | not measured | 1 (pass) | 0 (pass) | 6/6 | pass |
| engine.integrations | high | pass | 73.78% | not measured | 0 (pass) | 0 (pass) | 5/5 | pass |
| engine.result-producer | critical | pass | 92.0% | not measured | 5 (pass) | 0 (pass) | 7/7 | pass |
| platform.schema-deployment | critical | pass | 56.25% | not measured | 0 (pass) | 0 (pass) | 7/7 | pass |
| platform.styles-assets | medium | pass | 32.22% | not measured | 0 (pass) | 0 (pass) | 4/4 | pass |

Required check results from the recorded run:

- **catalog-and-architecture**: pass
- **python-lint**: pass
- **template-config-syntax**: pass
- **javascript-lint**: pass
- **css-lint**: pass
- **vendor-cdn**: pass
- **engine-fast**: pass
- **structural-debt**: pass
- **app-python-tests**: pass
- **javascript-tests**: pass
- **engine-python-tests**: pass
- **coverage-sanity**: pass

Raw evidence:

Test results, coverage and analyzer outputs are in the [CI run](https://github.com/openTdataCH/stop_sync_osm_atlas/actions/runs/42634092180) that produced this report, as the artifact `quality-a5f12afb2655fecbcc016f8ba5a662d7b58c7567`. GitHub keeps it for 30 days.

For invariants, tests, documentation and dependency context, run `python scripts/quality.py context MODULE_ID`. Use `impact PATH` or `symbol NAME --depth 1` for bounded navigation. Python imports are syntax evidence; dynamic calls and JavaScript symbols are heuristic.
