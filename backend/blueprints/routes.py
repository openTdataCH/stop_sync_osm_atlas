from collections import Counter

from flask import Blueprint, jsonify, render_template, request
from sqlalchemy import func, literal, or_

from backend.db_errors import is_missing_table_error
from backend.extensions import db
from backend.models import AtlasRoute, AtlasRouteDirection, AtlasStop, OsmNode, OsmRoute, RouteAtlasStops, RouteOsmStops, RoutesMatched, StopsMatched
from backend.services.gtfs_stop_id_sloid import (
    GTFS_STOP_ID_SLOID_DETAIL_LIMIT,
    GTFS_STOP_ID_SLOID_DETAIL_ZOOM,
    GTFS_STOP_ID_SLOID_OVERVIEW_LIMIT,
    build_atlas_stop_popup,
    build_gtfs_stop_id_sloid_map_payload,
    build_gtfs_stop_id_sloid_summary,
    build_gtfs_stop_popup,
)
from backend.services.transport_routes import get_atlas_route_display_name, get_osm_route_display_name


routes_bp = Blueprint('routes', __name__)

ROUTE_MATCH_ALL = 'all'
ROUTE_MATCHED = 'matched'
ROUTE_UNMATCHED = 'unmatched'
ROUTE_UNMATCHED_ATLAS = 'unmatched_atlas'
ROUTE_UNMATCHED_OSM = 'unmatched_osm'
ROUTE_MATCH_FILTERS = {
    ROUTE_MATCH_ALL,
    ROUTE_MATCHED,
    ROUTE_UNMATCHED,
    ROUTE_UNMATCHED_ATLAS,
    ROUTE_UNMATCHED_OSM,
}

ROUTES_PER_PAGE_OPTIONS = [5, 10, 20, 50, 100]

MATCH_FILTER_LABELS = {
    ROUTE_MATCH_ALL: 'All',
    ROUTE_MATCHED: 'Matched',
    ROUTE_UNMATCHED: 'Unmatched',
    ROUTE_UNMATCHED_ATLAS: 'Unmatched ATLAS',
    ROUTE_UNMATCHED_OSM: 'Unmatched OSM',
}

ROUTES_VIEW_ROUTES = 'routes'
ROUTES_VIEW_GTFS_STOP_ID_SLOID = 'gtfs_stop_id_sloid'


class _EmptyPagination:
    def __init__(self, page, per_page):
        self.page = page
        self.per_page = per_page
        self.total = 0
        self.pages = 0
        self.has_prev = False
        self.has_next = False
        self.prev_num = 1
        self.next_num = 1

    def iter_pages(self, **_kwargs):
        return []


def _normalize_route_match_filter(value: str | None) -> str:
    matched = (value or '').strip().lower()
    return matched if matched in ROUTE_MATCH_FILTERS else ROUTE_MATCH_ALL


def _parse_atlas_operator_filter() -> list[str]:
    selected = [
        value.strip()
        for value in request.args.getlist('atlas_operator')
        if value and value.strip()
    ]
    if selected:
        return sorted(set(selected))

    raw = (request.args.get('atlas_operator') or '').strip()
    if not raw:
        return []

    return sorted({operator.strip() for operator in raw.split(',') if operator.strip()})


def _serialize_atlas_operator_filter(atlas_operators: list[str]) -> str:
    return ','.join(sorted(set(atlas_operators)))


def _search_placeholder() -> str:
    return 'Search Atlas or OSM GTFS route ID'


def _filters_summary_text(matched_filter: str) -> str:
    matched_label = MATCH_FILTER_LABELS.get(matched_filter, MATCH_FILTER_LABELS[ROUTE_MATCH_ALL])
    return f'Status: {matched_label}'


def _render_routes_template(active_view: str, **context):
    return render_template(
        'pages/routes.html',
        active_view=active_view,
        gtfs_stop_id_sloid_detail_zoom=GTFS_STOP_ID_SLOID_DETAIL_ZOOM,
        gtfs_stop_id_sloid_detail_limit=GTFS_STOP_ID_SLOID_DETAIL_LIMIT,
        gtfs_stop_id_sloid_overview_limit=GTFS_STOP_ID_SLOID_OVERVIEW_LIMIT,
        **context,
    )


