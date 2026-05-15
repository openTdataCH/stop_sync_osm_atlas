import json
from collections import defaultdict

from flask import Blueprint, jsonify, render_template, request
from sqlalchemy import or_

from backend.db_errors import is_missing_table_error
from backend.extensions import db
from backend.models import (
    AtlasLineFamily,
    AtlasOperator,
    AtlasStop,
    Itinerary,
    ItineraryMatch,
    LineFamily,
    LineFamilyMatch,
    StopCall,
)
from backend.services.gtfs_stop_id_sloid import (
    GTFS_STOP_ID_SLOID_DETAIL_LIMIT,
    GTFS_STOP_ID_SLOID_DETAIL_ZOOM,
    GTFS_STOP_ID_SLOID_OVERVIEW_LIMIT,
    build_atlas_stop_popup,
    build_gtfs_stop_id_sloid_map_payload,
    build_gtfs_stop_id_sloid_summary,
    build_gtfs_stop_popup,
)


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
ROUTES_VIEW_NON_GTFS = 'non_gtfs_routes'
ROUTES_VIEW_GTFS_STOP_ID_SLOID = 'gtfs_stop_id_sloid'


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
    return matched if matched in ROUTE_MATCH_FILTERS else ROUTE_MATCH_ALL


def _parse_multi_filter(param_name: str) -> list[str]:
    selected = [
        value.strip()
        for value in request.args.getlist(param_name)
        if value and value.strip()
    ]
    if selected:
        return sorted(set(selected))

    raw = (request.args.get(param_name) or '').strip()
    if not raw:
        return []
    return sorted({value.strip() for value in raw.split(',') if value.strip()})


def _serialize_filter(values: list[str]) -> str:
    return ','.join(sorted(set(values)))


def _search_placeholder() -> str:
    return 'Search Atlas line IDs or OSM display route IDs'


def _route_listing_endpoint(active_view: str) -> str:
    if active_view == ROUTES_VIEW_NON_GTFS:
        return 'routes.non_gtfs_routes_page'
    return 'routes.routes_page'



def _osm_route_id_label(gtfs_route_id: str | None, display_route_id: str | None) -> str:
    if _clean_text(gtfs_route_id):
        return 'GTFS ID'
    if _clean_text(display_route_id):
        return 'Route ref'
    return 'Route ID'


def _render_routes_template(active_view: str, **context):
    return render_template(
        'pages/routes.html',
        active_view=active_view,
        listing_endpoint=_route_listing_endpoint(active_view),
        gtfs_stop_id_sloid_detail_zoom=GTFS_STOP_ID_SLOID_DETAIL_ZOOM,
        gtfs_stop_id_sloid_detail_limit=GTFS_STOP_ID_SLOID_DETAIL_LIMIT,
        gtfs_stop_id_sloid_overview_limit=GTFS_STOP_ID_SLOID_OVERVIEW_LIMIT,
        **context,
    )


def _clean_text(value):
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _deserialize_id_list(value):
    cleaned = _clean_text(value)
    if cleaned is None:
        return []
    try:
        parsed = json.loads(cleaned)
    except (TypeError, ValueError):
        parsed = cleaned
    if isinstance(parsed, list):
        seen = set()
        values = []
        for item in parsed:
            item_text = _clean_text(item)
            if item_text is None or item_text in seen:
                continue
            seen.add(item_text)
            values.append(item_text)
        return values
    return [cleaned]


def _group_stops_by_uic(direction_stops):
    if not direction_stops:
        return []

    grouped_by_uic = {}
    order = []
    for idx, stop in enumerate(direction_stops):
        uic = stop.get('uic_ref') or ''
        if uic not in grouped_by_uic:
            grouped_by_uic[uic] = {
                'uic_ref': uic,
                'stop_label': stop.get('stop_label') or '-',
                'members': [],
                'first_idx': idx,
            }
            order.append(uic)

        grouped_by_uic[uic]['members'].append(
            {
                'stop_id': stop.get('stop_id'),
                'stop_ids': stop.get('stop_ids') or ([stop.get('stop_id')] if stop.get('stop_id') else []),
                'stop_label': stop.get('stop_label') or '-',
                'stop_sequence': stop.get('stop_sequence'),
                'lat': stop.get('lat'),
                'lon': stop.get('lon'),
            }
        )

    groups = [grouped_by_uic[uic] for uic in order]
    for group in groups:
        group['member_count'] = sum(max(len(member.get('stop_ids') or []), 1) for member in group['members'])
    return groups


