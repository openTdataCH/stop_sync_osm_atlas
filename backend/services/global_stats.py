"""The map summary: ATLAS stops, OSM stop units and matches among the rows the map's filters keep.

See documentation/2.3 Global Stats.md.
"""
from sqlalchemy import case, func

from backend.extensions import db
from backend.models import OsmStopMember, StopsMatched
from backend.queries.helpers import (
    filtered_stops_query,
    parse_top_n,
    resolve_stop_type_match_filters,
    top_distance_matches,
)


def _build_scoped_global_stats_query(args):
    query = filtered_stops_query(args)
    # Disused OSM elements are not stops: count them only when asked for.
    if not resolve_stop_type_match_filters(args.get('stop_filter'), args.get('match_method'))['include_osm_disused']:
        query = query.filter(StopsMatched.stop_type != 'osm_disused')
    top_n = parse_top_n(args)
    return top_distance_matches(query, top_n) if top_n else query


def _build_effective_stop_type():
    return case(
        (
            db.or_(StopsMatched.stop_type == 'matched', StopsMatched.stop_type == 'effectively_matched'),
            'matched',
        ),
        else_=StopsMatched.stop_type,
    ).label('effective_stop_type')


def compute_global_stats_payload(args) -> dict:
    """The summary numbers for the filters in ``args``, in one query."""
    query = _build_scoped_global_stats_query(args)
    effective_stop_type = _build_effective_stop_type()

    filtered = query.with_entities(
        StopsMatched.sloid.label('sloid'),
        StopsMatched.osm_node_id.label('osm_node_id'),
        effective_stop_type,
    ).subquery('f')

    res = db.session.query(
        func.count(func.distinct(filtered.c.sloid)).label('total_atlas'),
        func.count(
            func.distinct(
                case((filtered.c.effective_stop_type == 'matched', filtered.c.sloid), else_=None)
            )
        ).label('matched_atlas'),
        func.count(
            func.distinct(
                case((filtered.c.effective_stop_type == 'atlas_unmatched', filtered.c.sloid), else_=None)
            )
        ).label('unmatched_atlas'),
        func.count(case((filtered.c.effective_stop_type == 'matched', 1), else_=None)).label('matched_pairs'),
        func.count(func.distinct(OsmStopMember.osm_stop_id)).label('total_osm_stops'),
        func.count(
            func.distinct(
                case(
                    (filtered.c.effective_stop_type == 'matched', OsmStopMember.osm_stop_id),
                    else_=None,
                )
            )
        ).label('matched_osm_stops'),
        func.count(func.distinct(filtered.c.osm_node_id)).label('total_osm_nodes'),
    ).outerjoin(
        OsmStopMember,
        OsmStopMember.node_id == filtered.c.osm_node_id,
    ).one()

    unmatched_osm_stops = max(0, (res.total_osm_stops or 0) - (res.matched_osm_stops or 0))
    return {
        'total_atlas_stops': res.total_atlas,
        'matched_atlas_stops': res.matched_atlas,
        'total_osm_stops': res.total_osm_stops,
        'matched_osm_stops': res.matched_osm_stops,
        'total_osm_nodes': res.total_osm_nodes,
        'matched_osm_nodes': int(res.matched_pairs or 0),
        'matched_pairs_count': int(res.matched_pairs or 0),
        'unmatched_entities_count': (res.unmatched_atlas or 0) + unmatched_osm_stops,
    }
