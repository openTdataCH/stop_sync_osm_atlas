"""Routes pages: the route listings and the GTFS stop ID to SLOID map, rendered as HTML."""
from flask import Blueprint, make_response, render_template, request

from backend.services import route_listing
from backend.services.pipeline_status import get_status
from backend.services.url_query import canonical_query_redirect


route_pages_bp = Blueprint('routes', __name__)


ROUTES_PER_PAGE_OPTIONS = [5, 10, 20, 50, 100]
ROUTES_DEFAULT_PER_PAGE = 10
MATCH_FILTER_LABELS = {
    route_listing.ROUTE_MATCH_ALL: 'All',
    route_listing.ROUTE_MATCHED: 'Matched',
    route_listing.ROUTE_UNMATCHED: 'Unmatched',
    route_listing.ROUTE_UNMATCHED_ATLAS: 'Unmatched ATLAS',
    route_listing.ROUTE_UNMATCHED_OSM: 'Unmatched OSM',
}
ROUTES_VIEW_ROUTES = 'routes'
ROUTES_VIEW_NON_GTFS = 'non_gtfs_routes'
ROUTES_VIEW_GTFS_STOP_ID_SLOID = 'gtfs_stop_id_sloid'


def _routes_unavailable_response(message: str, phase: str | None = None):
    response = make_response(render_template(
        'errors/maintenance.html',
        message=message,
        phase=phase,
        retry_after_seconds=route_listing.ROUTES_RETRY_AFTER_SECONDS,
    ), 503)
    response.headers['Retry-After'] = str(route_listing.ROUTES_RETRY_AFTER_SECONDS)
    return response


@route_pages_bp.before_request
def _guard_routes_during_blocking_maintenance():
    reason = route_listing.maintenance_reason(get_status())
    return _routes_unavailable_response(*reason) if reason else None


def _handle_route_database_error(exc):
    reason = route_listing.database_busy_reason(exc)
    return _routes_unavailable_response(*reason) if reason else None


