from collections import Counter

from flask import Blueprint, render_template, request
from sqlalchemy import or_

from backend.db_errors import is_missing_table_error
from backend.extensions import db
from backend.models import AtlasStop, OsmNode, RouteAtlasStops, RouteOsmStops, RoutesMatched
from backend.services.routes import get_atlas_route_display_name, get_osm_route_display_name


routes_bp = Blueprint('routes', __name__)

ROUTE_TAB_MATCHED = 'matched'
ROUTE_TAB_ATLAS = 'atlas'
ROUTE_TAB_OSM = 'osm'
ROUTE_TABS = {ROUTE_TAB_MATCHED, ROUTE_TAB_ATLAS, ROUTE_TAB_OSM}
ROUTES_PER_PAGE_OPTIONS = [5, 10, 20, 50, 100]

ROUTE_VIEW_CONFIG = {
    ROUTE_TAB_MATCHED: {
        'label': 'Matched routes',
        'title': 'Matched Routes',
        'description': 'Explore matched ATLAS and OSM routes with ordered stop lists grouped by direction.',
        'search_label': 'Search route ID',
        'search_placeholder': 'Search ATLAS or OSM route ID',
        'summary_label': 'matched routes',
        'empty_title': 'No matched routes to display',
        'empty_body': 'Try broadening your search, or verify that route matching data has been imported.',
    },
    ROUTE_TAB_ATLAS: {
        'label': 'ATLAS routes',
        'title': 'ATLAS Routes',
        'description': 'Explore ATLAS route definitions with ordered stop lists grouped by direction.',
        'search_label': 'Search ATLAS route ID',
        'search_placeholder': 'Search ATLAS route ID',
        'summary_label': 'ATLAS routes',
        'empty_title': 'No ATLAS routes to display',
        'empty_body': 'Try broadening your search, or verify that ATLAS route data has been imported.',
    },
    ROUTE_TAB_OSM: {
        'label': 'OSM routes',
        'title': 'OSM Routes',
        'description': 'Explore OSM route definitions with ordered stop lists grouped by direction.',
        'search_label': 'Search OSM route ID',
        'search_placeholder': 'Search OSM route ID',
        'summary_label': 'OSM routes',
        'empty_title': 'No OSM routes to display',
        'empty_body': 'Try broadening your search, or verify that OSM route data has been imported.',
    },
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


def _normalize_route_tab(value: str | None) -> str:
    tab = (value or '').strip().lower()
    return tab if tab in ROUTE_TABS else ROUTE_TAB_MATCHED


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
                "uic_ref": row.uic_ref,
                "shared_uic_count": 0,
                "stop_sequence": row.stop_sequence,
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
                "uic_ref": row.osm_uic_ref,
                "shared_uic_count": 0,
                "stop_sequence": row.stop_sequence,
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


def _build_matched_route_rows(matched_items, atlas_stops_by_route, osm_stops_by_route):
    route_rows = []

    for matched in matched_items:
        atlas_directions = atlas_stops_by_route.get(matched.atlas_route_id, {})
        osm_directions = osm_stops_by_route.get(matched.osm_route_id, {})

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

        route_rows.append(
            {
                'atlas_route_id': matched.atlas_route_id,
                'atlas_route_name': get_atlas_route_display_name(matched.atlas_route_id),
                'osm_route_id': matched.osm_route_id,
                'osm_route_name': get_osm_route_display_name(matched.osm_route_id),
                'direction_summary': _direction_summary(direction_groups),
                'direction_groups': direction_groups,
            }
        )

    return route_rows


def _build_single_source_route_rows(route_ids, stops_by_route, source):
    route_rows = []

    for route_id in route_ids:
        source_directions = stops_by_route.get(route_id, {})
        direction_groups = []
        for direction_id in sorted(source_directions.keys(), key=_direction_sort_key):
            stops = source_directions.get(direction_id, [])
            direction_groups.append(
                {
                    'direction_id': direction_id,
                    'atlas_uic_groups': _group_stops_by_uic(stops) if source == ROUTE_TAB_ATLAS else [],
                    'osm_uic_groups': _group_stops_by_uic(stops) if source == ROUTE_TAB_OSM else [],
                }
            )

        route_rows.append(
            {
                'route_id': route_id,
                'route_name': (
                    get_atlas_route_display_name(route_id)
                    if source == ROUTE_TAB_ATLAS
                    else get_osm_route_display_name(route_id)
                ),
                'direction_summary': _direction_summary(direction_groups),
                'direction_groups': direction_groups,
            }
        )

    return route_rows


def _load_matched_routes_view(q, page, per_page):
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

    route_rows = _build_matched_route_rows(
        matched_routes_page.items,
        atlas_stops_by_route,
        osm_stops_by_route,
    )
    return route_rows, matched_routes_page


def _load_atlas_routes_view(q, page, per_page):
    atlas_routes_query = RouteAtlasStops.query.with_entities(RouteAtlasStops.atlas_route_id)
    atlas_routes_query = atlas_routes_query.filter(RouteAtlasStops.atlas_route_id.isnot(None))
    if q:
        atlas_routes_query = atlas_routes_query.filter(RouteAtlasStops.atlas_route_id.ilike(f"%{q}%"))

    atlas_routes_page = (
        atlas_routes_query
        .distinct()
        .order_by(RouteAtlasStops.atlas_route_id.asc())
        .paginate(page=page, per_page=per_page, error_out=False)
    )

    atlas_route_ids = [
        _extract_scalar_id(row, 'atlas_route_id')
        for row in atlas_routes_page.items
    ]
    atlas_route_ids = [route_id for route_id in atlas_route_ids if route_id]

    atlas_stops_by_route = _load_atlas_route_stops(atlas_route_ids)
    route_rows = _build_single_source_route_rows(
        atlas_route_ids,
        atlas_stops_by_route,
        source=ROUTE_TAB_ATLAS,
    )
    return route_rows, atlas_routes_page


def _load_osm_routes_view(q, page, per_page):
    osm_routes_query = RouteOsmStops.query.with_entities(RouteOsmStops.osm_route_id)
    osm_routes_query = osm_routes_query.filter(RouteOsmStops.osm_route_id.isnot(None))
    if q:
        osm_routes_query = osm_routes_query.filter(RouteOsmStops.osm_route_id.ilike(f"%{q}%"))

    osm_routes_page = (
        osm_routes_query
        .distinct()
        .order_by(RouteOsmStops.osm_route_id.asc())
        .paginate(page=page, per_page=per_page, error_out=False)
    )

    osm_route_ids = [
        _extract_scalar_id(row, 'osm_route_id')
        for row in osm_routes_page.items
    ]
    osm_route_ids = [route_id for route_id in osm_route_ids if route_id]

    osm_stops_by_route = _load_osm_route_stops(osm_route_ids)
    route_rows = _build_single_source_route_rows(
        osm_route_ids,
        osm_stops_by_route,
        source=ROUTE_TAB_OSM,
    )
    return route_rows, osm_routes_page


@routes_bp.route('/routes')
def routes_page():
    active_tab = _normalize_route_tab(request.args.get('tab'))
    q = (request.args.get('q') or '').strip()
    page = _bounded_int(request.args.get('page'), default=1, minimum=1)
    per_page = _bounded_int(request.args.get('per_page'), default=20, minimum=5, maximum=100)
    view_config = ROUTE_VIEW_CONFIG[active_tab]

    try:
        if active_tab == ROUTE_TAB_MATCHED:
            route_rows, pagination = _load_matched_routes_view(q, page, per_page)
        elif active_tab == ROUTE_TAB_ATLAS:
            route_rows, pagination = _load_atlas_routes_view(q, page, per_page)
        else:
            route_rows, pagination = _load_osm_routes_view(q, page, per_page)

        range_start, range_end = _compute_page_range(pagination)

        return render_template(
            'pages/routes.html',
            route_rows=route_rows,
            pagination=pagination,
            active_tab=active_tab,
            route_view=view_config,
            per_page_options=ROUTES_PER_PAGE_OPTIONS,
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
                active_tab=active_tab,
                route_view=view_config,
                per_page_options=ROUTES_PER_PAGE_OPTIONS,
                q=q,
                per_page=per_page,
                range_start=0,
                range_end=0,
            )
        raise