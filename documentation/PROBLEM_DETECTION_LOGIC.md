# Problem Detection Logic

This document outlines the precise logic used to flag entries with specific problems. Problem detection is centrally managed by the [`matching_process/problem_detection.py`](../matching_process/problem_detection.py) module, with configuration defined in [`matching_process/detection_config.py`](../matching_process/detection_config.py).

An entry can be flagged with one or more of the following problem types:
- **Distance Problem** - When matched stops are too far apart
- **Isolated Problem** - When stops have no counterpart in the other dataset
- **Attributes Problem** - When matched stops have conflicting information

## Configuration

All detection thresholds and parameters are centralized in [`matching_process/detection_config.py`](../matching_process/detection_config.py):

- `ISOLATION_CHECK_RADIUS_M` = 50 meters (isolation detection radius)
- `DISTANCE_PROBLEM_THRESHOLD_M` = 25 meters (maximum acceptable distance for matched pairs)
- `ENABLE_OPERATOR_MISMATCH_CHECK` = True (configurable operator mismatch detection)

## 1. Distance Problem

A `distance_problem` is flagged to identify matched pairs of ATLAS and OSM stops that are suspiciously far apart.

### Detection Location
- **Function**: `detect_distance_problems()` in [`matching_process/problem_detection.py`](../matching_process/problem_detection.py)
- **Called from**: `analyze_stop_problems()` in the same module
- **Applied during**: Database import in [`import_data_db.py`](../import_data_db.py)

### Conditions for Flagging

A `distance_problem` is set to `True` if **all** of the following conditions are met:

1. The stop is a `matched` stop (i.e., `stop_type` is 'matched')
2. The `distance_m` attribute (distance in meters between the ATLAS and OSM stops) is present in the data record
3. The value of `distance_m` is greater than the configured threshold (currently **25 meters**)

The threshold is defined by `DISTANCE_PROBLEM_THRESHOLD_M` in [`matching_process/detection_config.py`](../matching_process/detection_config.py) and accessed via `get_distance_problem_threshold()`.

## 2. Isolated Problem

An `isolated_problem` is flagged to identify stops from one data source (ATLAS or OSM) that do not have a corresponding entry in the other data source within the configured isolation radius.

### Detection Location
- **Core Functions**: 
  - `detect_atlas_isolation()` and `detect_osm_isolation()` in [`matching_process/problem_detection.py`](../matching_process/problem_detection.py)
  - `detect_isolated_problems()` for individual stop analysis
- **Called from**: 
  - ATLAS isolation: Stage 4 of [`matching_process/distance_matching.py`](../matching_process/distance_matching.py) 
  - OSM isolation: [`matching_process/matching_script.py`](../matching_process/matching_script.py) final pipeline
- **Applied during**: Database import in [`import_data_db.py`](../import_data_db.py)

### Detection Process

The isolation detection uses a two-phase approach:

#### Phase 1: Spatial Analysis

The isolation radius is defined by `ISOLATION_CHECK_RADIUS_M` in [`matching_process/detection_config.py`](../matching_process/detection_config.py) (currently **50 meters**).

1. **ATLAS Isolation**: During distance matching (Stage 4), ATLAS stops with no OSM nodes within the isolation radius are flagged with `match_type` = `'no_nearby_counterpart'` 
2. **OSM Isolation**: After all matching phases, remaining unmatched OSM nodes are checked against all ATLAS stops using efficient spatial indexing (KDTree)

#### Phase 2: Problem Flagging
During database import, the `detect_isolated_problems()` function identifies isolation problems based on:

### Conditions for Flagging

An `isolated_problem` is set to `True` if **any** of the following conditions is met:

1. **ATLAS stops**: `stop_type` is 'unmatched' AND `match_type` is `'no_nearby_counterpart'`
2. **OSM nodes**: `stop_type` is 'osm' AND `is_isolated` flag is `True`
3. **Unified approach**: Any stop with `is_isolated` flag set to `True`

### Database Storage

Isolation problems are stored in the database using a dual approach:

1. **Problems Table**: Each isolation problem creates a record in the `problems` table with `problem_type` = 'isolated', linked to the stop via `stop_id`
2. **Match Type Column**: ATLAS stops with no nearby OSM counterparts also have their `match_type` set to `'no_nearby_counterpart'` in the `stops` table

This dual storage enables both individual problem tracking and aggregate statistics about potential matching opportunities.

## 3. Attributes Problem

An `attributes_problem` is flagged to identify `matched` pairs of stops where key descriptive attributes are inconsistent between the ATLAS and OSM datasets.

### Detection Location
- **Function**: `detect_attribute_problems()` in [`matching_process/problem_detection.py`](../matching_process/problem_detection.py)
- **Called from**: `analyze_stop_problems()` in the same module
- **Applied during**: Database import in [`import_data_db.py`](../import_data_db.py)

### Current Checks

The system supports four configurable attribute checks:

#### 1. Operator Mismatch Check
- **Enabled by**: `ENABLE_OPERATOR_MISMATCH_CHECK` in [`matching_process/detection_config.py`](../matching_process/detection_config.py)
- **Default**: True (enabled)
- **Comparison**: ATLAS `csv_business_org_abbr` vs OSM `osm_operator`

#### 2. Name Mismatch Check
- **Enabled by**: `ENABLE_NAME_MISMATCH_CHECK` in [`matching_process/detection_config.py`](../matching_process/detection_config.py)
- **Default**: True (enabled)
- **Comparison**: ATLAS `atlas_designation_official` vs OSM `osm_uic_name`

#### 3. Local Reference Mismatch Check
- **Enabled by**: `ENABLE_LOCAL_REF_MISMATCH_CHECK` in [`matching_process/detection_config.py`](../matching_process/detection_config.py)
- **Default**: True (enabled)
- **Comparison**: ATLAS `atlas_designation` vs OSM `osm_local_ref`

#### 4. UIC Reference Mismatch Check
- **Enabled by**: `ENABLE_UIC_MISMATCH_CHECK` in [`matching_process/detection_config.py`](../matching_process/detection_config.py)
- **Default**: True (enabled)
- **Comparison**: ATLAS `uic_ref` vs OSM `uic_ref`

### Conditions for Flagging

An `attributes_problem` is set to `True` if a `matched` stop has **any** attribute mismatch where:

1. The `stop_type` is 'matched'
2. The specific attribute check is enabled in configuration
3. Both the ATLAS and OSM values for that attribute are present (not null or empty string)
4. The values don't match according to the comparison rules:
   - **Operator, Name, Local Ref**: Case-insensitive comparison after whitespace stripping
   - **UIC Reference**: Exact string match (case-sensitive)

**Note:** If either the ATLAS or OSM value is missing for a specific attribute, that attribute check is **not** flagged to avoid false positives. The system only flags mismatches when both values are present and different.

---