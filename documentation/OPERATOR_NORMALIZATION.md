## Operator Normalization

Purpose: ensure OSM `operator` tag values are comparable to ATLAS business organisation abbreviations by mapping alias strings to a canonical standard name.

### How it works

- Source of truth: `matching_process/operator_normalizations.csv` with two columns: `alias,standard_name`.
- Application point: during OSM XML parsing in `matching_process/matching_script.parse_osm_xml` we call `standardize_operator()`.
- Behavior:
  - Trim whitespace on incoming `operator`.
  - Replace with `standard_name` if an exact alias match exists in the CSV.
  - If replaced, we attach the original value as `original_operator` to the in-memory tag dict for reference only.
  - If no mapping exists, we keep the trimmed original as-is (no change flag).

### Scope and persistence

- Only OSM operators are normalized. ATLAS `servicePointBusinessOrganisationAbbreviationEn` is not normalized.
- The normalized operator flows through matching and problem detection, and is persisted to the DB in `osm_nodes.osm_operator`.
- The original un-normalized OSM operator is not stored in the DB; it is only present in match records during the pipeline for debugging/reference.

### Maintenance

- Add or adjust aliases in `matching_process/operator_normalizations.csv` as needed. Prefer maintaining all mappings in the CSV rather than code.
- Keep alias and standard_name trimmed; avoid trailing spaces.

### Rationale

- This makes operator comparisons deterministic and reduces false positives when checking attributes mismatches (see the Attributes section in problem detection).


