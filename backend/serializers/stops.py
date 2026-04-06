from backend.models import StopsMatched, AtlasStop, OsmNode
from backend.services.routes import get_unified_routes_for_sloid, get_osm_routes_for_node

def format_stop_data(stop: StopsMatched, problem_type: str = None, include_routes: bool = True) -> dict:
    atlas_details = stop.atlas_stop_details
    osm_details = stop.osm_node_details
    has_atlas_duplicate = bool(atlas_details and atlas_details.duplicate_group_sloids)
    has_osm_duplicate = bool(osm_details and osm_details.duplicate_group_node_ids)

    result = {
        "id": stop.id,
        "sloid": stop.sloid,
        "stop_type": stop.stop_type,
        "match_type": stop.match_type,
        "atlas_lat": stop.atlas_lat if stop.atlas_lat is not None else stop.osm_lat,
        "atlas_lon": stop.atlas_lon if stop.atlas_lon is not None else stop.osm_lon,
        "atlas_business_org_abbr": atlas_details.atlas_business_org_abbr if atlas_details else None,
        "atlas_operator": atlas_details.atlas_business_org_abbr if atlas_details else None,
        "atlas_name": atlas_details.atlas_designation if atlas_details else None,
        "atlas_local_ref": None,
        "atlas_transport_type": osm_details.osm_node_type if osm_details else None,
        "osm_lat": stop.osm_lat,
        "osm_lon": stop.osm_lon,
        "osm_network": osm_details.osm_network if osm_details else None,
        "osm_operator": osm_details.osm_operator if osm_details else None,
        "osm_public_transport": osm_details.osm_public_transport if osm_details else None,
        "osm_railway": osm_details.osm_railway if osm_details else None,
        "osm_amenity": osm_details.osm_amenity if osm_details else None,
        "osm_aerialway": osm_details.osm_aerialway if osm_details else None,
        "distance_m": stop.distance_m,
        "matching_notes": stop.matching_notes,
        "atlas_designation": atlas_details.atlas_designation if atlas_details else None,
        "atlas_designation_official": atlas_details.atlas_designation_official if atlas_details else None,
        "uic_ref": atlas_details.uic_ref if atlas_details else None,
        "osm_node_id": stop.osm_node_id,
        "osm_local_ref": osm_details.osm_local_ref if osm_details else None,
        "osm_name": osm_details.osm_name if osm_details else None,
        "osm_uic_name": osm_details.osm_uic_name if osm_details else None,
        "osm_uic_ref": osm_details.osm_uic_ref if osm_details else None,
        "has_atlas_duplicate": has_atlas_duplicate,
        "has_osm_duplicate": has_osm_duplicate,
        "representative_sloid": atlas_details.representative_sloid if atlas_details else None,
        "duplicate_group_sloids": atlas_details.duplicate_group_sloids if atlas_details else None,
        "duplicate_group_node_ids": osm_details.duplicate_group_node_ids if osm_details else None,
        "osm_node_type": osm_details.osm_node_type if osm_details else None,
        # Keep API stable across schema revisions where these columns may be absent.
        "osm_is_way": bool(getattr(osm_details, 'is_way', False)) if osm_details else False,
        "osm_source_way_id": getattr(osm_details, 'source_way_id', None) if osm_details else None,
    }

    if include_routes:
        result.update({
            "routes_unified": get_unified_routes_for_sloid(stop.sloid) if stop.sloid else [],
            "routes_osm": get_osm_routes_for_node(stop.osm_node_id) if stop.osm_node_id else [],
        })

    if problem_type:
        result["problem"] = problem_type

    return result


