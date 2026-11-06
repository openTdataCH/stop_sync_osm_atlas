"""Per-source statistics for the analytics page, read from the published tables.

Each function returns one section of stats.json: ``atlas_stops``, ``osm_stops``,
``osm_routes`` and ``gtfs``. They read only the database, so
scripts/regenerate_stats.py can refresh them without the result bundle.

Counting units, which the page names explicitly:
- OSM *element*: one active node or way (retired lifecycle tags excluded).
- OSM *stop unit*: one single element, or one platform/stop_position group.
- OSM *line*: a route_master, or relations grouped by a shared key.
- GTFS *line*: one GTFS route; an *itinerary* is one distinct stop pattern.
"""

from collections import Counter, defaultdict
from statistics import mean, median
from typing import Any, Dict, Iterable, Optional

from sqlalchemy import func

MATCHED_STOP_TYPES = ('matched', 'effectively_matched')

# The Swiss GTFS codes trolleybuses as buses, so both sides count them as bus.
MODES = ('rail', 'tram', 'metro', 'bus', 'ferry', 'aerialway', 'funicular', 'other')

# OSM route=* values of public transport services, as the engine selects them;
# anything else (piste, mtb, railway infrastructure...) is not a service.
_OSM_ROUTE_MODES = {
    'train': 'rail',
    'tram': 'tram',
    'light_rail': 'tram',
    'subway': 'metro',
    'monorail': 'metro',
    'bus': 'bus',
    'minibus': 'bus',
    'trolleybus': 'bus',
    'coach': 'bus',
    'ferry': 'ferry',
    'aerialway': 'aerialway',
    'funicular': 'funicular',
    'share_taxi': 'other',
}
NOT_PUBLIC_TRANSPORT = 'not_public_transport'

# GTFS basic route types and the extended (HVT) ranges used by the Swiss feed.
_GTFS_BASIC_MODES = {
    0: 'tram', 1: 'metro', 2: 'rail', 3: 'bus', 4: 'ferry', 5: 'tram',
    6: 'aerialway', 7: 'funicular', 11: 'bus', 12: 'metro',
}
_GTFS_EXTENDED_MODES = (
    (100, 199, 'rail'), (200, 299, 'bus'), (400, 499, 'metro'), (700, 799, 'bus'),
    (800, 899, 'bus'), (900, 999, 'tram'), (1000, 1099, 'ferry'), (1200, 1299, 'ferry'),
    (1300, 1399, 'aerialway'), (1400, 1499, 'funicular'),
)

OSM_ELEMENT_TYPES = ('stop_position', 'platform', 'railway_station', 'aerialway', 'ferry_terminal', 'other')
OSM_GROUP_KINDS = (
    'ptv2_pair_uic_ref_equal_count', 'ptv2_pair_uic_ref', 'ptv2_pair_name_equal_count', 'ptv2_pair_name',
    'tram_stop_pair_equal_count', 'tram_stop_pair', 'ptv2_two_sided_stop',
)

# Tags reported on stop elements, by purpose. Shares use the element counts of
# each type, so amenities can be read against platforms.
OSM_STOP_TAG_GROUPS = (
    ('identifiers', ('name', 'uic_ref', 'uic_name', 'local_ref', 'ref', 'ref:sloid')),
    ('operator_network', ('operator', 'operator:wikidata', 'network', 'network:wikidata')),
    ('accessibility_amenities', ('wheelchair', 'tactile_paving', 'shelter', 'bench', 'bin', 'lit',
                                 'departures_board', 'passenger_information_display')),
)

# Route relation columns and the OSM tag each one holds.
OSM_ROUTE_TAG_COLUMNS = (
    ('ref', 'ref'), ('name', 'name'), ('from_name', 'from'), ('to_name', 'to'),
    ('operator', 'operator'), ('operator_wikidata', 'operator:wikidata'),
    ('network', 'network'), ('network_wikidata', 'network:wikidata'), ('colour', 'colour'),
    ('gtfs_route_id', 'gtfs:route_id'), ('gtfs_trip_id', 'gtfs:trip_id'), ('gtfs_shape_id', 'gtfs:shape_id'),
)


