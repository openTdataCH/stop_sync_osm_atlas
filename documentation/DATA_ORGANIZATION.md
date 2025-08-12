# Data Organization and File Structure

This document outlines the data organization, which consolidates all data files into a structured `data/` directory.

## Directory Structure

```
data/
├── raw/                     # Raw downloaded data (not processed)
│   ├── osm_data.xml        # Raw OSM data from Overpass API
│   ├── stops_ATLAS.csv     # Raw ATLAS stops data
│   └── gtfs_fp2025_2024-09-30/  # Raw GTFS data directory
│       ├── stops.txt
│       ├── routes.txt
│       ├── trips.txt
│       └── stop_times.txt
├── processed/              # Processed/transformed data ready for use
│   ├── osm_nodes_with_routes.csv     # OSM nodes with route information
│   ├── osm_routes_with_nodes.csv     # OSM routes with node lists
│   ├── atlas_routes.csv              # ATLAS stops with route mappings
│   └── atlas_routes_with_stops.csv   # ATLAS routes with stop lists (optional)
└── debug/                  # Debug and review files
    ├── review_stop_ids.txt
    ├── org_mismatches_review.txt
    └── route_org_mismatches_review.txt
```

## File Descriptions

### Raw Data (`data/raw/`)

| File | Description | Source | Size |
|------|-------------|---------|------|
| `osm_data.xml` | Complete OSM data (nodes + routes) from Switzerland | Overpass API | ~50MB |
| `stops_ATLAS.csv` | Swiss public transport stops | OpenTransportData.swiss | ~15MB |
| `gtfs_fp2025_2024-09-30/` | GTFS timetable data | OpenTransportData.swiss | ~200MB |

### Processed Data (`data/processed/`)

| File | Description | Used By | Required |
|------|-------------|---------|----------|
| `osm_nodes_with_routes.csv` | OSM nodes with route/direction info (node→routes) | Route matching, Database import | ✅ Yes |
| `atlas_routes_gtfs.csv` | ATLAS stops with GTFS route/direction info | Route matching, Database import | ✅ Yes |
| `atlas_routes_hrdf.csv` | ATLAS stops with HRDF direction info | Database import | ✅ Yes |
| `atlas_routes_with_stops.csv` | Routes with lists of stops | Web interface (optional) | ❌ Optional |
| `osm_routes_with_nodes.csv` | Routes with lists of nodes (route→nodes) | Future use | ❌ Optional |

### Debug Files (`data/debug/`)

| File | Description | Purpose |
|------|-------------|---------|
| `review_stop_ids.txt` | Problematic GTFS stop IDs | Manual review |
| `org_mismatches_review.txt` | Operator mismatches (distance) | Quality assurance |
| `route_org_mismatches_review.txt` | Operator mismatches (route) | Quality assurance |