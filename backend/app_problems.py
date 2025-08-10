from flask import Blueprint, request, jsonify, current_app as app
from sqlalchemy.orm import joinedload, subqueryload
from backend.models import db, Stop, AtlasStop, OsmNode, Problem, PersistentData
from backend.app_data import format_stop_data
from backend.query_helpers import get_query_builder, parse_filter_params, optimize_query_for_endpoint
from sqlalchemy.sql import func
from sqlalchemy import and_

# Create a blueprint for problems-related endpoints
problems_bp = Blueprint('problems', __name__)

def apply_atlas_operator_filter(query, atlas_operator_filter):
    """Helper function to apply Atlas operator filter to any query."""
    if atlas_operator_filter:
        atlas_operators = [op.strip() for op in atlas_operator_filter.split(',') if op.strip()]
        if atlas_operators:
            return query.filter(Stop.atlas_stop_details.has(
                AtlasStop.atlas_business_org_abbr.in_(atlas_operators)
            ))
    return query

# ----------------------------
# API Endpoint: /api/problems
# ----------------------------
@problems_bp.route('/api/problems', methods=['GET'])
def get_problems():
    """Get identified problems in the data for the problems page with pagination and filtering."""
    try:
        # Pagination parameters
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 100))
        offset = (page - 1) * limit

        # Filter parameters
        problem_type_filter = request.args.get('problem_type', 'all')
        solution_status_filter = request.args.get('solution_status', 'all') # 'solved', 'unsolved', 'all'
        atlas_operator_filter = request.args.get('atlas_operator', None)
        
        # Sorting parameters
        sort_by = request.args.get('sort_by', 'default')  # 'default', 'distance'
        sort_order = request.args.get('sort_order', 'asc')  # 'asc', 'desc'
        # Priority filter (optional)
        priority_filter = request.args.get('priority', None)

        # Base query on the Problem table
        query = Problem.query.join(Stop)

        # Problem type conditions
        if problem_type_filter != 'all':
            query = query.filter(Problem.problem_type == problem_type_filter)

        # Solution status conditions
        if solution_status_filter == 'solved':
            query = query.filter(Problem.solution.isnot(None) & (Problem.solution != ''))
        elif solution_status_filter == 'unsolved':
            query = query.filter(Problem.solution.is_(None) | (Problem.solution == ''))
        
        # Atlas operator filter
        query = apply_atlas_operator_filter(query, atlas_operator_filter)
        
        # Priority filter
        if priority_filter and priority_filter != 'all':
            try:
                priority_value = int(priority_filter)
                query = query.filter(Problem.priority == priority_value)
            except ValueError:
                pass
        
        # Special grouping logic for duplicates: return one row per duplicates group
        if problem_type_filter == 'duplicates':
            # Apply base filters to duplicates (do not pre-filter by solution; we'll evaluate at group level)
            dup_query = Problem.query.join(Stop).filter(Problem.problem_type == 'duplicates')
            # Atlas operator filter
            dup_query = apply_atlas_operator_filter(dup_query, atlas_operator_filter)
            # Priority: we keep all members to compute the group; we'll filter groups later

            # Eager load to avoid N+1
            dup_query = dup_query.options(
                joinedload(Problem.stop).subqueryload(Stop.atlas_stop_details),
                joinedload(Problem.stop).subqueryload(Stop.osm_node_details)
            )

            duplicate_problems = dup_query.all()

            # Group into OSM groups (uic_ref + osm_local_ref) and ATLAS groups (uic_ref + designation)
            from collections import defaultdict
            osm_groups = defaultdict(list)
            atlas_groups = defaultdict(list)
            for pr in duplicate_problems:
                st = pr.stop
                if st is None:
                    continue
                osm_details = st.osm_node_details
                atlas_details = st.atlas_stop_details
                # OSM duplicates group when we have a uic_ref and local_ref
                if st.osm_node_id and osm_details and osm_details.osm_local_ref:
                    key = (str(st.uic_ref or ''), str(osm_details.osm_local_ref or '').lower())
                    osm_groups[key].append(pr)
                # ATLAS duplicates group when same UIC + designation
                if st.sloid and atlas_details and (atlas_details.atlas_designation is not None):
                    key_atlas = (str(st.uic_ref or ''), str(atlas_details.atlas_designation or '').strip().lower())
                    atlas_groups[key_atlas].append(pr)

            # Keep only groups with at least 2 distinct members
            def build_osm_group_payload(key, problems_list):
                # Distinct by osm_node_id
                members = {}
                for pr in problems_list:
                    st = pr.stop
                    if st and st.osm_node_id:
                        members[st.osm_node_id] = pr
                if len(members) < 2:
                    return None
                uic_ref, local_ref = key
                # Members payloads
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
                # Distinct by stop id (or by osm_node_id)
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

            # Apply solution status filter at group level if requested
            def group_is_solved(item):
                member_solutions = [m.get('solution') for m in item.get('members', [])]
                # solved if all members have a non-empty solution
                return all(s and str(s).strip() != '' for s in member_solutions)

            if solution_status_filter == 'solved':
                group_items = [g for g in group_items if group_is_solved(g)]
            elif solution_status_filter == 'unsolved':
                group_items = [g for g in group_items if not group_is_solved(g)]

            # Sort groups by type then key for determinism
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

        # For counting, we need to count distinct stop_ids, but we need to do it differently
        # Create a subquery to get distinct stop_ids that match our criteria
        distinct_stop_ids_subquery = query.with_entities(Problem.stop_id).distinct().subquery()
        total_problems = db.session.query(func.count()).select_from(distinct_stop_ids_subquery).scalar()

        # Now get the actual problems with proper sorting and pagination
        # Apply sorting based on parameters
        if sort_by == 'distance' and problem_type_filter == 'distance':
            # For distance problems, sort by the distance_m field in the Stop table
            # Use COALESCE to emulate NULLS LAST in MySQL
            if sort_order == 'desc':
                query = query.order_by(func.coalesce(Stop.distance_m, -1).desc(), Problem.stop_id, Problem.problem_type)
            else:
                query = query.order_by(func.coalesce(Stop.distance_m, 1000000000000).asc(), Problem.stop_id, Problem.problem_type)
        elif sort_by == 'priority':
            # Sort by priority (1 highest), then by stop_id/problem_type for stability
            if sort_order == 'desc':
                query = query.order_by(func.coalesce(Problem.priority, 999).desc(), Problem.stop_id, Problem.problem_type)
            else:
                query = query.order_by(func.coalesce(Problem.priority, 999).asc(), Problem.stop_id, Problem.problem_type)
        else:
            # Default sorting by stop_id for consistent pagination
            query = query.order_by(Problem.stop_id, Problem.problem_type)

        # For pagination with sorting, we need a different approach
        # First, get a list of distinct stop_ids in the correct order
        if sort_by == 'distance' and problem_type_filter == 'distance':
            # For distance sorting, we need to get stops with their distances
            stop_distance_query = db.session.query(Stop.id, Stop.distance_m).join(Problem).filter(
                Problem.problem_type == problem_type_filter if problem_type_filter != 'all' else True
            )
            
            # Apply the same filters
            if solution_status_filter == 'solved':
                stop_distance_query = stop_distance_query.filter(Problem.solution.isnot(None) & (Problem.solution != ''))
            elif solution_status_filter == 'unsolved':
                stop_distance_query = stop_distance_query.filter(Problem.solution.is_(None) | (Problem.solution == ''))
            
            stop_distance_query = apply_atlas_operator_filter(stop_distance_query, atlas_operator_filter)
            # Apply priority filter
            if priority_filter and priority_filter != 'all':
                try:
                    priority_value = int(priority_filter)
                    stop_distance_query = stop_distance_query.filter(Problem.priority == priority_value)
                except ValueError:
                    pass
            
            # Order by distance and get distinct stop_ids
            if sort_order == 'desc':
                stop_distance_query = stop_distance_query.distinct().order_by(func.coalesce(Stop.distance_m, -1).desc(), Stop.id)
            else:
                stop_distance_query = stop_distance_query.distinct().order_by(func.coalesce(Stop.distance_m, 1000000000000).asc(), Stop.id)
            
            # Get paginated stop IDs
            paged_stops = stop_distance_query.offset(offset).limit(limit).all()
            paged_stop_ids = [stop[0] for stop in paged_stops]
            
        elif sort_by == 'priority':
            stop_ids_query = db.session.query(Problem.stop_id, func.min(Problem.priority)).join(Stop)
            # Apply same filters
            if problem_type_filter != 'all':
                stop_ids_query = stop_ids_query.filter(Problem.problem_type == problem_type_filter)
            if solution_status_filter == 'solved':
                stop_ids_query = stop_ids_query.filter(Problem.solution.isnot(None) & (Problem.solution != ''))
            elif solution_status_filter == 'unsolved':
                stop_ids_query = stop_ids_query.filter(Problem.solution.is_(None) | (Problem.solution == ''))
            stop_ids_query = apply_atlas_operator_filter(stop_ids_query, atlas_operator_filter)
            # Apply priority filter
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
            # For default sorting, use a simpler approach
            # Get distinct stop_ids with pagination
            stop_ids_query = db.session.query(Problem.stop_id).join(Stop)
            
            # Apply the same filters as the main query
            if problem_type_filter != 'all':
                mapped_type = 'unmatched' if problem_type_filter == 'isolated' else problem_type_filter
                stop_ids_query = stop_ids_query.filter(Problem.problem_type == mapped_type)
            if solution_status_filter == 'solved':
                stop_ids_query = stop_ids_query.filter(Problem.solution.isnot(None) & (Problem.solution != ''))
            elif solution_status_filter == 'unsolved':
                stop_ids_query = stop_ids_query.filter(Problem.solution.is_(None) | (Problem.solution == ''))
            stop_ids_query = apply_atlas_operator_filter(stop_ids_query, atlas_operator_filter)
            
            # Get distinct stop_ids in order
            paged_stop_ids = [item[0] for item in stop_ids_query.distinct().order_by(Problem.stop_id).offset(offset).limit(limit).all()]

        # Now fetch the actual problems for these stop_ids
        if not paged_stop_ids:
            final_problems = []
        else:
            final_query = Problem.query.options(
                joinedload(Problem.stop).subqueryload(Stop.atlas_stop_details),
                joinedload(Problem.stop).subqueryload(Stop.osm_node_details)
            ).filter(Problem.stop_id.in_(paged_stop_ids))

            # Important: Do NOT filter by problem_type here so we can display
            # other problems of the same entry as context. We still respect
            # the solution status filter.
            if solution_status_filter == 'solved':
                final_query = final_query.filter(Problem.solution.isnot(None) & (Problem.solution != ''))
            elif solution_status_filter == 'unsolved':
                final_query = final_query.filter(Problem.solution.is_(None) | (Problem.solution == ''))
            
            # Apply atlas operator filter to final query as well
            final_query = apply_atlas_operator_filter(final_query, atlas_operator_filter)
            # Apply priority filter to final query as well
            if priority_filter and priority_filter != 'all':
                try:
                    priority_value = int(priority_filter)
                    final_query = final_query.filter(Problem.priority == priority_value)
                except ValueError:
                    pass
            
            # Apply the same sorting to the final query to maintain order
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
            formatted_stop['stop_id'] = problem.stop_id  # Add stop_id for backend operations
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

