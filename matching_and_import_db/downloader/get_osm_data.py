import requests
import xml.etree.ElementTree as ET
from collections import defaultdict
import csv
import os


# Create data directories
os.makedirs("data/raw", exist_ok=True)
os.makedirs("data/processed", exist_ok=True)
os.makedirs("data/debug", exist_ok=True)

def query_overpass():
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
    url = "http://overpass-api.de/api/interpreter"
    response = requests.post(url, data={'data': query})
    if response.status_code == 200:
        response.encoding = 'utf-8'
        # Save to organized data directory
        with open("data/raw/osm_data.xml", "w", encoding="utf-8") as f:
            f.write(response.text)
        print("Raw OSM data saved to data/raw/osm_data.xml")
        return response.text
    else:
        print("Error fetching OSM data:", response.status_code)
        return None

def process_osm_data_to_csv(xml_data, output_file="data/processed/osm_nodes_with_routes.csv"):
    """
    Process the OSM XML data and output a CSV file with nodes and their routes.
    Each node-route pair gets its own row. Includes direction_id parsed from ref_trips H/R suffix.
    H = outbound (direction_id = 0), R = return/inbound (direction_id = 1)
    """
    print("Processing OSM data to CSV...")

    # Direction will be parsed from ref_trips H/R suffix
    print("Will parse direction from ref_trips H/R suffix (H=0, R=1)")
    
    # Parse the XML
    root = ET.fromstring(xml_data)
    
    # Create dictionaries to store stop elements and routes
    nodes = {}
    routes = {}
    node_routes = defaultdict(list)
    node_directions_name = defaultdict(set)
    node_directions_uic = defaultdict(set)
    node_uic_refs = set()
    
    # Extract all nodes
    for node in root.findall(".//node"):
        node_id = node.get('id')
        node_type = None
        uic_ref = None
        node_name = None
        
        for tag in node.findall("./tag"):
            if tag.get('k') == 'public_transport':
                node_type = tag.get('v')
            elif tag.get('k') == 'uic_ref':
                uic_ref = tag.get('v')
            elif tag.get('k') == 'name':
                node_name = tag.get('v')
        
        nodes[node_id] = {
            'id': node_id,
            'type': node_type,
            'uic_ref': uic_ref,
            'name': node_name,
        }
        if uic_ref:
            node_uic_refs.add(uic_ref)

    # Extract selected candidate ways and map to stable virtual IDs.
    # Keep this filter aligned with OsmState.from_xml_file to avoid route FK mismatches.
    for way in root.findall(".//way"):
        way_id = way.get('id')
        virtual_id = f"way_{way_id}"
        way_type = None
        uic_ref = None
        way_name = None
        aerialway = None

        for tag in way.findall("./tag"):
            key = tag.get('k')
            value = tag.get('v')
            if key == 'public_transport':
                way_type = value
            elif key == 'uic_ref':
                uic_ref = value
            elif key == 'name':
                way_name = value
            elif key == 'aerialway':
                aerialway = value

        is_aerialway_station = aerialway == 'station' and way_type == 'station'
        is_uic_without_node = bool(uic_ref) and uic_ref not in node_uic_refs
        if not (is_aerialway_station or is_uic_without_node):
            continue

        nodes[virtual_id] = {
            'id': virtual_id,
            'type': way_type,
            'uic_ref': uic_ref,
            'name': way_name,
        }
    
    # Extract all relations that are routes
    for relation in root.findall(".//relation"):
        # Check if this relation is a route
        is_route = False
        relation_id = relation.get('id')
        
        route_name = None
        route_ref = None
        route_type = None
        route_gtfs_id = None
        route_gtfs_trip_id = None
        
        for tag in relation.findall("./tag"):
            if tag.get('k') == 'type' and tag.get('v') == 'route':
                is_route = True
            elif tag.get('k') == 'name':
                route_name = tag.get('v')
            elif tag.get('k') == 'ref':
                route_ref = tag.get('v')
            elif tag.get('k') == 'route':
                route_type = tag.get('v')
            elif tag.get('k') == 'gtfs:route_id':
                route_gtfs_id = tag.get('v')
            # Only look for ref_trips tag since it's the only effective one
            elif tag.get('k') == 'ref_trips':
                route_gtfs_trip_id = tag.get('v')
        
        # Skip if not a route
        if not is_route:
            continue
        
        # Use only the name tag as requested
        route_text = route_name if route_name else f"Unnamed route {relation_id}"
        
        route_info = {
            'id': relation_id,
            'name': route_text,
            'gtfs_route_id': route_gtfs_id,
            'gtfs_trip_id': route_gtfs_trip_id
        }
        
        routes[relation_id] = route_info
        
        # Map each node/way in this route to the route
        members = []
        for member in relation.findall("./member"):
            member_type = member.get('type')
            member_ref = member.get('ref')
            if member_type == 'node':
                members.append(member_ref)
            elif member_type == 'way':
                members.append(f"way_{member_ref}")

        for node_ref in members:
            if node_ref in nodes:
                node_routes[node_ref].append(relation_id)

        # Extract direction strings based on first and last nodes of the relation
        if len(members) >= 2:
            first, last = members[0], members[-1]
            first_node = nodes.get(first, {})
            last_node = nodes.get(last, {})
            
            fn = first_node.get('name')
            ln = last_node.get('name')
            if fn and ln:
                ds = f"{fn} → {ln}"
                for nid in members:
                    node_directions_name[nid].add(ds)
                    
            fu = first_node.get('uic_ref')
            lu = last_node.get('uic_ref')
            if fu and lu:
                ds = f"{fu} → {lu}"
                for nid in members:
                    node_directions_uic[nid].add(ds)
    
    print(f"Found {len(nodes)} nodes and {len(routes)} routes")

    # Parse direction from ref_trips H/R suffix
    print("Parsing direction from ref_trips H/R suffix")
    
    def parse_direction_from_ref_trips(ref_trips_value):
        """
        Parse direction from ref_trips value based on H/R suffix.
        H = outbound (direction_id = 0)
        R = return/inbound (direction_id = 1)
        """
        if not ref_trips_value:
            return None
        
        # Handle multiple trip IDs separated by commas
        trip_ids = [tid.strip() for tid in ref_trips_value.split(',')]
        
        for trip_id in trip_ids:
            if trip_id.endswith('.H'):
                return '0'  # Outbound
            elif trip_id.endswith('.R'):
                return '1'  # Return/Inbound
        
        return None
    
    # Write data to CSV - one row per node-route pair
    total_rows = 0
    rows_with_direction = 0
    
    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['node_id', 'node_type', 'route_name', 'gtfs_route_id', 'direction_id', 'uic_ref'])
        
        for node_id, node_data in nodes.items():
            for route_id in node_routes[node_id]:
                route_data = routes[route_id]
                
                # Get direction_id by parsing the H/R suffix from ref_trips
                direction_id = parse_direction_from_ref_trips(route_data['gtfs_trip_id'])
                
                # Write row with direction if found, otherwise without
                if direction_id is not None:
                    writer.writerow([
                        node_data['id'],
                        node_data['type'] or '',
                        route_data['name'] or '',
                        route_data['gtfs_route_id'] or '',
                        direction_id,
                        node_data['uic_ref'] or ''
                    ])
                    rows_with_direction += 1
                else:
                    writer.writerow([
                        node_data['id'],
                        node_data['type'] or '',
                        route_data['name'] or '',
                        route_data['gtfs_route_id'] or '',
                        '',
                        node_data['uic_ref'] or ''
                    ])
                
                total_rows += 1
                
    
    print(f"CSV data saved to {output_file} with {total_rows} node-route pairs")
    print(f"Successfully matched direction_id for {rows_with_direction} node-route pairs")
    
    # Write directions CSV
    directions_output = "data/processed/osm_directions.csv"
    with open(directions_output, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['node_id', 'dir_type', 'direction_string'])
        for nid, dirs in node_directions_name.items():
            for d in dirs:
                writer.writerow([nid, 'name', d])
        for nid, dirs in node_directions_uic.items():
            for d in dirs:
                writer.writerow([nid, 'uic', d])
    print(f"Directions data saved to {directions_output}")
    
def main():
    """
    Main function to run the script.
    """
    xml_data = query_overpass()
    
    if xml_data:
        # Process the data and output as CSV with direction information
        process_osm_data_to_csv(xml_data, "data/processed/osm_nodes_with_routes.csv")

if __name__ == "__main__":
    main()