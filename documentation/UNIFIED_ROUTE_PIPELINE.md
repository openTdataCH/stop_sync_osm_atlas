### Unified Route Pipeline

This document describes the single-source route pipeline that produces a provenance-preserving dataset for route-based matching and downstream APIs/UI.

### Outputs
- data/processed/atlas_routes_unified.csv
  - Columns: sloid, source, evidence, as_of, route_id, route_id_normalized, route_name_short, route_name_long, line_name, direction_id, direction_name, direction_uic
  - One row per source. Keep both when both sources exist for the same stop/route/direction.

### Generation
1) Run get_atlas_data.py
   - Downloads ATLAS, GTFS, HRDF
   - Produces:
     - data/processed/atlas_routes_unified.csv (union with provenance and normalized identifiers)

### Matching
- matching_process/route_matching_unified.py
  - Loads unified routes once
  - Builds ATLAS tokens per sloid:
    - GTFS: (route_id, direction_id) and (route_id_normalized, direction_id), names optional
    - HRDF: (line_name, direction_uic), plus direction_name for display
  - Builds OSM tokens from data/processed/osm_nodes_with_routes.csv and OSM relations
  - Priority order:
    - P1: (route_id, direction_id)
    - P2: (route_id_normalized, direction_id)
    - P3: (line_name, direction_uic)
    - P4: name-based fallback using direction_name
  - Emits match_type route_unified_gtfs or route_unified_hrdf

### Database
- Atlas stops
  - backend/models.AtlasStop.routes_unified JSON contains the list of unified route entries per sloid
- Consolidated routes table
  - backend/models.RouteAndDirection includes:
    - source, atlas_line_name, direction_uic, route_id_normalized
    - indexes: idx_atlas_route_direction, idx_osm_route_direction, idx_atlas_line_direction_uic, idx_source

### Import
- import_data_db.import_to_database
  - Loads unified routes and stores them in AtlasStop.routes_unified
  - Builds consolidated RouteAndDirection rows for GTFS and HRDF sources

### API
- Unified routes are serialized under routes_unified for each ATLAS stop
- Route stops endpoint accepts both route_id (GTFS) and line_name (HRDF) via LIKE; normalized matching for GTFS supported

### UI
- Popup uses routes_unified and shows a compact list with source chips, names, and direction text

### Running end-to-end
1) Data generation
   - python get_atlas_data.py
   - python get_osm_data.py (after obtaining data/raw/osm_data.xml or running the Overpass query)
2) DB migrations
   - export FLASK_APP=backend/app.py
   - flask db upgrade
3) Import
   - python import_data_db.py

### Notes
- route_id_normalized removes jYY suffixes for stability while keeping original route_id
- HRDF direction_uic is the canonical direction key; direction_name is display-only


