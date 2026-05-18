from flask import current_app as app

from backend.extensions import db
from backend.models import Itinerary, LineFamily, LineFamilyMatch, StopCall

from matching_and_import_db.utils.route_id import normalize_route_id


def _clean_text(value):
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _build_atlas_route_payload(row):
    return {
        'route_id': row.source_family_id,
        'direction_id': row.direction_id,
        'route_name_short': _clean_text(row.ref),
        'route_name_long': _clean_text(row.public_name),
    }


def _build_osm_route_payload(row):
    return {
        'route_id': row.display_route_id,
        'display_route_id': row.display_route_id,
        'internal_route_id': row.source_itinerary_id,
        'direction_id': row.direction_id,
        'route_name': _clean_text(row.public_name) or _clean_text(row.ref) or _clean_text(row.display_route_id),
    }


def get_atlas_routes_for_sloids(sloids):
    normalized_sloids = sorted({str(sloid).strip() for sloid in (sloids or []) if str(sloid).strip()})
    if not normalized_sloids:
        return {}

    try:
        rows = (
            db.session.query(
                StopCall.source_sloid,
                LineFamily.source_family_id,
                Itinerary.direction_id,
                LineFamily.ref,
                LineFamily.public_name,
            )
            .join(Itinerary, Itinerary.line_family_id == LineFamily.id)
            .join(StopCall, StopCall.itinerary_id == Itinerary.id)
            .filter(LineFamily.source == 'atlas', StopCall.source_sloid.in_(normalized_sloids))
            .distinct()
            .order_by(StopCall.source_sloid.asc(), LineFamily.source_family_id.asc(), Itinerary.direction_id.asc())
            .all()
        )

        routes_by_sloid = {sloid: [] for sloid in normalized_sloids}
        for row in rows:
            routes_by_sloid.setdefault(row.source_sloid, []).append(_build_atlas_route_payload(row))
        return routes_by_sloid
    except Exception as exc:
        app.logger.error(f"Error fetching routes for sloids {normalized_sloids}: {exc}")
        return {sloid: [] for sloid in normalized_sloids}


def get_osm_routes_for_nodes(osm_node_ids):
    normalized_node_ids = sorted({str(node_id).strip() for node_id in (osm_node_ids or []) if str(node_id).strip()})
    if not normalized_node_ids:
        return {}

    try:
        rows = (
            db.session.query(
                StopCall.source_node_id,
                LineFamily.display_route_id,
                Itinerary.source_itinerary_id,
                Itinerary.direction_id,
                LineFamily.public_name,
                LineFamily.ref,
            )
            .join(Itinerary, Itinerary.line_family_id == LineFamily.id)
            .join(StopCall, StopCall.itinerary_id == Itinerary.id)
            .filter(LineFamily.source == 'osm', StopCall.source_node_id.in_(normalized_node_ids))
            .distinct()
            .order_by(StopCall.source_node_id.asc(), LineFamily.display_route_id.asc(), Itinerary.direction_id.asc())
            .all()
        )

        routes_by_node_id = {node_id: [] for node_id in normalized_node_ids}
        for row in rows:
            routes_by_node_id.setdefault(row.source_node_id, []).append(_build_osm_route_payload(row))
        return routes_by_node_id
    except Exception as exc:
        app.logger.error(f"Error fetching routes for osm_node_ids {normalized_node_ids}: {exc}")
        return {node_id: [] for node_id in normalized_node_ids}


def get_atlas_routes_for_sloid(sloid):
    if not sloid:
        return []
    return get_atlas_routes_for_sloids([sloid]).get(str(sloid), [])


def get_osm_routes_for_node(osm_node_id):
    if not osm_node_id:
        return []
    return get_osm_routes_for_nodes([osm_node_id]).get(str(osm_node_id), [])


def get_stops_for_route(route_id, direction=None):
    try:
        normalized_input = normalize_route_id(route_id) if route_id else None

        direct_family_rows = (
            db.session.query(LineFamily.id, LineFamily.source)
            .filter(
                db.or_(
                    LineFamily.source_family_id == route_id,
                    LineFamily.display_route_id == route_id,
                    LineFamily.gtfs_route_id == route_id,
                    LineFamily.representative_relation_id == route_id,
                    LineFamily.normalized_route_id == normalized_input,
                )
            )
            .all()
        )

        atlas_family_ids = {row.id for row in direct_family_rows if row.source == 'atlas'}
        osm_family_ids = {row.id for row in direct_family_rows if row.source == 'osm'}

        if atlas_family_ids:
            matched_osm_ids = (
                db.session.query(LineFamilyMatch.osm_line_family_id)
                .filter(LineFamilyMatch.atlas_line_family_id.in_(atlas_family_ids))
                .all()
            )
            osm_family_ids |= {row.osm_line_family_id for row in matched_osm_ids}

        if osm_family_ids:
            matched_atlas_ids = (
                db.session.query(LineFamilyMatch.atlas_line_family_id)
                .filter(LineFamilyMatch.osm_line_family_id.in_(osm_family_ids))
                .all()
            )
            atlas_family_ids |= {row.atlas_line_family_id for row in matched_atlas_ids}

        atlas_query = (
            db.session.query(StopCall.source_sloid)
            .join(Itinerary, Itinerary.id == StopCall.itinerary_id)
            .filter(Itinerary.line_family_id.in_(atlas_family_ids), StopCall.source_sloid.isnot(None))
        ) if atlas_family_ids else None
        osm_query = (
            db.session.query(StopCall.source_node_id)
            .join(Itinerary, Itinerary.id == StopCall.itinerary_id)
            .filter(Itinerary.line_family_id.in_(osm_family_ids), StopCall.source_node_id.isnot(None))
        ) if osm_family_ids else None

        if direction:
            if atlas_query is not None:
                atlas_query = atlas_query.filter(Itinerary.direction_id == direction)
            if osm_query is not None:
                osm_query = osm_query.filter(Itinerary.direction_id == direction)

        atlas_sloids = [row[0] for row in atlas_query.distinct().all()] if atlas_query is not None else []
        osm_nodes = [row[0] for row in osm_query.distinct().all()] if osm_query is not None else []

        app.logger.info(
            f"Found {len(osm_nodes)} OSM nodes and {len(atlas_sloids)} ATLAS sloids for route {route_id}"
            + (f" with direction {direction}" if direction else '')
        )
        return {
            'osm_nodes': list(set(osm_nodes)),
            'atlas_sloids': list(set(atlas_sloids)),
        }
    except Exception as exc:
        app.logger.error(f"Error retrieving stops for route {route_id}: {exc}")
        return {'osm_nodes': [], 'atlas_sloids': []}