def _direction_sort_key(direction_id):
    if direction_id is None:
        return (2, '')
    direction_text = str(direction_id).strip()
    if direction_text == '':
        return (2, '')
    if direction_text.lstrip('-').isdigit():
        return (0, int(direction_text))
    return (1, direction_text.lower())


def _direction_summary(direction_groups):
    if not direction_groups:
        return None
    labels = [group['direction_id'] if group['direction_id'] else 'Unspecified' for group in direction_groups]
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


def _load_available_atlas_operators() -> list[str]:
    rows = (
        db.session.query(AtlasOperator.atlas_business_org_abbr)
        .filter(AtlasOperator.atlas_business_org_abbr.isnot(None), AtlasOperator.atlas_business_org_abbr != '')
        .distinct()
        .order_by(AtlasOperator.atlas_business_org_abbr.asc())
        .all()
    )
    return [row[0] for row in rows if row and row[0]]


def _load_available_osm_route_operators() -> list[str]:
    rows = (
        db.session.query(LineFamily.operator)
        .filter(LineFamily.source == 'osm', LineFamily.operator.isnot(None), LineFamily.operator != '')
        .distinct()
        .order_by(LineFamily.operator.asc())
        .all()
    )
    return [row[0] for row in rows if row and row[0]]


def _load_route_page_data():
    atlas_generic_rows = db.session.query(LineFamily).filter(LineFamily.source == 'atlas').all()
    osm_generic_rows = db.session.query(LineFamily).filter(LineFamily.source == 'osm').all()
    atlas_generic_by_id = {row.id: row for row in atlas_generic_rows}
    osm_generic_by_id = {row.id: row for row in osm_generic_rows}

    atlas_raw_rows = db.session.query(AtlasLineFamily).all()
    atlas_raw_by_id = {row.atlas_line_id: row for row in atlas_raw_rows}

    operator_rows = (
        db.session.query(Itinerary.line_family_id, AtlasStop.atlas_business_org_abbr)
        .join(StopCall, StopCall.itinerary_id == Itinerary.id)
        .join(AtlasStop, AtlasStop.sloid == StopCall.source_sloid)
        .filter(Itinerary.source == 'atlas', AtlasStop.atlas_business_org_abbr.isnot(None), AtlasStop.atlas_business_org_abbr != '')
        .distinct()
        .all()
    )
    atlas_operator_map: dict[int, list[str]] = defaultdict(list)
    for line_family_id, operator in operator_rows:
        atlas_operator_map[line_family_id].append(operator)
    for line_family_id in list(atlas_operator_map.keys()):
        atlas_operator_map[line_family_id] = sorted(set(atlas_operator_map[line_family_id]))

    match_rows = db.session.query(LineFamilyMatch).all()
    matched_atlas_ids = {row.atlas_line_family_id for row in match_rows}
    matched_osm_ids = {row.osm_line_family_id for row in match_rows}

    route_items = []
    for match_row in match_rows:
        atlas_family = atlas_generic_by_id.get(match_row.atlas_line_family_id)
        osm_family = osm_generic_by_id.get(match_row.osm_line_family_id)
        if atlas_family is None or osm_family is None:
            continue
        atlas_raw = atlas_raw_by_id.get(atlas_family.source_family_id)
        route_items.append({
            'display_mode': 'matched',
            'is_matched': True,
            'match_label': 'Matched',
            'sort_route_id': _clean_text(atlas_family.display_route_id) or _clean_text(osm_family.display_route_id) or '',
            'atlas_family_id': atlas_family.id,
            'osm_family_id': osm_family.id,
            'line_family_match_id': match_row.id,
            'atlas_route_id': atlas_family.source_family_id,
            'atlas_route_short_name': _clean_text(getattr(atlas_raw, 'route_short_name', None)) or _clean_text(atlas_family.ref),
            'atlas_route_long_name': _clean_text(getattr(atlas_raw, 'route_long_name', None)),
            'atlas_route_name': _clean_text(atlas_family.public_name) or _clean_text(atlas_family.display_route_id),
            'atlas_operators': atlas_operator_map.get(atlas_family.id, []),
            'osm_route_master_id': _clean_text(osm_family.route_master_id),
            'osm_route_id': _clean_text(osm_family.representative_relation_id),
            'osm_representative_relation_id': _clean_text(osm_family.representative_relation_id),
            'osm_gtfs_route_id': _clean_text(osm_family.gtfs_route_id),
            'osm_route_display_id': _clean_text(osm_family.display_route_id),
            'osm_route_id_label': _osm_route_id_label(osm_family.gtfs_route_id, osm_family.display_route_id),
            'osm_route_name': _clean_text(osm_family.public_name) or _clean_text(osm_family.ref) or _clean_text(osm_family.display_route_id),
            'osm_operator': _clean_text(osm_family.operator),
            'osm_network': _clean_text(osm_family.network),
            'is_non_gtfs': getattr(osm_family, 'is_non_gtfs', False),
            'primary_route_id': _clean_text(atlas_family.source_family_id) or _clean_text(osm_family.display_route_id),
        })

    for atlas_family in atlas_generic_rows:
        if atlas_family.id in matched_atlas_ids:
            continue
        atlas_raw = atlas_raw_by_id.get(atlas_family.source_family_id)
        route_items.append({
            'display_mode': 'atlas_only',
            'is_matched': False,
            'match_label': 'Unmatched ATLAS',
            'sort_route_id': _clean_text(atlas_family.display_route_id) or '',
            'atlas_family_id': atlas_family.id,
            'osm_family_id': None,
            'line_family_match_id': None,
            'atlas_route_id': atlas_family.source_family_id,
            'atlas_route_short_name': _clean_text(getattr(atlas_raw, 'route_short_name', None)) or _clean_text(atlas_family.ref),
            'atlas_route_long_name': _clean_text(getattr(atlas_raw, 'route_long_name', None)),
            'atlas_route_name': _clean_text(atlas_family.public_name) or _clean_text(atlas_family.display_route_id),
            'atlas_operators': atlas_operator_map.get(atlas_family.id, []),
            'osm_route_master_id': None,
            'osm_route_id': None,
            'osm_representative_relation_id': None,
            'osm_gtfs_route_id': None,
            'osm_route_display_id': None,
            'osm_route_id_label': 'Route ID',
            'osm_route_name': None,
            'osm_operator': None,
            'osm_network': None,
            'is_non_gtfs': False,
            'primary_route_id': _clean_text(atlas_family.source_family_id),
        })

    for osm_family in osm_generic_rows:
        if osm_family.id in matched_osm_ids:
            continue
        route_items.append({
            'display_mode': 'osm_only',
            'is_matched': False,
            'match_label': 'Non-GTFS OSM' if getattr(osm_family, 'is_non_gtfs', False) else 'Unmatched OSM',
            'sort_route_id': _clean_text(osm_family.display_route_id) or '',
            'atlas_family_id': None,
            'osm_family_id': osm_family.id,
            'line_family_match_id': None,
            'atlas_route_id': None,
            'atlas_route_short_name': None,
            'atlas_route_long_name': None,
            'atlas_route_name': None,
            'atlas_operators': [],
            'osm_route_master_id': _clean_text(osm_family.route_master_id),
            'osm_route_id': _clean_text(osm_family.representative_relation_id),
            'osm_representative_relation_id': _clean_text(osm_family.representative_relation_id),
            'osm_gtfs_route_id': _clean_text(osm_family.gtfs_route_id),
            'osm_route_display_id': _clean_text(osm_family.display_route_id),
            'osm_route_id_label': _osm_route_id_label(osm_family.gtfs_route_id, osm_family.display_route_id),
            'osm_route_name': _clean_text(osm_family.public_name) or _clean_text(osm_family.ref) or _clean_text(osm_family.display_route_id),
            'osm_operator': _clean_text(osm_family.operator),
            'osm_network': _clean_text(osm_family.network),
            'is_non_gtfs': getattr(osm_family, 'is_non_gtfs', False),
            'primary_route_id': _clean_text(osm_family.display_route_id),
        })

    return route_items


