# Problem Detection Logic

This document outlines the precise logic used to flag entries with specific problems within the transit stop matching system. Problem detection is handled by the `matching_process/problem_detection.py` module.

An entry can be flagged with one or more of the following problem types:
- Distance Problem
- Isolated Problem
- Attributes Problem

## 1. Distance Problem

A `distance_problem` is flagged to identify matched pairs of ATLAS and OSM stops that are suspiciously far apart.

### Conditions for Flagging:

A `distance_problem` is set to `True` if **all** of the following conditions are met:

1.  The stop is a `matched` stop (i.e., `stop_type` is 'matched').
2.  The `distance_m` attribute (distance in meters between the ATLAS and OSM stops) is present in the data record.
3.  The value of `distance_m` is greater than **25 meters**.

The threshold is defined by the `DISTANCE_PROBLEM_THRESHOLD` constant in `problem_detection.py`.

## 2. Isolated Problem

An `isolated_problem` is flagged to identify stops from one data source (ATLAS or OSM) that do not have a corresponding entry in the other data source within a reasonable proximity (50 meters). The detection relies on pre-computed flags.

### Conditions for Flagging:

An `isolated_problem` is set to `True` if **one** of the following sets of conditions is met:

#### For Unmatched ATLAS Stops:
- The `stop_type` is 'unmatched' (representing an ATLAS stop with no match).
- The `match_type` for the record is exactly `'no_osm_within_50m'`. This flag is set during the data import process if no OSM node is found within the 50-meter `ISOLATION_CHECK_RADIUS`.

#### For Unmatched OSM Stops:
- The `stop_type` is 'osm' (representing an OSM stop with no match).
- The record contains a boolean flag `is_isolated` which is set to `True`. This flag is pre-computed during the matching pipeline.

## 3. Attributes Problem

An `attributes_problem` is flagged to identify `matched` pairs of stops where key descriptive attributes are inconsistent between the ATLAS and OSM datasets.

### Conditions for Flagging:

An `attributes_problem` is set to `True` if **all** of the following conditions are met for a `matched` stop:

1.  The `stop_type` is 'matched'.
2.  The logic currently checks for **operator mismatch**.
3.  The ATLAS operator, stored in `csv_business_org_abbr`, is present (not null or empty string).
4.  The OSM operator, stored in `osm_operator`, is present (not null or empty string).
5.  The lowercase, whitespace-stripped version of the ATLAS operator is **not equal** to the lowercase, whitespace-stripped version of the OSM operator.

**Note:** If either the ATLAS or OSM operator is missing, an attribute problem is **not** flagged for operator mismatch. The system is designed to be extended with more attribute checks in the future (e.g., stop names, transport types). 