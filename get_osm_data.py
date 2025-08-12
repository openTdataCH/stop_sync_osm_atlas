import requests
import xml.etree.ElementTree as ET
from collections import defaultdict
import pandas as pd
import csv 
import json
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
    [out:xml][timeout:180];
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
    );
    out;
    (
      relation(bn)[type=route];
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
    
    # Create dictionaries to store nodes and routes
    nodes = {}
    routes = {}
    node_routes = defaultdict(list)
    
    # Extract all nodes
    for node in root.findall(".//node"):
        node_id = node.get('id')
        node_type = None
        uic_ref = None
        
        for tag in node.findall("./tag"):
            if tag.get('k') == 'public_transport':
                node_type = tag.get('v')
            elif tag.get('k') == 'uic_ref':
                uic_ref = tag.get('v')
        
        nodes[node_id] = {
            'id': node_id,
            'type': node_type,
            'uic_ref': uic_ref,
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
        
        # Map each node in this route to the route
        for member in relation.findall("./member[@type='node']"):
            node_ref = member.get('ref')
            if node_ref in nodes:
                node_routes[node_ref].append(relation_id)
    
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
    
    # Create routes-with-nodes CSV
    create_routes_with_nodes_csv(output_file)

def create_routes_with_nodes_csv(nodes_routes_csv):
    """
    Create a CSV file that groups nodes by route and direction.
    
    Args:
        nodes_routes_csv: Path to the CSV with node-route pairs
    """
    print("\nCreating route to nodes mapping CSV...")
    
    try:
        # Read the node-routes CSV
        df = pd.read_csv(nodes_routes_csv)
        
        # Group by gtfs_route_id and direction_id
        route_groups = df.groupby(['gtfs_route_id', 'direction_id'])
        
        # Create rows with route info and list of nodes
        routes_with_nodes = []
        
        for (route_id, direction_id), group in route_groups:
            # Skip if route_id is missing
            if pd.isna(route_id) or route_id == '':
                continue
                
            # Get route info from first row
            first_row = group.iloc[0]
            route_name = first_row['route_name']
            
            # Get list of node_ids for this route+direction
            node_ids = group['node_id'].tolist()
            
            # Create a row for this route+direction combination
            route_row = {
                'route_id': route_id,
                'direction_id': direction_id,
                'route_name': route_name,
                'nodes_count': len(node_ids),
                'nodes_list': node_ids
            }
            
            routes_with_nodes.append(route_row)
        
        # Convert to DataFrame
        routes_df = pd.DataFrame(routes_with_nodes)
        
        # Add nodes_list as JSON string column for CSV export
        routes_df['nodes_json'] = routes_df['nodes_list'].apply(lambda x: json.dumps(x))
        
        # Save to processed directory
        output_file = "data/processed/osm_routes_with_nodes.csv"
        routes_df.to_csv(output_file, index=False)
        
        print(f"Created mapping for {len(routes_df)} route+direction combinations")
        print(f"Route-nodes mapping saved to {output_file}")
        
    except Exception as e:
        print(f"Error creating routes-with-nodes CSV: {e}")

def main():
    """
    Main function to run the script.
    """
    #xml_data = query_overpass()
    
    # If you need to read from file instead:
    with open("data/raw/osm_data.xml", "r", encoding="utf-8") as f:
       xml_data = f.read()
    
    if xml_data:
        # Process the data and output as CSV with direction information
        process_osm_data_to_csv(xml_data, "data/processed/osm_nodes_with_routes.csv")

if __name__ == "__main__":
    main()