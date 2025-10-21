## `load_gtfs_data_streaming`

A memory-efficient loader for GTFS that focuses on Swiss stops and performs two streaming passes over `stop_times.txt` to avoid building huge DataFrames.

- **Goal**: Build compact, analysis-ready pieces:
  - `stops`: Swiss stops within the CH border
  - `trips`: only trips that touch those Swiss stops
  - `routes`: only routes referenced by those trips
  - `stop_route_unique`: unique `(stop_id, route_id, direction_id)` triples
  - `route_directions`: readable strings like "A → B" per `route_id`

### 1) Load Swiss stops and clip to country border
```python
all_stops = pd.read_csv(
    f"{gtfs_folder}/stops.txt",
    usecols=['stop_id', 'stop_name', 'stop_lat', 'stop_lon'],
    dtype={'stop_id': str, 'stop_name': str, 'stop_lat': float, 'stop_lon': float}
)
swiss_stops = all_stops[all_stops['stop_id'].str.startswith('85')].copy()
# Filter by precise Swiss border (polygon)
swiss_stops = filter_points_in_switzerland(swiss_stops, lat_col='stop_lat', lon_col='stop_lon')
swiss_stop_ids: Set[str] = set(swiss_stops['stop_id'])
```
- **What it does**: Reads stops, keeps only those whose IDs start with `85` (Swiss UIC prefix), then spatially clips to the Switzerland polygon for accurate borders.

### 2) First streaming pass over `stop_times.txt`
```python
relevant_trip_ids: Set[str] = set()
trip_first: Dict[str, Tuple[int, str]] = {}
trip_last: Dict[str, Tuple[int, str]] = {}

chunk_size = 500000
for chunk in pd.read_csv(
    f"{gtfs_folder}/stop_times.txt",
    usecols=['trip_id', 'stop_id', 'stop_sequence'],
    dtype={'trip_id': str, 'stop_id': str, 'stop_sequence': int},
    chunksize=chunk_size
):
    mask = chunk['stop_id'].isin(swiss_stop_ids)
    if not mask.any():
        continue

    swiss_chunk = chunk[mask]

    # Collect relevant trips
    relevant_trip_ids.update(swiss_chunk['trip_id'].astype(str).unique().tolist())

    # For each trip: track earliest and latest Swiss stop_sequence
    grp = swiss_chunk.groupby('trip_id', sort=False)
    idx_first = grp['stop_sequence'].idxmin()
    idx_last = grp['stop_sequence'].idxmax()
    first_df = swiss_chunk.loc[idx_first, ['trip_id', 'stop_id', 'stop_sequence']]
    last_df  = swiss_chunk.loc[idx_last,  ['trip_id', 'stop_id', 'stop_sequence']]

    for r in first_df.itertuples(index=False):
        trip_first[str(r.trip_id)] = min(
            trip_first.get(str(r.trip_id), (r.stop_sequence, r.stop_id)),
            (int(r.stop_sequence), str(r.stop_id)),
            key=lambda x: x[0]
        )
    for r in last_df.itertuples(index=False):
        trip_last[str(r.trip_id)] = max(
            trip_last.get(str(r.trip_id), (r.stop_sequence, r.stop_id)),
            (int(r.stop_sequence), str(r.stop_id)),
            key=lambda x: x[0]
        )
```
- **What it does**: Reads `stop_times.txt` in big chunks, keeps rows whose `stop_id` is Swiss, collects all `trip_id`s touching Switzerland, and saves each trip’s first/last Swiss stop (by `stop_sequence`).

### 3) Load only those trips, then map each `trip_id` → `(route_id, direction_id)`
```python
if relevant_trip_ids:
    trips_df = pd.read_csv(
        f"{gtfs_folder}/trips.txt",
        usecols=['trip_id', 'route_id', 'direction_id'],
        dtype={'trip_id': str, 'route_id': str, 'direction_id': 'Int8'}
    )
    trips_df = trips_df[trips_df['trip_id'].isin(relevant_trip_ids)].copy()
else:
    trips_df = pd.DataFrame(columns=['trip_id', 'route_id', 'direction_id'])

trip_id_to_info: Dict[str, Tuple[str, Optional[int]]] = {
    str(r.trip_id): (str(r.route_id), None if pd.isna(r.direction_id) else int(r.direction_id))
    for r in trips_df.itertuples(index=False)
}
```
- **What it does**: Loads a filtered `trips` table only for the relevant `trip_id`s and builds a quick lookup for route/direction by `trip_id`.