# ----------------------------
# API Endpoint: /api/problems/stats
# ----------------------------
@problems_bp.route('/api/problems/stats', methods=['GET'])
def get_problem_stats():
    """Get statistics for the problem filter dropdown."""
    try:
        # Get operator filter if provided
        atlas_operator_filter = request.args.get('atlas_operator', None)
        
        stats = {
            'all': {'all': 0, 'solved': 0, 'unsolved': 0},
            'distance': {'all': 0, 'solved': 0, 'unsolved': 0},
            'unmatched': {'all': 0, 'solved': 0, 'unsolved': 0},
            'attributes': {'all': 0, 'solved': 0, 'unsolved': 0},
            'duplicates': {'all': 0, 'solved': 0, 'unsolved': 0}
        }

        # Optional: accept priority filter to reflect counts for a selected priority
        selected_priority = request.args.get('priority')

        # Internal DB types
        problem_types_internal = ['distance', 'unmatched', 'attributes', 'duplicates']
        
        for p_type in problem_types_internal:
            # Build base query for this problem type
            base_query = db.session.query(func.count(Problem.id)).join(Stop).filter(Problem.problem_type == p_type)
            
            # Apply operator filter if provided
            base_query = apply_atlas_operator_filter(base_query, atlas_operator_filter)
            
            # Apply selected priority if provided
            if selected_priority and selected_priority != 'all':
                try:
                    pr = int(selected_priority)
                    base_query = base_query.filter(Problem.priority == pr)
                except ValueError:
                    pass
            
            # Get total count for this problem type
            total_count = base_query.scalar()
            key_out = p_type
            stats[key_out]['all'] = total_count
            
            # Get solved count
            solved_query = base_query.filter(
                Problem.solution.isnot(None) & (Problem.solution != '')
            )
            solved_count = solved_query.scalar()
            stats[key_out]['solved'] = solved_count
            
            # Calculate unsolved
            stats[key_out]['unsolved'] = total_count - solved_count

        # Calculate totals for 'All Problems' based on distinct stops with problems
        all_problems_query = db.session.query(func.count(func.distinct(Problem.stop_id))).join(Stop)
        
        # Apply operator filter to 'all' stats as well
        all_problems_query = apply_atlas_operator_filter(all_problems_query, atlas_operator_filter)
        # Apply priority if provided
        if selected_priority and selected_priority != 'all':
            try:
                pr = int(selected_priority)
                all_problems_query = all_problems_query.filter(Problem.priority == pr)
            except ValueError:
                pass
        
        stats['all']['all'] = all_problems_query.scalar()
        
        # Calculate solved/unsolved for all. A stop is solved if all its problems are solved.
        # This is complex, so for now we sum up individual problem stats which is what the old code did.
        # The frontend will see total individual problems, which is fine.
        total_solved = sum(stats[p_type]['solved'] for p_type in ['distance', 'unmatched', 'attributes', 'duplicates'])
        total_unsolved = sum(stats[p_type]['unsolved'] for p_type in ['distance', 'unmatched', 'attributes', 'duplicates'])

        # The total number of problems is the sum of all types
        stats['all']['all'] = total_solved + total_unsolved
        stats['all']['solved'] = total_solved
        stats['all']['unsolved'] = total_unsolved


        return jsonify(stats)

    except Exception as e:
        app.logger.error(f"Error getting problem stats: {str(e)}")
        return jsonify({"error": str(e)}), 500

