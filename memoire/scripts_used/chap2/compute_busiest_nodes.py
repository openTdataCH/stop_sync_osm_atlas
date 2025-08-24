import xml.etree.ElementTree as ET
import pandas as pd
from typing import List, Dict


def load_nodes_with_routes(csv_path: str) -> pd.DataFrame:
    """Load the processed node–route pairs CSV.

    Required columns: node_id, route_name, node_type, uic_ref (others tolerated).
    """
    df = pd.read_csv(csv_path)
    expected = {"node_id", "route_name"}
    missing = expected - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns in CSV: {missing}")
    return df


def load_node_names_from_xml(xml_path: str) -> Dict[str, str]:
    """Build a mapping node_id -> name from the raw OSM XML."""
    root = ET.parse(xml_path).getroot()
    id_to_name: Dict[str, str] = {}
    for node in root.findall(".//node"):
        nid = node.get("id")
        if not nid:
            continue
        name_tag = node.find("tag[@k='name']")
        id_to_name[nid] = name_tag.get("v") if name_tag is not None else ""
    return id_to_name


def compute_busiest_nodes(csv_path: str, xml_path: str, top_k: int = 10) -> List[Dict[str, str]]:
    """Return top-k nodes by raw number of node–route connections (no deduplication).

    This matches the methodology used in the manuscript's “Les 5 nœuds…” section.
    """
    df = load_nodes_with_routes(csv_path)
    counts = df.groupby("node_id").size().reset_index(name="route_count")
    top = counts.nlargest(top_k, "route_count")

    id_to_name = load_node_names_from_xml(xml_path)

    # Optionally include node_type/uic_ref from the first row for each node
    first_rows = df.sort_values(["node_id"]).drop_duplicates("node_id")
    first_rows = first_rows.set_index("node_id")

    results: List[Dict[str, str]] = []
    for _, row in top.iterrows():
        node_id_int = int(row["node_id"])
        node_id = str(node_id_int)
        node_name = id_to_name.get(node_id, "")
        
        # Get node_type and uic_ref from first_rows, handling missing/nan values
        if node_id_int in first_rows.index:
            node_type_raw = first_rows.loc[node_id_int].get("node_type", "")
            uic_ref_raw = first_rows.loc[node_id_int].get("uic_ref", "")
            
            node_type = str(node_type_raw) if node_type_raw and str(node_type_raw) != 'nan' else ""
            uic_ref = str(uic_ref_raw) if uic_ref_raw and str(uic_ref_raw) != 'nan' else ""
        else:
            node_type = ""
            uic_ref = ""
            
        results.append({
            "node_id": node_id,
            "name": node_name,
            "route_count": int(row["route_count"]),
            "node_type": node_type,
            "uic_ref": uic_ref
        })
    return results


if __name__ == "__main__":
    CSV_PATH = "data/processed/osm_nodes_with_routes.csv"
    XML_PATH = "data/raw/osm_data.xml"
    top_nodes = compute_busiest_nodes(CSV_PATH, XML_PATH, top_k=10)

    print("TOP 10 BUSIEST TRANSIT NODES (raw node–route connections)")
    print("---------------------------------------------------------")
    for i, n in enumerate(top_nodes, 1):
        print(f"{i}. Node ID: {n['node_id']}")
        print(f"   Name: {n['name'] or 'N/A'}")
        print(f"   Routes served: {n['route_count']}")
        if n.get("node_type"):
            print(f"   Node type: {n['node_type']}")
        if n.get("uic_ref"):
            print(f"   UIC reference: {n['uic_ref']}")
        print()
    
    # Print LaTeX format for top 5
    print("\n" + "="*60)
    print("TOP 5 NODES IN LATEX FORMAT FOR CHAPTER UPDATE")
    print("="*60)
    
    colors = ["blue", "green", "orange", "purple", "red"]
    positions = ["1er", "2e", "3e", "4e", "5e"]
    
    for i, n in enumerate(top_nodes[:5]):
        color = colors[i]
        position = positions[i]
        name = n['name'] or 'N/A'
        routes = n['route_count']
        node_type = n.get('node_type', '')
        uic_ref = n.get('uic_ref', '')
        node_id = n['node_id']
        
        print(f"\n\\begin{{tcolorbox}}[colback={color}!5, colframe={color}!40, title=\\textbf{{{position}}} — {name}, fontupper=\\normalsize\\bfseries]")
        print(f"\\textbf{{Itinéraires desservis :}} {routes} \\\\")
        if node_type:
            print(f"\\textbf{{Type de nœud :}} \\texttt{{{node_type}}} \\\\")
        if uic_ref:
            print(f"\\textbf{{Référence UIC :}} {uic_ref} \\\\")
        print(f"\\textbf{{Node ID :}} {node_id}")
        print("\\end{tcolorbox}")
    
    print("\n" + "="*60)


