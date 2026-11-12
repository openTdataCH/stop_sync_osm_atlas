"""The Problems page's list and type counts. See documentation/2.4 Problems page.md."""
from collections import defaultdict
from types import SimpleNamespace

from flask import Blueprint, request, jsonify, current_app as app
from sqlalchemy import and_, or_
from sqlalchemy.orm import joinedload
from sqlalchemy.sql import func

from backend.extensions import db, limiter
from backend.models import AtlasStop, Problem, StopsMatched
from backend.serializers.stops import format_stop_data
from backend.services.problem_filters import (
    VISIBLE_PROBLEM_TYPES,
    area_condition,
    csv_values,
    parse_area,
    parse_priorities,
    parse_problem_types,
    problem_conditions,
)
from backend.services.transport_routes import get_gtfs_routes_for_sloids, get_osm_routes_for_nodes
from backend.services.validators import validate_pagination

problems_bp = Blueprint('problems', __name__)

# Duplicates of one side form groups: OSM-side duplicates are P3, ATLAS-side duplicates P2.
DUPLICATE_GROUP_PRIORITY = {'osm': 3, 'atlas': 2}


def parse_problem_filters(args):
    """The list filters of a request: problem types, priorities, ATLAS operators and area.

    Raises ValueError for a malformed bbox.
    """
    return {
        'problem_types': parse_problem_types(args.get('problem_type')),
        'priorities': parse_priorities(args.get('priority')),
        'atlas_operators': csv_values(args.get('atlas_operator')),
        'area': parse_area(args.get('bbox')),
    }


def filtered_problems(filters, *entities):
    """``entities`` of the problems that pass ``filters``, joined to their stop."""
    query = db.session.query(*entities).join(StopsMatched).filter(
        *problem_conditions(filters['problem_types'], filters['priorities']))
    if filters['atlas_operators']:
        query = query.filter(StopsMatched.atlas_stop_details.has(
            AtlasStop.atlas_business_org_abbr.in_(filters['atlas_operators'])))
    if filters['area']:
        query = query.filter(area_condition(filters['area']))
    return query


def parse_problem_focus(args):
    """The stop a permalink names: {'sloid', 'osm_node_id'}, or None.

    Both identifiers name one matched pair; either alone names every entry of
    that stop. Values use the stored form ("way_<id>" for OSM ways).
    """
    focus = {
        'sloid': (args.get('focus_sloid') or '').strip()[:255] or None,
        'osm_node_id': (args.get('focus_osm_node_id') or '').strip()[:255] or None,
    }
    return focus if focus['sloid'] or focus['osm_node_id'] else None


def matches_problem_focus(row, focus):
    """Whether a serialized stop row (problem or duplicate member) is the focus."""
    return all(
        not focus[key] or str(row.get(key) or '') == focus[key]
        for key in ('sloid', 'osm_node_id')
    )


def locate_focus_page(ranked_stops, focus, limit):
    """The page holding the focus stop's first entry, or None when it has none.

    ``ranked_stops`` has one row per stop: (stop_id, rank_priority), listed by
    rank_priority and then stop_id.
    """
    ranked = ranked_stops.subquery()
    target = (
        db.session.query(ranked.c.stop_id, ranked.c.rank_priority)
        .join(StopsMatched, StopsMatched.id == ranked.c.stop_id)
        .filter(*[getattr(StopsMatched, key) == value for key, value in focus.items() if value])
        .order_by(ranked.c.rank_priority, ranked.c.stop_id)
        .first()
    )
    if target is None:
        return None
    position = db.session.query(func.count()).select_from(ranked).filter(or_(
        ranked.c.rank_priority < target.rank_priority,
        and_(ranked.c.rank_priority == target.rank_priority, ranked.c.stop_id < target.stop_id),
    )).scalar()
    return position // limit + 1


def problem_formatter(problems, include_routes):
    """A function that serializes one of ``problems`` with its stop; routes are looked up once for all."""
    gtfs_routes, osm_routes = {}, {}
    if include_routes:
        gtfs_routes = get_gtfs_routes_for_sloids({problem.stop.sloid for problem in problems if problem.stop.sloid})
        osm_routes = get_osm_routes_for_nodes({problem.stop.osm_node_id for problem in problems if problem.stop.osm_node_id})

    def format_problem(problem):
        row = format_stop_data(
            problem.stop,
            problem_type=problem.problem_type,
            include_routes=include_routes,
            gtfs_routes=gtfs_routes.get(str(problem.stop.sloid), []),
            osm_routes=osm_routes.get(str(problem.stop.osm_node_id), []),
            # The identifier problem explains the element's own identifier tags.
            include_osm_tags=problem.problem_type == 'identifier',
        )
        row.update(priority=problem.priority, stop_id=problem.stop_id)
        return row

    return format_problem


