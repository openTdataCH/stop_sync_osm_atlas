import os
import xml.etree.ElementTree as ET
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from collections import defaultdict, Counter


GENEVA_BBOX = {
    'min_lat': 46.17,
    'max_lat': 46.30,
    'min_lon': 6.04,
    'max_lon': 6.20,
}


def ensure_dirs():
    fig_dir = os.path.join('memoire', 'figures', 'chap4')
    os.makedirs(fig_dir, exist_ok=True)
    return fig_dir


def in_bbox(lat, lon, bbox=GENEVA_BBOX):
    return (
        (lat >= bbox['min_lat']) and (lat <= bbox['max_lat']) and
        (lon >= bbox['min_lon']) and (lon <= bbox['max_lon'])
    )


def plot_lines(lines, title, out_path, color, lw=0.6, alpha=0.7):
    if not lines:
        print(f"No lines to plot for {title}")
        return
    plt.figure(figsize=(7.2, 5.6), dpi=150)
    for seg in lines:
        if len(seg) < 2:
            continue
        xs = [p[1] for p in seg]
        ys = [p[0] for p in seg]
        plt.plot(xs, ys, color=color, lw=lw, alpha=alpha)
    plt.title(title)
    plt.xlabel('Longitude')
    plt.ylabel('Latitude')
    plt.tight_layout()
    plt.savefig(out_path)
    plt.close()
    print(f"Saved figure to {out_path}")


def plot_osm_route_lines(fig_dir):
    xml_path = os.path.join('data', 'raw', 'osm_data.xml')
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
    except Exception as e:
        print('Error parsing OSM XML:', e)
        return

    # Build node_id -> (lat, lon)
    node_coords = {}
    for node in root.findall('.//node'):
        nid = node.get('id')
        try:
            lat = float(node.get('lat'))
            lon = float(node.get('lon'))
        except Exception:
            continue
        node_coords[nid] = (lat, lon)

    lines = []
    # For each route relation, use member nodes order if ways are not available
    for rel in root.findall('.//relation'):
        is_route = any(t.get('k') == 'type' and t.get('v') == 'route' for t in rel.findall('./tag'))
        if not is_route:
            continue
        # If the feed contains only node members, approximate polylines by node order
        nd_refs = [mem.get('ref') for mem in rel.findall("./member[@type='node']")]
        if nd_refs and len(nd_refs) >= 2:
            seg = []
            for nid in nd_refs:
                coord = node_coords.get(nid)
                if coord and in_bbox(coord[0], coord[1]):
                    seg.append(coord)
            # split into contiguous segments to avoid long jumps
            if len(seg) >= 2:
                lines.append(seg)

    out_path = os.path.join(fig_dir, 'geneva_osm_route_lines.png')
    plot_lines(lines, 'OSM: route relation lines (Geneva area)', out_path, color='#2ca02c', lw=0.7, alpha=0.8)