def _route_matches_filters(route_item, q, atlas_operators, osm_operators, matched_filter):
    if matched_filter == ROUTE_MATCHED and route_item['display_mode'] != 'matched':
        return False
    if matched_filter == ROUTE_UNMATCHED and route_item['display_mode'] == 'matched':
        return False
    if matched_filter == ROUTE_UNMATCHED_ATLAS and route_item['display_mode'] != 'atlas_only':
        return False
    if matched_filter == ROUTE_UNMATCHED_OSM and route_item['display_mode'] != 'osm_only':
        return False

    if atlas_operators:
        route_atlas_operators = set(route_item.get('atlas_operators', []))
        if not route_atlas_operators.intersection(atlas_operators):
            return False
    if osm_operators:
        osm_operator = route_item.get('osm_operator')
        if osm_operator not in osm_operators:
            return False

    if q:
        haystack = [
            route_item.get('atlas_route_id'),
            route_item.get('atlas_route_short_name'),
            route_item.get('atlas_route_long_name'),
            route_item.get('atlas_route_name'),
            route_item.get('osm_route_display_id'),
            route_item.get('osm_route_name'),
            route_item.get('osm_route_master_id'),
            route_item.get('osm_route_id'),
            route_item.get('osm_representative_relation_id'),
        ]
        query_text = q.lower()
        if not any(query_text in str(value).lower() for value in haystack if value):
            return False

    return True


