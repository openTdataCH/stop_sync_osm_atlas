from flask import Blueprint, request, jsonify, current_app as app
from flask_login import current_user, login_required
from sqlalchemy.orm import joinedload, subqueryload
from backend.models import Stop, AtlasStop, OsmNode, Problem, PersistentData
from backend.extensions import db, limiter
from functools import wraps
from backend.serializers.stops import format_stop_data
from sqlalchemy.sql import func
from sqlalchemy import and_

problems_bp = Blueprint('problems', __name__)


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or not getattr(current_user, 'is_admin', False):
            return jsonify({"success": False, "error": "Admin privileges required"}), 403
        return fn(*args, **kwargs)
    return wrapper


def apply_atlas_operator_filter(query, atlas_operator_filter):
    if atlas_operator_filter:
        atlas_operators = [op.strip() for op in atlas_operator_filter.split(',') if op.strip()]
        if atlas_operators:
            return query.filter(Stop.atlas_stop_details.has(
                AtlasStop.atlas_business_org_abbr.in_(atlas_operators)
            ))
    return query


@problems_bp.route('/api/problems', methods=['GET'])
@limiter.limit("120/minute")
def get_problems():
    try:
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 100))
        offset = (page - 1) * limit
        problem_type_filter = request.args.get('problem_type', 'all')
        solution_status_filter = request.args.get('solution_status', 'all')
        atlas_operator_filter = request.args.get('atlas_operator', None)
        sort_by = request.args.get('sort_by', 'default')
        sort_order = request.args.get('sort_order', 'asc')
        priority_filter = request.args.get('priority', None)
        query = Problem.query.join(Stop)
        if problem_type_filter != 'all':
            query = query.filter(Problem.problem_type == problem_type_filter)
        if solution_status_filter == 'solved':
            query = query.filter(Problem.solution.isnot(None) & (Problem.solution != ''))
        elif solution_status_filter == 'unsolved':
            query = query.filter(Problem.solution.is_(None) | (Problem.solution == ''))
        query = apply_atlas_operator_filter(query, atlas_operator_filter)
        if priority_filter and priority_filter != 'all':
            try:
                priority_value = int(priority_filter)
                query = query.filter(Problem.priority == priority_value)
            except ValueError:
                pass

        if problem_type_filter == 'duplicates':
            dup_query = Problem.query.join(Stop).filter(Problem.problem_type == 'duplicates')
            dup_query = apply_atlas_operator_filter(dup_query, atlas_operator_filter)
            dup_query = dup_query.options(
                joinedload(Problem.stop).subqueryload(Stop.atlas_stop_details),
                joinedload(Problem.stop).subqueryload(Stop.osm_node_details)
            )
            duplicate_problems = dup_query.all()
            from collections import defaultdict
            osm_groups = defaultdict(list)
            atlas_groups = defaultdict(list)
            for pr in duplicate_problems:
                st = pr.stop
                if st is None:
                    continue
                osm_details = st.osm_node_details
                atlas_details = st.atlas_stop_details
                if st.osm_node_id and osm_details and osm_details.osm_local_ref:
                    key = (str(st.uic_ref or ''), str(osm_details.osm_local_ref or '').lower())
                    osm_groups[key].append(pr)
                if st.sloid and atlas_details and (atlas_details.atlas_designation is not None):
                    key_atlas = (str(st.uic_ref or ''), str(atlas_details.atlas_designation or '').strip().lower())
                    atlas_groups[key_atlas].append(pr)
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
                for pr in members.values():
                    st = pr.stop
                    formatted = format_stop_data(st, problem_type='duplicates')
                    formatted.update({
                        'priority': pr.priority,
                        'solution': pr.solution or '',
                        'is_persistent': pr.is_persistent,
                        'stop_id': st.id
                    })
                    member_payloads.append(formatted)
                    if st.osm_lat is not None and st.osm_lon is not None:
                        centroid_lat.append(float(st.osm_lat))
                        centroid_lon.append(float(st.osm_lon))
                center_lat = sum(centroid_lat)/len(centroid_lat) if centroid_lat else None
                center_lon = sum(centroid_lon)/len(centroid_lon) if centroid_lon else None
                group_id = f"dup_osm_{uic_ref}_{local_ref}"
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
                    'priority': 3
                }
            def build_atlas_group_payload(key, problems_list):
                members = {}
                for pr in problems_list:
                    st = pr.stop
                    if st and st.id:
                        members[st.id] = pr
                if len(members) < 2:
                    return None
                member_payloads = []
                centroid_lat = []
                centroid_lon = []
                for pr in members.values():
                    st = pr.stop
                    formatted = format_stop_data(st, problem_type='duplicates')
                    formatted.update({
                        'priority': pr.priority,
                        'solution': pr.solution or '',
                        'is_persistent': pr.is_persistent,
                        'stop_id': st.id
                    })
                    member_payloads.append(formatted)
                    if st.atlas_lat is not None and st.atlas_lon is not None:
                        centroid_lat.append(float(st.atlas_lat))
                        centroid_lon.append(float(st.atlas_lon))
                center_lat = sum(centroid_lat)/len(centroid_lat) if centroid_lat else None
                center_lon = sum(centroid_lon)/len(centroid_lon) if centroid_lon else None
                uic_ref, designation = key
                group_id = f"dup_atlas_{uic_ref}_{designation}"
                return {
                    'id': group_id,
                    'problem': 'duplicates',
                    'group_type': 'atlas',
                    'uic_ref': uic_ref or None,
                    'atlas_designation': designation or None,
                    'atlas_lat': center_lat,
                    'atlas_lon': center_lon,
                    'members': member_payloads,
                    'priority': 2
                }
            group_items = []
            for key, pr_list in osm_groups.items():
                payload = build_osm_group_payload(key, pr_list)
                if payload:
                    group_items.append(payload)
            for key, pr_list in atlas_groups.items():
                payload = build_atlas_group_payload(key, pr_list)
                if payload:
                    group_items.append(payload)
            def group_is_solved(item):
                member_solutions = [m.get('solution') for m in item.get('members', [])]
                return all(s and str(s).strip() != '' for s in member_solutions)
            solution_status_filter = request.args.get('solution_status', 'all')
            if solution_status_filter == 'solved':
                group_items = [g for g in group_items if group_is_solved(g)]
            elif solution_status_filter == 'unsolved':
                group_items = [g for g in group_items if not group_is_solved(g)]
            group_items.sort(key=lambda g: (
                0 if g.get('group_type') == 'osm' else 1,
                str(g.get('uic_ref') or ''),
                str(g.get('osm_local_ref') or g.get('atlas_designation') or '')
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
        if sort_by == 'distance' and problem_type_filter == 'distance':
            if sort_order == 'desc':
                query = query.order_by(func.coalesce(Stop.distance_m, -1).desc(), Problem.stop_id, Problem.problem_type)
            else:
                query = query.order_by(func.coalesce(Stop.distance_m, 1000000000000).asc(), Problem.stop_id, Problem.problem_type)
        elif sort_by == 'priority':
            if sort_order == 'desc':
                query = query.order_by(func.coalesce(Problem.priority, 999).desc(), Problem.stop_id, Problem.problem_type)
            else:
                query = query.order_by(func.coalesce(Problem.priority, 999).asc(), Problem.stop_id, Problem.problem_type)
        else:
            query = query.order_by(Problem.stop_id, Problem.problem_type)
        if sort_by == 'distance' and problem_type_filter == 'distance':
            stop_distance_query = db.session.query(Stop.id, Stop.distance_m).join(Problem).filter(
                Problem.problem_type == problem_type_filter if problem_type_filter != 'all' else True
            )
            solution_status_filter = request.args.get('solution_status', 'all')
            if solution_status_filter == 'solved':
                stop_distance_query = stop_distance_query.filter(Problem.solution.isnot(None) & (Problem.solution != ''))
            elif solution_status_filter == 'unsolved':
                stop_distance_query = stop_distance_query.filter(Problem.solution.is_(None) | (Problem.solution == ''))
            stop_distance_query = apply_atlas_operator_filter(stop_distance_query, atlas_operator_filter)
            if priority_filter and priority_filter != 'all':
                try:
                    priority_value = int(priority_filter)
                    stop_distance_query = stop_distance_query.filter(Problem.priority == priority_value)
                except ValueError:
                    pass
            if sort_order == 'desc':
                stop_distance_query = stop_distance_query.distinct().order_by(func.coalesce(Stop.distance_m, -1).desc(), Stop.id)
            else:
                stop_distance_query = stop_distance_query.distinct().order_by(func.coalesce(Stop.distance_m, 1000000000000).asc(), Stop.id)
            paged_stops = stop_distance_query.offset(offset).limit(limit).all()
            paged_stop_ids = [stop[0] for stop in paged_stops]
        elif sort_by == 'priority':
            stop_ids_query = db.session.query(Problem.stop_id, func.min(Problem.priority)).join(Stop)
            if problem_type_filter != 'all':
                stop_ids_query = stop_ids_query.filter(Problem.problem_type == problem_type_filter)
            solution_status_filter = request.args.get('solution_status', 'all')
            if solution_status_filter == 'solved':
                stop_ids_query = stop_ids_query.filter(Problem.solution.isnot(None) & (Problem.solution != ''))
            elif solution_status_filter == 'unsolved':
                stop_ids_query = stop_ids_query.filter(Problem.solution.is_(None) | (Problem.solution == ''))
            stop_ids_query = apply_atlas_operator_filter(stop_ids_query, atlas_operator_filter)
            if priority_filter and priority_filter != 'all':
                try:
                    priority_value = int(priority_filter)
                    stop_ids_query = stop_ids_query.filter(Problem.priority == priority_value)
                except ValueError:
                    pass
            stop_ids_query = stop_ids_query.group_by(Problem.stop_id)
            if sort_order == 'desc':
                stop_ids_query = stop_ids_query.order_by(func.coalesce(func.min(Problem.priority), 999).desc(), Problem.stop_id)
            else:
                stop_ids_query = stop_ids_query.order_by(func.coalesce(func.min(Problem.priority), 999).asc(), Problem.stop_id)
            paged_stops = stop_ids_query.offset(offset).limit(limit).all()
            paged_stop_ids = [row[0] for row in paged_stops]
        else:
            stop_ids_query = db.session.query(Problem.stop_id).join(Stop)
            if problem_type_filter != 'all':
                mapped_type = 'unmatched' if problem_type_filter == 'isolated' else problem_type_filter
                stop_ids_query = stop_ids_query.filter(Problem.problem_type == mapped_type)
            solution_status_filter = request.args.get('solution_status', 'all')
            if solution_status_filter == 'solved':
                stop_ids_query = stop_ids_query.filter(Problem.solution.isnot(None) & (Problem.solution != ''))
            elif solution_status_filter == 'unsolved':
                stop_ids_query = stop_ids_query.filter(Problem.solution.is_(None) | (Problem.solution == ''))
            stop_ids_query = apply_atlas_operator_filter(stop_ids_query, atlas_operator_filter)
            paged_stop_ids = [item[0] for item in stop_ids_query.distinct().order_by(Problem.stop_id).offset(offset).limit(limit).all()]
        if not paged_stop_ids:
            final_problems = []
        else:
            final_query = Problem.query.options(
                joinedload(Problem.stop).subqueryload(Stop.atlas_stop_details),
                joinedload(Problem.stop).subqueryload(Stop.osm_node_details)
            ).filter(Problem.stop_id.in_(paged_stop_ids))
            solution_status_filter = request.args.get('solution_status', 'all')
            if solution_status_filter == 'solved':
                final_query = final_query.filter(Problem.solution.isnot(None) & (Problem.solution != ''))
            elif solution_status_filter == 'unsolved':
                final_query = final_query.filter(Problem.solution.is_(None) | (Problem.solution == ''))
            final_query = apply_atlas_operator_filter(final_query, atlas_operator_filter)
            if priority_filter and priority_filter != 'all':
                try:
                    priority_value = int(priority_filter)
                    final_query = final_query.filter(Problem.priority == priority_value)
                except ValueError:
                    pass
            if sort_by == 'distance' and problem_type_filter == 'distance':
                if sort_order == 'desc':
                    final_query = final_query.join(Stop).order_by(func.coalesce(Stop.distance_m, -1).desc(), Problem.stop_id, Problem.problem_type)
                else:
                    final_query = final_query.join(Stop).order_by(func.coalesce(Stop.distance_m, 1000000000000).asc(), Problem.stop_id, Problem.problem_type)
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
            formatted_stop['priority'] = problem.priority
            formatted_stop['solution'] = problem.solution
            formatted_stop['is_persistent'] = problem.is_persistent
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
        selected_priority = request.args.get('priority')
        problem_types_internal = ['distance', 'unmatched', 'attributes', 'duplicates']
        for p_type in problem_types_internal:
            base_query = db.session.query(func.count(Problem.id)).join(Stop).filter(Problem.problem_type == p_type)
            base_query = apply_atlas_operator_filter(base_query, atlas_operator_filter)
            if selected_priority and selected_priority != 'all':
                try:
                    pr = int(selected_priority)
                    base_query = base_query.filter(Problem.priority == pr)
                except ValueError:
                    pass
            total_count = base_query.scalar()
            key_out = p_type
            stats[key_out]['all'] = total_count
            solved_query = base_query.filter(Problem.solution.isnot(None) & (Problem.solution != ''))
            solved_count = solved_query.scalar()
            stats[key_out]['solved'] = solved_count
            stats[key_out]['unsolved'] = total_count - solved_count
        all_problems_query = db.session.query(func.count(func.distinct(Problem.stop_id))).join(Stop)
        all_problems_query = apply_atlas_operator_filter(all_problems_query, atlas_operator_filter)
        if selected_priority and selected_priority != 'all':
            try:
                pr = int(selected_priority)
                all_problems_query = all_problems_query.filter(Problem.priority == pr)
            except ValueError:
                pass
        stats['all']['all'] = all_problems_query.scalar()
        total_solved = sum(stats[p_type]['solved'] for p_type in ['distance', 'unmatched', 'attributes', 'duplicates'])
        total_unsolved = sum(stats[p_type]['unsolved'] for p_type in ['distance', 'unmatched', 'attributes', 'duplicates'])
        stats['all']['all'] = total_solved + total_unsolved
        stats['all']['solved'] = total_solved
        stats['all']['unsolved'] = total_unsolved
        return jsonify(stats)
    except Exception as e:
        app.logger.error(f"Error getting problem stats: {str(e)}")
        return jsonify({"error": str(e)}), 500


@problems_bp.route('/api/save_solution', methods=['POST'])
@limiter.limit("30/minute")
def save_solution():
    try:
        data = request.get_json()
        problem_id = data.get('problem_id')
        problem_type = data.get('problem_type')
        solution = data.get('solution')
        if not problem_id:
            return jsonify({"success": False, "error": "Missing problem_id parameter"}), 400
        mapped_problem_type = 'unmatched' if problem_type == 'isolated' else problem_type
        if problem_type == 'any':
            problem = Problem.query.filter_by(stop_id=problem_id).first()
            if not problem:
                return jsonify({"success": False, "error": f"No problem found for stop {problem_id}"}), 404
        else:
            if not problem_type:
                return jsonify({"success": False, "error": "Missing problem_type parameter"}), 400
            problem = Problem.query.filter_by(stop_id=problem_id, problem_type=mapped_problem_type).first()
            if not problem:
                 return jsonify({"success": False, "error": f"Problem of type {problem_type} for stop {problem_id} not found"}), 404
        problem.solution = solution
        # Attribute the author if authenticated
        if current_user.is_authenticated:
            problem.created_by_user_id = getattr(current_user, 'id', None)
            problem.created_by_user_email = getattr(current_user, 'email', None)
        problem.is_persistent = False
        db.session.commit()
        return jsonify({"success": True, "message": f"{problem.problem_type.capitalize()} solution saved successfully"})
    except Exception as e:
        app.logger.error(f"Exception in save_solution: {e}")
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


@problems_bp.route('/api/make_solution_persistent', methods=['POST'])
@limiter.limit("30/minute")
@login_required
def make_solution_persistent():
    try:
        data = request.get_json()
        problem_id = data.get('problem_id')
        problem_type = data.get('problem_type')
        if not problem_id or not problem_type:
            return jsonify({"success": False, "error": "Missing required parameters"}), 400
        mapped_problem_type = 'unmatched' if problem_type == 'isolated' else problem_type
        problem = Problem.query.filter_by(stop_id=problem_id, problem_type=mapped_problem_type).first()
        if not problem:
            return jsonify({"success": False, "error": f"Problem of type {problem_type} for stop {problem_id} not found"}), 404
        if not problem.solution:
            return jsonify({"success": False, "error": "Cannot make an empty solution persistent"}), 400
        stop = db.session.get(Stop, problem_id)
        if not stop:
            return jsonify({"success": False, "error": "Stop not found"}), 404
        persistent_solution = PersistentData.query.filter(
            PersistentData.sloid == stop.sloid,
            PersistentData.osm_node_id == stop.osm_node_id,
            PersistentData.problem_type == mapped_problem_type
        ).first()
        if persistent_solution:
            # Authorization: only owner or admin may update existing persistent solution
            is_admin = bool(getattr(current_user, 'is_admin', False))
            is_owner = (persistent_solution.created_by_user_id is not None) and (persistent_solution.created_by_user_id == getattr(current_user, 'id', None))
            if not (is_admin or is_owner):
                return jsonify({"success": False, "error": "Not authorized to update this persistent solution"}), 403
            # Update content but preserve original author attribution
            persistent_solution.solution = problem.solution
            message = "Solution updated in persistent storage"
        else:
            author_user_id = getattr(problem, 'created_by_user_id', None) or (getattr(current_user, 'id', None) if current_user.is_authenticated else None)
            author_email = getattr(problem, 'created_by_user_email', None) or (getattr(current_user, 'email', None) if current_user.is_authenticated else None)
            new_persistent_solution = PersistentData(
                sloid=stop.sloid,
                osm_node_id=stop.osm_node_id,
                problem_type=mapped_problem_type,
                solution=problem.solution,
                created_by_user_id=author_user_id,
                created_by_user_email=author_email
            )
            db.session.add(new_persistent_solution)
            message = "Solution saved to persistent storage"
        problem.is_persistent = True
        db.session.commit()
        return jsonify({"success": True, "message": message, "is_persistent": True})
    except Exception as e:
        app.logger.error(f"Exception in make_solution_persistent: {e}")
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


@problems_bp.route('/api/check_persistent_solution', methods=['GET'])
@limiter.limit("120/minute")
def check_persistent_solution():
    try:
        stop_id = request.args.get('stop_id')
        problem_type = request.args.get('problem_type')
        if not stop_id or not problem_type:
            return jsonify({"success": False, "error": "Missing required parameters"}), 400
        problem = Problem.query.filter_by(stop_id=stop_id, problem_type=problem_type).first()
        if not problem:
            return jsonify({"success": True, "is_persistent": False, "persistent_solution": None})
        is_persistent = problem.is_persistent
        solution = problem.solution if is_persistent else None
        return jsonify({"success": True, "is_persistent": is_persistent, "persistent_solution": solution})
    except Exception as e:
        app.logger.error(f"Exception in check_persistent_solution: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@problems_bp.route('/api/save_note/atlas', methods=['POST'])
@limiter.limit("60/minute")
def save_atlas_note():
    try:
        data = request.get_json()
        sloid = data.get('sloid')
        note = data.get('note', '')
        make_persistent = data.get('make_persistent', False)
        login_required_for_persistence = False
        if not sloid:
            return jsonify({"success": False, "error": "Missing sloid"}), 400
        atlas_stop = AtlasStop.query.filter_by(sloid=sloid).first()
        if not atlas_stop:
            atlas_stop = AtlasStop(sloid=sloid)
            db.session.add(atlas_stop)
        atlas_stop.atlas_note = note
        if current_user.is_authenticated:
            atlas_stop.atlas_note_user_id = getattr(current_user, 'id', None)
            atlas_stop.atlas_note_user_email = getattr(current_user, 'email', None)
        # Anonymous users can save notes but cannot persist
        effective_persist = bool(make_persistent and current_user.is_authenticated)
        if make_persistent and not current_user.is_authenticated:
            login_required_for_persistence = True
        atlas_stop.atlas_note_is_persistent = effective_persist
        if effective_persist:
            persistent_note = PersistentData.query.filter_by(
                sloid=sloid,
                note_type='atlas'
            ).first()
            if persistent_note:
                persistent_note.note = note
                # Persist original note author's identity
                persistent_note.created_by_user_id = getattr(atlas_stop, 'atlas_note_user_id', None)
                persistent_note.created_by_user_email = getattr(atlas_stop, 'atlas_note_user_email', None)
            else:
                new_persistent_note = PersistentData(
                    sloid=sloid,
                    note_type='atlas',
                    note=note,
                    created_by_user_id=getattr(atlas_stop, 'atlas_note_user_id', None),
                    created_by_user_email=getattr(atlas_stop, 'atlas_note_user_email', None)
                )
                db.session.add(new_persistent_note)
        db.session.commit()
        return jsonify({
            "success": True,
            "message": "ATLAS note saved successfully",
            "is_persistent": effective_persist,
            "login_required_for_persistence": login_required_for_persistence
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


@problems_bp.route('/api/save_note/osm', methods=['POST'])
@limiter.limit("60/minute")
def save_osm_note():
    try:
        data = request.get_json()
        osm_node_id = data.get('osm_node_id')
        note = data.get('note', '')
        make_persistent = data.get('make_persistent', False)
        login_required_for_persistence = False
        if not osm_node_id:
            return jsonify({"success": False, "error": "Missing osm_node_id"}), 400
        osm_node = OsmNode.query.filter_by(osm_node_id=osm_node_id).first()
        if not osm_node:
            osm_node = OsmNode(osm_node_id=osm_node_id)
            db.session.add(osm_node)
        osm_node.osm_note = note
        if current_user.is_authenticated:
            osm_node.osm_note_user_id = getattr(current_user, 'id', None)
            osm_node.osm_note_user_email = getattr(current_user, 'email', None)
        # Anonymous users can save notes but cannot persist
        effective_persist = bool(make_persistent and current_user.is_authenticated)
        if make_persistent and not current_user.is_authenticated:
            login_required_for_persistence = True
        osm_node.osm_note_is_persistent = effective_persist
        if effective_persist:
            persistent_note = PersistentData.query.filter_by(
                osm_node_id=osm_node_id,
                note_type='osm'
            ).first()
            if persistent_note:
                persistent_note.note = note
                # Persist original note author's identity
                persistent_note.created_by_user_id = getattr(osm_node, 'osm_note_user_id', None)
                persistent_note.created_by_user_email = getattr(osm_node, 'osm_note_user_email', None)
            else:
                new_persistent_note = PersistentData(
                    osm_node_id=osm_node_id,
                    note_type='osm',
                    note=note,
                    created_by_user_id=getattr(osm_node, 'osm_note_user_id', None),
                    created_by_user_email=getattr(osm_node, 'osm_note_user_email', None)
                )
                db.session.add(new_persistent_note)
        db.session.commit()
        return jsonify({
            "success": True,
            "message": "OSM note saved successfully",
            "is_persistent": effective_persist,
            "login_required_for_persistence": login_required_for_persistence
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


@problems_bp.route('/api/make_note_persistent/<string:note_type>', methods=['POST'])
@limiter.limit("60/minute")
@login_required
def make_note_persistent(note_type: str):
    try:
        data = request.get_json() or {}
        if note_type == 'atlas':
            sloid = (data.get('sloid') or '').strip()
            if not sloid:
                return jsonify({"success": False, "error": "Missing sloid"}), 400
            atlas_stop = AtlasStop.query.filter_by(sloid=sloid).first()
            if not atlas_stop or not atlas_stop.atlas_note:
                return jsonify({"success": False, "error": "No existing note to persist"}), 400
            persistent_note = PersistentData.query.filter_by(sloid=sloid, note_type='atlas').first()
            if persistent_note:
                # Authorization: only owner or admin may update existing persistent note
                is_admin = bool(getattr(current_user, 'is_admin', False))
                is_owner = (persistent_note.created_by_user_id is not None) and (persistent_note.created_by_user_id == getattr(current_user, 'id', None))
                if not (is_admin or is_owner):
                    return jsonify({"success": False, "error": "Not authorized to update this persistent note"}), 403
                # Update content but preserve original author attribution
                persistent_note.note = atlas_stop.atlas_note
            else:
                new_persistent_note = PersistentData(
                    sloid=sloid,
                    note_type='atlas',
                    note=atlas_stop.atlas_note,
                    created_by_user_id=getattr(atlas_stop, 'atlas_note_user_id', None),
                    created_by_user_email=getattr(atlas_stop, 'atlas_note_user_email', None)
                )
                db.session.add(new_persistent_note)
            atlas_stop.atlas_note_is_persistent = True
            if current_user.is_authenticated:
                atlas_stop.atlas_note_user_id = getattr(current_user, 'id', None)
                atlas_stop.atlas_note_user_email = getattr(current_user, 'email', None)
            db.session.commit()
            return jsonify({"success": True})
        elif note_type == 'osm':
            osm_node_id = (data.get('osm_node_id') or '').strip()
            if not osm_node_id:
                return jsonify({"success": False, "error": "Missing osm_node_id"}), 400
            osm_node = OsmNode.query.filter_by(osm_node_id=osm_node_id).first()
            if not osm_node or not osm_node.osm_note:
                return jsonify({"success": False, "error": "No existing note to persist"}), 400
            persistent_note = PersistentData.query.filter_by(osm_node_id=osm_node_id, note_type='osm').first()
            if persistent_note:
                # Authorization: only owner or admin may update existing persistent note
                is_admin = bool(getattr(current_user, 'is_admin', False))
                is_owner = (persistent_note.created_by_user_id is not None) and (persistent_note.created_by_user_id == getattr(current_user, 'id', None))
                if not (is_admin or is_owner):
                    return jsonify({"success": False, "error": "Not authorized to update this persistent note"}), 403
                # Update content but preserve original author attribution
                persistent_note.note = osm_node.osm_note
            else:
                new_persistent_note = PersistentData(
                    osm_node_id=osm_node_id,
                    note_type='osm',
                    note=osm_node.osm_note,
                    created_by_user_id=getattr(osm_node, 'osm_note_user_id', None),
                    created_by_user_email=getattr(osm_node, 'osm_note_user_email', None)
                )
                db.session.add(new_persistent_note)
            osm_node.osm_note_is_persistent = True
            if current_user.is_authenticated:
                osm_node.osm_note_user_id = getattr(current_user, 'id', None)
                osm_node.osm_note_user_email = getattr(current_user, 'email', None)
            db.session.commit()
            return jsonify({"success": True})
        else:
            return jsonify({"success": False, "error": "Invalid note type"}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


@problems_bp.route('/api/check_persistent_note/atlas', methods=['GET'])
@limiter.limit("120/minute")
def check_persistent_atlas_note():
    try:
        sloid = request.args.get('sloid')
        if not sloid:
            return jsonify({"success": False, "error": "Missing sloid"}), 400
        atlas_stop = AtlasStop.query.filter_by(sloid=sloid).first()
        if not atlas_stop:
            return jsonify({"success": True, "is_persistent": False, "persistent_note": None})
        return jsonify({
            "success": True,
            "is_persistent": atlas_stop.atlas_note_is_persistent,
            "persistent_note": atlas_stop.atlas_note if atlas_stop.atlas_note_is_persistent else None
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@problems_bp.route('/api/check_persistent_note/osm', methods=['GET'])
@limiter.limit("120/minute")
def check_persistent_osm_note():
    try:
        osm_node_id = request.args.get('osm_node_id')
        if not osm_node_id:
            return jsonify({"success": False, "error": "Missing osm_node_id"}), 400
        osm_node = OsmNode.query.filter_by(osm_node_id=osm_node_id).first()
        if not osm_node:
            return jsonify({"success": True, "is_persistent": False, "persistent_note": None})
        return jsonify({
            "success": True,
            "is_persistent": osm_node.osm_note_is_persistent,
            "persistent_note": osm_node.osm_note if osm_node.osm_note_is_persistent else None
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@problems_bp.route('/api/persistent_data', methods=['GET'])
@limiter.limit("60/minute")
def get_persistent_data():
    try:
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 100))
        offset = (page - 1) * limit
        problem_type = request.args.get('problem_type', None)
        note_type = request.args.get('note_type', None)
        query = PersistentData.query
        if problem_type:
            query = query.filter(PersistentData.problem_type == problem_type)
        if note_type:
            query = query.filter(PersistentData.note_type == note_type)
        total_count = query.count()
        persistent_solutions = query.order_by(PersistentData.updated_at.desc()).offset(offset).limit(limit).all()
        results = []
        for ps in persistent_solutions:
            result = {
                'id': ps.id,
                'sloid': ps.sloid,
                'osm_node_id': ps.osm_node_id,
                'problem_type': ps.problem_type,
                'solution': ps.solution,
                'note_type': ps.note_type,
                'note': ps.note,
                'created_at': ps.created_at.isoformat() if ps.created_at else None,
                'updated_at': ps.updated_at.isoformat() if ps.updated_at else None,
                'author_email': ps.created_by_user_email,
                'author_user_id': ps.created_by_user_id
            }
            results.append(result)
        return jsonify({
            'persistent_data': results,
            'total': total_count,
            'page': page,
            'limit': limit
        })
    except Exception as e:
        app.logger.error(f"Error fetching persistent solutions: {str(e)}")
        return jsonify({"error": str(e)}), 500


@problems_bp.route('/api/persistent_data/<int:solution_id>', methods=['DELETE'])
@limiter.limit("30/minute")
@login_required
def delete_persistent_data(solution_id):
    try:
        solution = db.session.get(PersistentData, solution_id)
        if not solution:
            return jsonify({"success": False, "error": "Solution not found"}), 404
        # Authorization: admin or owner of the persistent record
        is_admin = bool(getattr(current_user, 'is_admin', False))
        is_owner = (solution.created_by_user_id is not None) and (solution.created_by_user_id == getattr(current_user, 'id', None))
        if not (is_admin or is_owner):
            return jsonify({"success": False, "error": "Not authorized to delete this persistent record"}), 403
        if solution.problem_type:
            stop = Stop.query.filter(
                and_(Stop.sloid == solution.sloid, Stop.osm_node_id == solution.osm_node_id)
            ).first()
            if stop:
                problem = Problem.query.filter_by(
                    stop_id=stop.id,
                    problem_type=solution.problem_type
                ).first()
                if problem:
                    problem.is_persistent = False
        elif solution.note_type == 'atlas':
            atlas_stop = AtlasStop.query.filter_by(sloid=solution.sloid).first()
            if atlas_stop:
                atlas_stop.atlas_note_is_persistent = False
        elif solution.note_type == 'osm':
            osm_node = OsmNode.query.filter_by(osm_node_id=solution.osm_node_id).first()
            if osm_node:
                osm_node.osm_note_is_persistent = False
        db.session.delete(solution)
        db.session.commit()
        return jsonify({"success": True, "message": "Persistent solution deleted successfully"})
    except Exception as e:
        app.logger.error(f"Error deleting persistent solution: {str(e)}")
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


@problems_bp.route('/api/make_non_persistent/<int:solution_id>', methods=['POST'])
@limiter.limit("30/minute")
@login_required
def make_non_persistent(solution_id):
    try:
        solution = db.session.get(PersistentData, solution_id)
        if not solution:
            return jsonify({"success": False, "error": "Solution not found"}), 404
        # Authorization: admin or owner of the persistent record
        is_admin = bool(getattr(current_user, 'is_admin', False))
        is_owner = (solution.created_by_user_id is not None) and (solution.created_by_user_id == getattr(current_user, 'id', None))
        if not (is_admin or is_owner):
            return jsonify({"success": False, "error": "Not authorized to modify this persistent record"}), 403
        if solution.problem_type:
            stop = Stop.query.filter(
                and_(Stop.sloid == solution.sloid, Stop.osm_node_id == solution.osm_node_id)
            ).first()
            if stop:
                problem = Problem.query.filter_by(
                    stop_id=stop.id,
                    problem_type=solution.problem_type
                ).first()
                if problem:
                    problem.is_persistent = False
        elif solution.note_type == 'atlas':
            atlas_stop = AtlasStop.query.filter_by(sloid=solution.sloid).first()
            if atlas_stop:
                atlas_stop.atlas_note_is_persistent = False
        elif solution.note_type == 'osm':
            osm_node = OsmNode.query.filter_by(osm_node_id=solution.osm_node_id).first()
            if osm_node:
                osm_node.osm_note_is_persistent = False
        db.session.delete(solution)
        db.session.commit()
        return jsonify({"success": True, "message": "Solution made non-persistent successfully"})
    except Exception as e:
        app.logger.error(f"Error making solution non-persistent: {str(e)}")
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


@problems_bp.route('/api/clear_all_persistent', methods=['POST'])
@limiter.limit("10/hour")
@login_required
@admin_required
def clear_all_persistent():
    try:
        Problem.query.update({Problem.is_persistent: False})
        AtlasStop.query.update({AtlasStop.atlas_note_is_persistent: False})
        OsmNode.query.update({OsmNode.osm_note_is_persistent: False})
        PersistentData.query.delete()
        db.session.commit()
        return jsonify({"success": True, "message": "All persistent data cleared."})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


@problems_bp.route('/api/clear_all_non-persistent', methods=['POST'])
@limiter.limit("10/hour")
@login_required
@admin_required
def clear_all_non_persistent():
    try:
        Problem.query.filter(Problem.is_persistent == False).update({Problem.solution: None})
        AtlasStop.query.filter(AtlasStop.atlas_note_is_persistent == False).update({AtlasStop.atlas_note: None})
        OsmNode.query.filter(OsmNode.osm_note_is_persistent == False).update({OsmNode.osm_note: None})
        db.session.commit()
        return jsonify({"success": True, "message": "All non-persistent data cleared."})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


@problems_bp.route('/api/non_persistent_data', methods=['GET'])
@limiter.limit("60/minute")
def get_non_persistent_data():
    try:
        count_only = request.args.get('count_only', 'false').lower() == 'true'
        if count_only:
            solution_count = Problem.query.filter(
                Problem.is_persistent == False,
                Problem.solution.isnot(None),
                Problem.solution != ''
            ).count()
            atlas_note_count = AtlasStop.query.filter(
                AtlasStop.atlas_note.isnot(None), 
                AtlasStop.atlas_note != '', 
                AtlasStop.atlas_note_is_persistent == False
            ).count()
            osm_note_count = OsmNode.query.filter(
                OsmNode.osm_note.isnot(None), 
                OsmNode.osm_note != '', 
                OsmNode.osm_note_is_persistent == False
            ).count()
            return jsonify({'solution_count': solution_count, 'note_count': atlas_note_count + osm_note_count})
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 100))
        offset = (page - 1) * limit
        filter_type = request.args.get('filter', 'all')
        results = []
        if filter_type in ['all', 'distance', 'unmatched', 'attributes']:
            problem_query = db.session.query(
                Problem.id,
                Problem.problem_type,
                Problem.solution,
                Problem.stop_id,
                Stop.sloid,
                Stop.osm_node_id
            ).join(Stop).filter(
                Problem.is_persistent == False,
                Problem.solution.isnot(None),
                Problem.solution != ''
            ).order_by(Problem.id)
            if filter_type != 'all':
                problem_query = problem_query.filter(Problem.problem_type == filter_type)
            problems = problem_query.all()
            for p in problems:
                results.append({
                    'id': p.id,
                    'type': 'solution',
                    'problem_type': p.problem_type,
                    'solution': p.solution or '',
                    'sloid': p.sloid,
                    'osm_node_id': p.osm_node_id,
                    'stop_id': p.stop_id
                })
        if filter_type in ['all', 'atlas_note']:
            atlas_query = db.session.query(
                AtlasStop.sloid,
                AtlasStop.atlas_note
            ).filter(
                AtlasStop.atlas_note.isnot(None),
                AtlasStop.atlas_note != '',
                AtlasStop.atlas_note_is_persistent == False
            ).order_by(AtlasStop.sloid)
            atlas_notes = atlas_query.all()
            for note in atlas_notes:
                results.append({
                    'id': f"atlas_{note.sloid}",
                    'type': 'note',
                    'note_type': 'atlas',
                    'note': note.atlas_note,
                    'sloid': note.sloid,
                    'osm_node_id': None
                })
        if filter_type in ['all', 'osm_note']:
            osm_query = db.session.query(
                OsmNode.osm_node_id,
                OsmNode.osm_note
            ).filter(
                OsmNode.osm_note.isnot(None),
                OsmNode.osm_note != '',
                OsmNode.osm_note_is_persistent == False
            ).order_by(OsmNode.osm_node_id)
            osm_notes = osm_query.all()
            for note in osm_notes:
                results.append({
                    'id': f"osm_{note.osm_node_id}",
                    'type': 'note',
                    'note_type': 'osm', 
                    'note': note.osm_note,
                    'sloid': None,
                    'osm_node_id': note.osm_node_id
                })
        results.sort(key=lambda x: (x['type'], str(x['id'])))
        total_count = len(results)
        paged_results = results[offset:offset + limit]
        return jsonify({'data': paged_results, 'total': total_count, 'page': page, 'limit': limit})
    except Exception as e:
        app.logger.error(f"Error fetching non-persistent data: {str(e)}")
        return jsonify({"error": str(e)}), 500


@problems_bp.route('/api/make_all_persistent', methods=['POST'])
@limiter.limit("10/hour")
@login_required
@admin_required
def make_all_persistent():
    try:
        solutions_made_persistent = 0
        notes_made_persistent = 0
        problems_to_persist = Problem.query.join(Stop).filter(
            Problem.solution.isnot(None),
            Problem.solution != '',
            Problem.is_persistent == False
        ).all()
        for problem in problems_to_persist:
            stop = problem.stop
            new_persistent_solution = PersistentData(
                sloid=stop.sloid, osm_node_id=stop.osm_node_id,
                problem_type=problem.problem_type, solution=problem.solution
            )
            db.session.add(new_persistent_solution)
            problem.is_persistent = True
            solutions_made_persistent += 1
        atlas_notes_to_persist = AtlasStop.query.filter(
            AtlasStop.atlas_note.isnot(None),
            AtlasStop.atlas_note != '',
            AtlasStop.atlas_note_is_persistent == False
        ).all()
        for stop in atlas_notes_to_persist:
            new_persistent_note = PersistentData(
                sloid=stop.sloid, note_type='atlas', note=stop.atlas_note
            )
            db.session.add(new_persistent_note)
            stop.atlas_note_is_persistent = True
            notes_made_persistent += 1
        osm_notes_to_persist = OsmNode.query.filter(
            OsmNode.osm_note.isnot(None),
            OsmNode.osm_note != '',
            OsmNode.osm_note_is_persistent == False
        ).all()
        for node in osm_notes_to_persist:
            new_persistent_note = PersistentData(
                osm_node_id=node.osm_node_id, note_type='osm', note=node.osm_note
            )
            db.session.add(new_persistent_note)
            node.osm_note_is_persistent = True
            notes_made_persistent += 1
        db.session.commit()
        return jsonify({
            "success": True,
            "solutions_made_persistent": solutions_made_persistent,
            "notes_made_persistent": notes_made_persistent,
            "message": f"Made {solutions_made_persistent} solutions and {notes_made_persistent} notes persistent"
        })
    except Exception as e:
        app.logger.error(f"Error making all data persistent: {str(e)}")
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