def osm_route_mode(route: Optional[str]) -> str:
    value = (route or '').strip().lower()
    if not value:
        return 'other'
    return _OSM_ROUTE_MODES.get(value, NOT_PUBLIC_TRANSPORT)


def gtfs_route_mode(route_type: Any) -> str:
    try:
        code = int(str(route_type).strip())
    except (TypeError, ValueError):
        return 'other'
    if code in _GTFS_BASIC_MODES:
        return _GTFS_BASIC_MODES[code]
    return next((mode for low, high, mode in _GTFS_EXTENDED_MODES if low <= code <= high), 'other')


def percent(part: int, whole: int) -> float:
    return round(part / whole * 100, 1) if whole else 0.0


def summarize(values: Iterable[float]) -> Dict[str, float]:
    values = list(values)
    if not values:
        return {'mean': 0.0, 'median': 0.0}
    return {'mean': round(float(mean(values)), 2), 'median': round(float(median(values)), 2)}


def _present(value: Any) -> bool:
    return value is not None and str(value).strip() != ''


def _matched_osm_node_ids(session) -> set:
    from backend.models import StopsMatched
    return {
        node_id for (node_id,) in session.query(StopsMatched.osm_node_id)
        .filter(StopsMatched.stop_type.in_(MATCHED_STOP_TYPES), StopsMatched.osm_node_id.isnot(None))
        .distinct()
    }


# ---------------------------------------------------------------------------
# ATLAS stops
# ---------------------------------------------------------------------------

def compute_atlas_stop_stats(session) -> Dict[str, Any]:
    """Platforms, matched platforms and duplicate SLOID groups, counted in SLOIDs."""
    from backend.models import AtlasStop, StopsMatched

    matched = {
        sloid for (sloid,) in session.query(StopsMatched.sloid)
        .filter(StopsMatched.stop_type.in_(MATCHED_STOP_TYPES), StopsMatched.sloid.isnot(None))
        .distinct()
    }
    platforms = 0
    groups = set()
    duplicate_sloids = set()
    for sloid, group in session.query(AtlasStop.sloid, AtlasStop.duplicate_group_sloids):
        platforms += 1
        if isinstance(group, list) and len(group) > 1:
            groups.add(tuple(sorted(str(member) for member in group)))
            duplicate_sloids.add(sloid)
    matched_duplicates = len(duplicate_sloids & matched)
    return {
        'platforms': platforms,
        'matched': len(matched),
        'duplicates': {
            'groups': len(groups),
            'sloids': len(duplicate_sloids),
            'matched_sloids': matched_duplicates,
            'unmatched_sloids': len(duplicate_sloids) - matched_duplicates,
        },
    }


# ---------------------------------------------------------------------------
# OSM stops
# ---------------------------------------------------------------------------

def _relation_routes(session) -> Dict[str, str]:
    """The route value of each OSM route relation.

    A relation without a ``route`` tag takes the value of its route master,
    which the route master's line family carries as ``route_type``.
    """
    from backend.models import LineFamily, OsmRouteRelation

    master_routes = {
        master_id: route_type for master_id, route_type in
        session.query(LineFamily.route_master_id, LineFamily.route_type)
        .filter(LineFamily.source == 'osm', LineFamily.route_master_id.isnot(None))
    }
    return {
        relation_id: (route or '').strip() or master_routes.get(master_id) or ''
        for relation_id, route, master_id in
        session.query(OsmRouteRelation.relation_id, OsmRouteRelation.route, OsmRouteRelation.route_master_id)
    }


def _public_transport_relation_ids(session) -> set:
    return {relation_id for relation_id, route in _relation_routes(session).items()
            if osm_route_mode(route) != NOT_PUBLIC_TRANSPORT}