# ----------------------------
# API Endpoint: Save Solution
# ----------------------------
@problems_bp.route('/api/save_solution', methods=['POST'])
def save_solution():
    """Save a solution for a specific problem type (temporary, not persistent)."""
    try:
        data = request.get_json()
        
        problem_id = data.get('problem_id') # This is actually stop_id
        problem_type = data.get('problem_type')
        solution = data.get('solution')
        
        if not problem_id:
            return jsonify({"success": False, "error": "Missing problem_id parameter"}), 400
        
        # Normalize legacy problem type
        mapped_problem_type = 'unmatched' if problem_type == 'isolated' else problem_type

        # Handle the 'any' problem_type case from persistent data management
        if problem_type == 'any':
            # Try to find any problem for this stop_id
            problem = Problem.query.filter_by(stop_id=problem_id).first()
            if not problem:
                return jsonify({"success": False, "error": f"No problem found for stop {problem_id}"}), 404
        else:
            if not problem_type:
                return jsonify({"success": False, "error": "Missing problem_type parameter"}), 400
            
            # Find the specific problem to update
            problem = Problem.query.filter_by(stop_id=problem_id, problem_type=mapped_problem_type).first()
            
            if not problem:
                 return jsonify({"success": False, "error": f"Problem of type {problem_type} for stop {problem_id} not found"}), 404

        problem.solution = solution
        problem.is_persistent = False # Explicitly set to false when just saving
        db.session.commit()
        
        return jsonify({"success": True, "message": f"{problem.problem_type.capitalize()} solution saved successfully"})
        
    except Exception as e:
        app.logger.error(f"Exception in save_solution: {e}")
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500

