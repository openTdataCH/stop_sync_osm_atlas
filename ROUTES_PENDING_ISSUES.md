# Routes Pipeline Analysis

Review of the full route data pipeline: acquisition, processing, matching, database import, and web app consumption.

---

## 1. OSM Data Acquisition (`get_osm_data.py` / `state.py`)

### Issue: Direction fan-out when `direction_id` is missing (do not implement)

When an OSM route relation has no `ref_trips` tag (and hence no H/R suffix), `direction_id` is left blank. The state loader in `matching_and_import_db/state.py` (`OsmState.from_xml_file()`) then fans out to **both** directions `['0', '1']`:

```python
direction_ids = [direction_id] if direction_id is not None else ['0', '1']
for did in direction_ids:
    route_entry = { ... }
```

This doubles the number of entries for every route without direction info, inflating the route token sets used in matching. It can cause false-positive route matches (an ATLAS stop with direction_id=0 will match an OSM node that truly only runs direction_id=1 but was fanned out to both).

---

## 2. GTFS Processing (`get_atlas_gtfs.py`)

### Issue: `iterrows()` / `itertuples()` in hot loops (do not implement)

`match_gtfs_to_atlas()` uses `itertuples()` over the `remaining` DataFrame. For large GTFS datasets with thousands of unmatched stops, the Python-level loop is a bottleneck. A vectorized merge-based approach would be faster.

### Issue: Parent station broadcast creates a 1-to-many explosion (do not implement)

When a GTFS stop has no platform reference (`nref` is None), the fallback broadcasts to ALL ATLAS candidates at that station:

```python
if pd.isna(nref) or not nref:
    for sloid_cand in candidates['sloid']:
        fallback_rows.append((stop_id, sloid_cand))
    continue
```

For large stations with 20+ platforms, a single parent stop_id maps to 20+ sloids. This creates many rows in the integrated GTFS data, most of which are incorrect. Every one of these then becomes a route entry in `atlas_routes_unified.csv`, inflating the route matching token sets.

**Suggestion:** Parent stations should either be excluded (since their child platform-level stops already provide the linkage) or mapped only to a single "station-level" ATLAS sloid if one exists.

### Issue: `direction` is a single representative string per route (do not implement)

`build_integrated_gtfs_data_streaming()` joins `route_directions_unique`, which takes only the `.first()` direction string per route_id. If a route has both `A → B` and `B → A`, only one is kept. This means half the direction information from GTFS is silently dropped, making direction-based matching weaker than it could be.

---

## 3. HRDF Processing (`get_atlas_hrdf.py`)

### Issue: GLEISE_LV95 file parsed in two full passes even with `two_pass=True` (do not implement)

The two-pass approach (pass 1 collects sloid → (UIC, #ref), pass 2 collects trips for those pairs) is already an optimization, but both passes still read the **entire file** line by line in Python.

### Issue: Trip key is a tuple `(trip_no, op_no)` — fragile join (do not implement)

The trip key `(parts[1], parts[2])` from GLEISE_LV95 must exactly match `(parts[1], parts[2])` from FPLAN `*Z` lines. Any whitespace or padding difference between files causes silent misses.

---

## 4. Unified Route CSV (`get_atlas_data.py :: write_unified_routes_csv_direct`)

### Issue: Schema mismatch between writer and readers (do not implement)

The CSV is written with columns `route_name_short` and `route_name_long`. However, the matching reader in `matching_and_import_db/state.py` (`AtlasState._load_routes()`) reads `route_id`, `line_name`, `direction_id`, `direction_name`, `direction_uic` but **not** `route_name_short` or `route_name_long`. Meanwhile, `matching_and_import_db/database/route_loader.py` reads them.

This isn't a bug, but it means the matching engine ignores route names entirely, only using route IDs and direction tokens. Route name matching could improve recall.

### Issue: HRDF rows have no `route_id` or `direction_id` (do not implement)

HRDF rows in the unified CSV always have `route_id=None` and `direction_id=None`. The GTFS-token matching path (P1 in the predicate) requires both `route_id` and `direction_id` to be present. HRDF data can only participate through P2 and P3 fallback paths.

---

## 5. Route Matching (`route_matching_unified.py` / `route_loader.py`)

### Issue: `_build_route_name_to_id()` re-reads GTFS `routes.txt` to build a name→ID fallback (do not implement)

In `matching_and_import_db/database/route_loader.py`, the fallback logic parses `routes.txt` to build `route_name_to_id`. The directory scanning pattern (`os.listdir` + `startswith('gtfs')`) is fragile — it expects `data/raw/gtfs*/routes.txt`, which can easily break if the folder structure slightly changes.

### Issue: Priority tiers don't consider distance weighting (do not implement)

The three matching tiers (P1: GTFS tokens, P2: HRDF UIC direction, P3: name-based direction) in `RouteMatchPredicate` iterate candidates in order and take the **first** match. There's no minimum overlap threshold — a single shared token is enough. For a stop served by 20 routes, matching on just 1 shared route may wrongly tie it to an OSM node if another node shares 15 routes but was slightly further away.

---

## 6. Database Schema (`backend/models.py`)

*(Note: The JSONB dual-storage issues and un-indexable route arrays present in older versions of this document have been **RESOLVED**. The database now cleanly normalizes route mappings via `route_atlas_stops` and `route_osm_stops` junction tables.)*

---

## 7. Web App Route Consumption (`backend/services/routes.py`)

### Issue: SQL injection risk via LIKE with user input (do not implement)

```python
atlas_params = {"route_id": f'%{route_id}%'}
```

The `LIKE` semantics mean searching for route "1" matches route "10", "11", "100-1-A", returning an amalgam of unrelated stops. 

### Issue: `REGEXP_REPLACE` in the normalized fallback prevents index usage

The fallback SQL in `get_stops_for_route` uses:
```sql
WHERE REGEXP_REPLACE(atlas_route_id, '-j[0-9]+', '-jXX') LIKE :normalized_route_id
```
Forcing an inline function (`REGEXP_REPLACE`) defeats standard B-Tree indexing on the table, resulting in a sequential scan whenever the fallback path is executed.

### Issue: No conceptual deduplication of route results

The response merges nodes via `set()` after retrieving *all* matches from *all* substring collisions. This means users looking for "Route 1" receive stops from up to 20 different, similarly named routes combined entirely, rather than conceptually filtering down to the *one* correct matching entity.

---

## Summary of Outstanding Issues

| # | Area | Issue | Impact |
|---|------|-------|--------|
| 1 | OSM | Direction fan-out to both [0,1] when missing | False-positive route matches |
| 2 | GTFS | Parent station 1-to-many broadcast | Inflated route token sets |
| 3 | Web API | `%LIKE%` matching on user input | Over-broad and blended results |
| 4 | Web API | `REGEXP_REPLACE` inline string ops | Defeats index usage for routes |
