from collections import Counter

from flask import Blueprint, render_template, request

from backend.db_errors import is_missing_table_error
from backend.extensions import db
from backend.models import AtlasStop, OsmNode, RouteAtlasStops, RouteOsmStops, RoutesMatched, StopsMatched
from backend.services.transport_routes import get_atlas_route_display_name, get_osm_route_display_name


routes_bp = Blueprint('routes', __name__)

ROUTE_DATASET_ATLAS = 'atlas_gtfs'
ROUTE_DATASET_OSM = 'osm'
ROUTE_DATASETS = {ROUTE_DATASET_ATLAS, ROUTE_DATASET_OSM}

ROUTE_MATCH_ALL = 'all'
ROUTE_MATCHED = 'matched'
ROUTE_UNMATCHED = 'unmatched'
ROUTE_MATCH_FILTERS = {ROUTE_MATCH_ALL, ROUTE_MATCHED, ROUTE_UNMATCHED}

ROUTES_PER_PAGE_OPTIONS = [5, 10, 20, 50, 100]


DATASET_LABELS = {
    ROUTE_DATASET_ATLAS: 'Atlas GTFS',
    ROUTE_DATASET_OSM: 'OSM',
}


MATCH_FILTER_LABELS = {
    ROUTE_MATCH_ALL: 'All',
    ROUTE_MATCHED: 'Matched only',
    ROUTE_UNMATCHED: 'Unmatched only',
}


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


def _normalize_route_dataset(value: str | None) -> str:
    dataset = (value or '').strip().lower()
    return dataset if dataset in ROUTE_DATASETS else ROUTE_DATASET_ATLAS


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


def _search_placeholder_for_dataset(dataset: str) -> str:
    if dataset == ROUTE_DATASET_OSM:
        return 'Search OSM route ID'
    return 'Search Atlas GTFS route ID'


def _filters_summary_text(dataset: str, matched_filter: str) -> str:
    dataset_label = DATASET_LABELS.get(dataset, DATASET_LABELS[ROUTE_DATASET_ATLAS])
    matched_label = MATCH_FILTER_LABELS.get(matched_filter, MATCH_FILTER_LABELS[ROUTE_MATCH_ALL])
    return f'Dataset: {dataset_label} | Matched: {matched_label}'


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