# ----------------------------
# API Endpoint: Make Solution Persistent
# ----------------------------
@problems_bp.route('/api/make_solution_persistent', methods=['POST'])
def make_solution_persistent():
    """Make an existing solution persistent across data imports."""
    try:
        data = request.get_json()
        
        problem_id = data.get('problem_id') # This is actually stop_id
        problem_type = data.get('problem_type')
        
        if not problem_id or not problem_type:
            return jsonify({"success": False, "error": "Missing required parameters"}), 400
        
        # Find the specific problem
        mapped_problem_type = 'unmatched' if problem_type == 'isolated' else problem_type
        problem = Problem.query.filter_by(stop_id=problem_id, problem_type=mapped_problem_type).first()
        
        if not problem:
            return jsonify({"success": False, "error": f"Problem of type {problem_type} for stop {problem_id} not found"}), 404
        
        if not problem.solution:
            return jsonify({"success": False, "error": "Cannot make an empty solution persistent"}), 400
            
        # Get the stop to access sloid and osm_node_id for persistent solution
        stop = Stop.query.get(problem_id)
        if not stop:
            return jsonify({"success": False, "error": "Stop not found"}), 404
            
        # Save to persistent_data table
        # First check if a persistent solution already exists
        persistent_solution = PersistentData.query.filter(
            PersistentData.sloid == stop.sloid,
            PersistentData.osm_node_id == stop.osm_node_id,
            PersistentData.problem_type == mapped_problem_type
        ).first()
        
        if persistent_solution:
            # Update existing persistent solution
            persistent_solution.solution = problem.solution
            message = "Solution updated in persistent storage"
        else:
            # Create new persistent solution
            new_persistent_solution = PersistentData(
                sloid=stop.sloid,
                osm_node_id=stop.osm_node_id,
                problem_type=mapped_problem_type,
                solution=problem.solution
            )
            db.session.add(new_persistent_solution)
            message = "Solution saved to persistent storage"
        
        # Mark the problem as persistent
        problem.is_persistent = True
        
        db.session.commit()
        
        return jsonify({
            "success": True, 
            "message": message,
            "is_persistent": True
        })
        
    except Exception as e:
        app.logger.error(f"Exception in make_solution_persistent: {e}")
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500

