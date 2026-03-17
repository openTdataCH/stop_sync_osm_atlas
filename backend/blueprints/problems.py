from flask import Blueprint, request, jsonify, current_app as app
from sqlalchemy.orm import joinedload, subqueryload
from backend.models import StopsMatched, AtlasStop, OsmNode, Problem
from backend.extensions import db, limiter
from backend.serializers.stops import format_stop_data
from sqlalchemy.sql import func

problems_bp = Blueprint('problems', __name__)


def parse_csv_values(raw_value):
    if not raw_value:
        return []
    return [item.strip() for item in str(raw_value).split(',') if item.strip()]


def map_problem_type(problem_type):
    return 'unmatched' if problem_type == 'isolated' else problem_type


def parse_priority_values(raw_priority):
    values = []
    for item in parse_csv_values(raw_priority):
        if item == 'all':
            continue
        try:
            values.append(int(item))
        except ValueError:
            continue
    return values



def apply_atlas_operator_filter(query, atlas_operator_filter):
    if atlas_operator_filter:
        atlas_operators = [op.strip() for op in atlas_operator_filter.split(',') if op.strip()]
        if atlas_operators:
            return query.filter(StopsMatched.atlas_stop_details.has(
                AtlasStop.atlas_business_org_abbr.in_(atlas_operators)
            ))
    return query