def compute_osm_stop_stats(session) -> Dict[str, Any]:
    """Elements, stop units, groups, tag coverage and route service of OSM stops."""
    from backend.models import Itinerary, OsmNode, OsmStop, OsmStopMember, StopCall

    matched_nodes = _matched_osm_node_ids(session)

    by_type = {kind: {'type': kind, 'elements': 0, 'ways': 0, 'matched': 0} for kind in OSM_ELEMENT_TYPES}
    type_by_node = {}
    tag_keys = [key for _, keys in OSM_STOP_TAG_GROUPS for key in keys]
    tag_counts = {key: Counter() for key in tag_keys}
    retired = Counter()
    rows = (session.query(OsmNode.osm_node_id, OsmNode.osm_node_type, OsmNode.osm_lifecycle, OsmNode.osm_tags)
            .execution_options(yield_per=5000))
    for node_id, node_type, lifecycle, tags in rows:
        if lifecycle:
            retired[lifecycle] += 1
            continue
        kind = node_type if node_type in by_type else 'other'
        type_by_node[node_id] = kind
        row = by_type[kind]
        row['elements'] += 1
        row['ways'] += str(node_id).startswith('way_')
        row['matched'] += node_id in matched_nodes
        tags = tags if isinstance(tags, dict) else {}
        for key in tag_keys:
            if _present(tags.get(key)):
                tag_counts[key][kind] += 1
                tag_counts[key]['all'] += 1

    elements = len(type_by_node)
    element_counts = Counter(type_by_node.values())

    members_by_unit = defaultdict(list)
    for stop_id, node_id in session.query(OsmStopMember.osm_stop_id, OsmStopMember.node_id):
        members_by_unit[stop_id].append(node_id)

    served_nodes = set()
    public_transport_relations = _public_transport_relation_ids(session)
    for node_id, relation_id in (
        session.query(StopCall.source_node_id, Itinerary.source_itinerary_id)
        .join(Itinerary, Itinerary.id == StopCall.itinerary_id)
        .filter(Itinerary.source == 'osm', StopCall.source_node_id.isnot(None))
        .distinct()
    ):
        if relation_id in public_transport_relations:
            served_nodes.add(node_id)

    by_kind = {kind: {'units': 0, 'elements': 0, 'matched': 0} for kind in ('single', 'pair', 'two_sided_stop')}
    groups = {kind: {'group_kind': kind, 'units': 0, 'all_matched': 0, 'partly_matched': 0, 'none_matched': 0}
              for kind in OSM_GROUP_KINDS}
    units = matched_units = served_units = 0
    for stop_id, stop_kind, group_kind in session.query(OsmStop.id, OsmStop.stop_kind, OsmStop.group_kind):
        members = members_by_unit.get(stop_id, [])
        matched_members = sum(node_id in matched_nodes for node_id in members)
        units += 1
        matched_units += matched_members > 0
        served_units += any(node_id in served_nodes for node_id in members)
        kind_row = by_kind.setdefault(stop_kind, {'units': 0, 'elements': 0, 'matched': 0})
        kind_row['units'] += 1
        kind_row['elements'] += len(members)
        kind_row['matched'] += matched_members > 0
        if group_kind:
            group = groups.setdefault(group_kind, {'group_kind': group_kind, 'units': 0, 'all_matched': 0,
                                                   'partly_matched': 0, 'none_matched': 0})
            group['units'] += 1
            if matched_members == 0:
                group['none_matched'] += 1
            elif matched_members == len(members):
                group['all_matched'] += 1
            else:
                group['partly_matched'] += 1

    group_rows = [row for row in groups.values() if row['units']]
    return {
        'elements': {
            'total': elements,
            'ways': sum(row['ways'] for row in by_type.values()),
            'matched': sum(row['matched'] for row in by_type.values()),
            'by_type': [row for row in by_type.values() if row['elements']],
            'retired': {'total': sum(retired.values()), 'by_lifecycle': dict(retired.most_common())},
        },
        'stop_units': {
            'total': units,
            'matched': matched_units,
            'served_by_routes': served_units,
            'by_kind': by_kind,
        },
        'groups': {
            'total': sum(row['units'] for row in group_rows),
            'all_matched': sum(row['all_matched'] for row in group_rows),
            'partly_matched': sum(row['partly_matched'] for row in group_rows),
            'none_matched': sum(row['none_matched'] for row in group_rows),
            'by_kind': group_rows,
        },
        'tags': {
            'elements': elements,
            'platforms': element_counts['platform'],
            'stop_positions': element_counts['stop_position'],
            'groups': [
                {'group': group, 'keys': [
                    {'key': key, 'elements': tag_counts[key]['all'],
                     'platforms': tag_counts[key]['platform'], 'stop_positions': tag_counts[key]['stop_position']}
                    for key in keys
                ]}
                for group, keys in OSM_STOP_TAG_GROUPS
            ],
        },
    }


