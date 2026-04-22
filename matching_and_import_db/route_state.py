import pandas as pd
from typing import Dict
from matching_and_import_db.utils.route_id import normalize_route_id

class RouteState:
    """
    Pre-computes and holds global route equivalency state.
    Separates route-to-route matching from stop-to-stop matching.
    """
    _instance = None
    
    def __init__(self):
        self.osm_route_to_atlas_route: Dict[str, str] = {}
        self.atlas_routes: pd.DataFrame = None
        self.osm_routes: pd.DataFrame = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = RouteState()
        return cls._instance
        
    @classmethod
    def reset(cls):
        cls._instance = None

    def load_and_match(self, atlas_routes_path="data/processed/atlas_routes.csv", osm_routes_path="data/processed/osm_routes.csv"):
        """
        Loads the CSV files and precomputes the equivalency map.
        1. Exact ID match
        2. Normalized -jXX fallback match
        """
        try:
            self.atlas_routes = pd.read_csv(atlas_routes_path, dtype=str)
            self.osm_routes = pd.read_csv(osm_routes_path, dtype=str)
        except Exception as e:
            print(f"RouteState: Failed to load route data: {e}")
            return
            
        if self.atlas_routes.empty or self.osm_routes.empty:
            return
            
        # 1. Exact match on GTFS Route ID
        atlas_route_ids = set(self.atlas_routes['route_id'].dropna())
        
        for _, osm_row in self.osm_routes.iterrows():
            osm_rel_id = osm_row['relation_id']
            gtfs_id = osm_row['gtfs_route_id']
            
            if pd.notna(gtfs_id) and gtfs_id in atlas_route_ids:
                self.osm_route_to_atlas_route[osm_rel_id] = gtfs_id
                continue
                
            # 2. Normalized -jXX fallback match
            if pd.notna(gtfs_id):
                norm_osm = normalize_route_id(gtfs_id)
                # Find matching normalized atlas route
                matches = self.atlas_routes[self.atlas_routes['route_id_normalized'] == norm_osm]
                if not matches.empty:
                    # Just pick the first one for simplicity, or could refine with direction
                    self.osm_route_to_atlas_route[osm_rel_id] = matches.iloc[0]['route_id']
                    
        print(f"RouteState: Precomputed {len(self.osm_route_to_atlas_route)} route matches.")

    def get_atlas_route(self, osm_relation_id: str) -> str:
        """Return the equivalent ATLAS route ID for a given OSM relation ID."""
        return self.osm_route_to_atlas_route.get(osm_relation_id)