@problems_bp.route('/api/problems', methods=['GET'])
@limiter.limit("120/minute")
def get_problems():
    try:
        from backend.services.validators import validate_pagination
        try:
            page, limit = validate_pagination(
                request.args.get('page', 1),
                request.args.get('limit', 100),
                max_limit=1000
            )
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        offset = (page - 1) * limit
        
        
        problem_type_filter = request.args.get('problem_type', 'all')
        atlas_operator_filter = request.args.get('atlas_operator', None)
        sort_by = request.args.get('sort_by', 'default')
        sort_order = request.args.get('sort_order', 'asc')
        priority_filter = request.args.get('priority', None)

        selected_problem_types = []
        if problem_type_filter and problem_type_filter != 'all':
            selected_problem_types = [map_problem_type(t) for t in parse_csv_values(problem_type_filter)]

        selected_priorities = parse_priority_values(priority_filter)

        query = Problem.query.join(StopsMatched)
        if selected_problem_types:
            query = query.filter(Problem.problem_type.in_(selected_problem_types))
        query = apply_atlas_operator_filter(query, atlas_operator_filter)
        if selected_priorities:
            query = query.filter(Problem.priority.in_(selected_priorities))

        duplicates_only_mode = len(selected_problem_types) == 1 and selected_problem_types[0] == 'duplicates'

        if duplicates_only_mode:
            dup_query = Problem.query.join(StopsMatched).filter(Problem.problem_type == 'duplicates')
            dup_query = apply_atlas_operator_filter(dup_query, atlas_operator_filter)
            if selected_priorities:
                dup_query = dup_query.filter(Problem.priority.in_(selected_priorities))
            dup_query = dup_query.options(
                joinedload(Problem.stop).subqueryload(StopsMatched.atlas_stop_details),
                joinedload(Problem.stop).subqueryload(StopsMatched.osm_node_details)
            )
            duplicate_problems = dup_query.all()
            from collections import defaultdict
            osm_groups = defaultdict(list)
            atlas_groups = defaultdict(list)
            for pr in duplicate_problems:
                st = pr.stop
                if st is None:
                    continue
                # OSM-side grouping: (uic_ref, local_ref)
                osm_details = st.osm_node_details
                # Keep OSM groups side-pure: include only OSM-side duplicates (priority == 3)
                try:
                    prio_val = int(pr.priority) if pr.priority is not None else None
                except Exception:
                    prio_val = None
                if st.osm_node_id and osm_details and osm_details.osm_local_ref and prio_val == 3:
                    key = (str((st.atlas_stop_details.uic_ref if st.atlas_stop_details else None) or osm_details.osm_uic_ref or ''), str(osm_details.osm_local_ref or '').lower())
                    osm_groups[key].append(pr)
                # ATLAS-side grouping: (uic_ref, designation)
                atlas_details = st.atlas_stop_details
                # Keep ATLAS groups side-pure: include only ATLAS-side duplicates (priority == 2)
                if getattr(st, 'sloid', None) and atlas_details and getattr(atlas_details, 'atlas_designation', None) and prio_val == 2:
                    atlas_key = (str((atlas_details.uic_ref if atlas_details else None) or ''), str(atlas_details.atlas_designation or '').strip().lower())
                    atlas_groups[atlas_key].append(pr)
            def build_osm_group_payload(key, problems_list):
                members = {}
                for pr in problems_list:
                    st = pr.stop
                    if st and st.osm_node_id:
                        members[st.osm_node_id] = pr
                if len(members) < 2:
                    return None
                uic_ref, local_ref = key
                member_payloads = []
                centroid_lat = []
                centroid_lon = []
                priorities = []
                for pr in members.values():
                    st = pr.stop
                    formatted = format_stop_data(st, problem_type='duplicates')
                    formatted.update({
                        'priority': pr.priority,
                        'solution': '',
                        'is_persistent': False,
                        'stop_id': st.id
                    })
                    member_payloads.append(formatted)
                    if st.osm_lat is not None and st.osm_lon is not None:
                        centroid_lat.append(float(st.osm_lat))
                        centroid_lon.append(float(st.osm_lon))
                    # Track valid member priorities
                    try:
                        if pr.priority is not None:
                            priorities.append(int(pr.priority))
                    except Exception:
                        pass
                center_lat = sum(centroid_lat)/len(centroid_lat) if centroid_lat else None
                center_lon = sum(centroid_lon)/len(centroid_lon) if centroid_lon else None
                group_id = f"dup_osm_{uic_ref}_{local_ref}"
                # Derive a group-level priority from members (lower means higher priority)
                group_priority = min(priorities) if priorities else 3
                return {
                    'id': group_id,
                    'problem': 'duplicates',
                    'group_type': 'osm',
                    'uic_ref': uic_ref or None,
                    'osm_local_ref': local_ref or None,
                    'atlas_lat': center_lat,
                    'atlas_lon': center_lon,
                    'osm_lat': center_lat,
                    'osm_lon': center_lon,
                    'members': member_payloads,
                    'priority': group_priority
                }
            group_items = []
            for key, pr_list in osm_groups.items():
                payload = build_osm_group_payload(key, pr_list)
                if payload:
                    group_items.append(payload)
            def build_atlas_group_payload(key, problems_list):
                members = {}
                for pr in problems_list:
                    st = pr.stop
                    if st and getattr(st, 'sloid', None):
                        members[str(st.sloid)] = pr
                if len(members) < 2:
                    return None
                uic_ref, designation_norm = key
                member_payloads = []
                centroid_lat = []
                centroid_lon = []
                priorities = []
                for pr in members.values():
                    st = pr.stop
                    formatted = format_stop_data(st, problem_type='duplicates')
                    formatted.update({
                        'priority': pr.priority,
                        'solution': '',
                        'is_persistent': False,
                        'stop_id': st.id
                    })
                    member_payloads.append(formatted)
                    if st.atlas_lat is not None and st.atlas_lon is not None:
                        centroid_lat.append(float(st.atlas_lat))
                        centroid_lon.append(float(st.atlas_lon))
                    # Track valid member priorities
                    try:
                        if pr.priority is not None:
                            priorities.append(int(pr.priority))
                    except Exception:
                        pass
                center_lat = sum(centroid_lat)/len(centroid_lat) if centroid_lat else None
                center_lon = sum(centroid_lon)/len(centroid_lon) if centroid_lon else None
                # Choose a representative sloid for display/sorting
                rep_sloid = sorted(members.keys())[0] if members else None
                group_id = f"dup_atlas_{uic_ref}_{designation_norm}"
                # Derive a group-level priority from members (lower means higher priority)
                group_priority = min(priorities) if priorities else 2
                return {
                    'id': group_id,
                    'problem': 'duplicates',
                    'group_type': 'atlas',
                    'sloid': rep_sloid,
                    'uic_ref': uic_ref or None,
                    'atlas_designation': designation_norm or None,
                    'atlas_lat': center_lat,
                    'atlas_lon': center_lon,
                    'osm_lat': center_lat,
                    'osm_lon': center_lon,
                    'members': member_payloads,
                    'priority': group_priority
                }
            for key, pr_list in atlas_groups.items():
                payload = build_atlas_group_payload(key, pr_list)
                if payload:
                    group_items.append(payload)
            group_items.sort(key=lambda g: (
                0 if g.get('group_type') == 'osm' else 1,
                str(g.get('uic_ref') or g.get('sloid') or ''),
                str(g.get('osm_local_ref') or '')
            ))
            total_groups = len(group_items)
            paged_groups = group_items[offset:offset+limit]
            return jsonify({
                'problems': paged_groups,
                'total': total_groups,
                'page': page,
                'limit': limit,
                'sort_by': 'default',
                'sort_order': 'asc'
            })
        distinct_stop_ids_subquery = query.with_entities(Problem.stop_id).distinct().subquery()
        total_problems = db.session.query(func.count()).select_from(distinct_stop_ids_subquery).scalar()
        distance_only_mode = len(selected_problem_types) == 1 and selected_problem_types[0] == 'distance'

        if sort_by == 'distance' and distance_only_mode:
            if sort_order == 'desc':
                query = query.order_by(func.coalesce(StopsMatched.distance_m, -1).desc(), Problem.stop_id, Problem.problem_type)
            else:
                query = query.order_by(func.coalesce(StopsMatched.distance_m, 1000000000000).asc(), Problem.stop_id, Problem.problem_type)
        elif sort_by == 'priority':
            if sort_order == 'desc':
                query = query.order_by(func.coalesce(Problem.priority, 999).desc(), Problem.stop_id, Problem.problem_type)
            else:
                query = query.order_by(func.coalesce(Problem.priority, 999).asc(), Problem.stop_id, Problem.problem_type)
        else:
            query = query.order_by(Problem.stop_id, Problem.problem_type)
        if sort_by == 'distance' and distance_only_mode:
            stop_distance_query = db.session.query(StopsMatched.id, StopsMatched.distance_m).join(Problem).filter(
                Problem.problem_type.in_(selected_problem_types) if selected_problem_types else True
            )
            stop_distance_query = apply_atlas_operator_filter(stop_distance_query, atlas_operator_filter)
            if selected_priorities:
                stop_distance_query = stop_distance_query.filter(Problem.priority.in_(selected_priorities))
            if sort_order == 'desc':
                stop_distance_query = stop_distance_query.distinct().order_by(func.coalesce(StopsMatched.distance_m, -1).desc(), StopsMatched.id)
            else:
                stop_distance_query = stop_distance_query.distinct().order_by(func.coalesce(StopsMatched.distance_m, 1000000000000).asc(), StopsMatched.id)
            paged_stops = stop_distance_query.offset(offset).limit(limit).all()
            paged_stop_ids = [stop[0] for stop in paged_stops]
        elif sort_by == 'priority':
            stop_ids_query = db.session.query(Problem.stop_id, func.min(Problem.priority)).join(StopsMatched)
            if selected_problem_types:
                stop_ids_query = stop_ids_query.filter(Problem.problem_type.in_(selected_problem_types))
                stop_ids_query = apply_atlas_operator_filter(stop_ids_query, atlas_operator_filter)
            if selected_priorities:
                stop_ids_query = stop_ids_query.filter(Problem.priority.in_(selected_priorities))
            stop_ids_query = stop_ids_query.group_by(Problem.stop_id)
            if sort_order == 'desc':
                stop_ids_query = stop_ids_query.order_by(func.coalesce(func.min(Problem.priority), 999).desc(), Problem.stop_id)
            else:
                stop_ids_query = stop_ids_query.order_by(func.coalesce(func.min(Problem.priority), 999).asc(), Problem.stop_id)
            paged_stops = stop_ids_query.offset(offset).limit(limit).all()
            paged_stop_ids = [row[0] for row in paged_stops]
        else:
            stop_ids_query = db.session.query(Problem.stop_id).join(StopsMatched)
            if selected_problem_types:
                stop_ids_query = stop_ids_query.filter(Problem.problem_type.in_(selected_problem_types))
                stop_ids_query = apply_atlas_operator_filter(stop_ids_query, atlas_operator_filter)
            if selected_priorities:
                stop_ids_query = stop_ids_query.filter(Problem.priority.in_(selected_priorities))
            paged_stop_ids = [item[0] for item in stop_ids_query.distinct().order_by(Problem.stop_id).offset(offset).limit(limit).all()]
        if not paged_stop_ids:
            final_problems = []
        else:
            final_query = Problem.query.options(
                joinedload(Problem.stop).subqueryload(StopsMatched.atlas_stop_details),
                joinedload(Problem.stop).subqueryload(StopsMatched.osm_node_details)
            ).filter(Problem.stop_id.in_(paged_stop_ids))
            if selected_problem_types:
                final_query = final_query.filter(Problem.problem_type.in_(selected_problem_types))
                final_query = apply_atlas_operator_filter(final_query, atlas_operator_filter)
            if selected_priorities:
                final_query = final_query.filter(Problem.priority.in_(selected_priorities))
            if sort_by == 'distance' and distance_only_mode:
                if sort_order == 'desc':
                    final_query = final_query.join(StopsMatched).order_by(func.coalesce(StopsMatched.distance_m, -1).desc(), Problem.stop_id, Problem.problem_type)
                else:
                    final_query = final_query.join(StopsMatched).order_by(func.coalesce(StopsMatched.distance_m, 1000000000000).asc(), Problem.stop_id, Problem.problem_type)
            elif sort_by == 'priority':
                if sort_order == 'desc':
                    final_query = final_query.order_by(func.coalesce(Problem.priority, 999).desc(), Problem.stop_id, Problem.problem_type)
                else:
                    final_query = final_query.order_by(func.coalesce(Problem.priority, 999).asc(), Problem.stop_id, Problem.problem_type)
            else:
                final_query = final_query.order_by(Problem.stop_id, Problem.problem_type)
            final_problems = final_query.all()
        problems = []
        for problem in final_problems:
            formatted_stop = format_stop_data(problem.stop, problem_type=problem.problem_type)
            st = problem.stop
            formatted_stop['priority'] = problem.priority
            formatted_stop['solution'] = ''
            formatted_stop['is_persistent'] = False
            formatted_stop['stop_id'] = problem.stop_id
            problems.append(formatted_stop)
        return jsonify({
            "problems": problems,
            "total": total_problems,
            "page": page,
            "limit": limit,
            "sort_by": sort_by,
            "sort_order": sort_order
        })
    except Exception as e:
        app.logger.error(f"Error fetching problems: {str(e)}")
        import traceback
        app.logger.error(traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@problems_bp.route('/api/problems/stats', methods=['GET'])
@limiter.limit("120/minute")
def get_problem_stats():
    try:
        atlas_operator_filter = request.args.get('atlas_operator', None)
        stats = {
            'all': {'all': 0, 'solved': 0, 'unsolved': 0},
            'distance': {'all': 0, 'solved': 0, 'unsolved': 0},
            'unmatched': {'all': 0, 'solved': 0, 'unsolved': 0},
            'attributes': {'all': 0, 'solved': 0, 'unsolved': 0},
            'duplicates': {'all': 0, 'solved': 0, 'unsolved': 0}
        }
        selected_priorities = parse_priority_values(request.args.get('priority'))

        problem_types = ['distance', 'unmatched', 'attributes', 'duplicates']
        for ptype in problem_types:
            q = Problem.query.join(StopsMatched).filter(Problem.problem_type == ptype)
            q = apply_atlas_operator_filter(q, atlas_operator_filter)
            if selected_priorities:
                q = q.filter(Problem.priority.in_(selected_priorities))
            count = q.with_entities(Problem.stop_id).distinct().count()
            stats[ptype]['all'] = count
            stats[ptype]['unsolved'] = count

        stats['all']['all'] = sum(s['all'] for s in stats.values() if s is not stats['all'])
        stats['all']['unsolved'] = stats['all']['all']

        return jsonify(stats)
    except Exception as e:
        app.logger.error(f"Error fetching problem stats: {str(e)}")
        return jsonify({"error": str(e)}), 500