# ---------------------------------------------------------------------------
# OSM routes
# ---------------------------------------------------------------------------

def compute_osm_route_stats(session) -> Dict[str, Any]:
    """Route relations, their tags and how they form lines and itineraries."""
    from backend.models import Itinerary, LineFamily, OsmRouteRelation, StopCall

    columns = [getattr(OsmRouteRelation, column) for column, _ in OSM_ROUTE_TAG_COLUMNS]
    routes = _relation_routes(session)
    relations = 0
    by_mode = Counter()
    by_route_value = Counter()
    in_route_master = ptv2 = 0
    tag_counts = Counter()
    public_transport_ids = set()
    for relation_id, route, route_master_id, version, *values in session.query(
        OsmRouteRelation.relation_id, OsmRouteRelation.route, OsmRouteRelation.route_master_id,
        OsmRouteRelation.public_transport_version, *columns,
    ):
        relations += 1
        route = routes.get(relation_id, route)
        mode = osm_route_mode(route)
        by_mode[mode] += 1
        if mode == NOT_PUBLIC_TRANSPORT:
            by_route_value[route] += 1
            continue
        public_transport_ids.add(relation_id)
        in_route_master += _present(route_master_id)
        ptv2 += str(version or '').strip() == '2'
        for (_, tag), value in zip(OSM_ROUTE_TAG_COLUMNS, values):
            tag_counts[tag] += _present(value)

    public_transport = len(public_transport_ids)
    line_rows = session.query(LineFamily.id, LineFamily.family_origin, LineFamily.route_type,
                              LineFamily.is_non_gtfs).filter(LineFamily.source == 'osm').all()
    lines_by_origin = Counter()
    lines_by_mode = Counter()
    for _, origin, route_type, _ in line_rows:
        lines_by_origin[origin or 'other'] += 1
        lines_by_mode[osm_route_mode(route_type)] += 1
    relations_by_origin = Counter({
        origin or 'other': count for origin, count in
        session.query(LineFamily.family_origin, func.count(Itinerary.id))
        .join(Itinerary, Itinerary.line_family_id == LineFamily.id)
        .filter(LineFamily.source == 'osm')
        .group_by(LineFamily.family_origin)
    })

    itineraries = with_direction = 0
    for relation_id, direction_id in session.query(Itinerary.source_itinerary_id, Itinerary.direction_id).filter(
        Itinerary.source == 'osm'
    ):
        if relation_id in public_transport_ids:
            itineraries += 1
            with_direction += _present(direction_id)

    calls = resolved_calls = 0
    for relation_id, calls_count, resolved_count in (
        session.query(Itinerary.source_itinerary_id, func.count(StopCall.id), func.count(StopCall.source_sloid))
        .join(StopCall, StopCall.itinerary_id == Itinerary.id)
        .filter(Itinerary.source == 'osm')
        .group_by(Itinerary.source_itinerary_id)
    ):
        if relation_id in public_transport_ids:
            calls += calls_count
            resolved_calls += resolved_count

    return {
        'relations': {
            'total': relations,
            'public_transport': public_transport,
            'by_mode': {mode: by_mode[mode] for mode in (*MODES, NOT_PUBLIC_TRANSPORT) if by_mode[mode]},
            'not_public_transport_by_route': dict(by_route_value.most_common()),
            'in_route_master': in_route_master,
            'ptv2': ptv2,
            'tags': [{'key': tag, 'count': tag_counts[tag]} for _, tag in OSM_ROUTE_TAG_COLUMNS],
        },
        'lines': {
            'total': len(line_rows),
            'public_transport': sum(count for mode, count in lines_by_mode.items() if mode != NOT_PUBLIC_TRANSPORT),
            'non_gtfs': sum(1 for row in line_rows if row.is_non_gtfs),
            'by_origin': dict(lines_by_origin),
            'relations_by_origin': dict(relations_by_origin),
            'by_mode': {mode: lines_by_mode[mode] for mode in (*MODES, NOT_PUBLIC_TRANSPORT) if lines_by_mode[mode]},
        },
        'itineraries': {
            'total': itineraries,
            'with_direction': with_direction,
            'stop_calls': calls,
            'resolved_stop_calls': resolved_calls,
        },
    }