# ----------------------------
# API Endpoint: Check Persistent Solution Status
# ----------------------------
@problems_bp.route('/api/check_persistent_solution', methods=['GET'])
def check_persistent_solution():
    """Check if a persistent solution exists for a problem."""
    try:
        stop_id = request.args.get('stop_id')
        problem_type = request.args.get('problem_type')
        
        if not stop_id or not problem_type:
            return jsonify({"success": False, "error": "Missing required parameters"}), 400
            
        # Use the flag from the problems table for a faster check
        problem = Problem.query.filter_by(stop_id=stop_id, problem_type=problem_type).first()
        
        if not problem:
            return jsonify({"success": True, "is_persistent": False, "persistent_solution": None})

        is_persistent = problem.is_persistent
        solution = problem.solution if is_persistent else None

        return jsonify({
            "success": True,
            "is_persistent": is_persistent,
            "persistent_solution": solution
        })
        
    except Exception as e:
        app.logger.error(f"Exception in check_persistent_solution: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

# -------------------------------
# API Endpoints: Note Saving
# -------------------------------
@problems_bp.route('/api/save_note/atlas', methods=['POST'])
def save_atlas_note():
    """Save a note for an ATLAS stop."""
    try:
        data = request.get_json()
        sloid = data.get('sloid')
        note = data.get('note', '')
        make_persistent = data.get('make_persistent', False)
        
        if not sloid:
            return jsonify({"success": False, "error": "Missing sloid"}), 400
        
        atlas_stop = AtlasStop.query.filter_by(sloid=sloid).first()
        if not atlas_stop:
            atlas_stop = AtlasStop(sloid=sloid)
            db.session.add(atlas_stop)
        
        atlas_stop.atlas_note = note
        atlas_stop.atlas_note_is_persistent = make_persistent
        
        # If requested, also save as persistent note
        if make_persistent:
            # Check if a persistent note already exists
            persistent_note = PersistentData.query.filter_by(
                sloid=sloid,
                note_type='atlas'
            ).first()
            
            if persistent_note:
                # Update existing persistent note
                persistent_note.note = note
            else:
                # Create new persistent note
                new_persistent_note = PersistentData(
                    sloid=sloid,
                    note_type='atlas',
                    note=note
                )
                db.session.add(new_persistent_note)
        
        db.session.commit()
        
        return jsonify({
            "success": True, 
            "message": "ATLAS note saved successfully",
            "is_persistent": make_persistent
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500

@problems_bp.route('/api/save_note/osm', methods=['POST'])
def save_osm_note():
    """Save a note for an OSM node."""
    try:
        data = request.get_json()
        osm_node_id = data.get('osm_node_id')
        note = data.get('note', '')
        make_persistent = data.get('make_persistent', False)
        
        if not osm_node_id:
            return jsonify({"success": False, "error": "Missing osm_node_id"}), 400
        
        osm_node = OsmNode.query.filter_by(osm_node_id=osm_node_id).first()
        if not osm_node:
            osm_node = OsmNode(osm_node_id=osm_node_id)
            db.session.add(osm_node)
        
        osm_node.osm_note = note
        osm_node.osm_note_is_persistent = make_persistent
        
        # If requested, also save as persistent note
        if make_persistent:
            # Check if a persistent note already exists
            persistent_note = PersistentData.query.filter_by(
                osm_node_id=osm_node_id,
                note_type='osm'
            ).first()
            
            if persistent_note:
                # Update existing persistent note
                persistent_note.note = note
            else:
                # Create new persistent note
                new_persistent_note = PersistentData(
                    osm_node_id=osm_node_id,
                    note_type='osm',
                    note=note
                )
                db.session.add(new_persistent_note)
        
        db.session.commit()
        
        return jsonify({
            "success": True, 
            "message": "OSM note saved successfully",
            "is_persistent": make_persistent
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500

# Add endpoints to check if notes are persistent
@problems_bp.route('/api/check_persistent_note/atlas', methods=['GET'])
def check_persistent_atlas_note():
    """Check if an ATLAS note is persistent."""
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
def check_persistent_osm_note():
    """Check if an OSM note is persistent."""
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

# -------------------------------
# API Endpoints: Persistent Solutions Management
# -------------------------------
@problems_bp.route('/api/persistent_data', methods=['GET'])
def get_persistent_data():
    """Get all persistent solutions with pagination and filtering."""
    try:
        # Pagination parameters
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 100))
        offset = (page - 1) * limit
        
        # Filter parameters
        problem_type = request.args.get('problem_type', None)
        note_type = request.args.get('note_type', None)
        
        # Base query
        query = PersistentData.query
        
        # Apply filters
        if problem_type:
            query = query.filter(PersistentData.problem_type == problem_type)
        if note_type:
            query = query.filter(PersistentData.note_type == note_type)
        
        # Get total count for pagination
        total_count = query.count()
        
        # Get paginated results
        persistent_solutions = query.order_by(PersistentData.updated_at.desc()).offset(offset).limit(limit).all()
        
        # Format results
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
                'updated_at': ps.updated_at.isoformat() if ps.updated_at else None
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
def delete_persistent_data(solution_id):
    """Delete a persistent solution by ID and unset the corresponding flag."""
    try:
        solution = PersistentData.query.get(solution_id)
        if not solution:
            return jsonify({"success": False, "error": "Solution not found"}), 404
        
        # Unset the persistent flag on the related problem or note
        if solution.problem_type:
            # This is a problem solution
            # Find the stop_id first
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
def make_non_persistent(solution_id):
    """Make a persistent solution non-persistent."""
    try:
        solution = PersistentData.query.get(solution_id)
        if not solution:
            return jsonify({"success": False, "error": "Solution not found"}), 404

        # Unset the persistent flag on the related problem or note
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
def clear_all_persistent():
    """Clear all persistent data."""
    try:
        # Unset all persistent flags
        Problem.query.update({Problem.is_persistent: False})
        AtlasStop.query.update({AtlasStop.atlas_note_is_persistent: False})
        OsmNode.query.update({OsmNode.osm_note_is_persistent: False})
        
        # Delete all persistent data entries
        PersistentData.query.delete()
        
        db.session.commit()
        return jsonify({"success": True, "message": "All persistent data cleared."})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500

@problems_bp.route('/api/clear_all_non-persistent', methods=['POST'])
def clear_all_non_persistent():
    """Clear all non-persistent solutions and notes."""
    try:
        # Clear non-persistent solutions
        Problem.query.filter(Problem.is_persistent == False).update({Problem.solution: None})
        
        # Clear non-persistent notes
        AtlasStop.query.filter(AtlasStop.atlas_note_is_persistent == False).update({AtlasStop.atlas_note: None})
        OsmNode.query.filter(OsmNode.osm_note_is_persistent == False).update({OsmNode.osm_note: None})
        
        db.session.commit()
        return jsonify({"success": True, "message": "All non-persistent data cleared."})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500

# -------------------------------
# API Endpoint: Get Non-Persistent Data
# -------------------------------
@problems_bp.route('/api/non_persistent_data', methods=['GET'])
def get_non_persistent_data():
    """Get all non-persistent solutions and notes with optimized SQL queries."""
    try:
        # Check if this is just a count request
        count_only = request.args.get('count_only', 'false').lower() == 'true'
        
        if count_only:
            # Count non-persistent problems and notes efficiently
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
            
            return jsonify({
                'solution_count': solution_count, 
                'note_count': atlas_note_count + osm_note_count
            })

        # Pagination and filtering
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 100))
        offset = (page - 1) * limit
        filter_type = request.args.get('filter', 'all')
        
        results = []
        
        # Build optimized queries with proper ordering for consistent pagination
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
            )
            
            if filter_type != 'all':
                problem_query = problem_query.filter(Problem.problem_type == filter_type)
            
            # Use database ordering for consistent pagination
            problem_query = problem_query.order_by(Problem.id)
            
            # Only get the problems for the current page if not filtering by notes only
            if filter_type in ['all', 'distance', 'unmatched', 'attributes']:
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

        # Get non-persistent ATLAS notes
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
        
        # Get non-persistent OSM notes
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
        
        # Sort results by type and ID for consistent ordering
        results.sort(key=lambda x: (x['type'], str(x['id'])))
        
        total_count = len(results)
        paged_results = results[offset:offset + limit]
        
        return jsonify({
            'data': paged_results, 
            'total': total_count, 
            'page': page, 
            'limit': limit
        })
        
    except Exception as e:
        app.logger.error(f"Error fetching non-persistent data: {str(e)}")
        return jsonify({"error": str(e)}), 500

