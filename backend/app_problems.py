from flask import Blueprint, request, jsonify, current_app as app
from sqlalchemy.orm import joinedload, subqueryload
from backend.models import db, Stop, AtlasStop, OsmNode, Problem, PersistentData
from backend.app_data import format_stop_data
from sqlalchemy.sql import func
from sqlalchemy import and_

# Create a blueprint for problems-related endpoints
problems_bp = Blueprint('problems', __name__)

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
        if atlas_operator_filter:
            atlas_operators = [op.strip() for op in atlas_operator_filter.split(',') if op.strip()]
            if atlas_operators:
                # Filter for problems where the stop has Atlas details with the specified operator(s)
                query = query.filter(Stop.atlas_stop_details.has(
                    AtlasStop.atlas_business_org_abbr.in_(atlas_operators)
                ))
        
        # For counting, we need to count distinct stop_ids, but we need to do it differently
        # Create a subquery to get distinct stop_ids that match our criteria
        distinct_stop_ids_subquery = query.with_entities(Problem.stop_id).distinct().subquery()
        total_problems = db.session.query(func.count()).select_from(distinct_stop_ids_subquery).scalar()

        # Now get the actual problems with proper sorting and pagination
        # Apply sorting based on parameters
        if sort_by == 'distance' and problem_type_filter == 'distance':
            # For distance problems, sort by the distance_m field in the Stop table
            if sort_order == 'desc':
                query = query.order_by(Stop.distance_m.desc().nulls_last(), Problem.stop_id, Problem.problem_type)
            else:
                query = query.order_by(Stop.distance_m.asc().nulls_last(), Problem.stop_id, Problem.problem_type)
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
            
            if atlas_operator_filter:
                atlas_operators = [op.strip() for op in atlas_operator_filter.split(',') if op.strip()]
                if atlas_operators:
                    stop_distance_query = stop_distance_query.filter(Stop.atlas_stop_details.has(
                        AtlasStop.atlas_business_org_abbr.in_(atlas_operators)
                    ))
            
            # Order by distance and get distinct stop_ids
            if sort_order == 'desc':
                stop_distance_query = stop_distance_query.distinct().order_by(Stop.distance_m.desc().nulls_last(), Stop.id)
            else:
                stop_distance_query = stop_distance_query.distinct().order_by(Stop.distance_m.asc().nulls_last(), Stop.id)
            
            # Get paginated stop IDs
            paged_stops = stop_distance_query.offset(offset).limit(limit).all()
            paged_stop_ids = [stop[0] for stop in paged_stops]
            
        else:
            # For default sorting, use a simpler approach
            # Get distinct stop_ids with pagination
            stop_ids_query = db.session.query(Problem.stop_id).join(Stop)
            
            # Apply the same filters as the main query
            if problem_type_filter != 'all':
                stop_ids_query = stop_ids_query.filter(Problem.problem_type == problem_type_filter)
            if solution_status_filter == 'solved':
                stop_ids_query = stop_ids_query.filter(Problem.solution.isnot(None) & (Problem.solution != ''))
            elif solution_status_filter == 'unsolved':
                stop_ids_query = stop_ids_query.filter(Problem.solution.is_(None) | (Problem.solution == ''))
            if atlas_operator_filter:
                atlas_operators = [op.strip() for op in atlas_operator_filter.split(',') if op.strip()]
                if atlas_operators:
                    stop_ids_query = stop_ids_query.filter(Stop.atlas_stop_details.has(
                        AtlasStop.atlas_business_org_abbr.in_(atlas_operators)
                    ))
            
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

            if problem_type_filter != 'all':
                final_query = final_query.filter(Problem.problem_type == problem_type_filter)
            if solution_status_filter == 'solved':
                final_query = final_query.filter(Problem.solution.isnot(None) & (Problem.solution != ''))
            elif solution_status_filter == 'unsolved':
                final_query = final_query.filter(Problem.solution.is_(None) | (Problem.solution == ''))
            
            # Apply atlas operator filter to final query as well
            if atlas_operator_filter:
                atlas_operators = [op.strip() for op in atlas_operator_filter.split(',') if op.strip()]
                if atlas_operators:
                    final_query = final_query.filter(Stop.atlas_stop_details.has(
                        AtlasStop.atlas_business_org_abbr.in_(atlas_operators)
                    ))
            
            # Apply the same sorting to the final query to maintain order
            if sort_by == 'distance' and problem_type_filter == 'distance':
                if sort_order == 'desc':
                    final_query = final_query.join(Stop).order_by(Stop.distance_m.desc().nulls_last(), Problem.stop_id, Problem.problem_type)
                else:
                    final_query = final_query.join(Stop).order_by(Stop.distance_m.asc().nulls_last(), Problem.stop_id, Problem.problem_type)
            else:
                final_query = final_query.order_by(Problem.stop_id, Problem.problem_type)
            
            final_problems = final_query.all()

        problems = []
        for problem in final_problems:
            formatted_stop = format_stop_data(problem.stop, problem_type=problem.problem_type)
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
            'isolated': {'all': 0, 'solved': 0, 'unsolved': 0},
            'attributes': {'all': 0, 'solved': 0, 'unsolved': 0}
        }

        problem_types = ['distance', 'isolated', 'attributes']
        
        for p_type in problem_types:
            # Build base query for this problem type
            base_query = db.session.query(func.count(Problem.id)).join(Stop).filter(Problem.problem_type == p_type)
            
            # Apply operator filter if provided
            if atlas_operator_filter:
                atlas_operators = [op.strip() for op in atlas_operator_filter.split(',') if op.strip()]
                if atlas_operators:
                    base_query = base_query.filter(Stop.atlas_stop_details.has(
                        AtlasStop.atlas_business_org_abbr.in_(atlas_operators)
                    ))
            
            # Get total count for this problem type
            total_count = base_query.scalar()
            stats[p_type]['all'] = total_count
            
            # Get solved count
            solved_query = base_query.filter(
                Problem.solution.isnot(None) & (Problem.solution != '')
            )
            solved_count = solved_query.scalar()
            stats[p_type]['solved'] = solved_count
            
            # Calculate unsolved
            stats[p_type]['unsolved'] = total_count - solved_count

        # Calculate totals for 'All Problems' based on distinct stops with problems
        all_problems_query = db.session.query(func.count(func.distinct(Problem.stop_id))).join(Stop)
        
        # Apply operator filter to 'all' stats as well
        if atlas_operator_filter:
            atlas_operators = [op.strip() for op in atlas_operator_filter.split(',') if op.strip()]
            if atlas_operators:
                all_problems_query = all_problems_query.filter(Stop.atlas_stop_details.has(
                    AtlasStop.atlas_business_org_abbr.in_(atlas_operators)
                ))
        
        stats['all']['all'] = all_problems_query.scalar()
        
        # Calculate solved/unsolved for all. A stop is solved if all its problems are solved.
        # This is complex, so for now we sum up individual problem stats which is what the old code did.
        # The frontend will see total individual problems, which is fine.
        total_solved = sum(stats[p_type]['solved'] for p_type in problem_types)
        total_unsolved = sum(stats[p_type]['unsolved'] for p_type in problem_types)

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
            problem = Problem.query.filter_by(stop_id=problem_id, problem_type=problem_type).first()
            
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
        problem = Problem.query.filter_by(stop_id=problem_id, problem_type=problem_type).first()
        
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
            PersistentData.problem_type == problem_type
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
                problem_type=problem_type,
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