# ---------------------------------------------------------------------------
# Swiss GTFS
# ---------------------------------------------------------------------------

def compute_gtfs_stats(session) -> Dict[str, Any]:
    """GTFS stop IDs resolved to SLOIDs, and the lines and itineraries built from GTFS."""
    from backend.models import AtlasStop, GtfsStopIdentityResolution, Itinerary, LineFamily, StopCall

    used_stop_ids = {
        stop_id for (stop_id,) in session.query(StopCall.source_stop_id)
        .join(Itinerary, Itinerary.id == StopCall.itinerary_id)
        .filter(Itinerary.source == 'atlas', StopCall.source_stop_id.isnot(None))
        .distinct()
    }
    levels = {}
    methods = Counter()
    referenced_sloids = set()
    for stop_id, level, sloid, method in session.query(
        GtfsStopIdentityResolution.stop_id, GtfsStopIdentityResolution.identity_level,
        GtfsStopIdentityResolution.resolved_sloid, GtfsStopIdentityResolution.resolution_method,
    ):
        row = levels.setdefault(level or 'stop', {'level': level or 'stop', 'total': 0, 'resolved': 0,
                                                  'used': 0, 'used_resolved': 0})
        row['total'] += 1
        used = stop_id in used_stop_ids
        row['used'] += used
        if sloid:
            row['resolved'] += 1
            row['used_resolved'] += used
            referenced_sloids.add(sloid)
            methods[method] += 1
    level_rows = [levels[level] for level in ('platform', 'child_stop', 'stop', 'station') if level in levels]

    atlas_platforms = session.query(func.count(AtlasStop.sloid)).scalar() or 0

    line_rows = session.query(LineFamily.id, LineFamily.route_type).filter(LineFamily.source == 'atlas').all()
    lines_by_mode = Counter(gtfs_route_mode(route_type) for _, route_type in line_rows)
    itinerary_rows = (session.query(Itinerary.line_family_id, Itinerary.direction_id, Itinerary.trip_count)
                      .filter(Itinerary.source == 'atlas').all())
    calls, resolved_calls = (
        session.query(func.count(StopCall.id), func.count(StopCall.source_sloid))
        .join(Itinerary, Itinerary.id == StopCall.itinerary_id)
        .filter(Itinerary.source == 'atlas')
        .one()
    )
    return {
        'stops': {
            'total': sum(row['total'] for row in level_rows),
            'resolved': sum(row['resolved'] for row in level_rows),
            'used': sum(row['used'] for row in level_rows),
            'used_resolved': sum(row['used_resolved'] for row in level_rows),
            'by_level': level_rows,
            'by_method': dict(methods.most_common()),
        },
        'atlas_platforms': {'total': atlas_platforms, 'referenced': len(referenced_sloids)},
        'routes': {
            'lines': len(line_rows),
            'by_mode': {mode: lines_by_mode[mode] for mode in MODES if lines_by_mode[mode]},
            'itineraries': len(itinerary_rows),
            'directions': len({(family, direction) for family, direction, _ in itinerary_rows}),
            'trips_per_itinerary': summarize(trips for _, _, trips in itinerary_rows if trips is not None),
            'stop_calls': calls or 0,
            'resolved_stop_calls': resolved_calls or 0,
        },
    }


