import os
import pandas as pd
from collections import defaultdict
import xml.etree.ElementTree as ET

# Since DB is empty in the agent's Docker context, we will run the matching pipeline
# in memory to gather the matches, then select a representative 40-stop sample.
print("Running pipeline to find representative examples...")

from matching_process.matching_script import final_pipeline

# Run the full pipeline in memory to get match metadata
output = final_pipeline('unified')
matches = output.matched

# Group matches by type
by_type = defaultdict(list)
for m in matches:
    t = m.get('match_type')
    if t:
        by_type[t].append(m)

# Pick samples
samples = []
for t in ['exact', 'name', 'distance_matching_1_uic_ref', 'distance_matching_2', 'distance_matching_3a', 'distance_matching_3b', 'route_match', 'duplicate_propagation']:
    samples.extend(by_type.get(t, [])[:5])

# Add 5 unmatched and 5 isolated
unm = output.unmatched_atlas[:5]
no_nearby = output.no_nearby_osm_sloids
iso = [u for u in output.unmatched_atlas if u['sloid'] in no_nearby][:5]

samples.extend(unm)
samples.extend(iso)

# Now we have our representative sloids
selected_sloids = {s.get('sloid') for s in samples if s.get('sloid')}

# Read the full ATLAS CSV and keep only those rows
atlas_df = pd.read_csv('data/atlas_stops.csv')
sample_atlas = atlas_df[atlas_df['sloid'].isin(selected_sloids)]

os.makedirs('tests/data', exist_ok=True)
sample_atlas.to_csv('tests/data/sample_atlas.csv', index=False)
print(f"Saved {len(sample_atlas)} selective ATLAS rows to tests/data/sample_atlas.csv")

# Now build the sample_osm.xml
required_osm_nodes = {s.get('osm_node_id') for s in samples if s.get('osm_node_id') and s.get('osm_node_id') != 'NA'}

print(f"Required OSM Nodes: {len(required_osm_nodes)}")
import xml.etree.ElementTree as ET

xml_file = 'data/osm_public_transport.xml'
out_file = 'tests/data/sample_osm.xml'

print("Filtering corresponding OSM nodes...")
lats = pd.to_numeric(sample_atlas['wgs84North'], errors='coerce').dropna()
lons = pd.to_numeric(sample_atlas['wgs84East'], errors='coerce').dropna()

lat_min, lat_max = lats.min() - 0.05, lats.max() + 0.05
lon_min, lon_max = lons.min() - 0.05, lons.max() + 0.05

with open(out_file, 'w', encoding='utf-8') as f:
    f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
    f.write('<osm version="0.6" generator="sample_extractor">\n')
    
    context = ET.iterparse(xml_file, events=('end',))
    nodes_written = 0
    
    for event, elem in context:
        if elem.tag == 'node':
            nid = elem.get('id')
            keep = False
            if nid in required_osm_nodes:
                keep = True
            else:
                lat = float(elem.get('lat', 0))
                lon = float(elem.get('lon', 0))
                if lat_min <= lat <= lat_max and lon_min <= lon <= lon_max:
                    keep = True
                    
            if keep:
                f.write(ET.tostring(elem, encoding='unicode'))
                nodes_written += 1
            elem.clear()
            
    f.write('</osm>\n')
    
print(f"Saved {nodes_written} OSM nodes to {out_file}.")
print("Extraction script completed.")