# -------------------------------
# API Endpoint: Get Non-Persistent Data
# -------------------------------
@problems_bp.route('/api/non_persistent_data', methods=['GET'])
def get_non_persistent_data():
    """Get all non-persistent solutions and notes using the new flags."""
    try:
        # Check if this is just a count request
        count_only = request.args.get('count_only', 'false').lower() == 'true'
        
        if count_only:
            # Count non-persistent problems (both with and without solutions)
            solution_count = Problem.query.filter_by(is_persistent=False).count()
            note_count = AtlasStop.query.filter_by(atlas_note_is_persistent=False).filter(AtlasStop.atlas_note.isnot(None), AtlasStop.atlas_note != '').count()
            note_count += OsmNode.query.filter_by(osm_note_is_persistent=False).filter(OsmNode.osm_note.isnot(None), OsmNode.osm_note != '').count()
            
            return jsonify({'solution_count': solution_count, 'note_count': note_count})

        # Pagination and filtering
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 100))
        offset = (page - 1) * limit
        filter_type = request.args.get('filter', 'all')
        
        results = []
        
        # Get non-persistent problems (including those without solutions)
        if filter_type in ['all', 'distance', 'isolated', 'attributes']:
            query = Problem.query.options(joinedload(Problem.stop)).filter(
                Problem.is_persistent == False
            )
            if filter_type != 'all':
                query = query.filter(Problem.problem_type == filter_type)
            
            for problem in query.all():
                results.append({
                    'id': problem.id, 
                    'type': 'solution', 
                    'problem_type': problem.problem_type,
                    'solution': problem.solution or '', 
                    'sloid': problem.stop.sloid, 
                    'osm_node_id': problem.stop.osm_node_id,
                    'stop_id': problem.stop_id  # Add stop_id for backend operations
                })

        # Get non-persistent ATLAS notes
        if filter_type in ['all', 'atlas_note']:
            query = AtlasStop.query.filter(
                AtlasStop.atlas_note.isnot(None), 
                AtlasStop.atlas_note != '', 
                AtlasStop.atlas_note_is_persistent == False
            )
            for stop in query.all():
                results.append({
                    'id': f"atlas_{stop.sloid}", 'type': 'note', 'note_type': 'atlas', 'note': stop.atlas_note,
                    'sloid': stop.sloid, 'osm_node_id': None
                })
        
        # Get non-persistent OSM notes
        if filter_type in ['all', 'osm_note']:
            query = OsmNode.query.filter(
                OsmNode.osm_note.isnot(None), 
                OsmNode.osm_note != '', 
                OsmNode.osm_note_is_persistent == False
            )
            for node in query.all():
                results.append({
                    'id': f"osm_{node.osm_node_id}", 'type': 'note', 'note_type': 'osm', 'note': node.osm_note,
                    'sloid': None, 'osm_node_id': node.osm_node_id
                })
        
        total_count = len(results)
        paged_results = results[offset:offset + limit]
        
        return jsonify({'data': paged_results, 'total': total_count, 'page': page, 'limit': limit})
        
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