def _partition_route_items(route_items):
    gtfs_route_items = []
    non_gtfs_route_items = []
    for item in route_items:
        if item.get('is_non_gtfs'):
            non_gtfs_route_items.append(item)
        else:
            gtfs_route_items.append(item)
    return gtfs_route_items, non_gtfs_route_items


def _load_detail_maps(page_items):
    selected_family_ids = {
        family_id
        for item in page_items
        for family_id in (item.get('atlas_family_id'), item.get('osm_family_id'))
        if family_id is not None
    }
    selected_match_ids = {item['line_family_match_id'] for item in page_items if item.get('line_family_match_id') is not None}

    itineraries = db.session.query(Itinerary).filter(Itinerary.line_family_id.in_(selected_family_ids)).all() if selected_family_ids else []
    itinerary_by_id = {row.id: row for row in itineraries}

    stop_calls = db.session.query(StopCall).filter(StopCall.itinerary_id.in_(itinerary_by_id.keys())).all() if itinerary_by_id else []
    stop_calls_by_itinerary: dict[int, list[StopCall]] = defaultdict(list)
    for stop_call in stop_calls:
        stop_calls_by_itinerary[stop_call.itinerary_id].append(stop_call)
    for stop_call_list in stop_calls_by_itinerary.values():
        stop_call_list.sort(key=lambda row: (row.stop_sequence, row.id))

    itinerary_matches = db.session.query(ItineraryMatch).filter(ItineraryMatch.line_family_match_id.in_(selected_match_ids)).all() if selected_match_ids else []
    itinerary_matches_by_family_match: dict[int, list[ItineraryMatch]] = defaultdict(list)
    for itinerary_match in itinerary_matches:
        itinerary_matches_by_family_match[itinerary_match.line_family_match_id].append(itinerary_match)
    for match_list in itinerary_matches_by_family_match.values():
        match_list.sort(key=lambda row: (_direction_sort_key(itinerary_by_id.get(row.atlas_itinerary_id).direction_id if itinerary_by_id.get(row.atlas_itinerary_id) else None), row.id))

    itineraries_by_family: dict[int, list[Itinerary]] = defaultdict(list)
    for itinerary in itineraries:
        itineraries_by_family[itinerary.line_family_id].append(itinerary)
    for itinerary_list in itineraries_by_family.values():
        itinerary_list.sort(key=lambda row: (_direction_sort_key(row.direction_id), row.id))

    return itinerary_by_id, stop_calls_by_itinerary, itinerary_matches_by_family_match, itineraries_by_family