def plot_gtfs_trip_lines(fig_dir, max_trips=500):
    gtfs_root = os.path.join('data', 'raw', 'gtfs')
    stops_path = os.path.join(gtfs_root, 'stops.txt')
    stop_times_path = os.path.join(gtfs_root, 'stop_times.txt')
    trips_path = os.path.join(gtfs_root, 'trips.txt')
    if not (os.path.exists(stops_path) and os.path.exists(stop_times_path) and os.path.exists(trips_path)):
        print('GTFS files not found for trip lines')
        return

    stops = pd.read_csv(stops_path, dtype=str, usecols=['stop_id', 'stop_lat', 'stop_lon'])
    stops['stop_lat'] = pd.to_numeric(stops['stop_lat'], errors='coerce')
    stops['stop_lon'] = pd.to_numeric(stops['stop_lon'], errors='coerce')
    stops = stops.dropna(subset=['stop_lat', 'stop_lon'])

    # Filter stops to Geneva bbox
    stops_ge = stops[stops.apply(lambda r: in_bbox(r['stop_lat'], r['stop_lon']), axis=1)].copy()
    stop_set = set(stops_ge['stop_id'])

    # Stop times only for trips that touch bbox
    st = pd.read_csv(
        stop_times_path,
        dtype={'trip_id': str, 'stop_id': str, 'stop_sequence': str},
        usecols=['trip_id', 'stop_id', 'stop_sequence'],
        engine='python',
        on_bad_lines='skip'
    )
    # coerce stop_sequence to int safely
    st['stop_sequence'] = pd.to_numeric(st['stop_sequence'], errors='coerce')
    st = st.dropna(subset=['stop_sequence'])
    st['stop_sequence'] = st['stop_sequence'].astype(int)
    st = st[st['stop_id'].isin(stop_set)].copy()
    if st.empty:
        print('No GTFS trips crossing Geneva bbox')
        return

    # Select top repeated trip sequences within bbox (by exact stop_id sequence)
    lines = []
    trip_ids = st['trip_id'].unique().tolist()
    # Reconstruct ordered sequences per trip using only in-bbox stops
    seq_map = {}
    for tid, g in st.groupby('trip_id'):
        seq = tuple(g.sort_values('stop_sequence')['stop_id'].tolist())
        if len(seq) >= 2:
            seq_map[tid] = seq
    # Count repeated sequences
    seq_counts = Counter(seq_map.values())
    repeated_seqs = {seq for seq, c in seq_counts.items() if c >= 2}
    # Choose up to max_trips sequences, prioritizing repeated ones
    chosen_tids = [tid for tid, seq in seq_map.items() if seq in repeated_seqs]
    if len(chosen_tids) < max_trips:
        # fill with arbitrary others
        extra = [tid for tid in trip_ids if tid not in chosen_tids]
        chosen_tids = chosen_tids + extra[:max_trips - len(chosen_tids)]
    else:
        chosen_tids = chosen_tids[:max_trips]

    stops_index = {row['stop_id']: (row['stop_lat'], row['stop_lon']) for _, row in stops.iterrows()}
    for tid in chosen_tids:
        seq = [sid for sid in seq_map.get(tid, []) if sid in stops_index]
        pts = [stops_index[sid] for sid in seq]
        pts = [p for p in pts if in_bbox(p[0], p[1])]
        if len(pts) >= 2:
            lines.append(pts)

    out_path = os.path.join(fig_dir, 'geneva_gtfs_trip_lines.png')
    out_path_alias = os.path.join(fig_dir, 'geneva_atlas_gtfs_trip_lines.png')
    title = 'Atlas-GTFS: trip line approximations (Geneva area)'
    plot_lines(lines, title, out_path, color='#1f77b4', lw=0.6, alpha=0.5)
    # also save alias for clarity in manuscript
    try:
        import shutil
        shutil.copyfile(out_path, out_path_alias)
        print(f"Saved alias figure to {out_path_alias}")
    except Exception as e:
        print("Could not create alias file:", e)


def _find_fplan_file():
    """Try to find an HRDF FPLAN file in common locations."""
    candidates = [
        os.path.join('data', 'raw', 'FPLAN'),
        os.path.join('data', 'raw', 'FPLAN.TXT'),
        os.path.join('data', 'raw', 'hrdf', 'FPLAN'),
        os.path.join('data', 'raw', 'HRDF', 'FPLAN'),
        os.path.join('data', 'raw', 'hrdf', 'FPLAN.TXT'),
        os.path.join('data', 'raw', 'HRDF', 'FPLAN.TXT'),
    ]
    for c in candidates:
        if os.path.exists(c) and os.path.isfile(c):
            return c
    # last resort: scan directory for files starting with FPLAN
    for base in [os.path.join('data', 'raw'), os.path.join('data', 'raw', 'hrdf'), os.path.join('data', 'raw', 'HRDF')]:
        if os.path.exists(base):
            for name in os.listdir(base):
                if name.upper().startswith('FPLAN'):
                    path = os.path.join(base, name)
                    if os.path.isfile(path):
                        return path
    return None


def _extract_uic_tokens_from_line(line: str):
    """Extract plausible UIC codes (7+ digits) from a line."""
    import re
    return re.findall(r"\b\d{7,}\b", line)


def _split_by_jump(points, max_jump_m=3000):
    """Split a list of (lat, lon) points into segments when jump exceeds max_jump_m."""
    from math import radians, cos, sin, asin, sqrt
    def haversine_distance(lat1, lon1, lat2, lon2):
        try:
            lat1, lon1, lat2, lon2 = float(lat1), float(lon1), float(lat2), float(lon2)
        except Exception:
            return None
        # Haversine in meters
        R = 6371000.0
        dlat = radians(lat2 - lat1)
        dlon = radians(lon2 - lon1)
        a = sin(dlat/2.0)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2.0)**2
        c = 2 * asin(sqrt(a))
        return R * c
    if not points:
        return []
    segments = []
    current = [points[0]]
    for i in range(1, len(points)):
        p_prev = points[i-1]
        p_cur = points[i]
        d = haversine_distance(p_prev[0], p_prev[1], p_cur[0], p_cur[1])
        if d is None or d > max_jump_m:
            if len(current) >= 2:
                segments.append(current)
            current = [p_cur]
        else:
            current.append(p_cur)
    if len(current) >= 2:
        segments.append(current)
    return segments