# -------------------------------
# API Endpoint: Make All Persistent
# -------------------------------
@problems_bp.route('/api/make_all_persistent', methods=['POST'])
def make_all_persistent():
    """Make all non-persistent solutions and notes persistent using flags."""
    try:
        solutions_made_persistent = 0
        notes_made_persistent = 0
        
        # Process non-persistent problem solutions
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
            
        # Process non-persistent ATLAS notes
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

        # Process non-persistent OSM notes
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

# -------------------------------
# API Endpoints: Make Notes Persistent
# -------------------------------
@problems_bp.route('/api/make_note_persistent/atlas', methods=['POST'])
def make_atlas_note_persistent():
    """Make an existing ATLAS note persistent."""
    try:
        data = request.get_json()
        sloid = data.get('sloid')
        
        if not sloid:
            return jsonify({"success": False, "error": "Missing sloid"}), 400
        
        # Find the ATLAS stop
        atlas_stop = AtlasStop.query.filter_by(sloid=sloid).first()
        if not atlas_stop or not atlas_stop.atlas_note:
            return jsonify({"success": False, "error": "No note found for this ATLAS stop"}), 404
        
        # Save to persistent_data table
        persistent_note = PersistentData.query.filter_by(
            sloid=sloid,
            note_type='atlas'
        ).first()
        
        if persistent_note:
            # Update existing persistent note
            persistent_note.note = atlas_stop.atlas_note
            message = "ATLAS note updated in persistent storage"
        else:
            # Create new persistent note
            new_persistent_note = PersistentData(
                sloid=sloid,
                note_type='atlas',
                note=atlas_stop.atlas_note
            )
            db.session.add(new_persistent_note)
            message = "ATLAS note saved to persistent storage"
        
        # Mark the note as persistent
        atlas_stop.atlas_note_is_persistent = True
        
        db.session.commit()
        
        return jsonify({
            "success": True, 
            "message": message
        })
        
    except Exception as e:
        app.logger.error(f"Exception in make_atlas_note_persistent: {e}")
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500

