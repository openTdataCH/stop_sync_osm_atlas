Evidence: **partial**. Generated: 2026-11-02T16:44:52.145539+00:00.

App revision: `aeca682fddaa2cbf5015d8ede1f75a7ec0dada26`. Engine revision: `ccc5d5c84c979499a1de219ddd2701c2a1ad7320`.

Tools: coverage 7.17.0, eslint 10.11.0, hypothesis 6.168.0, jest 29.7.0, jscpd 4.3.0, jsonschema 4.26.0, node v22.23.4, pytest 9.2.0, pytest-cov 7.1.0, python 3.13.17, ruff 0.15.7, stylelint 16.26.1, vulture 2.15.

Missing measurements are explicit. Criticality is declared in the module catalog from the impact of a failure, not measured. Duplicated blocks counts code clones of at least 10 lines; "pass" means none is new since the reviewed baseline. There is no combined quality score.

| Module | Criticality | Tests | Branch coverage | Mutation | Duplicated blocks | Python dead code | Docs | Architecture |
|---|---|---|---|---|---|---|---|---|
| app.docs-delivery | medium | pass | 55.62% | not measured | 0 (pass) | 0 (pass) | 4/4 | pass |
| app.pipeline-orchestration | high | pass | 51.3% | not measured | 3 (pass) | 0 (pass) | 5/5 | pass |
| app.query-api | high | pass | 45.36% | not measured | 5 (pass) | 0 (pass) | 4/4 | pass |
| app.review-ui | high | pass | 51.23% | not measured | 3 (pass) | not applicable | 4/4 | pass |
| app.snapshot-publication | critical | pass | 74.85% | not measured | 7 (pass) | 0 (pass) | 7/7 | pass |
| engine.core-matching | critical | pass | 81.24% | not measured | 2 (pass) | 0 (pass) | 6/6 | pass |
| engine.integrations | high | pass | 72.59% | not measured | 1 (pass) | 0 (pass) | 5/5 | pass |
| engine.result-producer | critical | pass | 92.0% | not measured | 5 (pass) | 0 (pass) | 7/7 | pass |
| platform.schema-deployment | critical | pass | 57.14% | not measured | 0 (pass) | 0 (pass) | 7/7 | pass |
| platform.styles-assets | medium | pass | not applicable | not measured | 0 (pass) | not applicable | 4/4 | pass |

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

Test results, coverage and analyzer outputs are in the [CI run](https://github.com/openTdataCH/stop_sync_osm_atlas/actions/runs/41483893640) that produced this report, as the artifact `quality-aeca682fddaa2cbf5015d8ede1f75a7ec0dada26`. GitHub keeps it for 30 days.

For invariants, tests, documentation and dependency context, run `python scripts/quality.py context MODULE_ID`. Use `impact PATH` or `symbol NAME --depth 1` for bounded navigation. Python imports are syntax evidence; dynamic calls and JavaScript symbols are heuristic.
