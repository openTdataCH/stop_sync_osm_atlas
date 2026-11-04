"""Routes JSON API: route comparisons and the GTFS stop ID to SLOID map data."""
from flask import Blueprint, jsonify, make_response, request

from backend.db_errors import is_missing_table_error
from backend.extensions import db
from backend.services import route_listing
from backend.services.gtfs_stop_id_sloid import (
    GTFS_STOP_ID_SLOID_FILTER_STATUSES,
    GTFS_STOP_ID_SLOID_SEARCH_KINDS,
    build_atlas_stop_popup,
    build_gtfs_stop_id_sloid_map_payload,
    build_gtfs_stop_id_sloid_summary,
    build_gtfs_stop_popup,
    find_gtfs_stop_id_sloid_targets,
)
from backend.services.pipeline_status import get_status
from backend.services.route_comparison import build_route_comparison, list_comparison_options


routes_bp = Blueprint('routes_api', __name__)


GTFS_STOP_ID_SLOID_SEARCH_VALUE_MAX_LENGTH = 255


def _routes_unavailable_response(message: str, *, phase: str | None = None):
    response = make_response(jsonify({
        'error': message,
        'phase': phase,
        'retry_after_seconds': route_listing.ROUTES_RETRY_AFTER_SECONDS,
    }), 503)
    response.headers['Retry-After'] = str(route_listing.ROUTES_RETRY_AFTER_SECONDS)
    return response


@routes_bp.before_request
def _guard_routes_during_blocking_maintenance():
    status = get_status()
    if not status.get('blocking_maintenance'):
        return None
    return _routes_unavailable_response(
        status.get('message') or 'Route data is being refreshed.',
        phase=status.get('phase') or 'import',
    )


def _handle_route_database_error(exc):
    if route_listing.recover_database_error(exc) == 'busy':
        return _routes_unavailable_response(
            'Route data is temporarily busy. Please retry shortly.',
            phase='database',
        )
    return None


def _parse_gtfs_stop_id_sloid_search():
    search_kind = (request.args.get('search_kind') or request.args.get('kind') or '').strip().lower()
    search_value = (request.args.get('search_value') or request.args.get('value') or '').strip()

    if not search_kind and not search_value:
        return None, None
    if search_kind not in GTFS_STOP_ID_SLOID_SEARCH_KINDS:
        raise ValueError('Invalid identifier search kind')
    if not search_value or len(search_value) > GTFS_STOP_ID_SLOID_SEARCH_VALUE_MAX_LENGTH:
        raise ValueError('Invalid identifier search value')
    return search_kind, search_value


def _parse_gtfs_stop_id_sloid_map_limit():
    raw_limit = request.args.get('limit')
    if raw_limit is None:
        return None

    normalized = raw_limit.strip().lower()
    if normalized == 'all':
        return 'all'

    limit = int(normalized)
    if limit < 1 or limit > 10_000:
        raise ValueError('Invalid map limit')
    return limit


def _parse_gtfs_stop_id_sloid_include_matches():
    raw_value = (request.args.get('include_matches') or '1').strip().lower()
    if raw_value in {'1', 'true'}:
        return True
    if raw_value in {'0', 'false'}:
        return False
    raise ValueError('Invalid include_matches value')


def _parse_gtfs_stop_id_sloid_filters():
    statuses = route_listing.parse_multi_filter('status')
    if any(status not in GTFS_STOP_ID_SLOID_FILTER_STATUSES for status in statuses):
        raise ValueError('Invalid GTFS stop map status filter')

    match_methods = route_listing.parse_multi_filter('match_method')
    if len(match_methods) > 20 or any(len(method) > 100 for method in match_methods):
        raise ValueError('Invalid GTFS stop map match method filter')
    return statuses, match_methods


def _comparison_integer(name, *, default=None, maximum=2_147_483_647):
    raw_value = request.args.get(name)
    if raw_value is None:
        return default
    value = int(raw_value)
    if value < 1 or value > maximum:
        raise ValueError(f'Invalid {name}')
    return value


def _comparison_database_error(exc):
    if is_missing_table_error(exc):
        db.session.rollback()
        return _routes_unavailable_response('Route tables are not initialized yet.', phase='database')
    return _handle_route_database_error(exc)


@routes_bp.route('/api/routes/comparison')
def routes_comparison_api():
    try:
        atlas_id = _comparison_integer('atlas_itinerary_id')
        osm_id = _comparison_integer('osm_itinerary_id')
        if atlas_id is None and osm_id is None:
            raise ValueError('Select at least one itinerary.')
    except (TypeError, ValueError):
        return jsonify({'error': 'Select at least one valid itinerary ID.'}), 400

    try:
        return jsonify(build_route_comparison(atlas_id, osm_id))
    except LookupError as exc:
        return jsonify({'error': str(exc)}), 404
    except Exception as exc:
        return _comparison_database_error(exc)