def _build_direction_groups(atlas_directions, osm_directions):
    all_directions = set(atlas_directions.keys()) | set(osm_directions.keys())
    direction_groups = []
    for direction_id in sorted(all_directions, key=_direction_sort_key):
        atlas_stops = atlas_directions.get(direction_id, [])
        osm_stops = osm_directions.get(direction_id, [])
        direction_groups.append(
            {
                'direction_id': direction_id,
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


def _atlas_routes_query(matched_filter, atlas_operators, q):
    query = db.session.query(RouteAtlasStops.atlas_route_id.label('route_id'))
    query = query.filter(RouteAtlasStops.atlas_route_id.isnot(None))

    matched_atlas_subquery = (
        db.session.query(RoutesMatched.atlas_route_id)
        .filter(RoutesMatched.atlas_route_id.isnot(None))
    )

    if matched_filter == ROUTE_MATCHED:
        query = query.filter(RouteAtlasStops.atlas_route_id.in_(matched_atlas_subquery))
    elif matched_filter == ROUTE_UNMATCHED:
        query = query.filter(~RouteAtlasStops.atlas_route_id.in_(matched_atlas_subquery))

    if atlas_operators:
        query = query.join(AtlasStop, RouteAtlasStops.sloid == AtlasStop.sloid)
        query = query.filter(AtlasStop.atlas_business_org_abbr.in_(atlas_operators))

    if q:
        query = query.filter(RouteAtlasStops.atlas_route_id.ilike(f'%{q}%'))

    return query


def _osm_routes_query(matched_filter, atlas_operators, q):
    query = db.session.query(RouteOsmStops.osm_route_id.label('route_id'))
    query = query.filter(RouteOsmStops.osm_route_id.isnot(None))

    matched_osm_subquery = (
        db.session.query(RoutesMatched.osm_route_id)
        .filter(RoutesMatched.osm_route_id.isnot(None))
    )

    if matched_filter == ROUTE_MATCHED:
        query = query.filter(RouteOsmStops.osm_route_id.in_(matched_osm_subquery))
    elif matched_filter == ROUTE_UNMATCHED:
        query = query.filter(~RouteOsmStops.osm_route_id.in_(matched_osm_subquery))

    if atlas_operators:
        osm_routes_for_operator_subquery = (
            db.session.query(RoutesMatched.osm_route_id)
            .join(RouteAtlasStops, RoutesMatched.atlas_route_id == RouteAtlasStops.atlas_route_id)
            .join(AtlasStop, RouteAtlasStops.sloid == AtlasStop.sloid)
            .filter(RoutesMatched.osm_route_id.isnot(None))
            .filter(AtlasStop.atlas_business_org_abbr.in_(atlas_operators))
            .distinct()
        )
        query = query.filter(RouteOsmStops.osm_route_id.in_(osm_routes_for_operator_subquery))

    if q:
        query = query.filter(RouteOsmStops.osm_route_id.ilike(f'%{q}%'))

    return query


def _load_primary_route_page(dataset, matched_filter, atlas_operators, q, page, per_page):
    if dataset == ROUTE_DATASET_OSM:
        query = _osm_routes_query(matched_filter, atlas_operators, q)
        pagination = (
            query
            .distinct()
            .order_by(RouteOsmStops.osm_route_id.asc())
            .paginate(page=page, per_page=per_page, error_out=False)
        )
    else:
        query = _atlas_routes_query(matched_filter, atlas_operators, q)
        pagination = (
            query
            .distinct()
            .order_by(RouteAtlasStops.atlas_route_id.asc())
            .paginate(page=page, per_page=per_page, error_out=False)
        )

    route_ids = [
        _extract_scalar_id(row, 'route_id')
        for row in pagination.items
    ]
    route_ids = [route_id for route_id in route_ids if route_id]
    return route_ids, pagination


def _build_route_row(dataset, primary_route_id, atlas_route_id, osm_route_id, atlas_stops_by_route, osm_stops_by_route, atlas_operators_by_route):
    atlas_directions = atlas_stops_by_route.get(atlas_route_id, {}) if atlas_route_id else {}
    osm_directions = osm_stops_by_route.get(osm_route_id, {}) if osm_route_id else {}

    direction_groups = _build_direction_groups(atlas_directions, osm_directions)
    is_matched = bool(atlas_route_id and osm_route_id)

    atlas_operators = atlas_operators_by_route.get(atlas_route_id, []) if atlas_route_id else []
    atlas_operators_summary = ', '.join(atlas_operators[:3])
    if len(atlas_operators) > 3:
        atlas_operators_summary += f' (+{len(atlas_operators) - 3} more)'

    map_filter = _build_route_map_filter(atlas_route_id, osm_route_id)
    display_mode = _route_display_mode(atlas_route_id, osm_route_id)

    return {
        'route_key': f'{dataset}:{primary_route_id}',
        'dataset': dataset,
        'primary_route_id': primary_route_id,
        'is_matched': is_matched,
        'display_mode': display_mode,
        'match_label': 'Matched' if is_matched else 'Unmatched',
        'atlas_route_id': atlas_route_id,
        'atlas_route_name': get_atlas_route_display_name(atlas_route_id) if atlas_route_id else None,
        'osm_route_id': osm_route_id,
        'osm_route_name': get_osm_route_display_name(osm_route_id) if osm_route_id else None,
        'atlas_operators': atlas_operators,
        'atlas_operators_summary': atlas_operators_summary,
        'direction_summary': _direction_summary(direction_groups),
        'direction_groups': direction_groups,
        'map_filter': map_filter,
        'map_point_count': len(_extract_coordinates_from_direction_groups(direction_groups)),
    }


def _load_routes_view(dataset, matched_filter, atlas_operators, q, page, per_page):
    primary_route_ids, pagination = _load_primary_route_page(
        dataset=dataset,
        matched_filter=matched_filter,
        atlas_operators=atlas_operators,
        q=q,
        page=page,
        per_page=per_page,
    )

    if not primary_route_ids:
        return [], pagination

    if dataset == ROUTE_DATASET_OSM:
        osm_route_ids = primary_route_ids
        osm_to_atlas = _load_osm_to_atlas_map(osm_route_ids)
        atlas_route_ids = sorted({atlas_id for atlas_id in osm_to_atlas.values() if atlas_id})
    else:
        atlas_route_ids = primary_route_ids
        atlas_to_osm = _load_atlas_to_osm_map(atlas_route_ids)
        osm_route_ids = sorted({osm_id for osm_id in atlas_to_osm.values() if osm_id})

    atlas_stops_by_route = _load_atlas_route_stops(atlas_route_ids)
    osm_stops_by_route = _load_osm_route_stops(osm_route_ids)
    atlas_operators_by_route = _load_atlas_route_operators(atlas_route_ids)

    route_rows = []
    if dataset == ROUTE_DATASET_OSM:
        for osm_route_id in osm_route_ids:
            atlas_route_id = osm_to_atlas.get(osm_route_id)
            route_rows.append(
                _build_route_row(
                    dataset=dataset,
                    primary_route_id=osm_route_id,
                    atlas_route_id=atlas_route_id,
                    osm_route_id=osm_route_id,
                    atlas_stops_by_route=atlas_stops_by_route,
                    osm_stops_by_route=osm_stops_by_route,
                    atlas_operators_by_route=atlas_operators_by_route,
                )
            )
    else:
        for atlas_route_id in atlas_route_ids:
            osm_route_id = atlas_to_osm.get(atlas_route_id)
            route_rows.append(
                _build_route_row(
                    dataset=dataset,
                    primary_route_id=atlas_route_id,
                    atlas_route_id=atlas_route_id,
                    osm_route_id=osm_route_id,
                    atlas_stops_by_route=atlas_stops_by_route,
                    osm_stops_by_route=osm_stops_by_route,
                    atlas_operators_by_route=atlas_operators_by_route,
                )
            )

    return route_rows, pagination


@routes_bp.route('/routes')
def routes_page():
    dataset = _normalize_route_dataset(request.args.get('dataset'))
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
            dataset=dataset,
            matched_filter=matched_filter,
            atlas_operators=selected_atlas_operators,
            q=q,
            page=page,
            per_page=per_page,
        )

        range_start, range_end = _compute_page_range(pagination)

        return render_template(
            'pages/routes.html',
            route_rows=route_rows,
            pagination=pagination,
            dataset=dataset,
            matched_filter=matched_filter,
            available_atlas_operators=available_atlas_operators,
            selected_atlas_operators=selected_atlas_operators,
            atlas_operator_query=atlas_operator_query,
            per_page_options=ROUTES_PER_PAGE_OPTIONS,
            dataset_labels=DATASET_LABELS,
            match_filter_labels=MATCH_FILTER_LABELS,
            filters_summary=_filters_summary_text(dataset, matched_filter),
            search_placeholder=_search_placeholder_for_dataset(dataset),
            q=q,
            per_page=per_page,
            range_start=range_start,
            range_end=range_end,
        )
    except Exception as e:
        if is_missing_table_error(e):
            db.session.rollback()
            empty_pagination = _EmptyPagination(page=page, per_page=per_page)
            return render_template(
                'pages/routes.html',
                route_rows=[],
                pagination=empty_pagination,
                dataset=dataset,
                matched_filter=matched_filter,
                available_atlas_operators=available_atlas_operators,
                selected_atlas_operators=selected_atlas_operators,
                atlas_operator_query=atlas_operator_query,
                per_page_options=ROUTES_PER_PAGE_OPTIONS,
                dataset_labels=DATASET_LABELS,
                match_filter_labels=MATCH_FILTER_LABELS,
                filters_summary=_filters_summary_text(dataset, matched_filter),
                search_placeholder=_search_placeholder_for_dataset(dataset),
                q=q,
                per_page=per_page,
                range_start=0,
                range_end=0,
            )
        raise