def unlisted_group_members(problems):
    """The members of the ATLAS duplicate groups of ``problems`` that none of ``problems`` is about.

    The engine reports a duplicate on some members of its group only: not on a member matched by propagation, and as
    the OSM duplicate when the matched OSM element is one too (E4.1). A group lists every member all the same, so each
    missing one comes as a problem-like row with its stop and no priority. A SLOID with several pairs comes once.
    """
    listed = {str(problem.stop.sloid) for problem in problems if problem.stop.sloid}
    wanted = {
        str(sloid)
        for problem in problems if problem.stop.atlas_stop_details
        for sloid in problem.stop.atlas_stop_details.duplicate_group_sloids or ()
    } - listed
    if not wanted:
        return []
    stops = StopsMatched.query.options(
        joinedload(StopsMatched.atlas_stop_details), joinedload(StopsMatched.osm_node_details),
    ).filter(StopsMatched.sloid.in_(wanted)).order_by(StopsMatched.id).all()
    members = {}
    for stop in stops:
        members.setdefault(stop.sloid, SimpleNamespace(stop=stop, problem_type='duplicates', priority=None, stop_id=stop.id))
    return list(members.values())


def duplicate_groups(problems, format_problem):
    """The duplicate problems as groups of at least two stops, in priority order.

    An OSM group holds the OSM-side duplicates (P3) with one UIC reference and one local_ref (compared without case).
    An ATLAS group is a duplicate group of the engine (``duplicate_group_sloids``), formed when any member carries a
    duplicates problem, P2 or P3; ``problems`` also holds its other members (``unlisted_group_members``). Its priority
    is P2, an ATLAS duplicate, whatever its members carry.
    """
    members_by_group = defaultdict(dict)
    for problem in problems:
        stop = problem.stop
        atlas, osm = stop.atlas_stop_details, stop.osm_node_details
        if problem.priority == DUPLICATE_GROUP_PRIORITY['osm'] and stop.osm_node_id and osm and osm.osm_local_ref:
            uic_ref = (atlas.uic_ref if atlas else None) or osm.osm_uic_ref or ''
            members_by_group['osm', str(uic_ref), str(osm.osm_local_ref).lower()][stop.osm_node_id] = problem
        if stop.sloid and atlas and atlas.duplicate_group_sloids:
            # The first row of a SLOID stays: a stop matched to a PTv2 pair has two rows with the same problem.
            members_by_group['atlas', tuple(sorted(atlas.duplicate_group_sloids))].setdefault(str(stop.sloid), problem)

    groups = []
    for key, members in members_by_group.items():
        if len(members) < 2:
            continue
        side = key[0]
        if side == 'osm':
            uic_ref, name = key[1], key[2]
        else:
            atlas = next(iter(members.values())).stop.atlas_stop_details
            uic_ref, name = str(atlas.uic_ref or ''), str(atlas.atlas_designation or '').strip().lower()
        stops = [problem.stop for problem in members.values()]
        points = [(getattr(stop, f'{side}_lat'), getattr(stop, f'{side}_lon')) for stop in stops]
        points = [(float(lat), float(lon)) for lat, lon in points if lat is not None and lon is not None]
        center_lat = sum(lat for lat, _ in points) / len(points) if points else None
        center_lon = sum(lon for _, lon in points) / len(points) if points else None
        group = {
            'id': f'dup_{side}_{uic_ref}_{name}',
            'problem': 'duplicates',
            'group_type': side,
            'uic_ref': uic_ref or None,
            'atlas_lat': center_lat,
            'atlas_lon': center_lon,
            'osm_lat': center_lat,
            'osm_lon': center_lon,
            'members': [format_problem(problem) for problem in members.values()],
            'priority': DUPLICATE_GROUP_PRIORITY[side],
        }
        if side == 'osm':
            group['osm_local_ref'] = name or None
        else:
            group.update(sloid=min(members), atlas_designation=name or None)
        groups.append(group)
    return sorted(groups, key=lambda group: (
        group['priority'],
        str(group['uic_ref'] or group.get('sloid') or ''),
        str(group.get('osm_local_ref') or group.get('atlas_designation') or ''),
    ))


