Evidence: **partial**. Generated: 2026-11-04T15:49:16.312455+00:00.

App revision: `3c96451c2ddf932d25b8cf943a98d16183cf00a1`. Engine revision: `3fd9a39c8c3a7b2590db0de5baf90a73b93c40de`.

Tools: coverage 7.17.1, eslint 10.11.0, hypothesis 6.168.0, jest 29.7.0, jscpd 4.3.0, jsonschema 4.26.0, node v22.23.4, pytest 9.2.0, pytest-cov 7.1.0, python 3.13.17, ruff 0.15.7, stylelint 16.26.1, vulture 2.15.

Missing measurements are explicit. Criticality is declared in the module catalog from the impact of a failure, not measured. Duplicated blocks counts code clones of at least 10 lines; "pass" means none is new since the reviewed baseline. There is no combined quality score.

| Module | Criticality | Tests | Branch coverage | Mutation | Duplicated blocks | Python dead code | Docs | Architecture |
|---|---|---|---|---|---|---|---|---|
| app.docs-delivery | medium | pass | 48.5% | not measured | 0 (pass) | 0 (pass) | 4/4 | pass |
| app.pipeline-orchestration | high | pass | 51.3% | not measured | 3 (pass) | 0 (pass) | 5/5 | pass |
| app.query-api | high | pass | 47.72% | not measured | 5 (pass) | 0 (pass) | 4/4 | pass |
| app.review-ui | high | pass | 51.4% | not measured | 3 (pass) | 0 (pass) | 4/4 | pass |
| app.snapshot-publication | critical | pass | 74.85% | not measured | 7 (pass) | 0 (pass) | 7/7 | pass |
| engine.core-matching | critical | pass | 81.32% | not measured | 2 (pass) | 0 (pass) | 6/6 | pass |
| engine.integrations | high | pass | 73.05% | not measured | 1 (pass) | 0 (pass) | 5/5 | pass |
| engine.result-producer | critical | pass | 92.0% | not measured | 5 (pass) | 0 (pass) | 7/7 | pass |
| platform.schema-deployment | critical | pass | 58.33% | not measured | 0 (pass) | 0 (pass) | 7/7 | pass |
| platform.styles-assets | medium | pass | 75.0% | not measured | 0 (pass) | not applicable | 4/4 | pass |

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

Test results, coverage and analyzer outputs are in the [CI run](https://github.com/openTdataCH/stop_sync_osm_atlas/actions/runs/41860240732) that produced this report, as the artifact `quality-3c96451c2ddf932d25b8cf943a98d16183cf00a1`. GitHub keeps it for 30 days.

For invariants, tests, documentation and dependency context, run `python scripts/quality.py context MODULE_ID`. Use `impact PATH` or `symbol NAME --depth 1` for bounded navigation. Python imports are syntax evidence; dynamic calls and JavaScript symbols are heuristic.
