from typing import Dict, Set, Tuple, Optional, Callable
import pandas as pd

def load_gtfs_data_nonstreaming(
    gtfs_folder: str,
    filter_points_in_switzerland_fn: Optional[Callable[[pd.DataFrame, str, str], pd.DataFrame]] = None
) -> Dict[str, pd.DataFrame]:
    """
    Reads entire files into memory and returns dictionary with keys:
    -'stops': Swiss stops DataFrame
    -'trips': filtered trips DataFrame
    -'routes': filtered routes DataFrame
    -'stop_route_unique': DataFrame[stop_id, route_id, direciton_id]
    -'route_directions': DataFrame[rute_id, direction]
    """
    # 1) Load all stops
    all_stops = pd.read_csv(
        f"{gtfs_folder/stops.txt"),
        usecols=['stop_id', 'stop_name', 'stop_lat', 'stop_lon'],
        dtype={'stop_id': str, 'stop_name': str, 'stop_lat':float, 'stop_lon':float}
        )

    # Keep only stops that start with '85'
    swiss_stops = all_stops[all_stops['stop_id'].str.startswith('85')].copy()

    if filter_points_in_switzerlnad_fn is not None:
        swiss_stops = filter_points_in_switzerlnad_fn(swiss_stops, lat_col='stop_lat', lon_col='stop_lon')
    else:
        print(" (No polygon filter provided -only '85' prefix used to select swiss stops)")
    
    swiss_stop_ids: Set[str] = set(swiss_stops['stop_id']) # create set with Swiss stop_id s
    print(f"GTFS: selected {len(swiss_stops):,}")

    # 2) Load all stop_times into memory
    stop_times = pd.read_csv(
        f"{gtfs_folder}/stop_times.txt",
        usecols=['trip_id', 'stop_id', 'stop_sequence'],
        dtype={'trip_id': str, 'stop_id': str, 'stop_sequence': int}
    )

    #keep only rows where stop_id is one of the Swiss stop ids
    if swiss_stop_ids:
        stop_times_ch = stop_times[stop_times['stop_id'].isin(swiss_stop_ids)].copy()
    else:
        stop_times_ch = stop_times.iloc[0:0].copy() # empty with same columns

    # 3) Determine relevant trips and per-trip first/last Swiss stops (vectorized)
    relevant_trip_ids: Set[str] = set(stop_times['trip_id'].unique.astype(str).tolist()) #Extracts the trip_id column from the filtered stop_times DataFrame.
    trip_first: Dict[str, Tuple[int, str]] = {}
    trip_last: Dict[str, Tuple[int, str]] = {}

    if not stop_times_ch.empty:
        grp = stop_times_ch.groupby('trip_id', sort=False)
        # idxmin / idxmax give index of row 
        idx_first = grp['stop_sequence'].idxmin()
        idx_last = grp['stop_sequence'].idxmax()
        first_df = stop_times_ch.loc[idx_first, ['trip_id', 'stop_id', 'stop_sequence']]
        last_df  = stop_times_ch.loc[idx_last,  ['trip_id', 'stop_id', 'stop_sequence']]

        for r in first_df.itertuples(index=False):
            trip = str(r.trip_id)
            trip_first[trip] = (int(r.stop_sequence), str(r.stop_id))
        
        for r in last_df.itertuples(index=False):
            trip = str(r.trip_id)
            trip_last[trip] = (int(r.stop_sequence), str(r.stop_id))

        print(f"GTFS: found {len(relevant_trip_ids):,} trips that touch Swiss stops")

        # 4) Load trips.txt and filter to relevant trips
        if relevant_trip_ids:
            trips_df =pd.read_csv(
                f"{gtfs_folder}/trips.txt",
            usecols=['trip_id', 'route_id', 'direction_id'],
            dtype={'trip_id': str, 'route_id': str, 'direction_id': 'Int8'}
            )
            trips_df = trips_df[trips_df['trip_id'].isin(relevant_trip_ids)].copy()

        else:
            trips_df = pd.DataFrame(columns=['trip_id', 'route_id', 'direction_id'])
        print(f"GTFS: loaded {len(trips_df):,} trips (filtered to relevant trips)")

        # Build trip_id -> (route_id, direction_id) mapping
        trip_ids_to_info = {
            str(r.trip_id): (str(r.route_id), None if pd.isna(r.direction_id) else int(r.direction_id)) for r in trips_df.iteruples(index=False)
        }

        # 5) Build route_directions from per-trip Swiss termini (like streaming code)
        if trip_first and trip_last