def _load_available_atlas_operators() -> list[str]:
    try:
        rows = (
            db.session.query(AtlasStop.atlas_business_org_abbr)
            .filter(AtlasStop.atlas_business_org_abbr.isnot(None))
            .filter(AtlasStop.atlas_business_org_abbr != '')
            .distinct()
            .order_by(AtlasStop.atlas_business_org_abbr.asc())
            .all()
        )
        return [row[0] for row in rows if row and row[0]]
    except Exception as exc:
        if is_missing_table_error(exc):
            db.session.rollback()
            return []
        raise


def _extract_scalar_id(row, key):
    """Extract a route_id value from model/tuple/SQLAlchemy row payloads."""
    if row is None:
        return None

    if isinstance(row, tuple):
        return row[0] if row else None

    if hasattr(row, '_mapping') and key in row._mapping:
        return row._mapping[key]

    if hasattr(row, key):
        return getattr(row, key)

    try:
        return row[0]
    except Exception:
        return None


def _clean_text(value):
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _group_stops_by_uic(direction_stops):
    """Group ordered stops by UIC for two-level rendering in the routes view."""
    if not direction_stops:
        return []

    grouped_by_uic = {}
    order = []

    for idx, stop in enumerate(direction_stops):
        uic = stop.get("uic_ref") or ""
        if uic not in grouped_by_uic:
            grouped_by_uic[uic] = {
                "uic_ref": uic,
                "stop_label": stop.get("stop_label") or '-',
                "members": [],
                "first_idx": idx,
            }
            order.append(uic)

        grouped_by_uic[uic]["members"].append(
            {
                "stop_id": stop.get("stop_id"),
                "stop_label": stop.get("stop_label") or '-',
                "stop_sequence": stop.get("stop_sequence"),
                "lat": stop.get("lat"),
                "lon": stop.get("lon"),
            }
        )

    groups = [grouped_by_uic[uic] for uic in order]
    for group in groups:
        group["member_count"] = len(group["members"])

    return groups


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


def _direction_summary(direction_groups):
    if not direction_groups:
        return None

    labels = [
        group['direction_id'] if group['direction_id'] else 'Unspecified'
        for group in direction_groups
    ]
    summary = ', '.join(labels[:4])
    if len(labels) > 4:
        summary += f" (+{len(labels) - 4} more)"
    return summary


def _compute_page_range(pagination):
    if pagination.total <= 0:
        return 0, 0

    start = ((pagination.page - 1) * pagination.per_page) + 1
    end = start + len(pagination.items) - 1
    return start, end


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


def _parse_gtfs_stop_id_sloid_bbox_args():
    return (
        float(request.args.get('min_lat', '0')),
        float(request.args.get('min_lon', '0')),
        float(request.args.get('max_lat', '0')),
        float(request.args.get('max_lon', '0')),
    )


def _empty_gtfs_stop_id_sloid_map_payload(zoom: int):
    return {
        'gtfs_stops': [],
        'atlas_stops': [],
        'matches': [],
        'meta': {
            'zoom': zoom,
            'detail_zoom': GTFS_STOP_ID_SLOID_DETAIL_ZOOM,
            'detail_limit': GTFS_STOP_ID_SLOID_DETAIL_LIMIT,
            'overview_limit': GTFS_STOP_ID_SLOID_OVERVIEW_LIMIT,
            'overview_mode': zoom < GTFS_STOP_ID_SLOID_DETAIL_ZOOM,
            'gtfs_capped': False,
            'atlas_capped': False,
            'gtfs_returned': 0,
            'atlas_returned': 0,
            'matches_returned': 0,
        },
    }


