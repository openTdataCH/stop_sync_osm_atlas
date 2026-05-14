from flask import current_app as app

from backend.extensions import db
from backend.models import AtlasLineFamily, Itinerary, LineFamily, LineFamilyMatch, OsmRouteRelation, StopCall

from matching_and_import_db.utils.route_id import normalize_route_id


def _clean_text(value):
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def get_osm_route_metadata(route_id: str | None) -> dict[str, str | None]:
    if not route_id:
        return {
            'relation_id': None,
            'gtfs_route_id': None,
            'name': None,
            'ref': None,
        }

    try:
        row = (
            db.session.query(OsmRouteRelation.gtfs_route_id, OsmRouteRelation.name, OsmRouteRelation.ref)
            .filter(OsmRouteRelation.relation_id == route_id)
            .first()
        )
    except Exception as exc:
        app.logger.error(f"Error fetching OSM route metadata for {route_id}: {exc}")
        return {
            'relation_id': route_id,
            'gtfs_route_id': None,
            'name': None,
            'ref': None,
        }

    return {
        'relation_id': route_id,
        'gtfs_route_id': _clean_text(getattr(row, 'gtfs_route_id', None)) if row else None,
        'name': _clean_text(getattr(row, 'name', None)) if row else None,
        'ref': _clean_text(getattr(row, 'ref', None)) if row else None,
    }


def get_atlas_route_metadata(route_id: str | None) -> dict[str, str | None]:
    if not route_id:
        return {'route_name_short': None, 'route_name_long': None}

    try:
        row = db.session.get(AtlasLineFamily, route_id)
    except Exception as exc:
        app.logger.error(f"Error fetching ATLAS route metadata for {route_id}: {exc}")
        return {'route_name_short': None, 'route_name_long': None}

    if row is None:
        return {'route_name_short': None, 'route_name_long': None}

    return {
        'route_name_short': _clean_text(row.route_short_name),
        'route_name_long': _clean_text(row.route_long_name),
    }


def get_atlas_route_display_name(route_id: str | None) -> str | None:
    if not route_id:
        return None
    metadata = get_atlas_route_metadata(route_id)
    return metadata.get('route_name_short') or metadata.get('route_name_long') or route_id


def get_osm_route_display_id(route_id: str | None) -> str | None:
    if not route_id:
        return None
    return get_osm_route_metadata(route_id).get('gtfs_route_id') or route_id


def get_osm_route_name(route_id: str | None) -> str | None:
    if not route_id:
        return None
    metadata = get_osm_route_metadata(route_id)
    return metadata.get('name') or metadata.get('ref') or metadata.get('gtfs_route_id') or route_id


def get_osm_route_display_name(route_id: str | None) -> str | None:
    if not route_id:
        return None
    return get_osm_route_name(route_id)


def get_atlas_routes_for_sloid(sloid):
    if not sloid:
        return []
    try:
        rows = (
            db.session.query(LineFamily.source_family_id, Itinerary.direction_id, LineFamily.ref, LineFamily.public_name)
            .join(Itinerary, Itinerary.line_family_id == LineFamily.id)
            .join(StopCall, StopCall.itinerary_id == Itinerary.id)
            .filter(LineFamily.source == 'atlas', StopCall.source_sloid == sloid)
            .distinct()
            .order_by(LineFamily.source_family_id.asc(), Itinerary.direction_id.asc())
            .all()
        )
        return [
            {
                'route_id': row.source_family_id,
                'direction_id': row.direction_id,
                'route_name_short': _clean_text(row.ref),
                'route_name_long': _clean_text(row.public_name),
            }
            for row in rows
        ]
    except Exception as exc:
        app.logger.error(f"Error fetching routes for sloid {sloid}: {exc}")
        return []


def get_osm_routes_for_node(osm_node_id):
    if not osm_node_id:
        return []
    try:
        rows = (
            db.session.query(
                LineFamily.display_route_id,
                Itinerary.source_itinerary_id,
                Itinerary.direction_id,
                LineFamily.public_name,
                LineFamily.ref,
            )
            .join(Itinerary, Itinerary.line_family_id == LineFamily.id)
            .join(StopCall, StopCall.itinerary_id == Itinerary.id)
            .filter(LineFamily.source == 'osm', StopCall.source_node_id == str(osm_node_id))
            .distinct()
            .order_by(LineFamily.display_route_id.asc(), Itinerary.direction_id.asc())
            .all()
        )
        return [
            {
                'route_id': row.display_route_id,
                'display_route_id': row.display_route_id,
                'internal_route_id': row.source_itinerary_id,
                'direction_id': row.direction_id,
                'route_name': _clean_text(row.public_name) or _clean_text(row.ref) or _clean_text(row.display_route_id),
            }
            for row in rows
        ]
    except Exception as exc:
        app.logger.error(f"Error fetching routes for osm_node_id {osm_node_id}: {exc}")
        return []


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