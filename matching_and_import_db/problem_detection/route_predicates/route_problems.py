import math


def _normalize_text(value, *, lower=True):
    """Return a safe, stripped text value for mixed CSV payload types."""
    if value is None:
        return ''

    if isinstance(value, float) and math.isnan(value):
        return ''

    text = str(value).strip()
    if not text or text.lower() == 'nan':
        return ''

    return text.lower() if lower else text

def detect_route_problems(atlas_line_families, osm_route_relations, routes_matched_rows):
    problems = []
    
    # Create lookups
    atlas_map = {r.get('route_id'): r for r in atlas_line_families if r.get('route_id')}
    osm_map = {r.get('relation_id'): r for r in osm_route_relations if r.get('relation_id')}
    
    for match in routes_matched_rows:
        atlas_route = atlas_map.get(match['atlas_route_id'])
        osm_route = osm_map.get(match['osm_route_id'])
        
        if not atlas_route or not osm_route:
            continue
            
        atlas_short_name = _normalize_text(atlas_route.get('route_short_name'))
        osm_ref = _normalize_text(osm_route.get('ref'))
        osm_name = _normalize_text(osm_route.get('name'))
        
        # Check Name/Ref Mismatch
        if atlas_short_name and not (atlas_short_name in osm_ref or atlas_short_name in osm_name or osm_ref in atlas_short_name):
            problems.append({
                'atlas_route_id': match['atlas_route_id'],
                'osm_route_id': match['osm_route_id'],
                'problem_type': 'route_metadata_mismatch',
                'priority': 2,
                'details': {
                    'dimension': 'name',
                    'atlas_short_name': atlas_short_name,
                    'osm_ref': osm_ref,
                    'osm_name': osm_name
                }
            })
            
        # Check Mode/Type Mismatch
        atlas_type = _normalize_text(atlas_route.get('route_type'), lower=False)
        osm_mode = _normalize_text(osm_route.get('route'))
        
        mode_mismatch = False
        # GTFS route_type to OSM route approximations
        if atlas_type in ('0', '900') and osm_mode not in ('tram', 'light_rail'): # Tram
            mode_mismatch = True
        elif atlas_type in ('2', '100') and osm_mode not in ('train', 'railway'): # Rail
            mode_mismatch = True
        elif atlas_type in ('3', '700') and osm_mode not in ('bus',): # Bus
            mode_mismatch = True
            
        if mode_mismatch:
            problems.append({
                'atlas_route_id': match['atlas_route_id'],
                'osm_route_id': match['osm_route_id'],
                'problem_type': 'route_metadata_mismatch',
                'priority': 1,
                'details': {
                    'dimension': 'mode',
                    'atlas_type': atlas_type,
                    'osm_mode': osm_mode
                }
            })
            
    return problems