def plot_hrdf_trip_lines(fig_dir, max_trips=500):
    # Build mapping UIC -> (lat, lon) from ATLAS
    atlas_path = os.path.join('data', 'raw', 'stops_ATLAS.csv')
    if not os.path.exists(atlas_path):
        print('ATLAS CSV not found for HRDF plotting')
        return
    atlas = pd.read_csv(atlas_path, sep=';')
    atlas['wgs84North'] = pd.to_numeric(atlas['wgs84North'], errors='coerce')
    atlas['wgs84East'] = pd.to_numeric(atlas['wgs84East'], errors='coerce')
    atlas = atlas.dropna(subset=['wgs84North', 'wgs84East'])
    # Filter to bbox to get local UICs
    atlas_ge = atlas[atlas.apply(lambda r: in_bbox(r['wgs84North'], r['wgs84East']), axis=1)].copy()
    uic_in_bbox = set(atlas_ge['number'].astype(str).unique())
    uic_to_coord = {str(row['number']): (row['wgs84North'], row['wgs84East']) for _, row in atlas.iterrows()}
    print(f"Found {len(uic_in_bbox)} UICs in Geneva bbox, {len(uic_to_coord)} total UICs")

    # Parse FPLAN: collect stop sequences for trips that touch bbox UICs
    fplan_path = _find_fplan_file()
    if not fplan_path:
        print('FPLAN file not found for HRDF plotting in common locations')
        return
    print(f"Using FPLAN at: {fplan_path}")
    lines = []
    current_trip = None
    current_stops = []
    selected = 0
    trips_processed = 0
    trips_with_bbox_uics = 0
    with open(fplan_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            if not line.strip():
                continue
            if line.startswith('*Z'):
                trips_processed += 1
                if trips_processed % 50000 == 0:
                    print(f"Processed {trips_processed:,} trips, selected {selected} line segments so far")
                # flush previous
                if current_trip and current_stops:
                    trips_with_bbox_uics += 1
                    # if any UIC in bbox, build line
                    if any(s in uic_in_bbox for s in current_stops):
                        # Map to coords where available and filter to bbox
                        seq_pts = [uic_to_coord.get(s) for s in current_stops if s in uic_to_coord]
                        seq_pts = [p for p in seq_pts if p and in_bbox(p[0], p[1])]
                        # Split by large jumps to avoid diagonals
                        segs = _split_by_jump(seq_pts, max_jump_m=3000)
                        for seg in segs:
                            if len(seg) >= 2:  # require at least 2 in-bbox points (relaxed)
                                lines.append(seg)
                                selected += 1
                                if selected >= max_trips:
                                    break
                        if selected >= max_trips:
                            break
                # start new trip
                parts = line.split()
                current_trip = (parts[1], parts[2]) if len(parts) >= 3 else None
                current_stops = []
            elif not line.startswith('*'):
                parts = line.split()
                # Parse UIC from stop entries: first token should be UIC
                if parts and parts[0].isdigit() and len(parts[0]) >= 7:
                    current_stops.append(parts[0])
    # Process final trip
    if selected < max_trips and current_trip and current_stops:
        trips_with_bbox_uics += 1
        if any(s in uic_in_bbox for s in current_stops):
            seq_pts = [uic_to_coord.get(s) for s in current_stops if s in uic_to_coord]
            seq_pts = [p for p in seq_pts if p and in_bbox(p[0], p[1])]
            segs = _split_by_jump(seq_pts, max_jump_m=3000)
            for seg in segs:
                if len(seg) >= 2:
                    lines.append(seg)

    print(f"HRDF parsing complete: {trips_processed:,} trips total, {trips_with_bbox_uics} touched Geneva bbox, {len(lines)} line segments created")
    out_path = os.path.join(fig_dir, 'geneva_hrdf_trip_lines.png')
    plot_lines(lines, 'HRDF: trip line approximations (Geneva area)', out_path, color='#ff7f0e', lw=0.6, alpha=0.5)


def main():
    fig_dir = ensure_dirs()
    plot_osm_route_lines(fig_dir)
    plot_gtfs_trip_lines(fig_dir)
    plot_hrdf_trip_lines(fig_dir)


if __name__ == '__main__':
    main()


