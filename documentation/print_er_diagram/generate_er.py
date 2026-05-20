import os
import sys
import argparse

def generate(landscape=True):
    try:
        from eralchemy2 import render_er
        import pygraphviz as pgv
    except ImportError:
        print("Error: eralchemy2 or pygraphviz is not installed.")
        print("Please install them with: pip install -r documentation/print_er_diagram/requirements.txt")
        sys.exit(1)

    # Add the project root to sys.path so we can import backend
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    print("Importing backend models...")
    try:
        from backend.extensions import db
        import backend.models
    except ImportError as e:
        print(f"Error: Could not import project modules. Details: {e}")
        sys.exit(1)

    output_path = os.path.join(os.path.dirname(__file__), 'er_diagram.pdf')
    dot_path = os.path.join(os.path.dirname(__file__), 'er_diagram.dot')
    
    print(f"Generating intermediate DOT file...")
    try:
        # Generate DOT format first
        render_er(db.Model.metadata, dot_path)
        
        # Load the DOT file with pygraphviz for customization
        G = pgv.AGraph(dot_path)
        
        # Set orientation and layout attributes
        if landscape:
            G.graph_attr['rankdir'] = 'LR'
            G.graph_attr['size'] = '15.5,10.7' # Limit graph size slightly smaller than A3
            G.graph_attr['page'] = '16.5,11.7' # Force A3 Landscape PDF canvas
            print("Setting orientation to Landscape (Left-to-Right, A3 Page Size)...")
        else:
            G.graph_attr['rankdir'] = 'TB'
            G.graph_attr['size'] = '10.7,15.5' # Limit graph size slightly smaller than A3
            G.graph_attr['page'] = '11.7,16.5' # Force A3 Portrait PDF canvas
            print("Setting orientation to Portrait (Top-to-Bottom, A3 Page Size)...")
            
        # Improve aesthetic defaults
        G.graph_attr['nodesep'] = '0.5'
        G.graph_attr['ranksep'] = '0.8'
        G.graph_attr['splines'] = 'ortho'  # Nice orthogonal lines
        G.graph_attr['overlap'] = 'false'
        G.graph_attr['fontsize'] = '20'
        G.graph_attr['label'] = 'Stop Sync OSM Atlas - Database Schema'
        G.graph_attr['labelloc'] = 't'
        
        print(f"Rendering ER diagram to {output_path}...")
        G.layout(prog='dot')
        G.draw(output_path)
        
        # Cleanup temp dot file
        if os.path.exists(dot_path):
            os.remove(dot_path)
            
        print(f"Successfully generated: {output_path}")
    except Exception as e:
        print(f"An error occurred: {e}")
        sys.exit(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate ER diagram.")
    parser.add_argument("--portrait", action="store_true", help="Generate in portrait mode (Top-to-Bottom)")
    args = parser.parse_args()
    
    generate(landscape=not args.portrait)
