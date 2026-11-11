"""Routes pages: the route listings and the GTFS stop ID to SLOID map, rendered as HTML."""
from flask import Blueprint, make_response, render_template, request

from backend.pages.pagination import ListPagination, bounded_int, page_range, per_page_choice
from backend.services import route_listing
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


def _handle_route_database_error(exc):
    """The maintenance page after a database timeout; any other error is raised again."""
    return _routes_unavailable_response(*route_listing.database_busy_reason(exc))


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
        return page, _handle_route_database_error(exc)
    return (located or page), None


@route_pages_bp.route('/routes')
def routes_page():
    page = bounded_int(request.args.get('page'), 1, minimum=1)
    per_page = per_page_choice(request.args.get('per_page'), ROUTES_PER_PAGE_OPTIONS, ROUTES_DEFAULT_PER_PAGE, minimum=1)
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
        return _handle_route_database_error(exc)

    pagination = ListPagination(page_items, page, per_page, total)
    range_start, range_end = page_range(pagination)

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
    page = bounded_int(request.args.get('page'), 1, minimum=1)
    per_page = per_page_choice(request.args.get('per_page'), ROUTES_PER_PAGE_OPTIONS, ROUTES_DEFAULT_PER_PAGE, minimum=1)
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
        return _handle_route_database_error(exc)

    pagination = ListPagination(page_items, page, per_page, total)
    range_start, range_end = page_range(pagination)

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
