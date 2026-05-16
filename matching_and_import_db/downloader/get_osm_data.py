import requests
import xml.etree.ElementTree as ET
from collections import defaultdict
import csv
import os
import time
import datetime
from typing import Optional

from backend.services.data_meta import update_data_meta
from backend.services.time_utils import format_zurich_timestamp, get_zurich_now


def ensure_data_dirs():
    """Ensure required data directories exist."""
    os.makedirs("data/raw", exist_ok=True)
    os.makedirs("data/processed", exist_ok=True)
    os.makedirs("data/debug", exist_ok=True)


OVERPASS_URL = os.getenv("OVERPASS_API_URL", "https://overpass-api.de/api/interpreter")
OVERPASS_USER_AGENT = os.getenv(
    "OVERPASS_USER_AGENT",
    "stop-sync-osm-atlas/1.0 (+https://github.com/openTdataCH/stop_sync_osm_atlas)",
)
OVERPASS_HEADERS = {
    "Content-Type": "text/plain; charset=utf-8",
    "Accept": "application/osm3s+xml, text/xml, application/xml;q=0.9, */*;q=0.1",
    "User-Agent": OVERPASS_USER_AGENT,
}
OVERPASS_RETRY_STATUS_CODES = {502, 504}
OVERPASS_MAX_RETRIES = int(os.getenv("OVERPASS_MAX_RETRIES", "2"))
OVERPASS_RETRY_BACKOFF_SECONDS = float(os.getenv("OVERPASS_RETRY_BACKOFF_SECONDS", "5"))


def _raise_overpass_error(response: requests.Response) -> None:
    preview = response.text[:400].replace("\n", " ").strip()
    raise RuntimeError(
        f"Overpass request failed ({response.status_code}) at {response.url}. "
        f"Response preview: {preview}"
    )


def query_overpass(session: Optional[requests.Session] = None):
    """
    Queries the Overpass API for public transport nodes in Switzerland and 
    all routes that reference them. The result is saved to 'data/raw/osm_data.xml'.
    """
    ensure_data_dirs()
    query = """
        [out:xml][timeout:360];
        area["ISO3166-1"="CH"]->.searchArea;

        (
            node(area.searchArea)["public_transport"~"platform|stop_position|station|halt|stop"];
            node(area.searchArea)["railway"="tram_stop"];
            node(area.searchArea)["amenity"="ferry_terminal"];
            node(area.searchArea)["amenity"="bus_station"];
            node(area.searchArea)["highway"="bus_stop"];
            node(area.searchArea)["railway"="halt"];
            node(area.searchArea)["railway"="station"];
            node(area.searchArea)["aerialway"="station"];
        )->.pt_nodes;

        (
            way(area.searchArea)["aerialway"="station"]["public_transport"="station"];
            way(area.searchArea)["uic_ref"];
        )->.candidate_ways;

        (
            relation(bn.pt_nodes)[type=route][route!=hiking];
            relation(bw.candidate_ways)[type=route][route!=hiking];
        )->.seed_routes;

        relation(br.seed_routes)[type=route_master]->.route_masters;

        (
            .seed_routes;
            relation(r.route_masters)[type=route][route!=hiking];
        )->.routes;

        .pt_nodes out body qt;
        .candidate_ways out body center qt;
        .routes out meta;
        .route_masters out meta;
        """
    print("Querying OpenStreetMap data...")
    client = session or requests
    request_body = query.strip().encode("utf-8")
    response = None
    for attempt in range(OVERPASS_MAX_RETRIES + 1):
        response = client.post(
            OVERPASS_URL,
            data=request_body,
            headers=OVERPASS_HEADERS,
            timeout=(30, 600),
        )
        if response.status_code == 200:
            break

        should_retry = (
            response.status_code in OVERPASS_RETRY_STATUS_CODES
            and attempt < OVERPASS_MAX_RETRIES
        )
        if not should_retry:
            _raise_overpass_error(response)

        delay_seconds = OVERPASS_RETRY_BACKOFF_SECONDS * (2 ** attempt)
        print(
            "Overpass request returned "
            f"{response.status_code}. Retrying in {delay_seconds:.1f}s "
            f"(attempt {attempt + 2}/{OVERPASS_MAX_RETRIES + 1})..."
        )
        time.sleep(delay_seconds)

    if response is None:
        raise RuntimeError("Overpass request did not produce a response")

    response.encoding = 'utf-8'
    # Save to organized data directory
    os.makedirs("data/raw", exist_ok=True)
    with open("data/raw/osm_data.xml", "w", encoding="utf-8") as f:
        f.write(response.text)
    print("Raw OSM data saved to data/raw/osm_data.xml")

    # Save the timestamp
    update_data_meta(last_overpass_query_at=format_zurich_timestamp(get_zurich_now()))
    
    return response.text