def _serialize_stop_calls(stop_calls, source_kind):
    serialized = []
    for stop_call in stop_calls:
        stop_ids = []
        if source_kind == 'atlas':
            stop_ids = _deserialize_id_list(stop_call.source_sloid_variants)
            if not stop_ids and stop_call.source_sloid:
                stop_ids = [stop_call.source_sloid]
        elif stop_call.source_node_id:
            stop_ids = [stop_call.source_node_id]
        serialized.append({
            'stop_id': stop_call.source_sloid if source_kind == 'atlas' else stop_call.source_node_id,
            'stop_ids': stop_ids,
            'uic_ref': stop_call.uic_ref,
            'stop_label': stop_call.stop_label,
            'stop_sequence': stop_call.stop_sequence,
            'lat': stop_call.stop_lat,
            'lon': stop_call.stop_lon,
        })
    return serialized


def _build_direction_group(atlas_itinerary, osm_itinerary, atlas_calls, osm_calls):
    direction_id = atlas_itinerary.direction_id if atlas_itinerary is not None else (osm_itinerary.direction_id if osm_itinerary is not None else None)
    direction_label = None
    representative_headsign = None
    if atlas_itinerary is not None:
        direction_label = atlas_itinerary.display_name
        representative_headsign = atlas_itinerary.representative_headsign
    if direction_label is None and osm_itinerary is not None:
        direction_label = osm_itinerary.display_name
    if representative_headsign is None and osm_itinerary is not None:
        representative_headsign = osm_itinerary.representative_headsign

    atlas_stops = _serialize_stop_calls(atlas_calls, 'atlas')
    osm_stops = _serialize_stop_calls(osm_calls, 'osm')
    return {
        'direction_id': direction_id,
        'direction_label': direction_label,
        'representative_headsign': representative_headsign,
        'osm_relation_id': _clean_text(osm_itinerary.source_itinerary_id) if osm_itinerary is not None else None,
        'atlas_uic_groups': _group_stops_by_uic(atlas_stops),
        'osm_uic_groups': _group_stops_by_uic(osm_stops),
    }


def _build_route_rows(page_items):
    itinerary_by_id, stop_calls_by_itinerary, itinerary_matches_by_family_match, itineraries_by_family = _load_detail_maps(page_items)
    route_rows = []

    for item in page_items:
        direction_groups = []
        matched_atlas_itinerary_ids = set()
        matched_osm_itinerary_ids = set()

        if item.get('line_family_match_id') is not None:
            for itinerary_match in itinerary_matches_by_family_match.get(item['line_family_match_id'], []):
                atlas_itinerary = itinerary_by_id.get(itinerary_match.atlas_itinerary_id)
                osm_itinerary = itinerary_by_id.get(itinerary_match.osm_itinerary_id)
                if atlas_itinerary is None or osm_itinerary is None:
                    continue
                matched_atlas_itinerary_ids.add(atlas_itinerary.id)
                matched_osm_itinerary_ids.add(osm_itinerary.id)
                direction_groups.append(
                    _build_direction_group(
                        atlas_itinerary,
                        osm_itinerary,
                        stop_calls_by_itinerary.get(atlas_itinerary.id, []),
                        stop_calls_by_itinerary.get(osm_itinerary.id, []),
                    )
                )

        if item.get('atlas_family_id') is not None:
            for itinerary in itineraries_by_family.get(item['atlas_family_id'], []):
                if itinerary.id in matched_atlas_itinerary_ids:
                    continue
                direction_groups.append(
                    _build_direction_group(
                        itinerary,
                        None,
                        stop_calls_by_itinerary.get(itinerary.id, []),
                        [],
                    )
                )
        if item.get('osm_family_id') is not None:
            for itinerary in itineraries_by_family.get(item['osm_family_id'], []):
                if itinerary.id in matched_osm_itinerary_ids:
                    continue
                direction_groups.append(
                    _build_direction_group(
                        None,
                        itinerary,
                        [],
                        stop_calls_by_itinerary.get(itinerary.id, []),
                    )
                )

        direction_groups.sort(key=lambda group: (_direction_sort_key(group['direction_id']), group['direction_label'] or ''))

        map_filter = None
        has_geolocated_stops = any(
            member.get('lat') is not None and member.get('lon') is not None
            for direction_group in direction_groups
            for uic_group in (direction_group.get('atlas_uic_groups', []) + direction_group.get('osm_uic_groups', []))
            for member in uic_group.get('members', [])
        )
        if has_geolocated_stops and item.get('primary_route_id'):
            map_filter = {
                'station_filter': item['primary_route_id'],
                'filter_types': 'route',
                'route_directions': '',
            }

        route_rows.append({
            **item,
            'atlas_operators_summary': ', '.join(item.get('atlas_operators', [])) if item.get('atlas_operators') else None,
            'direction_groups': direction_groups,
            'direction_summary': _direction_summary(direction_groups),
            'map_filter': map_filter,
        })

    return route_rows