### 4) Derive friendly route direction strings (first → last)
```python
if trip_first and trip_last:
    stop_id_to_name = dict(zip(
        swiss_stops['stop_id'].astype(str),
        swiss_stops['stop_name'].astype(str)
    ))
    route_directions_rows = []
    for trip_id, (seq_min, stop_min) in trip_first.items():
        last_info = trip_last.get(trip_id)
        if trip_id not in trip_id_to_info or last_info is None:
            continue
        route_id, _ = trip_id_to_info[trip_id]
        first_name = stop_id_to_name.get(stop_min, 'Unknown')
        last_name  = stop_id_to_name.get(last_info[1], 'Unknown')
        route_directions_rows.append((route_id, f"{first_name} → {last_name}"))

    route_directions = (
        pd.DataFrame(route_directions_rows, columns=['route_id', 'direction'])
        .dropna()
        .drop_duplicates()
    )
else:
    route_directions = pd.DataFrame(columns=['route_id', 'direction'])
```
- **What it does**: For each trip, look up the names of its first/last Swiss stops and generate a human-readable direction string, then deduplicate per `route_id`.

### 5) Second streaming pass: unique `(stop_id, route_id, direction_id)` triples
```python
stop_route_unique_set: Set[Tuple[str, str, Optional[int]]] = set()

for chunk in pd.read_csv(
    f"{gtfs_folder}/stop_times.txt",
    usecols=['trip_id', 'stop_id', 'stop_sequence'],
    dtype={'trip_id': str, 'stop_id': str, 'stop_sequence': int},
    chunksize=chunk_size
):
    mask = chunk['stop_id'].isin(swiss_stop_ids)
    if not mask.any():
        continue

    swiss_chunk = chunk[mask][['trip_id', 'stop_id']].copy()
    if swiss_chunk.empty:
        continue

    # Vectorized join of trips → (route_id, direction_id)
    trips_small = pd.DataFrame(
        [(k, v[0], v[1]) for k, v in trip_id_to_info.items()],
        columns=['trip_id', 'route_id', 'direction_id']
    )
    joined = swiss_chunk.merge(trips_small, on='trip_id', how='inner')[
        ['stop_id', 'route_id', 'direction_id']
    ]

    if not joined.empty:
        for t in joined.drop_duplicates().itertuples(index=False):
            stop_route_unique_set.add((
                str(t.stop_id),
                str(t.route_id),
                None if pd.isna(t.direction_id) else int(t.direction_id)
            ))

stop_route_unique = pd.DataFrame(
    list(stop_route_unique_set),
    columns=['stop_id', 'route_id', 'direction_id']
) if stop_route_unique_set else pd.DataFrame(
    columns=['stop_id', 'route_id', 'direction_id']
)
```
- **What it does**: Streams `stop_times.txt` again, but now merges with the trip mapping to emit unique `(stop_id, route_id, direction_id)` combinations for Swiss stops.

### 6) Load only routes we actually reference
```python
relevant_route_ids: Set[str] = set(trips_df['route_id'].unique())
if relevant_route_ids:
    all_routes = pd.read_csv(
        f"{gtfs_folder}/routes.txt",
        usecols=['route_id', 'route_short_name', 'route_long_name'],
        dtype={'route_id': str, 'route_short_name': str, 'route_long_name': str}
    )
    swiss_routes = all_routes[all_routes['route_id'].isin(relevant_route_ids)].copy()
else:
    swiss_routes = pd.DataFrame(columns=['route_id', 'route_short_name', 'route_long_name'])
```
- **What it does**: Filters `routes.txt` so we only keep rows that are actually referenced by the filtered trips.

### 7) Return compact, analysis-ready pieces
```python
return {
    'stops': swiss_stops,
    'trips': trips_df,
    'routes': swiss_routes,
    'stop_route_unique': stop_route_unique,
    'route_directions': route_directions,
}
```
- **What it does**: Returns a small set of DataFrames you can immediately use downstream without loading gigantic tables into memory.

## Why it’s memory-lean
- **Chunked reading**: Processes `stop_times.txt` in large but bounded chunks; never materializes the full table.
- **Early filtering**: Limits to Swiss stops early to shrink subsequent operations.
- **Set/dict accumulation**: Tracks only necessary keys and small summaries (first/last stop per trip) between passes.
- **Targeted loads**: Loads `trips` and `routes` only for referenced IDs.

## Expected return schema
- **stops**: `stop_id`, `stop_name`, `stop_lat`, `stop_lon` (Swiss, clipped to CH)
- **trips**: `trip_id`, `route_id`, `direction_id` (filtered to relevant trips)
- **routes**: `route_id`, `route_short_name`, `route_long_name` (referenced only)
- **stop_route_unique**: unique `(stop_id, route_id, direction_id)`
- **route_directions**: `route_id`, `direction` (string like "Zürich HB → Bern")

## Minimal usage example
```python
from Download_and_process_data.get_atlas_gtfs import load_gtfs_data_streaming

gtfs_folder = "data/raw/gtfs"  # or result of download_and_extract_gtfs(...)
parts = load_gtfs_data_streaming(gtfs_folder)

stops = parts['stops']
trips = parts['trips']
routes = parts['routes']
stop_route_unique = parts['stop_route_unique']
route_directions = parts['route_directions']
```