def process_osm_routes_data(xml_data, out_dir="data/processed/"):
    ensure_data_dirs()
    import datetime
    run_id = datetime.date.today().isoformat()

    print("Processing OSM data to route entity CSVs...")
    root = ET.fromstring(xml_data)

    os.makedirs(out_dir, exist_ok=True)

    def _tags_for(element):
        return {tag.get('k'): tag.get('v') for tag in element.findall('./tag')}

    def _to_optional_text(value):
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None

    def _first_non_empty(*values):
        for value in values:
            cleaned = _to_optional_text(value)
            if cleaned is not None:
                return cleaned
        return None

    def _build_synthetic_family_key(gtfs_route_id, ref, relation_id, route_master_id):
        if route_master_id:
            return f"route_master:{route_master_id}"
        if gtfs_route_id:
            return f"gtfs_route:{gtfs_route_id}"
        if ref:
            return f"ref:{ref}"
        return f"relation:{relation_id}"

    def _build_stop_lookup_record(node_id, tags, lat=None, lon=None):
        uic_ref = _to_optional_text(tags.get('uic_ref'))
        stop_label = _first_non_empty(
            tags.get('name'),
            tags.get('uic_name'),
            tags.get('local_ref'),
            uic_ref,
            node_id,
        )
        canonical_stop_key = f"uic:{uic_ref}" if uic_ref else f"osm:{node_id}"
        return {
            'uic_ref': uic_ref,
            'stop_label': stop_label,
            'stop_lat': float(lat) if lat not in (None, '') else None,
            'stop_lon': float(lon) if lon not in (None, '') else None,
            'canonical_stop_key': canonical_stop_key,
        }

    def _write_csv(path, rows, fieldnames):
        if not rows:
            print(f"No data for {path}")
            return
        with open(path, 'w', newline='', encoding='utf-8') as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        print(f"Wrote {len(rows)} rows to {path}")

    nodes = {}
    node_uic_refs = set()

    for node in root.findall(".//node"):
        node_id = node.get('id')
        tags = _tags_for(node)
        uic_ref = tags.get('uic_ref')
        nodes[node_id] = _build_stop_lookup_record(
            node_id,
            tags,
            lat=node.get('lat'),
            lon=node.get('lon'),
        )
        if uic_ref:
            node_uic_refs.add(uic_ref)

    for way in root.findall(".//way"):
        way_id = way.get('id')
        virtual_id = f"way_{way_id}"
        tags = _tags_for(way)
        uic_ref = tags.get('uic_ref')
        way_type = tags.get('public_transport')
        aerialway = tags.get('aerialway')
        center = way.find('./center')
        center_lat = center.get('lat') if center is not None else None
        center_lon = center.get('lon') if center is not None else None
        
        is_aerialway_station = aerialway == 'station' and way_type == 'station'
        is_uic_without_node = bool(uic_ref) and uic_ref not in node_uic_refs
        if is_aerialway_station or is_uic_without_node:
            nodes[virtual_id] = _build_stop_lookup_record(
                virtual_id,
                tags,
                lat=center_lat,
                lon=center_lon,
            )

    def parse_direction_from_ref_trips(ref_trips_value):
        if not ref_trips_value: return None
        for tid in [t.strip() for t in ref_trips_value.split(',')]:
            if tid.endswith('.H'): return '0'
            elif tid.endswith('.R'): return '1'
        return None

    route_master_rows = []
    route_master_tag_rows = []
    route_master_member_rows = []
    route_master_by_relation = {}
    duplicate_route_master_member_count = 0

    for relation in root.findall(".//relation"):
        tags = _tags_for(relation)
        if tags.get('type') != 'route_master':
            continue

        route_master_id = relation.get('id')
        route_master_rows.append({
            'run_id': run_id,
            'route_master_id': route_master_id,
            'route_master': tags.get('route_master', ''),
            'name': tags.get('name', ''),
            'ref': tags.get('ref', ''),
            'operator': tags.get('operator', ''),
            'operator_wikidata': tags.get('operator:wikidata', ''),
            'network': tags.get('network', ''),
            'network_wikidata': tags.get('network:wikidata', ''),
            'is_non_gtfs': str((tags.get('network') or '').lower() == 'flixbus').lower(),
            'colour': tags.get('colour', ''),
            'gtfs_route_id': tags.get('gtfs:route_id', ''),
        })
        for key, value in tags.items():
            route_master_tag_rows.append({
                'run_id': run_id,
                'route_master_id': route_master_id,
                'tag_key': key,
                'tag_value': value,
            })

        sequence = 0
        seen_relation_ids = set()
        for member in relation.findall('./member'):
            if member.get('type') != 'relation':
                continue
            relation_id = member.get('ref')
            if relation_id in seen_relation_ids:
                duplicate_route_master_member_count += 1
                continue
            seen_relation_ids.add(relation_id)
            route_master_member_rows.append({
                'run_id': run_id,
                'route_master_id': route_master_id,
                'relation_id': relation_id,
                'member_sequence': sequence,
                'member_role': member.get('role', ''),
            })
            route_master_by_relation.setdefault(relation_id, route_master_id)
            sequence += 1

    if duplicate_route_master_member_count:
        print(
            "Deduplicated "
            f"{duplicate_route_master_member_count} duplicate route_master relation memberships"
        )

    routes_rows = []
    tags_rows = []
    members_rows = []
    relation_stop_rows = []

    for relation in root.findall(".//relation"):
        tags = _tags_for(relation)
        if tags.get('type') != 'route':
            continue

        relation_id = relation.get('id')
        route_master_id = route_master_by_relation.get(relation_id)
        gtfs_route_id = tags.get('gtfs:route_id', '')
        relation_version = relation.get('version', '')
        synthetic_family_key = _build_synthetic_family_key(gtfs_route_id, tags.get('ref'), relation_id, route_master_id)
        family_origin = 'route_master' if route_master_id else 'relation'
        
        routes_rows.append({
            'run_id': run_id,
            'relation_id': relation_id,
            'route': tags.get('route', ''),
            'name': tags.get('name', ''),
            'ref': tags.get('ref', ''),
            'operator': tags.get('operator', ''),
            'operator_wikidata': tags.get('operator:wikidata', ''),
            'network': tags.get('network', ''),
            'network_wikidata': tags.get('network:wikidata', ''),
            'is_non_gtfs': str((tags.get('network') or '').lower() == 'flixbus').lower(),
            'from_name': tags.get('from', ''),
            'to_name': tags.get('to', ''),
            'via': tags.get('via', ''),
            'public_transport_version': tags.get('public_transport:version', ''),
            'colour': tags.get('colour', ''),
            'gtfs_route_id': gtfs_route_id,
            'gtfs_trip_id': tags.get('gtfs:trip_id', ''),
            'gtfs_trip_id_sample': tags.get('gtfs:trip_id:sample', '') or tags.get('gtfs:trip_id', ''),
            'gtfs_shape_id': tags.get('gtfs:shape_id', ''),
            'route_master_id': route_master_id or '',
            'family_origin': family_origin,
            'synthetic_family_key': synthetic_family_key,
        })

        for k, v in tags.items():
            tags_rows.append({'run_id': run_id, 'relation_id': relation_id, 'tag_key': k, 'tag_value': v})

        direction_id_derived = parse_direction_from_ref_trips(tags.get('ref_trips'))

        seq = 0
        for member in relation.findall("./member"):
            member_type = member.get('type')
            member_ref = member.get('ref')
            member_role = member.get('role', '')
            resolved_node_id = None
            if member_type == 'node':
                resolved_node_id = member_ref if member_ref in nodes else None
            elif member_type == 'way':
                virtual = f"way_{member_ref}"
                resolved_node_id = virtual if virtual in nodes else None

            members_rows.append({
                'run_id': run_id,
                'relation_id': relation_id,
                'member_type': member_type,
                'member_ref': member_ref,
                'member_role': member_role,
                'member_sequence': seq,
                'resolved_node_id': resolved_node_id,
                'direction_id_derived': direction_id_derived
            })

            if resolved_node_id is not None:
                stop_record = nodes.get(resolved_node_id, {})
                relation_stop_rows.append({
                    'run_id': run_id,
                    'relation_id': relation_id,
                    'direction_id': direction_id_derived,
                    'stop_sequence': seq,
                    'osm_node_id': resolved_node_id,
                    'stop_role': member_role,
                    'canonical_stop_key': stop_record.get('canonical_stop_key'),
                    'stop_label': stop_record.get('stop_label'),
                    'uic_ref': stop_record.get('uic_ref'),
                    'stop_lat': stop_record.get('stop_lat'),
                    'stop_lon': stop_record.get('stop_lon'),
                })
            seq += 1

    _write_csv(
        os.path.join(out_dir, 'osm_route_masters.csv'),
        route_master_rows,
        ['run_id', 'route_master_id', 'route_master', 'name', 'ref', 'operator', 'network', 'is_non_gtfs', 'colour', 'gtfs_route_id'],
    )
    _write_csv(
        os.path.join(out_dir, 'osm_route_master_tags.csv'),
        route_master_tag_rows,
        ['run_id', 'route_master_id', 'tag_key', 'tag_value'],
    )
    _write_csv(
        os.path.join(out_dir, 'osm_route_master_members.csv'),
        route_master_member_rows,
        ['run_id', 'route_master_id', 'relation_id', 'member_sequence', 'member_role'],
    )
    _write_csv(
        os.path.join(out_dir, 'osm_route_relations.csv'),
        routes_rows,
        [
            'run_id', 'relation_id', 'route', 'name', 'ref', 'operator', 'network', 'is_non_gtfs',
            'from_name', 'to_name', 'via', 'public_transport_version', 'colour',
            'gtfs_route_id', 'gtfs_trip_id', 'gtfs_trip_id_sample', 'gtfs_shape_id',
            'route_master_id', 'family_origin', 'synthetic_family_key',
        ],
    )
    _write_csv(
        os.path.join(out_dir, 'osm_route_relation_tags.csv'),
        tags_rows,
        ['run_id', 'relation_id', 'tag_key', 'tag_value'],
    )
    _write_csv(
        os.path.join(out_dir, 'osm_route_relation_members.csv'),
        members_rows,
        ['run_id', 'relation_id', 'member_type', 'member_ref', 'member_role', 'member_sequence', 'resolved_node_id', 'direction_id_derived'],
    )
    _write_csv(
        os.path.join(out_dir, 'osm_route_relation_stops.csv'),
        relation_stop_rows,
        ['run_id', 'relation_id', 'direction_id', 'stop_sequence', 'osm_node_id', 'stop_role', 'canonical_stop_key', 'stop_label', 'uic_ref', 'stop_lat', 'stop_lon'],
    )


def main():
    xml_data = query_overpass()
    process_osm_routes_data(xml_data, "data/processed/")

if __name__ == "__main__":
    main()