# Contributing to Transport Matcher

Install the engine in editable mode and run a small example before changing a rule:

```bash
python -m pip install -e '.[test,gtfs,swiss,acquisition]'
python -m pytest tests
```

For only the core, install `.[test]` and run `tests/test_api.py`, `tests/test_matching_regressions.py` and `tests/test_results.py`. Those tests use normalized records, do not import adapters and need no network, database or review application.

## Add or improve a predicate

1. Add a small failing example using `SourceStop` and `OsmNode` in `tests/`. Assert expected identity pairs, not only total counts. Include the ambiguous or negative case that could create a false positive.
2. Edit or add a class in `src/transport_matcher/core/predicates/`. Subclass `BasePredicate` and implement `run(ctx)`. Read candidates from `ctx.source` and `ctx.osm` and record accepted links with `ctx.commit(...)`.
3. For a new public stage, register its factory in `api._predicates` and add its identifier to the desired profile's `predicate_names`. Record its inputs, assumptions and ordering below or in the module docstring.
4. Run the affected regression and the core suite. Preserve group propagation and candidate locks. Build reusable attribute indexes once per rule. Batch queries can contain candidates consumed by an earlier iteration; filter those candidates before committing. The 100-reference regression prevents repeated full OSM scans during exact matching.

`ctx.commit` expands source duplicates and OSM pairs. Trio sides have their own predicate; never propagate a direct match to a trio middle. Exact station references intentionally support one-to-many and many-to-one links. Changing these allocation rules requires explicit regression cases.

| Stage identifier | Inputs and assumptions | Default position |
|---|---|---|
| `trio` | Profile-approved station references; two source stops, two OSM sides and one nearby middle. | First, before exact matching. |
| `exact` | A profile rule with compatible reference namespace, scope and OSM tag. Platform codes refine station candidates. | Before weaker evidence. |
| `name` | Exact source name against OSM name/UIC-name/GTFS-name; platform code can disambiguate. | Before route/distance. |
| `route` | Scoped route IDs and direction IDs, or direction labels; mutual unique best candidate. | Before distance. |
| `group_proximity` | Name or approved station groups; maximum-cardinality assignment under the distance cap. | First distance stage. |
| `long_distance_group_proximity` | Same evidence under the profile's longer cap. | After normal group proximity. |
| `local_ref` | Equal platform/local reference within the normal distance cap. | Before nearest-only rules. |
| `nearest_single`, `nearest_ratio`, `nearest_second` | Spatial candidates and compatible platform codes; single candidate or sufficient separation from the second candidate. | Last, in that order. |

Name equality alone can be ambiguous across cities. The generic profile caps name matching at 1 km. Swiss behavior retains its historical unrestricted name stage. Route labels are weaker evidence than scoped route IDs. Profile options make such tradeoffs visible.

## Support another dataset

Create an adapter under `adapters/` that produces `SourceStop` records and optionally a `SourceState` with explicit duplicate groups and route evidence. Keep source IDs as strings and select a stable namespace without a colon. Preserve source-specific fields under `extensions`; core predicates must not require them.

Use existing GTFS parsing when possible. Add a profile with reference mappings, thresholds and any grouping policy. Never infer that equal stop IDs or route IDs from different feeds mean the same entity. If an OSM extract's unscoped GTFS tags are assigned to a feed, make that adapter configuration explicit.

Include an offline fixture covering at least one accepted match, one unmatched source stop, one unmatched OSM element and missing optional route data. Do not put file reading, pandas, environment lookups, Flask or SQLAlchemy in the core. Parser/acquisition dependencies belong in optional extras in `pyproject.toml`.

## Understand or report a bad match

Include the dataset namespace, source ID, OSM type/ID, observed rule, expected link and a small relevant extract. A regression should explain why an adjacent candidate is wrong. Do not include credentials, private dataset URLs or a national dump.

Result schemas are versioned separately from the engine package. Changing fields consumed by the review app requires updating `RESULT_FORMAT.md`, contract fixtures and importer compatibility checks. A failed engine run or bundle validation must not replace an earlier published bundle.

No commit or push is required to run tests or propose a patch. Preserve the repository's AGPL-3.0-or-later license notice when extracting files.