@routes_bp.route('/api/routes/comparison/options')
def routes_comparison_options_api():
    try:
        source = (request.args.get('source') or '').strip().lower()
        if source not in {'atlas', 'osm'}:
            raise ValueError('Invalid source')
        q = (request.args.get('q') or '').strip()
        if len(q) > 255:
            raise ValueError('Search is too long')
        fixed_id = _comparison_integer('fixed_itinerary_id')
        unmatched = request.args.get('unmatched', '0' if fixed_id is not None else '1')
        if unmatched not in {'0', '1'}:
            raise ValueError('Invalid unmatched filter')
        page = _comparison_integer('page', default=1)
        per_page = _comparison_integer('per_page', default=30, maximum=100)
        anchor_id = _comparison_integer('anchor_id')
        shared_only = request.args.get('shared_only', '0')
        if shared_only not in {'0', '1'} or (shared_only == '1' and fixed_id is None):
            raise ValueError('Invalid shared filter')
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid comparison source, search, filter, page, or itinerary ID.'}), 400

    try:
        return jsonify(list_comparison_options(
            source, q=q, unmatched=unmatched == '1', page=page, per_page=per_page, anchor_id=anchor_id,
            fixed_itinerary_id=fixed_id, shared_only=shared_only == '1',
        ))
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except LookupError as exc:
        return jsonify({'error': str(exc)}), 404
    except Exception as exc:
        return _comparison_database_error(exc)


@routes_bp.route('/api/routes/gtfs-stop-id-sloid/summary')
def routes_gtfs_stop_id_sloid_summary_api():
    try:
        return jsonify(build_gtfs_stop_id_sloid_summary())
    except Exception as exc:
        if is_missing_table_error(exc):
            db.session.rollback()
            return jsonify({'error': 'GTFS route tables are not initialized yet.'}), 503
        return _handle_route_database_error(exc)


@routes_bp.route('/api/routes/gtfs-stop-id-sloid/map')
def routes_gtfs_stop_id_sloid_map_api():
    try:
        min_lat = float(request.args.get('min_lat'))
        min_lon = float(request.args.get('min_lon'))
        max_lat = float(request.args.get('max_lat'))
        max_lon = float(request.args.get('max_lon'))
        zoom = int(request.args.get('zoom', 0))
        search_kind, search_value = _parse_gtfs_stop_id_sloid_search()
        requested_limit = _parse_gtfs_stop_id_sloid_map_limit()
        include_matches = _parse_gtfs_stop_id_sloid_include_matches()
        filter_statuses, match_methods = _parse_gtfs_stop_id_sloid_filters()
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid map bounds, zoom, limit, relationship mode, filters, or identifier search'}), 400

    try:
        return jsonify(build_gtfs_stop_id_sloid_map_payload(
            min_lat,
            min_lon,
            max_lat,
            max_lon,
            zoom,
            search_kind,
            search_value,
            requested_limit,
            include_matches,
            filter_statuses,
            match_methods,
        ))
    except Exception as exc:
        if is_missing_table_error(exc):
            db.session.rollback()
            return jsonify({'error': 'GTFS route tables are not initialized yet.'}), 503
        return _handle_route_database_error(exc)


@routes_bp.route('/api/routes/gtfs-stop-id-sloid/search')
def routes_gtfs_stop_id_sloid_search_api():
    try:
        search_kind, search_value = _parse_gtfs_stop_id_sloid_search()
    except ValueError:
        return jsonify({'error': 'Missing or invalid identifier search'}), 400

    if not search_kind:
        return jsonify({'error': 'Missing or invalid identifier search'}), 400

    try:
        targets = find_gtfs_stop_id_sloid_targets(search_kind, search_value)
    except Exception as exc:
        if is_missing_table_error(exc):
            db.session.rollback()
            return jsonify({'error': 'GTFS route tables are not initialized yet.'}), 503
        return _handle_route_database_error(exc)

    if not targets:
        return jsonify({'error': 'No mappable stop found for this identifier.'}), 404

    return jsonify({
        'search': {'kind': search_kind, 'value': search_value},
        'targets': targets,
    })


@routes_bp.route('/api/routes/gtfs-stop-id-sloid/popup')
def routes_gtfs_stop_id_sloid_popup_api():
    entity_type = (request.args.get('entity_type') or '').strip().lower()
    identifier = (
        request.args.get('id')
        or request.args.get('stop_id')
        or request.args.get('sloid')
        or ''
    ).strip()
    if entity_type not in {'gtfs', 'atlas'} or not identifier:
        return jsonify({'error': 'Missing or invalid entity_type/id'}), 400

    try:
        payload = build_gtfs_stop_popup(identifier) if entity_type == 'gtfs' else build_atlas_stop_popup(identifier)
    except Exception as exc:
        if is_missing_table_error(exc):
            db.session.rollback()
            return jsonify({'error': 'GTFS route tables are not initialized yet.'}), 503
        return _handle_route_database_error(exc)

    if payload is None:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(payload)