@problems_bp.route('/api/problems', methods=['GET'])
@limiter.limit("120/minute")
def get_problems():
    """One page of problems in priority order: the stops with a P1 problem first, then P2, then P3."""
    try:
        try:
            page, limit = validate_pagination(request.args.get('page', 1), request.args.get('limit', 100), max_limit=1000)
            filters = parse_problem_filters(request.args)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        include_routes = str(request.args.get('include_routes', '0')).strip().lower() in ('1', 'true', 'yes', 'on')
        # A permalink's stop: serve the page that holds its first entry
        # instead of the requested page.
        focus = parse_problem_focus(request.args)
        focus_response = {}
        eager_stop = (
            joinedload(Problem.stop).subqueryload(StopsMatched.atlas_stop_details),
            joinedload(Problem.stop).subqueryload(StopsMatched.osm_node_details),
        )

        if filters['problem_types'] == ['duplicates']:
            # The priority filter applies to the groups: an ATLAS group is P2 even when its members carry P3.
            duplicate_problems = filtered_problems({**filters, 'priorities': []}, Problem).options(*eager_stop).all()
            rows = duplicate_problems + unlisted_group_members(duplicate_problems)
            groups = duplicate_groups(rows, problem_formatter(rows, include_routes))
            if filters['priorities']:
                groups = [group for group in groups if group['priority'] in filters['priorities']]
            if focus is not None:
                focus_index = next((
                    index for index, group in enumerate(groups)
                    if any(matches_problem_focus(member, focus) for member in group['members'])
                ), None)
                focus_response['focus_found'] = focus_index is not None
                if focus_index is not None:
                    page = focus_index // limit + 1
            offset = (page - 1) * limit
            return jsonify({
                'problems': groups[offset:offset + limit],
                # Entries are groups here; problem_count counts the duplicate problems, as the type counts do.
                'total': len(groups),
                'problem_count': filtered_problems(filters, func.count(Problem.id)).scalar(),
                'page': page,
                'limit': limit,
                **focus_response
            })

        # One row per stop with its most urgent problem; the list's order.
        rank_priority = func.coalesce(func.min(Problem.priority), 999)
        ranked_stops = filtered_problems(
            filters, Problem.stop_id.label('stop_id'), rank_priority.label('rank_priority'),
        ).group_by(Problem.stop_id)
        total_stops = db.session.query(func.count()).select_from(ranked_stops.subquery()).scalar()
        if focus is not None:
            focus_page = locate_focus_page(ranked_stops, focus, limit)
            focus_response['focus_found'] = focus_page is not None
            if focus_page is not None:
                page = focus_page
        paged_stop_ids = [row.stop_id for row in ranked_stops.order_by(rank_priority, Problem.stop_id)
                          .offset((page - 1) * limit).limit(limit)]
        page_problems = Problem.query.options(*eager_stop).filter(
            Problem.stop_id.in_(paged_stop_ids),
            *problem_conditions(filters['problem_types'], filters['priorities']),
        ).order_by(func.coalesce(Problem.priority, 999), Problem.stop_id, Problem.problem_type).all()
        format_problem = problem_formatter(page_problems, include_routes)
        return jsonify({
            "problems": [format_problem(problem) for problem in page_problems],
            # An entry is one stop with all its problems: total counts entries, problem_count problems.
            "total": total_stops,
            "problem_count": filtered_problems(filters, func.count(Problem.id)).scalar(),
            "page": page,
            "limit": limit,
            **focus_response
        })
    except Exception as e:
        app.logger.exception(f"Error fetching problems: {str(e)}")
        return jsonify({"error": str(e)}), 500


@problems_bp.route('/api/problems/stats', methods=['GET'])
@limiter.limit("120/minute")
def get_problem_stats():
    """The number of problems of each type, and of all types, under the priority, operator and area filters."""
    try:
        try:
            filters = {**parse_problem_filters(request.args), 'problem_types': []}
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        counts = dict(
            filtered_problems(filters, Problem.problem_type, func.count(Problem.id))
            .group_by(Problem.problem_type).all()
        )
        stats = {problem_type: {'all': counts.get(problem_type, 0)} for problem_type in VISIBLE_PROBLEM_TYPES}
        stats['all'] = {'all': sum(counts.values())}
        return jsonify(stats)
    except Exception as e:
        app.logger.error(f"Error fetching problem stats: {str(e)}")
        return jsonify({"error": str(e)}), 500
