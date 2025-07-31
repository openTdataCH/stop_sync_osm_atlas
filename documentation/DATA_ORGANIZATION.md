# Data Organization and File Structure

This document outlines the cleaned-up data organization for the bachelor project, which consolidates all data files into a structured `data/` directory.

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
| `osm_nodes_with_routes.csv` | OSM nodes with route/direction info | Route matching, Database import | ✅ Yes |
| `atlas_routes.csv` | ATLAS stops with route/direction info | Route matching, Database import | ✅ Yes |
| `atlas_routes_with_stops.csv` | Routes with lists of stops | Web interface (optional) | ❌ Optional |
| `osm_routes_with_nodes.csv` | Routes with lists of nodes | Future use | ❌ Optional |

### Debug Files (`data/debug/`)

| File | Description | Purpose |
|------|-------------|---------|
| `review_stop_ids.txt` | Problematic GTFS stop IDs | Manual review |
| `org_mismatches_review.txt` | Operator mismatches (distance) | Quality assurance |
| `route_org_mismatches_review.txt` | Operator mismatches (route) | Quality assurance |

## Changes Made

### Files Eliminated
- **`osm_nodes.xml`** - Redundant (can be extracted from `osm_data.xml` when needed)
- **`route_matches.csv`** - Debug file, not needed for production

### Files Optimized
- **`atlas_routes_with_stops.csv`** - Now optional, controlled by `CREATE_ROUTES_WITH_STOPS` environment variable
- Debug files moved to dedicated `data/debug/` directory

### Path Updates
All scripts updated to use the new structure:
- `get_osm_data.py` → Uses `data/raw/` and `data/processed/`
- `get_atlas_data.py` → Uses `data/raw/` and `data/processed/`
- `matching_process/` → Updated to read from `data/processed/`
- `import_data_db.py` → Updated to read from `data/processed/`

## Environment Variables

### `CREATE_ROUTES_WITH_STOPS`
- **Default**: `false`
- **Purpose**: Controls creation of `atlas_routes_with_stops.csv`
- **Usage**: Set to `true` only if the web interface needs route-to-stops mapping

## Benefits

### 1. **Cleaner Project Structure**
- All data files contained in `data/` directory
- Clear separation between raw, processed, and debug data
- Project root no longer cluttered with data files

### 2. **Reduced File Count**
- **Before**: 8-9 data files in project root
- **After**: 3 directories with organized files
- Eliminated 1 redundant file (`osm_nodes.xml`)

### 3. **Improved Performance**
- Optional creation of expensive `atlas_routes_with_stops.csv`
- Debug files only created when needed
- Memory-efficient processing maintained

### 4. **Better Docker Integration**
- Single `./data:/app/data` volume mount
- Persistent data across container restarts
- Environment variables for optimization

### 5. **Easier Maintenance**
- Clear file dependencies documented
- Standardized paths across all scripts
- Debug files organized for review

## Migration Notes

### For Development
- Existing data files can be moved to appropriate `data/` subdirectories
- Docker Compose automatically creates the structure
- Set `CREATE_ROUTES_WITH_STOPS=false` for faster processing

### For Production
- All file paths are automatically handled by updated scripts
- No manual intervention required
- Environment variables provide optimization control

## Future Improvements

1. **Incremental Updates**: Only download changed data
2. **Data Validation**: Automated checks for data quality
3. **Compression**: Compress large raw files
4. **Archiving**: Keep historical versions of data 