class _ListPagination:
    def __init__(self, items, page, per_page, total):
        self.items = items
        self.page = page
        self.per_page = per_page
        self.total = total
        self.pages = ((total - 1) // per_page) + 1 if total > 0 else 0
        self.has_prev = page > 1
        self.has_next = page < self.pages
        self.prev_num = max(page - 1, 1)
        self.next_num = min(page + 1, self.pages or 1)

    def iter_pages(self, left_edge=1, left_current=1, right_current=2, right_edge=1):
        if self.pages <= 0:
            return []
        pages = []
        last = 0
        for num in range(1, self.pages + 1):
            if (
                num <= left_edge
                or (self.page - left_current - 1 < num < self.page + right_current)
                or num > self.pages - right_edge
            ):
                if last + 1 != num:
                    pages.append(None)
                pages.append(num)
                last = num
        return pages


class _EmptyPagination(_ListPagination):
    def __init__(self, page, per_page):
        super().__init__([], page, per_page, 0)


def _normalize_route_match_filter(value: str | None) -> str:
    matched = (value or '').strip().lower()
    return matched if matched in route_listing.ROUTE_MATCH_FILTERS else route_listing.ROUTE_MATCH_ALL


def _serialize_filter(values: list[str]) -> str:
    return ','.join(sorted(set(values)))


def _search_placeholder() -> str:
    return 'Search Atlas line IDs or OSM display route IDs'


def _route_listing_endpoint(active_view: str) -> str:
    if active_view == ROUTES_VIEW_NON_GTFS:
        return 'routes.non_gtfs_routes_page'
    return 'routes.routes_page'


def _render_routes_template(active_view: str, **context):
    return render_template(
        'pages/routes.html',
        active_view=active_view,
        listing_endpoint=_route_listing_endpoint(active_view),
        **context,
    )


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


def _parse_variant_params():
    """A permalink's variant: ATLAS itinerary id and OSM relation id, as stored."""
    def value(name):
        return (request.args.get(name) or '').strip()[:255] or None
    return value('atlas_variant'), value('osm_variant')


def _page_for_variant(page, per_page, atlas_variant, osm_variant, **filters):
    """The requested page, or the one holding the linked variant.

    Returns (page, error_response); a database timeout answers 503.
    """
    if not (atlas_variant or osm_variant):
        return page, None
    try:
        located = route_listing.locate_route_variant_page(
            atlas_variant=atlas_variant,
            osm_variant=osm_variant,
            per_page=per_page,
            **filters,
        )
    except Exception as exc:
        busy_response = _handle_route_database_error(exc)
        if busy_response is not None:
            return page, busy_response
        located = None
    return (located or page), None


@route_pages_bp.route('/routes')
def routes_page():
    page = _bounded_int(request.args.get('page', 1), 1, minimum=1)
    requested_per_page = _bounded_int(
        request.args.get('per_page', ROUTES_DEFAULT_PER_PAGE),
        ROUTES_DEFAULT_PER_PAGE,
        minimum=1,
        maximum=max(ROUTES_PER_PAGE_OPTIONS),
    )
    per_page = (
        requested_per_page
        if requested_per_page in ROUTES_PER_PAGE_OPTIONS
        else ROUTES_DEFAULT_PER_PAGE
    )
    q = (request.args.get('q') or '').strip()
    matched_filter = _normalize_route_match_filter(request.args.get('matched'))
    selected_atlas_operators = route_listing.parse_multi_filter('atlas_operator')
    selected_osm_operators = route_listing.parse_multi_filter('osm_operator')
    atlas_variant, osm_variant = _parse_variant_params()
    page, busy_response = _page_for_variant(
        page,
        per_page,
        atlas_variant,
        osm_variant,
        q=q,
        matched_filter=matched_filter,
        atlas_operators=selected_atlas_operators,
        osm_operators=selected_osm_operators,
    )
    if busy_response is not None:
        return busy_response

    canonical_redirect = canonical_query_redirect(
        'routes.routes_page',
        (
            ('page', page if page > 1 else None),
            (
                'per_page',
                per_page if per_page != ROUTES_DEFAULT_PER_PAGE else None,
            ),
            (
                'matched',
                matched_filter if matched_filter != route_listing.ROUTE_MATCH_ALL else None,
            ),
            (
                'atlas_operator',
                _serialize_filter(selected_atlas_operators) or None,
            ),
            (
                'osm_operator',
                _serialize_filter(selected_osm_operators) or None,
            ),
            ('q', q or None),
            ('atlas_variant', atlas_variant),
            ('osm_variant', osm_variant),
        ),
    )
    if canonical_redirect is not None:
        return canonical_redirect

    try:
        page_items, total = route_listing.query_route_page(
            page=page,
            per_page=per_page,
            q=q,
            matched_filter=matched_filter,
            atlas_operators=selected_atlas_operators,
            osm_operators=selected_osm_operators,
        )
        available_atlas_operators = route_listing.load_available_atlas_operators()
        available_osm_operators = route_listing.load_available_osm_route_operators()
        route_rows = route_listing.build_route_rows(page_items)
        route_listing.attach_best_overlaps(route_rows)
    except Exception as exc:
        busy_response = _handle_route_database_error(exc)
        if busy_response is not None:
            return busy_response
        page_items = []
        total = 0
        available_atlas_operators = []
        available_osm_operators = []
        route_rows = []

    pagination = _ListPagination(page_items, page, per_page, total) if total else _EmptyPagination(page, per_page)
    range_start, range_end = _compute_page_range(pagination)

    return _render_routes_template(
        ROUTES_VIEW_ROUTES,
        route_rows=route_rows,
        pagination=pagination,
        range_start=range_start,
        range_end=range_end,
        per_page=per_page,
        per_page_options=ROUTES_PER_PAGE_OPTIONS,
        match_filter_labels=MATCH_FILTER_LABELS,
        matched_filter=matched_filter,
        available_atlas_operators=available_atlas_operators,
        available_osm_operators=available_osm_operators,
        selected_atlas_operators=selected_atlas_operators,
        selected_osm_operators=selected_osm_operators,
        atlas_operator_query=_serialize_filter(selected_atlas_operators),
        osm_operator_query=_serialize_filter(selected_osm_operators),
        q=q,
        search_placeholder=_search_placeholder(),
    )


@route_pages_bp.route('/routes/non-gtfs')
def non_gtfs_routes_page():
    page = _bounded_int(request.args.get('page', 1), 1, minimum=1)
    requested_per_page = _bounded_int(
        request.args.get('per_page', ROUTES_DEFAULT_PER_PAGE),
        ROUTES_DEFAULT_PER_PAGE,
        minimum=1,
        maximum=max(ROUTES_PER_PAGE_OPTIONS),
    )
    per_page = (
        requested_per_page
        if requested_per_page in ROUTES_PER_PAGE_OPTIONS
        else ROUTES_DEFAULT_PER_PAGE
    )
    _, osm_variant = _parse_variant_params()
    page, busy_response = _page_for_variant(page, per_page, None, osm_variant, non_gtfs_only=True)
    if busy_response is not None:
        return busy_response

    canonical_redirect = canonical_query_redirect(
        'routes.non_gtfs_routes_page',
        (
            ('page', page if page > 1 else None),
            (
                'per_page',
                per_page if per_page != ROUTES_DEFAULT_PER_PAGE else None,
            ),
            ('osm_variant', osm_variant),
        ),
    )
    if canonical_redirect is not None:
        return canonical_redirect

    try:
        page_items, total = route_listing.query_route_page(
            page=page,
            per_page=per_page,
            non_gtfs_only=True,
        )
        route_rows = route_listing.build_route_rows(page_items)
    except Exception as exc:
        busy_response = _handle_route_database_error(exc)
        if busy_response is not None:
            return busy_response
        page_items = []
        total = 0
        route_rows = []

    pagination = _ListPagination(page_items, page, per_page, total) if total else _EmptyPagination(page, per_page)
    range_start, range_end = _compute_page_range(pagination)

    return _render_routes_template(
        ROUTES_VIEW_NON_GTFS,
        route_rows=route_rows,
        pagination=pagination,
        range_start=range_start,
        range_end=range_end,
        per_page=per_page,
        per_page_options=ROUTES_PER_PAGE_OPTIONS,
        match_filter_labels=MATCH_FILTER_LABELS,
        matched_filter=route_listing.ROUTE_MATCH_ALL,
        available_atlas_operators=[],
        available_osm_operators=[],
        selected_atlas_operators=[],
        selected_osm_operators=[],
        atlas_operator_query='',
        osm_operator_query='',
        q='',
        search_placeholder=_search_placeholder(),
    )


@route_pages_bp.route('/routes/gtfs-stop-id-sloid')
def routes_gtfs_stop_id_sloid_page():
    # A permalink's stop: the page opens its popup. The map view is in the
    # #map= hash, which the server never sees.
    canonical_redirect = canonical_query_redirect(
        'routes.routes_gtfs_stop_id_sloid_page',
        (
            ('sloid', (request.args.get('sloid') or '').strip()[:255] or None),
            ('gtfs_stop_id', (request.args.get('gtfs_stop_id') or '').strip()[:255] or None),
        ),
        safe=',:/',
    )
    if canonical_redirect is not None:
        return canonical_redirect
    return _render_routes_template(ROUTES_VIEW_GTFS_STOP_ID_SLOID)