def _load_atlas_route_stops(atlas_route_ids):
    if not atlas_route_ids:
        return {}

    rows = (
        db.session.query(
            RouteAtlasStops.atlas_route_id,
            RouteAtlasStops.direction_id,
            RouteAtlasStops.sloid,
            RouteAtlasStops.stop_sequence,
            AtlasStop.uic_ref,
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

    sloids = sorted({row.sloid for row in rows if row.sloid})
    atlas_coords_by_sloid = _load_atlas_stop_coordinates(sloids)

    grouped = {}
    for row in rows:
        route_key = row.atlas_route_id
        direction_key = "" if row.direction_id is None else str(row.direction_id)
        route_bucket = grouped.setdefault(route_key, {})
        direction_bucket = route_bucket.setdefault(direction_key, [])
        stop_label = row.atlas_designation_official or row.atlas_designation or row.sloid
        stop_coords = atlas_coords_by_sloid.get(row.sloid, (None, None))
        direction_bucket.append(
            {
                "stop_id": row.sloid,
                "stop_label": stop_label,
                "uic_ref": row.uic_ref,
                "shared_uic_count": 0,
                "stop_sequence": row.stop_sequence,
                "lat": stop_coords[0],
                "lon": stop_coords[1],
            }
        )

    for route_bucket in grouped.values():
        for direction_bucket in route_bucket.values():
            uic_counts = Counter(
                stop.get("uic_ref")
                for stop in direction_bucket
                if stop.get("uic_ref")
            )
            for stop in direction_bucket:
                uic = stop.get("uic_ref")
                stop["shared_uic_count"] = uic_counts.get(uic, 0) if uic else 0

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
            OsmNode.osm_uic_ref,
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

    osm_node_ids = sorted({row.osm_node_id for row in rows if row.osm_node_id})
    osm_coords_by_node = _load_osm_stop_coordinates(osm_node_ids)

    grouped = {}
    for row in rows:
        route_key = row.osm_route_id
        direction_key = "" if row.direction_id is None else str(row.direction_id)
        route_bucket = grouped.setdefault(route_key, {})
        direction_bucket = route_bucket.setdefault(direction_key, [])
        stop_label = row.osm_name or row.osm_uic_name or row.osm_local_ref or row.osm_node_id
        stop_coords = osm_coords_by_node.get(row.osm_node_id, (None, None))
        direction_bucket.append(
            {
                "stop_id": row.osm_node_id,
                "stop_label": stop_label,
                "uic_ref": row.osm_uic_ref,
                "shared_uic_count": 0,
                "stop_sequence": row.stop_sequence,
                "lat": stop_coords[0],
                "lon": stop_coords[1],
            }
        )

    for route_bucket in grouped.values():
        for direction_bucket in route_bucket.values():
            uic_counts = Counter(
                stop.get("uic_ref")
                for stop in direction_bucket
                if stop.get("uic_ref")
            )
            for stop in direction_bucket:
                uic = stop.get("uic_ref")
                stop["shared_uic_count"] = uic_counts.get(uic, 0) if uic else 0

    return grouped


def _load_atlas_stop_coordinates(sloids):
    if not sloids:
        return {}

    rows = (
        db.session.query(StopsMatched.sloid, StopsMatched.atlas_lat, StopsMatched.atlas_lon)
        .filter(StopsMatched.sloid.in_(sloids))
        .filter(StopsMatched.atlas_lat.isnot(None))
        .filter(StopsMatched.atlas_lon.isnot(None))
        .order_by(StopsMatched.sloid.asc(), StopsMatched.id.asc())
        .all()
    )

    coords = {}
    for row in rows:
        if row.sloid and row.sloid not in coords:
            coords[row.sloid] = (float(row.atlas_lat), float(row.atlas_lon))
    return coords


def _load_osm_stop_coordinates(osm_node_ids):
    if not osm_node_ids:
        return {}

    rows = (
        db.session.query(StopsMatched.osm_node_id, StopsMatched.osm_lat, StopsMatched.osm_lon)
        .filter(StopsMatched.osm_node_id.in_(osm_node_ids))
        .filter(StopsMatched.osm_lat.isnot(None))
        .filter(StopsMatched.osm_lon.isnot(None))
        .order_by(StopsMatched.osm_node_id.asc(), StopsMatched.id.asc())
        .all()
    )

    coords = {}
    for row in rows:
        if row.osm_node_id and row.osm_node_id not in coords:
            coords[row.osm_node_id] = (float(row.osm_lat), float(row.osm_lon))
    return coords


def _load_atlas_route_operators(atlas_route_ids):
    if not atlas_route_ids:
        return {}

    rows = (
        db.session.query(RouteAtlasStops.atlas_route_id, AtlasStop.atlas_business_org_abbr)
        .join(AtlasStop, RouteAtlasStops.sloid == AtlasStop.sloid)
        .filter(RouteAtlasStops.atlas_route_id.in_(atlas_route_ids))
        .filter(AtlasStop.atlas_business_org_abbr.isnot(None))
        .filter(AtlasStop.atlas_business_org_abbr != '')
        .distinct()
        .order_by(RouteAtlasStops.atlas_route_id.asc(), AtlasStop.atlas_business_org_abbr.asc())
        .all()
    )

    grouped = {}
    for row in rows:
        grouped.setdefault(row.atlas_route_id, []).append(row.atlas_business_org_abbr)
    return grouped


def _load_atlas_route_metadata(atlas_route_ids):
    if not atlas_route_ids:
        return {}

    rows = (
        db.session.query(AtlasRoute.route_id, AtlasRoute.route_short_name, AtlasRoute.route_long_name)
        .filter(AtlasRoute.route_id.in_(atlas_route_ids))
        .all()
    )

    metadata = {}
    for row in rows:
        metadata[row.route_id] = {
            'route_short_name': _clean_text(row.route_short_name),
            'route_long_name': _clean_text(row.route_long_name),
        }
    return metadata


def _load_atlas_direction_metadata(atlas_route_ids):
    if not atlas_route_ids:
        return {}

    rows = (
        db.session.query(
            AtlasRouteDirection.route_id,
            AtlasRouteDirection.direction_id,
            AtlasRouteDirection.representative_headsign,
            AtlasRouteDirection.direction_label,
        )
        .filter(AtlasRouteDirection.route_id.in_(atlas_route_ids))
        .order_by(AtlasRouteDirection.route_id.asc(), AtlasRouteDirection.direction_id.asc(), AtlasRouteDirection.id.asc())
        .all()
    )

    metadata = {}
    for row in rows:
        route_bucket = metadata.setdefault(row.route_id, {})
        direction_key = '' if row.direction_id is None else str(row.direction_id)
        route_bucket[direction_key] = {
            'representative_headsign': _clean_text(row.representative_headsign),
            'direction_label': _clean_text(row.direction_label),
        }
    return metadata


def _load_atlas_to_osm_map(atlas_route_ids):
    if not atlas_route_ids:
        return {}

    rows = (
        db.session.query(RoutesMatched.atlas_route_id, RoutesMatched.osm_route_id)
        .filter(RoutesMatched.atlas_route_id.in_(atlas_route_ids))
        .filter(RoutesMatched.osm_route_id.isnot(None))
        .order_by(RoutesMatched.atlas_route_id.asc(), RoutesMatched.osm_route_id.asc())
        .all()
    )

    mapping = {}
    for row in rows:
        if row.atlas_route_id and row.atlas_route_id not in mapping:
            mapping[row.atlas_route_id] = row.osm_route_id
    return mapping


def _load_osm_to_atlas_map(osm_route_ids):
    if not osm_route_ids:
        return {}

    rows = (
        db.session.query(RoutesMatched.osm_route_id, RoutesMatched.atlas_route_id)
        .filter(RoutesMatched.osm_route_id.in_(osm_route_ids))
        .filter(RoutesMatched.atlas_route_id.isnot(None))
        .order_by(RoutesMatched.osm_route_id.asc(), RoutesMatched.atlas_route_id.asc())
        .all()
    )

    mapping = {}
    for row in rows:
        if row.osm_route_id and row.osm_route_id not in mapping:
            mapping[row.osm_route_id] = row.atlas_route_id
    return mapping


def _load_osm_route_metadata(osm_route_ids):
    if not osm_route_ids:
        return {}

    rows = (
        db.session.query(OsmRoute.relation_id, OsmRoute.gtfs_route_id, OsmRoute.name, OsmRoute.ref, OsmRoute.operator)
        .filter(OsmRoute.relation_id.in_(osm_route_ids))
        .all()
    )

    metadata = {}
    for row in rows:
        metadata[row.relation_id] = {
            'gtfs_route_id': _clean_text(row.gtfs_route_id),
            'display_name': _clean_text(row.name) or _clean_text(row.ref) or _clean_text(row.gtfs_route_id),
            'operator': _clean_text(row.operator),
        }
    return metadata


def _build_direction_groups(atlas_directions, osm_directions, atlas_direction_metadata):
    all_directions = set(atlas_directions.keys()) | set(osm_directions.keys())
    direction_groups = []
    for direction_id in sorted(all_directions, key=_direction_sort_key):
        atlas_stops = atlas_directions.get(direction_id, [])
        osm_stops = osm_directions.get(direction_id, [])
        direction_metadata = atlas_direction_metadata.get(direction_id, {}) if atlas_direction_metadata else {}
        direction_groups.append(
            {
                'direction_id': direction_id,
                'direction_label': direction_metadata.get('direction_label'),
                'representative_headsign': direction_metadata.get('representative_headsign'),
                'atlas_uic_groups': _group_stops_by_uic(atlas_stops),
                'osm_uic_groups': _group_stops_by_uic(osm_stops),
            }
        )
    return direction_groups


def _extract_coordinates_from_direction_groups(direction_groups):
    coordinates = []
    for direction in direction_groups:
        for group_key in ('atlas_uic_groups', 'osm_uic_groups'):
            for group in direction.get(group_key, []):
                for member in group.get('members', []):
                    lat = member.get('lat')
                    lon = member.get('lon')
                    if lat is None or lon is None:
                        continue
                    try:
                        lat_value = float(lat)
                        lon_value = float(lon)
                    except (TypeError, ValueError):
                        continue
                    if -90 <= lat_value <= 90 and -180 <= lon_value <= 180:
                        coordinates.append((lat_value, lon_value))
    return coordinates


def _build_route_map_filter(atlas_route_id, osm_route_id):
    filter_values = []
    if atlas_route_id:
        filter_values.append(atlas_route_id)
    if osm_route_id and osm_route_id not in filter_values:
        filter_values.append(osm_route_id)

    if not filter_values:
        return None

    filter_types = ['route'] * len(filter_values)
    route_directions = [''] * len(filter_values)

    return {
        'station_filter': ','.join(filter_values),
        'filter_types': ','.join(filter_types),
        'route_directions': ','.join(route_directions),
    }


def _route_display_mode(atlas_route_id, osm_route_id):
    if atlas_route_id and osm_route_id:
        return 'matched'
    if atlas_route_id:
        return 'atlas_only'
    if osm_route_id:
        return 'osm_only'
    return 'unmatched'


def _matched_routes_query(atlas_operators, q):
    query = (
        db.session.query(
            literal('matched').label('entry_type'),
            RouteAtlasStops.atlas_route_id.label('atlas_route_id'),
            func.min(RoutesMatched.osm_route_id).label('osm_route_id'),
            func.coalesce(AtlasRoute.route_id, OsmRoute.gtfs_route_id, RouteAtlasStops.atlas_route_id).label('sort_route_id'),
        )
        .join(RoutesMatched, RouteAtlasStops.atlas_route_id == RoutesMatched.atlas_route_id)
        .outerjoin(AtlasRoute, RouteAtlasStops.atlas_route_id == AtlasRoute.route_id)
        .outerjoin(OsmRoute, RoutesMatched.osm_route_id == OsmRoute.relation_id)
        .filter(RouteAtlasStops.atlas_route_id.isnot(None))
        .filter(RoutesMatched.osm_route_id.isnot(None))
    )

    if atlas_operators:
        query = query.join(AtlasStop, RouteAtlasStops.sloid == AtlasStop.sloid)
        query = query.filter(AtlasStop.atlas_business_org_abbr.in_(atlas_operators))

    if q:
        query = query.filter(
            or_(
                RouteAtlasStops.atlas_route_id.ilike(f'%{q}%'),
                OsmRoute.gtfs_route_id.ilike(f'%{q}%'),
            )
        )

    return query.group_by(RouteAtlasStops.atlas_route_id, AtlasRoute.route_id, OsmRoute.gtfs_route_id)


def _unmatched_atlas_routes_query(atlas_operators, q):
    matched_atlas_subquery = (
        db.session.query(RoutesMatched.atlas_route_id)
        .filter(RoutesMatched.atlas_route_id.isnot(None))
    )

    query = (
        db.session.query(
            literal('atlas_only').label('entry_type'),
            RouteAtlasStops.atlas_route_id.label('atlas_route_id'),
            literal(None).label('osm_route_id'),
            func.coalesce(AtlasRoute.route_id, RouteAtlasStops.atlas_route_id).label('sort_route_id'),
        )
        .outerjoin(AtlasRoute, RouteAtlasStops.atlas_route_id == AtlasRoute.route_id)
        .filter(RouteAtlasStops.atlas_route_id.isnot(None))
        .filter(~RouteAtlasStops.atlas_route_id.in_(matched_atlas_subquery))
    )

    if atlas_operators:
        query = query.join(AtlasStop, RouteAtlasStops.sloid == AtlasStop.sloid)
        query = query.filter(AtlasStop.atlas_business_org_abbr.in_(atlas_operators))

    if q:
        query = query.filter(RouteAtlasStops.atlas_route_id.ilike(f'%{q}%'))

    return query.group_by(RouteAtlasStops.atlas_route_id, AtlasRoute.route_id)

def _unmatched_osm_routes_query(atlas_operators, q):
    matched_osm_subquery = (
        db.session.query(RoutesMatched.osm_route_id)
        .filter(RoutesMatched.osm_route_id.isnot(None))
    )

    query = (
        db.session.query(
            literal('osm_only').label('entry_type'),
            literal(None).label('atlas_route_id'),
            RouteOsmStops.osm_route_id.label('osm_route_id'),
            func.coalesce(OsmRoute.gtfs_route_id, RouteOsmStops.osm_route_id).label('sort_route_id'),
        )
        .outerjoin(OsmRoute, RouteOsmStops.osm_route_id == OsmRoute.relation_id)
        .filter(RouteOsmStops.osm_route_id.isnot(None))
        .filter(~RouteOsmStops.osm_route_id.in_(matched_osm_subquery))
    )

    if atlas_operators:
        query = query.filter(literal(False))

    if q:
        query = query.filter(OsmRoute.gtfs_route_id.ilike(f'%{q}%'))

    return query.group_by(RouteOsmStops.osm_route_id, OsmRoute.gtfs_route_id)

def _load_primary_route_page(matched_filter, atlas_operators, q, page, per_page):
    queries = []
    if matched_filter in {ROUTE_MATCH_ALL, ROUTE_MATCHED}:
        queries.append(_matched_routes_query(atlas_operators, q))
    if matched_filter in {ROUTE_MATCH_ALL, ROUTE_UNMATCHED, ROUTE_UNMATCHED_ATLAS}:
        queries.append(_unmatched_atlas_routes_query(atlas_operators, q))
    if matched_filter in {ROUTE_MATCH_ALL, ROUTE_UNMATCHED, ROUTE_UNMATCHED_OSM}:
        queries.append(_unmatched_osm_routes_query(atlas_operators, q))

    if not queries:
        return [], _EmptyPagination(page=page, per_page=per_page)

    combined_query = queries[0]
    for query in queries[1:]:
        combined_query = combined_query.union_all(query)

    raw_combined_subquery = combined_query.subquery()
    raw_columns = list(raw_combined_subquery.c)
    combined_subquery = (
        db.session.query(
            raw_columns[0].label('entry_type'),
            raw_columns[1].label('atlas_route_id'),
            raw_columns[2].label('osm_route_id'),
            raw_columns[3].label('sort_route_id'),
        )
        .subquery()
    )
    pagination = (
        db.session.query(combined_subquery)
        .order_by(
            combined_subquery.c.sort_route_id.asc().nulls_last(),
            combined_subquery.c.atlas_route_id.asc().nulls_last(),
            combined_subquery.c.osm_route_id.asc().nulls_last(),
        )
        .paginate(page=page, per_page=per_page, error_out=False)
    )

    return pagination.items, pagination


def _atlas_direction_context(direction_groups):
    labels = []
    context_label = None
    for direction in direction_groups:
        if direction.get('representative_headsign'):
            label = direction['representative_headsign']
            context_label = context_label or 'Headsign'
        else:
            label = direction.get('direction_label')
            context_label = context_label or ('Direction' if label else None)
        if label and label not in labels:
            labels.append(label)

    if not labels:
        return None, None

    summary = ', '.join(labels[:3])
    if len(labels) > 3:
        summary += f' (+{len(labels) - 3} more)'
    return summary, context_label


def _build_route_row(primary_route_id, atlas_route_id, osm_route_id, atlas_stops_by_route, osm_stops_by_route, atlas_operators_by_route, osm_route_metadata_by_id, atlas_route_metadata_by_id, atlas_direction_metadata_by_route):
    atlas_directions = atlas_stops_by_route.get(atlas_route_id, {}) if atlas_route_id else {}
    osm_directions = osm_stops_by_route.get(osm_route_id, {}) if osm_route_id else {}
    osm_metadata = osm_route_metadata_by_id.get(osm_route_id, {}) if osm_route_id else {}
    atlas_route_metadata = atlas_route_metadata_by_id.get(atlas_route_id, {}) if atlas_route_id else {}
    atlas_direction_metadata = atlas_direction_metadata_by_route.get(atlas_route_id, {}) if atlas_route_id else {}

    direction_groups = _build_direction_groups(atlas_directions, osm_directions, atlas_direction_metadata)
    is_matched = bool(atlas_route_id and osm_route_id)

    atlas_operators = atlas_operators_by_route.get(atlas_route_id, []) if atlas_route_id else []
    atlas_operators_summary = ', '.join(atlas_operators[:3])
    if len(atlas_operators) > 3:
        atlas_operators_summary += f' (+{len(atlas_operators) - 3} more)'

    map_filter = _build_route_map_filter(atlas_route_id, osm_route_id)
    display_mode = _route_display_mode(atlas_route_id, osm_route_id)
    atlas_direction_context, atlas_direction_context_label = _atlas_direction_context(direction_groups)
    atlas_route_short_name = atlas_route_metadata.get('route_short_name') or (get_atlas_route_display_name(atlas_route_id) if atlas_route_id else None)
    atlas_route_long_name = atlas_route_metadata.get('route_long_name')

    if display_mode == 'matched':
        match_label = 'Matched'
    elif display_mode == 'atlas_only':
        match_label = 'Unmatched ATLAS'
    elif display_mode == 'osm_only':
        match_label = 'Unmatched OSM'
    else:
        match_label = 'Unmatched'

    return {
        'route_key': f'{display_mode}:{primary_route_id}',
        'primary_route_id': primary_route_id,
        'is_matched': is_matched,
        'display_mode': display_mode,
        'match_label': match_label,
        'atlas_route_id': atlas_route_id,
        'atlas_route_name': get_atlas_route_display_name(atlas_route_id) if atlas_route_id else None,
        'atlas_route_short_name': atlas_route_short_name,
        'atlas_route_long_name': atlas_route_long_name,
        'atlas_direction_context': atlas_direction_context,
        'atlas_direction_context_label': atlas_direction_context_label or ('Long name' if atlas_route_long_name else None),
        'osm_route_id': osm_route_id,
        'osm_route_display_id': osm_metadata.get('gtfs_route_id'),
        'osm_route_name': osm_metadata.get('display_name') or (get_osm_route_display_name(osm_route_id) if osm_route_id else None),
        'osm_operator': osm_metadata.get('operator'),
        'atlas_operators': atlas_operators,
        'atlas_operators_summary': atlas_operators_summary,
        'direction_summary': _direction_summary(direction_groups),
        'direction_groups': direction_groups,
        'map_filter': map_filter,
        'map_point_count': len(_extract_coordinates_from_direction_groups(direction_groups)),
    }


def _load_routes_view(matched_filter, atlas_operators, q, page, per_page):
    primary_entries, pagination = _load_primary_route_page(
        matched_filter=matched_filter,
        atlas_operators=atlas_operators,
        q=q,
        page=page,
        per_page=per_page,
    )

    if not primary_entries:
        return [], pagination

    atlas_route_ids = sorted({row.atlas_route_id for row in primary_entries if getattr(row, 'atlas_route_id', None)})
    osm_route_ids = sorted({row.osm_route_id for row in primary_entries if getattr(row, 'osm_route_id', None)})

    atlas_stops_by_route = _load_atlas_route_stops(atlas_route_ids)
    osm_stops_by_route = _load_osm_route_stops(osm_route_ids)
    atlas_operators_by_route = _load_atlas_route_operators(atlas_route_ids)
    atlas_route_metadata_by_id = _load_atlas_route_metadata(atlas_route_ids)
    atlas_direction_metadata_by_route = _load_atlas_direction_metadata(atlas_route_ids)
    osm_route_metadata_by_id = _load_osm_route_metadata(osm_route_ids)

    route_rows = []
    for row in primary_entries:
        atlas_route_id = getattr(row, 'atlas_route_id', None)
        osm_route_id = getattr(row, 'osm_route_id', None)
        primary_route_id = atlas_route_id or osm_route_id
        route_rows.append(
            _build_route_row(
                primary_route_id=primary_route_id,
                atlas_route_id=atlas_route_id,
                osm_route_id=osm_route_id,
                atlas_stops_by_route=atlas_stops_by_route,
                osm_stops_by_route=osm_stops_by_route,
                atlas_operators_by_route=atlas_operators_by_route,
                osm_route_metadata_by_id=osm_route_metadata_by_id,
                atlas_route_metadata_by_id=atlas_route_metadata_by_id,
                atlas_direction_metadata_by_route=atlas_direction_metadata_by_route,
            )
        )

    return route_rows, pagination


@routes_bp.route('/routes')
def routes_page():
    matched_filter = _normalize_route_match_filter(request.args.get('matched'))
    selected_atlas_operators = _parse_atlas_operator_filter()
    atlas_operator_query = _serialize_atlas_operator_filter(selected_atlas_operators)

    q = (request.args.get('q') or '').strip()
    page = _bounded_int(request.args.get('page'), default=1, minimum=1)
    per_page = _bounded_int(request.args.get('per_page'), default=20, minimum=5, maximum=100)
    available_atlas_operators = []

    try:
        available_atlas_operators = _load_available_atlas_operators()
        route_rows, pagination = _load_routes_view(
            matched_filter=matched_filter,
            atlas_operators=selected_atlas_operators,
            q=q,
            page=page,
            per_page=per_page,
        )

        range_start, range_end = _compute_page_range(pagination)

        return _render_routes_template(
            ROUTES_VIEW_ROUTES,
            route_rows=route_rows,
            pagination=pagination,
            matched_filter=matched_filter,
            available_atlas_operators=available_atlas_operators,
            selected_atlas_operators=selected_atlas_operators,
            atlas_operator_query=atlas_operator_query,
            per_page_options=ROUTES_PER_PAGE_OPTIONS,
            match_filter_labels=MATCH_FILTER_LABELS,
            filters_summary=_filters_summary_text(matched_filter),
            search_placeholder=_search_placeholder(),
            q=q,
            per_page=per_page,
            range_start=range_start,
            range_end=range_end,
        )
    except Exception as e:
        if is_missing_table_error(e):
            db.session.rollback()
            empty_pagination = _EmptyPagination(page=page, per_page=per_page)
            return _render_routes_template(
                ROUTES_VIEW_ROUTES,
                route_rows=[],
                pagination=empty_pagination,
                matched_filter=matched_filter,
                available_atlas_operators=available_atlas_operators,
                selected_atlas_operators=selected_atlas_operators,
                atlas_operator_query=atlas_operator_query,
                per_page_options=ROUTES_PER_PAGE_OPTIONS,
                match_filter_labels=MATCH_FILTER_LABELS,
                filters_summary=_filters_summary_text(matched_filter),
                search_placeholder=_search_placeholder(),
                q=q,
                per_page=per_page,
                range_start=0,
                range_end=0,
            )
        raise


@routes_bp.route('/routes/gtfs-stop-id-sloid')
def routes_gtfs_stop_id_sloid_page():
    return _render_routes_template(ROUTES_VIEW_GTFS_STOP_ID_SLOID)


@routes_bp.route('/api/routes/gtfs-stop-id-sloid/summary')
def routes_gtfs_stop_id_sloid_summary_api():
    try:
        return jsonify(build_gtfs_stop_id_sloid_summary())
    except Exception as exc:
        if is_missing_table_error(exc):
            db.session.rollback()
            return jsonify({
                'algorithm_version': None,
                'total_gtfs_stops': 0,
                'matched_gtfs_stops': 0,
                'unmatched_gtfs_stops': 0,
                'gtfs_coverage_percent': 0.0,
                'total_atlas_stops': 0,
                'matched_atlas_stops': 0,
                'unmatched_atlas_stops': 0,
                'atlas_coverage_percent': 0.0,
                'assignments': {
                    'strict': 0,
                    'coordinate_proximity': 0,
                    'unique_number_fallback': 0,
                    'total': 0,
                },
            })
        raise


@routes_bp.route('/api/routes/gtfs-stop-id-sloid/map')
def routes_gtfs_stop_id_sloid_map_api():
    zoom = _bounded_int(request.args.get('zoom'), default=GTFS_STOP_ID_SLOID_DETAIL_ZOOM, minimum=0)
    try:
        min_lat, min_lon, max_lat, max_lon = _parse_gtfs_stop_id_sloid_bbox_args()
    except ValueError:
        return jsonify({'error': 'Invalid viewport bounds'}), 400

    try:
        return jsonify(build_gtfs_stop_id_sloid_map_payload(min_lat, min_lon, max_lat, max_lon, zoom))
    except Exception as exc:
        if is_missing_table_error(exc):
            db.session.rollback()
            return jsonify(_empty_gtfs_stop_id_sloid_map_payload(zoom))
        raise


@routes_bp.route('/api/routes/gtfs-stop-id-sloid/popup')
def routes_gtfs_stop_id_sloid_popup_api():
    entity_type = (request.args.get('entity_type') or '').strip().lower()
    try:
        if entity_type == 'gtfs':
            stop_id = (request.args.get('stop_id') or '').strip()
            if not stop_id:
                return jsonify({'error': 'Missing stop_id'}), 400
            popup_payload = build_gtfs_stop_popup(stop_id)
        elif entity_type == 'atlas':
            sloid = (request.args.get('sloid') or '').strip()
            if not sloid:
                return jsonify({'error': 'Missing sloid'}), 400
            popup_payload = build_atlas_stop_popup(sloid)
        else:
            return jsonify({'error': 'entity_type must be atlas or gtfs'}), 400
    except Exception as exc:
        if is_missing_table_error(exc):
            db.session.rollback()
            return jsonify({'error': 'GTFS stop_id to sloid data is not available yet'}), 404
        raise

    if popup_payload is None:
        return jsonify({'error': 'Stop not found'}), 404

    return jsonify(popup_payload)