@routes_bp.route('/routes')
def routes_page():
    page = _bounded_int(request.args.get('page', 1), 1, minimum=1)
    per_page = _bounded_int(request.args.get('per_page', 10), 10, minimum=1, maximum=max(ROUTES_PER_PAGE_OPTIONS))
    q = (request.args.get('q') or '').strip()
    matched_filter = _normalize_route_match_filter(request.args.get('matched'))
    selected_atlas_operators = _parse_multi_filter('atlas_operator')
    selected_osm_operators = _parse_multi_filter('osm_operator')

    try:
        route_items = _load_route_page_data()
        available_atlas_operators = _load_available_atlas_operators()
        available_osm_operators = _load_available_osm_route_operators()
    except Exception as exc:
        if is_missing_table_error(exc):
            db.session.rollback()
            route_items = []
            available_atlas_operators = []
            available_osm_operators = []
        else:
            raise

    route_items, _non_gtfs_route_items = _partition_route_items(route_items)

    filtered_items = [
        item
        for item in route_items
        if _route_matches_filters(item, q, selected_atlas_operators, selected_osm_operators, matched_filter)
    ]
    filtered_items.sort(key=lambda item: (item['sort_route_id'].lower(), item['display_mode']))

    total = len(filtered_items)
    start_index = (page - 1) * per_page
    page_items = filtered_items[start_index:start_index + per_page]
    pagination = _ListPagination(page_items, page, per_page, total) if total else _EmptyPagination(page, per_page)
    route_rows = _build_route_rows(page_items)
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


@routes_bp.route('/routes/non-gtfs')
def non_gtfs_routes_page():
    page = _bounded_int(request.args.get('page', 1), 1, minimum=1)
    per_page = _bounded_int(request.args.get('per_page', 10), 10, minimum=1, maximum=max(ROUTES_PER_PAGE_OPTIONS))

    try:
        route_items = _load_route_page_data()
    except Exception as exc:
        if is_missing_table_error(exc):
            db.session.rollback()
            route_items = []
        else:
            raise

    _gtfs_route_items, non_gtfs_route_items = _partition_route_items(route_items)
    non_gtfs_route_items.sort(key=lambda item: (item['sort_route_id'].lower(), item['display_mode']))

    total = len(non_gtfs_route_items)
    start_index = (page - 1) * per_page
    page_items = non_gtfs_route_items[start_index:start_index + per_page]
    pagination = _ListPagination(page_items, page, per_page, total) if total else _EmptyPagination(page, per_page)
    route_rows = _build_route_rows(page_items)
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
        matched_filter=ROUTE_MATCH_ALL,
        available_atlas_operators=[],
        available_osm_operators=[],
        selected_atlas_operators=[],
        selected_osm_operators=[],
        atlas_operator_query='',
        osm_operator_query='',
        q='',
        search_placeholder=_search_placeholder(),
    )


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
            return jsonify({'error': 'GTFS route tables are not initialized yet.'}), 503
        raise


@routes_bp.route('/api/routes/gtfs-stop-id-sloid/map')
def routes_gtfs_stop_id_sloid_map_api():
    try:
        min_lat = float(request.args.get('min_lat'))
        min_lon = float(request.args.get('min_lon'))
        max_lat = float(request.args.get('max_lat'))
        max_lon = float(request.args.get('max_lon'))
        zoom = int(request.args.get('zoom', 0))
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid map bounds or zoom'}), 400

    try:
        return jsonify(build_gtfs_stop_id_sloid_map_payload(min_lat, min_lon, max_lat, max_lon, zoom))
    except Exception as exc:
        if is_missing_table_error(exc):
            db.session.rollback()
            return jsonify({'error': 'GTFS route tables are not initialized yet.'}), 503
        raise


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
        raise

    if payload is None:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(payload)