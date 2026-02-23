import os
import pandas as pd
import xml.etree.ElementTree as ET

# Instead of running the full 15-minute pipeline, just randomly sample 
# stops from the ATLAS csv and grab a small bounding box of OSM data around them.

print("Loading raw ATLAS CSV...")
atlas_path = 'data/raw/stops_ATLAS.csv'
if not os.path.exists(atlas_path):
    print("Error: data/raw/stops_ATLAS.csv not found!")
    exit(1)

atlas_df = pd.read_csv(atlas_path, sep=';')

# Grab 40 random stops that have valid coordinates
valid_coords = atlas_df.dropna(subset=['wgs84North', 'wgs84East'])
sample_atlas = valid_coords.sample(n=40, random_state=42)

os.makedirs('tests/data', exist_ok=True)
sample_atlas.to_csv('tests/data/sample_atlas.csv', index=False)
print(f"Saved {len(sample_atlas)} selective ATLAS rows to tests/data/sample_atlas.csv")

# Now build the sample_osm.xml by grabbing a bounding box
xml_file = 'data/raw/osm_data.xml'
out_file = 'tests/data/sample_osm.xml'

print("Filtering OSM nodes corresponding to the bounding box...")
lats = pd.to_numeric(sample_atlas['wgs84North'], errors='coerce').dropna()
lons = pd.to_numeric(sample_atlas['wgs84East'], errors='coerce').dropna()

# Adding a 0.05 degree margin (~5km) around our random stops
lat_min, lat_max = lats.min() - 0.05, lats.max() + 0.05
lon_min, lon_max = lons.min() - 0.05, lons.max() + 0.05

with open(out_file, 'w', encoding='utf-8') as f:
    f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
    f.write('<osm version="0.6" generator="sample_extractor">\n')
    
    if os.path.exists(xml_file):
        context = ET.iterparse(xml_file, events=('end',))
        nodes_written = 0
        
        for event, elem in context:
            if elem.tag == 'node':
                try:
                    lat = float(elem.get('lat', 0))
                    lon = float(elem.get('lon', 0))
                    if lat_min <= lat <= lat_max and lon_min <= lon <= lon_max:
                        f.write(ET.tostring(elem, encoding='unicode'))
                        nodes_written += 1
                except ValueError:
                    pass
                elem.clear()
        
        f.write('</osm>\n')
        print(f"Saved {nodes_written} OSM nodes to {out_file}.")
    else:
        print(f"Warning: {xml_file} not found. Generated empty bounding box OSM file.")
        
print("Extraction script completed.")
