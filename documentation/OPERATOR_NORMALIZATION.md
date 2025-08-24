## Operator Normalization

Ensure OSM `operator` values are comparable to ATLAS abbreviations by mapping aliases to a canonical standard.

### How

- Source: `matching_process/operator_normalizations.csv` (`alias,standard_name`)
- Code: `standardize_operator()` in [matching_process/org_standardization.py](../matching_process/org_standardization.py)
- Application: during OSM XML parse in `parse_osm_xml()` ([matching_process/matching_script.py](../matching_process/matching_script.py))
- Behavior:
  - Trim input; replace with `standard_name` on exact alias match
  - If replaced, keep `original_operator` in-memory (not persisted) for reference
  - If no match, keep trimmed original

### Scope

- Only OSM operators are normalized; ATLAS `servicePointBusinessOrganisationAbbreviationEn` is not
- Persisted value: `osm_nodes.osm_operator` (normalized)

### Maintenance

- Edit `matching_process/operator_normalizations.csv` (avoid code changes)

### Why

- Stabilizes comparisons and reduces false positives in attribute mismatch checks (see [PROBLEMS_DEFINITIONS.md](./PROBLEMS_DEFINITIONS.md))


