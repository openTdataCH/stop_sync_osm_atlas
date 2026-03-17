from flask import Blueprint, render_template, request
from sqlalchemy import or_

from backend.extensions import db
from backend.models import AtlasStop, OsmNode, RouteAtlasStops, RouteOsmStops, RoutesMatched


routes_bp = Blueprint('routes', __name__)


def _direction_sort_key(direction_id):
    """Sort directions: numeric first, then text, empty last."""
    if direction_id is None:
        return (2, "")

    direction_text = str(direction_id).strip()
    if direction_text == "":
        return (2, "")

    if direction_text.lstrip('-').isdigit():
        return (0, int(direction_text))

    return (1, direction_text.lower())


def _bounded_int(value, default, minimum=None, maximum=None):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default

    if minimum is not None and parsed < minimum:
        parsed = minimum
    if maximum is not None and parsed > maximum:
        parsed = maximum

    return parsed


def _load_atlas_route_stops(atlas_route_ids):
    if not atlas_route_ids:
        return {}

    rows = (
        db.session.query(
            RouteAtlasStops.atlas_route_id,
            RouteAtlasStops.direction_id,
            RouteAtlasStops.sloid,
            RouteAtlasStops.stop_sequence,
            AtlasStop.atlas_designation_official,
            AtlasStop.atlas_designation,
        )
        .outerjoin(AtlasStop, RouteAtlasStops.sloid == AtlasStop.sloid)
        .filter(RouteAtlasStops.atlas_route_id.in_(atlas_route_ids))
        .order_by(
            RouteAtlasStops.atlas_route_id.asc(),
            RouteAtlasStops.direction_id.asc(),
            RouteAtlasStops.stop_sequence.asc(),
            RouteAtlasStops.id.asc(),
        )
        .all()
    )

    grouped = {}
    for row in rows:
        route_key = row.atlas_route_id
        direction_key = "" if row.direction_id is None else str(row.direction_id)
        route_bucket = grouped.setdefault(route_key, {})
        direction_bucket = route_bucket.setdefault(direction_key, [])
        stop_label = row.atlas_designation_official or row.atlas_designation or row.sloid
        direction_bucket.append(
            {
                "stop_id": row.sloid,
                "stop_label": stop_label,
                "stop_sequence": row.stop_sequence,
            }
        )

    return grouped


def _load_osm_route_stops(osm_route_ids):
    if not osm_route_ids:
        return {}

    rows = (
        db.session.query(
            RouteOsmStops.osm_route_id,
            RouteOsmStops.direction_id,
            RouteOsmStops.osm_node_id,
            RouteOsmStops.stop_sequence,
            OsmNode.osm_name,
            OsmNode.osm_uic_name,
            OsmNode.osm_local_ref,
        )
        .outerjoin(OsmNode, RouteOsmStops.osm_node_id == OsmNode.osm_node_id)
        .filter(RouteOsmStops.osm_route_id.in_(osm_route_ids))
        .order_by(
            RouteOsmStops.osm_route_id.asc(),
            RouteOsmStops.direction_id.asc(),
            RouteOsmStops.stop_sequence.asc(),
            RouteOsmStops.id.asc(),
        )
        .all()
    )

    grouped = {}
    for row in rows:
        route_key = row.osm_route_id
        direction_key = "" if row.direction_id is None else str(row.direction_id)
        route_bucket = grouped.setdefault(route_key, {})
        direction_bucket = route_bucket.setdefault(direction_key, [])
        stop_label = row.osm_name or row.osm_uic_name or row.osm_local_ref or row.osm_node_id
        direction_bucket.append(
            {
                "stop_id": row.osm_node_id,
                "stop_label": stop_label,
                "stop_sequence": row.stop_sequence,
            }
        )

    return grouped


@routes_bp.route('/routes')
def routes_page():
    q = (request.args.get('q') or '').strip()
    page = _bounded_int(request.args.get('page'), default=1, minimum=1)
    per_page = _bounded_int(request.args.get('per_page'), default=20, minimum=5, maximum=100)

    matched_routes_query = RoutesMatched.query
    if q:
        like_pattern = f"%{q}%"
        matched_routes_query = matched_routes_query.filter(
            or_(
                RoutesMatched.atlas_route_id.ilike(like_pattern),
                RoutesMatched.osm_route_id.ilike(like_pattern),
            )
        )

    matched_routes_page = (
        matched_routes_query
        .order_by(RoutesMatched.atlas_route_id.asc(), RoutesMatched.osm_route_id.asc())
        .paginate(page=page, per_page=per_page, error_out=False)
    )

    atlas_route_ids = sorted({item.atlas_route_id for item in matched_routes_page.items if item.atlas_route_id})
    osm_route_ids = sorted({item.osm_route_id for item in matched_routes_page.items if item.osm_route_id})

    atlas_stops_by_route = _load_atlas_route_stops(atlas_route_ids)
    osm_stops_by_route = _load_osm_route_stops(osm_route_ids)

    route_rows = []
    for matched in matched_routes_page.items:
        atlas_directions = atlas_stops_by_route.get(matched.atlas_route_id, {})
        osm_directions = osm_stops_by_route.get(matched.osm_route_id, {})

        all_directions = set(atlas_directions.keys()) | set(osm_directions.keys())
        direction_groups = []
        for direction_id in sorted(all_directions, key=_direction_sort_key):
            direction_groups.append(
                {
                    "direction_id": direction_id,
                    "atlas_stops": atlas_directions.get(direction_id, []),
                    "osm_stops": osm_directions.get(direction_id, []),
                }
            )

        route_rows.append(
            {
                "atlas_route_id": matched.atlas_route_id,
                "atlas_route_name": matched.atlas_route_id,
                "osm_route_id": matched.osm_route_id,
                "osm_route_name": matched.osm_route_id,
                "direction_groups": direction_groups,
            }
        )

    if matched_routes_page.total > 0:
        range_start = ((matched_routes_page.page - 1) * matched_routes_page.per_page) + 1
        range_end = range_start + len(matched_routes_page.items) - 1
    else:
        range_start = 0
        range_end = 0

    return render_template(
        'pages/routes.html',
        route_rows=route_rows,
        pagination=matched_routes_page,
        q=q,
        per_page=per_page,
        range_start=range_start,
        range_end=range_end,
    )