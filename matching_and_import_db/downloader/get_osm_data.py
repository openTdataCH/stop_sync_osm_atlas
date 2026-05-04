import requests
import xml.etree.ElementTree as ET
from collections import defaultdict
import csv
import os
import time
from typing import Optional


# Create data directories
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

        .pt_nodes out body qt;
        .candidate_ways out body center qt;

        (
            relation(bn.pt_nodes)[type=route];
            relation(bw.candidate_ways)[type=route];
        );
        out meta;
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
    return response.text

def process_osm_routes_data(xml_data, out_dir="data/processed/"):
    import datetime
    run_id = datetime.date.today().isoformat()

    print("Processing OSM data to route entity CSVs...")
    root = ET.fromstring(xml_data)

    nodes = {}
    node_uic_refs = set()

    for node in root.findall(".//node"):
        node_id = node.get('id')
        uic_ref = next((tag.get('v') for tag in node.findall("./tag") if tag.get('k') == 'uic_ref'), None)
        nodes[node_id] = node_id
        if uic_ref:
            node_uic_refs.add(uic_ref)

    for way in root.findall(".//way"):
        way_id = way.get('id')
        virtual_id = f"way_{way_id}"
        uic_ref = None
        way_type = None
        aerialway = None
        for tag in way.findall("./tag"):
            if tag.get('k') == 'uic_ref': uic_ref = tag.get('v')
            if tag.get('k') == 'public_transport': way_type = tag.get('v')
            if tag.get('k') == 'aerialway': aerialway = tag.get('v')
        
        is_aerialway_station = aerialway == 'station' and way_type == 'station'
        is_uic_without_node = bool(uic_ref) and uic_ref not in node_uic_refs
        if is_aerialway_station or is_uic_without_node:
            nodes[virtual_id] = virtual_id

    def parse_direction_from_ref_trips(ref_trips_value):
        if not ref_trips_value: return None
        for tid in [t.strip() for t in ref_trips_value.split(',')]:
            if tid.endswith('.H'): return '0'
            elif tid.endswith('.R'): return '1'
        return None

    routes_rows = []
    tags_rows = []
    members_rows = []

    for relation in root.findall(".//relation"):
        tags = {tag.get('k'): tag.get('v') for tag in relation.findall("./tag")}
        if tags.get('type') != 'route':
            continue

        relation_id = relation.get('id')
        
        routes_rows.append({
            'run_id': run_id,
            'relation_id': relation_id,
            'relation_version': relation.get('version', ''),
            'route': tags.get('route', ''),
            'name': tags.get('name', ''),
            'ref': tags.get('ref', ''),
            'operator': tags.get('operator', ''),
            'network': tags.get('network', ''),
            'from_node': tags.get('from', ''),
            'to_node': tags.get('to', ''),
            'via': tags.get('via', ''),
            'public_transport_version': tags.get('public_transport:version', ''),
            'colour': tags.get('colour', ''),
            'gtfs_route_id': tags.get('gtfs:route_id', ''),
            'gtfs_feed': tags.get('gtfs:feed', ''),
            'ref_trips': tags.get('ref_trips', ''),
            'source_query_hash': ''
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
            seq += 1

    import csv
    def write_csv(path, rows, fieldnames):
        if not rows:
            print(f"No data for {path}")
            return
        with open(path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        print(f"Wrote {len(rows)} rows to {path}")

    write_csv(os.path.join(out_dir, "osm_routes.csv"), routes_rows, list(routes_rows[0].keys()) if routes_rows else [])
    write_csv(os.path.join(out_dir, "osm_route_tags.csv"), tags_rows, ['run_id', 'relation_id', 'tag_key', 'tag_value'])
    write_csv(os.path.join(out_dir, "osm_route_members.csv"), members_rows, ['run_id', 'relation_id', 'member_type', 'member_ref', 'member_role', 'member_sequence', 'resolved_node_id', 'direction_id_derived'])

def main():
    xml_data = query_overpass()
    process_osm_routes_data(xml_data, "data/processed/")

if __name__ == "__main__":
    main()