@problems_bp.route('/api/make_note_persistent/osm', methods=['POST'])
def make_osm_note_persistent():
    """Make an existing OSM note persistent."""
    try:
        data = request.get_json()
        osm_node_id = data.get('osm_node_id')
        
        if not osm_node_id:
            return jsonify({"success": False, "error": "Missing osm_node_id"}), 400
        
        # Find the OSM node
        osm_node = OsmNode.query.filter_by(osm_node_id=osm_node_id).first()
        if not osm_node or not osm_node.osm_note:
            return jsonify({"success": False, "error": "No note found for this OSM node"}), 404
        
        # Save to persistent_data table
        persistent_note = PersistentData.query.filter_by(
            osm_node_id=osm_node_id,
            note_type='osm'
        ).first()
        
        if persistent_note:
            # Update existing persistent note
            persistent_note.note = osm_node.osm_note
            message = "OSM note updated in persistent storage"
        else:
            # Create new persistent note
            new_persistent_note = PersistentData(
                osm_node_id=osm_node_id,
                note_type='osm',
                note=osm_node.osm_note
            )
            db.session.add(new_persistent_note)
            message = "OSM note saved to persistent storage"
        
        # Mark the note as persistent
        osm_node.osm_note_is_persistent = True
        
        db.session.commit()
        
        return jsonify({
            "success": True, 
            "message": message
        })
        
    except Exception as e:
        app.logger.error(f"Exception in make_osm_note_persistent: {e}")
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500