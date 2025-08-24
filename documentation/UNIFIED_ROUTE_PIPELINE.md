## Unified Route Pipeline

Produce a provenance-preserving, unified route dataset for route-based matching and the UI/API.

### Output

- `data/processed/atlas_routes_unified.csv`
  - Columns: `sloid, source, evidence, as_of, route_id, route_id_normalized, route_name_short, route_name_long, line_name, direction_id, direction_name, direction_uic`
  - One row per source; keep both when GTFS and HRDF exist for the same sloid/direction

### Generation

Run [get_atlas_data.py](../get_atlas_data.py)
- Downloads ATLAS, GTFS, HRDF
- Writes `atlas_routes_unified.csv` via `write_unified_routes_csv_direct()`
  - GTFS: integrates `stop_id → sloid`, dedups `(stop_id, route_id, direction_id)`, derives a representative `direction`
  - HRDF: derives `(line_name, direction_name, direction_uic)` from GLEISE/FPLAN

### Matching usage

[matching_process/route_matching_unified.py](../matching_process/route_matching_unified.py)
- Loads unified routes once
- Builds per-sloid tokens:
  - GTFS: `(route_id, direction_id)` and `(route_id_normalized, direction_id)`
  - HRDF: `(line_name, direction_uic)`; `direction_name` for display
- Builds per-node OSM tokens from `data/processed/osm_nodes_with_routes.csv` and derives name/UIC directions from OSM XML
- Priority: P1 route_id → P2 normalized route_id → P3 HRDF line+uic → P4 direction_name fallback
- Emits `match_type` `route_unified_gtfs` or `route_unified_hrdf`

### Database

- `backend/models.AtlasStop.routes_unified` stores unified entries per sloid (JSON)
- `backend/models.RouteAndDirection` stores consolidated per-route/direction groupings

### Import

`import_to_database()` in [import_data_db.py](../import_data_db.py)
- Loads unified routes and writes to `AtlasStop.routes_unified`
- Builds `RouteAndDirection` rows (matched, osm_only, atlas_only)

### UI/API

- Unified routes serialized in the stop payloads; UI popups show compact, source-tagged lists

### Notes

- `route_id_normalized` removes `-jYY` suffixes (keeps original `route_id`)
- HRDF `direction_uic` is the canonical direction key; `direction_name` is display-only