# ---------------------------------------------------------------------------
# Route links (GTFS line <-> OSM line)
# ---------------------------------------------------------------------------

def _route_keys(row) -> Dict[str, Optional[str]]:
    return {key: (str(getattr(row, key)).strip() or None) if getattr(row, key) is not None else None
            for key in ('gtfs_route_id', 'normalized_route_id', 'display_route_id')}


def compute_route_link_stats(session) -> Dict[str, Any]:
    """Links between GTFS and OSM lines and between their itineraries.

    The engine links lines and itineraries one to one, so the number of links
    equals the linked lines on each side; coverage and the reasons a line stays
    unlinked carry the information.
    """
    from backend.models import Itinerary, ItineraryMatch, LineFamily, LineFamilyMatch

    families = session.query(LineFamily.id, LineFamily.source, LineFamily.route_type, LineFamily.is_non_gtfs,
                             LineFamily.gtfs_route_id, LineFamily.normalized_route_id,
                             LineFamily.display_route_id).all()
    gtfs_lines = [row for row in families if row.source == 'atlas']
    osm_lines = [row for row in families if row.source == 'osm']
    links = session.query(LineFamilyMatch.atlas_line_family_id, LineFamilyMatch.osm_line_family_id,
                          LineFamilyMatch.match_method).all()
    linked_gtfs = {gtfs_id for gtfs_id, _, _ in links}
    linked_osm = {osm_id for _, osm_id, _ in links}

    by_mode = {mode: {'mode': mode, 'gtfs_lines': 0, 'gtfs_linked': 0, 'osm_lines': 0, 'osm_linked': 0}
               for mode in MODES}
    for row in gtfs_lines:
        mode_row = by_mode[gtfs_route_mode(row.route_type)]
        mode_row['gtfs_lines'] += 1
        mode_row['gtfs_linked'] += row.id in linked_gtfs
    osm_public_transport = 0
    for row in osm_lines:
        mode = osm_route_mode(row.route_type)
        if mode == NOT_PUBLIC_TRANSPORT:
            continue
        osm_public_transport += 1
        by_mode[mode]['osm_lines'] += 1
        by_mode[mode]['osm_linked'] += row.id in linked_osm

    # The engine's candidate rule: OSM gtfs_route_id, normalized ID or display ID
    # equal to the GTFS route ID (normalized IDs compare with each other).
    gtfs_by_route_id = defaultdict(set)
    gtfs_by_normalized = defaultdict(set)
    for row in gtfs_lines:
        keys = _route_keys(row)
        if keys['gtfs_route_id']:
            gtfs_by_route_id[keys['gtfs_route_id']].add(row.id)
        if keys['normalized_route_id']:
            gtfs_by_normalized[keys['normalized_route_id']].add(row.id)
    osm_candidates_by_gtfs = defaultdict(set)
    osm_unlinked = Counter({reason: 0 for reason in (
        NOT_PUBLIC_TRANSPORT, 'non_gtfs', 'no_route_id', 'several_route_ids', 'route_id_not_in_gtfs',
        'gtfs_line_already_linked')})
    for row in osm_lines:
        keys = _route_keys(row)
        candidates = set()
        if not row.is_non_gtfs:
            candidates = (gtfs_by_route_id.get(keys['gtfs_route_id'], set())
                          | gtfs_by_normalized.get(keys['normalized_route_id'], set())
                          | gtfs_by_route_id.get(keys['display_route_id'], set()))
        for gtfs_id in candidates:
            osm_candidates_by_gtfs[gtfs_id].add(row.id)
        if row.id in linked_osm:
            continue
        if osm_route_mode(row.route_type) == NOT_PUBLIC_TRANSPORT:
            osm_unlinked[NOT_PUBLIC_TRANSPORT] += 1
        elif row.is_non_gtfs:
            osm_unlinked['non_gtfs'] += 1
        elif candidates:
            osm_unlinked['gtfs_line_already_linked'] += 1
        # The normalized ID falls back to the line's ref, so only gtfs:route_id
        # tells whether the line carries a GTFS route ID at all.
        elif not keys['gtfs_route_id']:
            osm_unlinked['no_route_id'] += 1
        elif ';' in keys['gtfs_route_id']:
            osm_unlinked['several_route_ids'] += 1
        else:
            osm_unlinked['route_id_not_in_gtfs'] += 1
    gtfs_unlinked = Counter({'no_osm_line': 0, 'osm_line_already_linked': 0})
    for row in gtfs_lines:
        if row.id not in linked_gtfs:
            gtfs_unlinked['osm_line_already_linked' if osm_candidates_by_gtfs.get(row.id) else 'no_osm_line'] += 1

    method_counts = Counter(method or 'other' for _, _, method in links)

    itineraries = session.query(Itinerary.id, Itinerary.source, Itinerary.line_family_id, Itinerary.direction_id,
                                Itinerary.trip_count).all()
    itinerary_links = session.query(ItineraryMatch.atlas_itinerary_id, ItineraryMatch.osm_itinerary_id).all()
    linked_gtfs_itineraries = {gtfs_id for gtfs_id, _ in itinerary_links}
    linked_osm_itineraries = {osm_id for _, osm_id in itinerary_links}
    itinerary_counts = Counter(row.line_family_id for row in itineraries)
    gtfs_in_linked = [row for row in itineraries if row.source == 'atlas' and row.line_family_id in linked_gtfs]
    osm_in_linked = [row for row in itineraries if row.source == 'osm' and row.line_family_id in linked_osm]

    gaps = [itinerary_counts[gtfs_id] - itinerary_counts[osm_id] for gtfs_id, osm_id, _ in links]
    return {
        'line_links': len(links),
        'gtfs_lines': {'total': len(gtfs_lines), 'linked': len(linked_gtfs), 'unlinked': dict(gtfs_unlinked)},
        'osm_lines': {'total': len(osm_lines), 'public_transport': osm_public_transport,
                      'linked': len(linked_osm), 'unlinked': dict(osm_unlinked)},
        'by_mode': [row for row in by_mode.values() if row['gtfs_lines'] or row['osm_lines']],
        'by_match_method': dict(method_counts.most_common()),
        'itineraries': {
            'links': len(itinerary_links),
            'gtfs_in_linked_lines': len(gtfs_in_linked),
            'gtfs_linked': sum(row.id in linked_gtfs_itineraries for row in gtfs_in_linked),
            'osm_in_linked_lines': len(osm_in_linked),
            'osm_linked': sum(row.id in linked_osm_itineraries for row in osm_in_linked),
            'osm_in_linked_lines_without_direction': sum(not _present(row.direction_id) for row in osm_in_linked),
        },
        'itineraries_per_line': {
            'gtfs': summarize(itinerary_counts[row.id] for row in gtfs_lines),
            'osm': summarize(itinerary_counts[row.id] for row in osm_lines
                             if osm_route_mode(row.route_type) != NOT_PUBLIC_TRANSPORT),
        },
        'linked_line_itinerary_gap': {
            **summarize(gaps),
            'gtfs_has_more': sum(gap > 0 for gap in gaps),
            'same': sum(gap == 0 for gap in gaps),
            'osm_has_more': sum(gap < 0 for gap in gaps),
        },
    }


def add_dataset_stats(stats: Dict[str, Any], session) -> Dict[str, Any]:
    """Set every section computed from the published tables on ``stats``."""
    stats['atlas_stops'] = compute_atlas_stop_stats(session)
    stats['osm_stops'] = compute_osm_stop_stats(session)
    stats['osm_routes'] = compute_osm_route_stats(session)
    stats['gtfs'] = compute_gtfs_stats(session)
    stats['route_links'] = compute_route_link_stats(session)
    # Sections that earlier versions derived from the bundle or counted differently.
    for key in ('route_route_matching', 'duplicates', 'osm_way_stops', 'routes'):
        stats.pop(key, None)
    return stats
