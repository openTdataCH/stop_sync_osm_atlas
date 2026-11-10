"""The map's attribute filters as conditions on stops_matched: search tokens, ATLAS and OSM attributes, problems.

``apply_common_filters`` reads the filters ``parse_filter_params`` (backend/queries/helpers.py) builds.
See documentation/2.2 Filters and Search logic.md.
"""

from backend.extensions import db
from backend.models import StopsMatched, AtlasStop, OsmNode, OsmStop, OsmStopMember
from backend.services.problem_filters import has_problem_condition
from backend.services.transport_routes import get_stops_for_route


def osm_list_contains(column, value):
    """``column`` is ``value`` or lists it among ;-separated values, as OSM tags write several values."""
    escaped = value.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    return db.or_(column == value, (db.literal(';') + column + db.literal(';')).like(f'%;{escaped};%', escape='\\'))


def _transport_type_condition(transport_types):
    """The OSM element is one of the chosen kinds; unknown kinds are ignored."""
    kinds = {
        'ferry_terminal': OsmNode.osm_amenity == 'ferry_terminal',
        'tram_stop': OsmNode.osm_railway == 'tram_stop',
        'station': OsmNode.osm_node_type == 'railway_station',
        'platform': OsmNode.osm_public_transport == 'platform',
        'stop_position': OsmNode.osm_public_transport == 'stop_position',
        'aerialway_station': OsmNode.osm_aerialway == 'station',
    }
    chosen = [kinds[kind] for kind in transport_types if kind in kinds]
    return StopsMatched.osm_node_details.has(db.or_(*chosen)) if chosen else None


def search_token_conditions(filters):
    """One condition per search token: a SLOID, an OSM element, a route or a UIC number.

    ``filter_types``, ``route_directions`` and ``route_variants`` are positional,
    like ``filter_values``; a missing entry is a UIC number, both directions and
    the whole route. Identifiers match whole: ch:1:sloid:10035:0:1 must not keep
    ch:1:sloid:10035:0:1955.
    """
    values = filters['filter_values']
    padding = len(values)
    token_types = list(filters.get('filter_types') or []) + ['station'] * padding
    directions = list(filters.get('route_directions') or []) + [''] * padding
    variants = list(filters.get('route_variants') or []) + [None] * padding

    conditions = []
    for value, token_type, direction, variant in zip(values, token_types, directions, variants):
        token_type, direction = token_type.strip(), direction.strip()
        if token_type == 'atlas':
            conditions.append(StopsMatched.sloid == value)
        elif token_type == 'osm':
            conditions.append(StopsMatched.osm_node_id == value)
        elif token_type == 'route':
            route_stops = get_stops_for_route(value, direction or None, variant)
            route_conditions = []
            if route_stops['atlas_sloids']:
                route_conditions.append(StopsMatched.sloid.in_(route_stops['atlas_sloids']))
            if route_stops['osm_nodes']:
                route_conditions.append(StopsMatched.osm_node_id.in_(route_stops['osm_nodes']))
            if route_conditions:
                conditions.append(db.or_(*route_conditions))
        else:  # UIC number of the ATLAS stop, or among the OSM element's uic_ref values
            conditions.append(db.or_(
                StopsMatched.atlas_stop_details.has(AtlasStop.uic_ref == value),
                StopsMatched.osm_node_details.has(osm_list_contains(OsmNode.osm_uic_ref, value)),
            ))
    return conditions


def _osm_group_members(group_kinds):
    """Node ids of the members of OSM pairs and two-sided stops of the chosen kinds; every group when empty."""
    query = db.session.query(OsmStopMember.node_id).join(OsmStop, OsmStopMember.osm_stop_id == OsmStop.id)
    if not group_kinds:
        return query.filter(OsmStop.stop_kind.in_(['pair', 'two_sided_stop']))

    pair_kinds = [kind for kind in group_kinds if kind != 'ptv2_two_sided_stop']
    conditions = []
    if pair_kinds:
        conditions.append(db.and_(OsmStop.stop_kind == 'pair', OsmStop.group_kind.in_(pair_kinds)))
    if 'ptv2_two_sided_stop' in group_kinds:
        conditions.append(db.and_(OsmStop.stop_kind == 'two_sided_stop', OsmStop.group_kind == 'ptv2_two_sided_stop'))
    return query.filter(db.or_(*conditions))


def apply_common_filters(query, filters):
    """Keep the rows of ``query`` that pass every attribute filter in ``filters``."""
    conditions = []

    if filters.get('transport_types'):
        conditions.append(_transport_type_condition(filters['transport_types']))

    node_types = filters.get('node_types') or []
    node_conditions = ([StopsMatched.sloid.isnot(None)] if 'atlas' in node_types else []) + \
        ([StopsMatched.osm_node_id.isnot(None)] if 'osm' in node_types else [])
    if node_conditions:
        conditions.append(db.or_(*node_conditions))

    if filters.get('atlas_operators'):
        conditions.append(StopsMatched.atlas_stop_details.has(
            AtlasStop.atlas_business_org_abbr.in_(filters['atlas_operators'])))

    if filters.get('filter_values'):
        token_conditions = search_token_conditions(filters)
        conditions.append(db.or_(*token_conditions) if token_conditions else db.false())

    # Entries with a problem of the chosen types and priorities.
    if 'problem_types' in filters:
        conditions.append(has_problem_condition(filters['problem_types'], filters.get('problem_priorities')))

    if 'osm_group_types' in filters:
        conditions.append(StopsMatched.osm_node_id.in_(_osm_group_members(filters['osm_group_types'])))

    if 'way' in (filters.get('osm_entity_types') or []):
        conditions.append(StopsMatched.osm_node_id.like('way_%'))

    if filters.get('osm_operators'):
        conditions.append(StopsMatched.osm_node_details.has(OsmNode.osm_operator.in_(filters['osm_operators'])))

    if filters.get('missing_osm_operator_wikidata'):
        conditions.append(StopsMatched.osm_node_details.has(db.or_(
            OsmNode.osm_operator_wikidata.is_(None),
            OsmNode.osm_operator_wikidata == '',
        )))

    if filters.get('osm_operator_wikidata'):
        conditions.append(StopsMatched.osm_node_details.has(
            OsmNode.osm_operator_wikidata.in_(filters['osm_operator_wikidata'])))

    conditions = [condition for condition in conditions if condition is not None]
    return query.filter(db.and_(*conditions)) if conditions else query
