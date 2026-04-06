from flask import Blueprint, request, jsonify, render_template, current_app as app
from backend.models import StopsMatched, Problem, AtlasStop
from backend.extensions import db, limiter
from sqlalchemy.orm import joinedload
from backend.query_helpers import optimize_query_for_endpoint
from datetime import datetime
import csv
from io import StringIO
import threading
import time
import uuid
import os
import tempfile
from sqlalchemy import case

reports_bp = Blueprint('reports', __name__)

# Global storage for report progress and completed reports
# In production, consider using Redis or database storage
report_progress = {}  # task_id -> {status, processed, total, eta, error, created_at}
completed_reports = {}  # task_id -> {file_path, filename, created_at}
_state_lock = threading.Lock()

# Cleanup configuration
REPORT_MAX_AGE_SECONDS = 604800    # 1 week
CLEANUP_INTERVAL_SECONDS = 3600    # 1 hour


def _cleanup_stale_reports():
    """Remove report files and state entries older than REPORT_MAX_AGE_SECONDS."""
    now = datetime.now()
    stale_task_ids = []

    with _state_lock:
        # Find stale completed reports
        for task_id, info in list(completed_reports.items()):
            age = (now - info['created_at']).total_seconds()
            if age > REPORT_MAX_AGE_SECONDS:
                stale_task_ids.append(task_id)

        # Find stale/abandoned progress entries (no completed report)
        for task_id, info in list(report_progress.items()):
            if task_id in stale_task_ids:
                continue
            if task_id not in completed_reports:
                created_at = info.get('created_at')
                if created_at and (now - created_at).total_seconds() > REPORT_MAX_AGE_SECONDS:
                    stale_task_ids.append(task_id)

        # Remove stale entries and their files
        for task_id in stale_task_ids:
            report_info = completed_reports.pop(task_id, None)
            report_progress.pop(task_id, None)
            if report_info:
                filepath = report_info.get('file_path')
                if filepath:
                    try:
                        if os.path.exists(filepath):
                            os.remove(filepath)
                    except OSError:
                        pass

    return len(stale_task_ids)


def _periodic_cleanup():
    """Background thread that periodically cleans up stale reports."""
    while True:
        time.sleep(CLEANUP_INTERVAL_SECONDS)
        try:
            count = _cleanup_stale_reports()
            if count > 0:
                print(f"Report cleanup: removed {count} stale report(s)")
        except Exception:
            pass


_cleanup_thread = threading.Thread(target=_periodic_cleanup, daemon=True)
_cleanup_thread.start()


def update_progress(task_id, processed, total, start_time=None):
    """Update progress for a report generation task"""
    with _state_lock:
        if task_id not in report_progress:
            return

        report_progress[task_id]['processed'] = processed
        report_progress[task_id]['total'] = total

        # Calculate ETA
        if start_time and processed > 0:
            elapsed = time.time() - start_time
            rate = processed / elapsed
            remaining = total - processed
            eta = remaining / rate if rate > 0 else None
            report_progress[task_id]['eta'] = eta

    print(f"Progress {task_id}: {processed}/{total}")


def generate_report_data(params, task_id):
    """Generate report data with progress tracking"""
    try:
        start_time = time.time()
        
        # Parse parameters (similar to existing function)
        limit_raw = (params.get('limit', '10') or '10').strip().lower()
        limit = None if limit_raw == 'all' else int(limit_raw)
        sort_param = params.get('sort', 'operator_asc')
        report_type = (params.get('report_type', 'distance') or 'distance').lower()
        
        if report_type in ('top_matches', 'exact_matches', 'name_matches'):
            report_type = 'distance'
        
        atlas_operator_str = params.get('atlas_operator', '')
        atlas_operators = [op.strip() for op in atlas_operator_str.split(',') if op and op.strip()]

        # Normalize sort per report type
        def _normalize_sort(rt, s):
            allowed = {
                'distance': {'operator_asc','operator_desc','distance_asc','distance_desc'},
                'unmatched': {'operator_asc','operator_desc'},
                'problems': {'operator_asc','operator_desc','priority_asc','priority_desc'}
            }
            s = (s or '').strip().lower()
            if s not in allowed.get(rt, set()):
                # Choose sensible default per category
                return 'distance_desc' if rt == 'distance' else ('priority_desc' if rt == 'problems' else 'operator_asc')
            return s

        sort_param = _normalize_sort(report_type, sort_param)
        
        if report_type == 'summary':
            # Summary report doesn't use standard data queries, it uses the pre-calculated stats
            from backend.services.stats_export import get_pipeline_stats
            from backend.extensions import db
            from backend.services.stats_export import compute_db_stats
            
            stats = get_pipeline_stats()
            # Also get real-time problem stats from DB
            problem_stats = compute_db_stats(db.session)
            
            update_progress(task_id, 100, 100, start_time)
            return {'stats': stats, 'problem_stats': problem_stats}, 'summary'

        def _apply_atlas_operator_filter(query):
            if not atlas_operators:
                return query
            return query.filter(StopsMatched.atlas_stop_details.has(AtlasStop.atlas_business_org_abbr.in_(atlas_operators)))

        def _operator_order_columns(ascending=True):
            # Cross-DB NULL handling: order NULLs first to mimic previous behavior for ASC
            nulls_first_col = case((AtlasStop.atlas_business_org_abbr == None, 0), else_=1)
            # For ASC: (NULL first) then value ASC; for DESC: (NULL first) then value DESC
            if ascending:
                return (nulls_first_col.asc(), AtlasStop.atlas_business_org_abbr.asc())
            else:
                return (nulls_first_col.asc(), AtlasStop.atlas_business_org_abbr.desc())

        # Build base query and get total count first
        if report_type == 'unmatched':
            sources_str = params.get('sources', 'atlas,osm')
            sources = set([s.strip().lower() for s in sources_str.split(',') if s.strip()])
            valid_sources = {'atlas', 'osm'}
            sources = sources.intersection(valid_sources) or {'atlas', 'osm'}

            query = StopsMatched.query
            if sources == {'atlas', 'osm'}:
                query = query.filter(StopsMatched.stop_type.in_(['atlas_unmatched', 'osm_unmatched']))
            elif 'atlas' in sources:
                query = query.filter(StopsMatched.stop_type == 'atlas_unmatched')
            else:
                query = query.filter(StopsMatched.stop_type == 'osm_unmatched')

            query = _apply_atlas_operator_filter(query)

        elif report_type == 'problems':
            problem_types_str = params.get('problem_types', '')
            selected_types = [t.strip() for t in problem_types_str.split(',') if t.strip()]
            valid_problem_types = {'distance', 'unmatched', 'attributes', 'duplicates'}
            if selected_types:
                selected_types = [t for t in selected_types if t in valid_problem_types]
            else:
                selected_types = list(valid_problem_types)

            priorities_str = params.get('priorities', '')
            selected_priorities = []
            if priorities_str:
                for p in priorities_str.split(','):
                    p = p.strip()
                    if not p:
                        continue
                    try:
                        pi = int(p)
                        if pi in (1, 2, 3):
                            selected_priorities.append(pi)
                    except Exception:
                        continue

            solution_status_str = params.get('solution_status', '')
            solution_status = set([s.strip().lower() for s in solution_status_str.split(',') if s.strip()])

            query = db.session.query(Problem).join(StopsMatched)
            if selected_types:
                query = query.filter(Problem.problem_type.in_(selected_types))
            if selected_priorities:
                query = query.filter(Problem.priority.in_(selected_priorities))
            if solution_status == {'solved'}:
                query = query.filter(Problem.solution.isnot(None), Problem.solution != '')
            elif solution_status == {'unsolved'}:
                query = query.filter((Problem.solution.is_(None)) | (Problem.solution == ''))
            if atlas_operators:
                query = query.filter(StopsMatched.atlas_stop_details.has(AtlasStop.atlas_business_org_abbr.in_(atlas_operators)))
                
        else:  # distance
            query = StopsMatched.query.filter(StopsMatched.stop_type == 'matched')
            query = _apply_atlas_operator_filter(query)

        # Apply any sort-specific filters prior to counting (e.g., exclude NULL distances)
        pre_count_query = query
        if report_type == 'distance' and sort_param in ('distance_asc','distance_desc'):
            pre_count_query = pre_count_query.filter(StopsMatched.distance_m != None)

        # Get total count
        total_count = pre_count_query.count()
        update_progress(task_id, 0, total_count, start_time)
        
        # Apply sorting and eager loading
        if report_type == 'unmatched':
            query = query.outerjoin(AtlasStop, StopsMatched.sloid == AtlasStop.sloid)
            if sort_param == 'operator_desc':
                query = query.order_by(*_operator_order_columns(ascending=False))
            else:
                query = query.order_by(*_operator_order_columns(ascending=True))
            query = optimize_query_for_endpoint(query, 'data')
            
        elif report_type == 'problems':
            query = query.outerjoin(AtlasStop, StopsMatched.sloid == AtlasStop.sloid)
            if sort_param == 'priority_asc':
                query = query.order_by(db.func.coalesce(Problem.priority, 999).asc(), Problem.stop_id, Problem.problem_type)
            elif sort_param == 'priority_desc':
                query = query.order_by(db.func.coalesce(Problem.priority, 999).desc(), Problem.stop_id, Problem.problem_type)
            elif sort_param == 'operator_desc':
                query = query.order_by(*_operator_order_columns(ascending=False), Problem.stop_id, Problem.problem_type)
            else:
                query = query.order_by(*_operator_order_columns(ascending=True), Problem.stop_id, Problem.problem_type)
            query = query.options(
                joinedload(Problem.stop).joinedload(StopsMatched.atlas_stop_details),
                joinedload(Problem.stop).joinedload(StopsMatched.osm_node_details)
            )
            
        else:  # distance
            query = query.outerjoin(AtlasStop, StopsMatched.sloid == AtlasStop.sloid)
            if sort_param == 'distance_asc':
                query = query.filter(StopsMatched.distance_m != None).order_by(StopsMatched.distance_m.asc())
            elif sort_param == 'distance_desc':
                query = query.filter(StopsMatched.distance_m != None).order_by(StopsMatched.distance_m.desc())
            elif sort_param == 'operator_desc':
                query = query.order_by(*_operator_order_columns(ascending=False))
            else:
                query = query.order_by(*_operator_order_columns(ascending=True))
            query = optimize_query_for_endpoint(query, 'reports')

        # Process in chunks to show progress
        chunk_size = 1000
        offset = 0
        all_data = []
        
        while True:
            with _state_lock:
                cancelled = task_id not in report_progress
            if cancelled:  # Check if cancelled
                return None
                
            chunk_query = query.offset(offset).limit(chunk_size)
            if isinstance(limit, int) and offset >= limit:
                break
                
            chunk_data = chunk_query.all()
            if not chunk_data:
                break
                
            all_data.extend(chunk_data)
            offset += len(chunk_data)
            
            # Apply limit if specified
            if isinstance(limit, int) and len(all_data) >= limit:
                all_data = all_data[:limit]
                break
                
            update_progress(task_id, min(offset, total_count), total_count, start_time)
            
            # Small delay to allow cancellation
            time.sleep(0.01)
        
        update_progress(task_id, len(all_data), total_count, start_time)
        return all_data, report_type
        
    except Exception as e:
        with _state_lock:
            if task_id in report_progress:
                report_progress[task_id]['status'] = 'error'
                report_progress[task_id]['error'] = str(e)
        print(f"Error in generate_report_data: {e}")
        return None


@reports_bp.route('/api/generate_report_async', methods=['POST'])
@limiter.limit("10/hour")
def generate_report_async():
    """Start async report generation"""
    try:
        # Lazy cleanup of stale reports on each new request
        _cleanup_stale_reports()

        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400

        task_id = str(uuid.uuid4())

        # Initialize progress tracking
        with _state_lock:
            report_progress[task_id] = {
                'status': 'starting',
                'processed': 0,
                'total': 0,
                'eta': None,
                'error': None,
                'created_at': datetime.now()
            }
        
        # Get the actual app instance for the background thread
        flask_app = app._get_current_object()
        
        # Start background thread
        thread = threading.Thread(target=background_report_generation, args=(data, task_id, flask_app))
        thread.daemon = True
        thread.start()
        
        return jsonify({
            "task_id": task_id,
            "status": "started"
        })
        
    except Exception as e:
        app.logger.error(f"Error starting async report: {str(e)}")
        return jsonify({"error": str(e)}), 500


def background_report_generation(params, task_id, flask_app):
    """Background function to generate report"""
    with flask_app.app_context():
        try:
            with _state_lock:
                if task_id not in report_progress:
                    return
                report_progress[task_id]['status'] = 'processing'

            # Generate report data
            result = generate_report_data(params, task_id)
            if result is None:
                return  # Cancelled or error
                
            data_for_report, report_type = result
            report_format = params.get('format', 'pdf').lower()
            include_fields_str = params.get('include_fields', '') or ''
            include_fields = [f.strip() for f in include_fields_str.split(',') if f.strip()]
            
            # Generate file
            temp_dir = tempfile.gettempdir()
            filename_stem = f"{report_type}_{params.get('sort', 'operator_asc')}_{task_id[:8]}"
            
            if report_format == 'csv':
                filename = f"{filename_stem}.csv"
                filepath = os.path.join(temp_dir, filename)
                
                with open(filepath, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    
                    # Write headers and data based on report type
                    if report_type == 'unmatched':
                        headers = ['Source', 'ATLAS Sloid', 'Official Designation', 'ATLAS Operator', 'OSM Node ID', 'OSM Local Ref', 'OSM Name', 'UIC Ref']
                        if 'atlas_coords' in include_fields:
                            headers.extend(['Atlas Lat', 'Atlas Lon'])
                        if 'osm_coords' in include_fields:
                            headers.extend(['OSM Lat', 'OSM Lon'])
                        writer.writerow(headers)
                        for stop in data_for_report:
                            source = 'ATLAS' if stop.stop_type == 'atlas_unmatched' else 'OSM'
                            atlas_details = getattr(stop, 'atlas_stop_details', None)
                            osm_details = getattr(stop, 'osm_node_details', None)
                            row = [
                                source,
                                stop.sloid or 'N/A',
                                (atlas_details.atlas_designation_official if atlas_details and atlas_details.atlas_designation_official else 'N/A'),
                                (atlas_details.atlas_business_org_abbr if atlas_details and atlas_details.atlas_business_org_abbr else 'N/A'),
                                stop.osm_node_id or 'N/A',
                                (osm_details.osm_local_ref if osm_details and osm_details.osm_local_ref else 'N/A'),
                                (osm_details.osm_name if osm_details and osm_details.osm_name else 'N/A'),
                                ((stop.atlas_stop_details.uic_ref if stop.atlas_stop_details and stop.atlas_stop_details.uic_ref else (stop.osm_node_details.osm_uic_ref if stop.osm_node_details else None)) or 'N/A')
                            ]
                            if 'atlas_coords' in include_fields:
                                row.extend([
                                    '{:.6f}'.format(stop.atlas_lat) if stop.atlas_lat is not None else 'N/A',
                                    '{:.6f}'.format(stop.atlas_lon) if stop.atlas_lon is not None else 'N/A'
                                ])
                            if 'osm_coords' in include_fields:
                                row.extend([
                                    '{:.6f}'.format(stop.osm_lat) if stop.osm_lat is not None else 'N/A',
                                    '{:.6f}'.format(stop.osm_lon) if stop.osm_lon is not None else 'N/A'
                                ])
                            writer.writerow(row)
                    elif report_type == 'problems':
                        headers = ['Problem Type', 'Priority', 'Solved', 'ATLAS Sloid', 'Official Designation', 'ATLAS Operator', 'OSM Node ID', 'Distance (m)', 'Matching Method', 'Solution']
                        if 'atlas_coords' in include_fields:
                            headers.extend(['Atlas Lat', 'Atlas Lon'])
                        if 'osm_coords' in include_fields:
                            headers.extend(['OSM Lat', 'OSM Lon'])
                        writer.writerow(headers)
                        for pr in data_for_report:
                            st = pr.stop
                            atlas_details = getattr(st, 'atlas_stop_details', None)
                            row = [
                                pr.problem_type,
                                pr.priority if pr.priority is not None else 'N/A',
                                'Yes' if pr.solution and str(pr.solution).strip() != '' else 'No',
                                st.sloid if st and st.sloid else 'N/A',
                                (atlas_details.atlas_designation_official if atlas_details and atlas_details.atlas_designation_official else 'N/A'),
                                (atlas_details.atlas_business_org_abbr if atlas_details and atlas_details.atlas_business_org_abbr else 'N/A'),
                                st.osm_node_id if st and st.osm_node_id else 'N/A',
                                ('{:.1f}'.format(st.distance_m) if st and st.distance_m is not None else 'N/A'),
                                st.match_type if st and st.match_type else 'N/A',
                                (pr.solution or '').strip()
                            ]
                            if 'atlas_coords' in include_fields:
                                row.extend([
                                    '{:.6f}'.format(st.atlas_lat) if st and st.atlas_lat is not None else 'N/A',
                                    '{:.6f}'.format(st.atlas_lon) if st and st.atlas_lon is not None else 'N/A'
                                ])
                            if 'osm_coords' in include_fields:
                                row.extend([
                                    '{:.6f}'.format(st.osm_lat) if st and st.osm_lat is not None else 'N/A',
                                    '{:.6f}'.format(st.osm_lon) if st and st.osm_lon is not None else 'N/A'
                                ])
                            writer.writerow(row)
                    else:  # distance
                        headers = ['ATLAS Sloid', 'Official Designation', 'ATLAS Operator', 'OSM Node ID', 'Distance (m)', 'Matching Method']
                        if 'atlas_coords' in include_fields:
                            headers.extend(['Atlas Lat', 'Atlas Lon'])
                        if 'osm_coords' in include_fields:
                            headers.extend(['OSM Lat', 'OSM Lon'])
                        writer.writerow(headers)
                        for stop in data_for_report:
                            row = [
                                stop.sloid if stop.sloid else 'N/A',
                                stop.atlas_stop_details.atlas_designation_official if stop.atlas_stop_details and stop.atlas_stop_details.atlas_designation_official else 'N/A',
                                stop.atlas_stop_details.atlas_business_org_abbr if stop.atlas_stop_details and stop.atlas_stop_details.atlas_business_org_abbr else 'N/A',
                                stop.osm_node_id if stop.osm_node_id else 'N/A',
                                '{:.1f}'.format(stop.distance_m) if stop.distance_m is not None else 'N/A',
                                stop.match_type if stop.match_type else 'N/A'
                            ]
                            if 'atlas_coords' in include_fields:
                                row.extend([
                                    '{:.6f}'.format(stop.atlas_lat) if stop.atlas_lat is not None else 'N/A',
                                    '{:.6f}'.format(stop.atlas_lon) if stop.atlas_lon is not None else 'N/A'
                                ])
                            if 'osm_coords' in include_fields:
                                row.extend([
                                    '{:.6f}'.format(stop.osm_lat) if stop.osm_lat is not None else 'N/A',
                                    '{:.6f}'.format(stop.osm_lon) if stop.osm_lon is not None else 'N/A'
                                ])
                            writer.writerow(row)
            else:  # PDF
                filename = f"{filename_stem}.pdf"
                filepath = os.path.join(temp_dir, filename)
                
                report_title_map = {
                    'distance': 'Top Distance Matched Pairs',
                    'unmatched': 'Unmatched Entries Report', 
                    'problems': 'Problems Report',
                    'summary': 'Statistics Summary Report'
                }
                report_title = report_title_map.get(report_type, 'OSM & ATLAS Report')
                
                if report_type == 'summary':
                    template = 'reports/stats_summary.html'
                    kwargs = {
                        'stats': data_for_report['stats'],
                        'problem_breakdown': data_for_report['problem_stats'].get('by_priority', {}),
                        'probs': data_for_report['problem_stats'],
                        'generated_at': datetime.now()
                    }
                else:
                    template = 'reports/report.html'
                    kwargs = {
                        'report_items': data_for_report,
                        'generated_at': datetime.now(),
                        'sort_order': params.get('sort', 'operator_asc'),
                        'report_title': report_title,
                        'report_type': report_type,
                        'include_fields': include_fields
                    }

                report_html = render_template(template, **kwargs)
                try:
                    from weasyprint import HTML
                except ModuleNotFoundError as exc:
                    raise RuntimeError(
                        "WeasyPrint is required to generate PDF reports. Install web dependencies."
                    ) from exc
                HTML(string=report_html).write_pdf(filepath)
            
            # Store completed report
            with _state_lock:
                completed_reports[task_id] = {
                    'file_path': filepath,
                    'filename': filename,
                    'created_at': datetime.now()
                }
                if task_id in report_progress:
                    report_progress[task_id]['status'] = 'completed'

        except Exception as e:
            with _state_lock:
                if task_id in report_progress:
                    report_progress[task_id]['status'] = 'error'
                    report_progress[task_id]['error'] = str(e)
            flask_app.logger.error(f"Background report generation error: {str(e)}")


@reports_bp.route('/api/report_progress/<task_id>', methods=['GET'])
@limiter.limit("60/minute")
def get_report_progress(task_id):
    """Get progress of report generation"""
    with _state_lock:
        if task_id not in report_progress:
            return jsonify({"error": "Task not found"}), 404
        progress = report_progress[task_id].copy()
    return jsonify(progress)


@reports_bp.route('/api/download_report/<task_id>', methods=['GET'])
@limiter.limit("20/minute")  
def download_report(task_id):
    """Download completed report"""
    with _state_lock:
        if task_id not in completed_reports:
            return jsonify({"error": "Report not found"}), 404
        report_info = completed_reports[task_id]
        filepath = report_info['file_path']
        filename = report_info['filename']
    
    if not os.path.exists(filepath):
        return jsonify({"error": "Report file not found"}), 404
    
    try:
        def remove_file():
            try:
                time.sleep(1)  # Give time for download to start
                os.remove(filepath)
                with _state_lock:
                    completed_reports.pop(task_id, None)
                    report_progress.pop(task_id, None)
            except Exception as e:
                # Non-critical cleanup failure - log for debugging
                app.logger.debug(f"Cleanup failed for report {task_id} (non-critical): {e}")
        
        # Schedule file cleanup
        cleanup_thread = threading.Thread(target=remove_file)
        cleanup_thread.daemon = True
        cleanup_thread.start()
        
        mimetype = 'application/pdf' if filename.endswith('.pdf') else 'text/csv'
        
        with open(filepath, 'rb') as f:
            file_data = f.read()
        
        response = app.response_class(file_data, mimetype=mimetype)
        response.headers["Content-Disposition"] = f"attachment; filename={filename}"
        return response
        
    except Exception as e:
        app.logger.error(f"Error downloading report: {str(e)}")
        return jsonify({"error": str(e)}), 500


@reports_bp.route('/api/cancel_report/<task_id>', methods=['POST'])
@limiter.limit("60/minute")
def cancel_report(task_id):
    """Cancel report generation"""
    with _state_lock:
        report_progress.pop(task_id, None)
        report_info = completed_reports.pop(task_id, None)
    if report_info:
        try:
            filepath = report_info['file_path']
            if os.path.exists(filepath):
                os.remove(filepath)
        except Exception as e:
            # Non-critical cleanup failure - log for debugging
            app.logger.debug(f"Failed to clean up report file (non-critical): {e}")

    return jsonify({"status": "cancelled"})


@reports_bp.route('/api/generate_report', methods=['GET'])
@limiter.limit("20/day")
def generate_report():
    try:
        # Limit: support 'all' or numeric
        limit_raw = (request.args.get('limit', '10') or '10').strip().lower()
        limit = None if limit_raw == 'all' else int(limit_raw)
        # Sort: default operator ascending
        sort_param = request.args.get('sort', 'operator_asc')
        # New categories: 'distance' | 'unmatched' | 'problems'
        report_type = (request.args.get('report_type', 'distance') or 'distance').lower()
        # Backward compatibility
        if report_type in ('top_matches', 'exact_matches', 'name_matches'):
            report_type = 'distance'
        report_format = (request.args.get('format', 'pdf') or 'pdf').lower()
        include_fields_str = request.args.get('include_fields', '') or ''
        include_fields = [f.strip() for f in include_fields_str.split(',') if f.strip()]

        # Common filters
        atlas_operator_str = request.args.get('atlas_operator', '')
        atlas_operators = [op.strip() for op in atlas_operator_str.split(',') if op and op.strip()]

        data_for_report = []
        report_title = "OSM & ATLAS Report"

        def _apply_atlas_operator_filter(query):
            if not atlas_operators:
                return query
            return query.filter(StopsMatched.atlas_stop_details.has(AtlasStop.atlas_business_org_abbr.in_(atlas_operators)))

        # Normalize sort per report type
        def _normalize_sort(rt, s):
            allowed = {
                'distance': {'operator_asc','operator_desc','distance_asc','distance_desc'},
                'unmatched': {'operator_asc','operator_desc'},
                'problems': {'operator_asc','operator_desc','priority_asc','priority_desc'}
            }
            s = (s or '').strip().lower()
            if s not in allowed.get(rt, set()):
                return 'distance_desc' if rt == 'distance' else ('priority_desc' if rt == 'problems' else 'operator_asc')
            return s

        sort_param = _normalize_sort(report_type, sort_param)

        def _operator_order_columns(ascending=True):
            nulls_first_col = case((AtlasStop.atlas_business_org_abbr == None, 0), else_=1)
            return ((nulls_first_col.asc(), AtlasStop.atlas_business_org_abbr.asc()) if ascending else (nulls_first_col.asc(), AtlasStop.atlas_business_org_abbr.desc()))

        if report_type == 'unmatched':
            # sources: 'atlas', 'osm' (both by default)
            sources_str = request.args.get('sources', 'atlas,osm')
            sources = set([s.strip().lower() for s in sources_str.split(',') if s.strip()])
            valid_sources = {'atlas', 'osm'}
            sources = sources.intersection(valid_sources) or {'atlas', 'osm'}

            query = StopsMatched.query
            if sources == {'atlas', 'osm'}:
                query = query.filter(StopsMatched.stop_type.in_(['atlas_unmatched', 'osm_unmatched']))
            elif 'atlas' in sources:
                query = query.filter(StopsMatched.stop_type == 'atlas_unmatched')
            else:
                query = query.filter(StopsMatched.stop_type == 'osm_unmatched')

            # Operator filter applies only where ATLAS data exists; .has() will naturally drop OSM-only
            query = _apply_atlas_operator_filter(query)

            # For unmatched we may need both atlas and osm details in template; use 'data' for full eager load
            query = optimize_query_for_endpoint(query, 'data')

            # Join AtlasStop for operator sorting
            query = query.outerjoin(AtlasStop, StopsMatched.sloid == AtlasStop.sloid)
            if sort_param == 'operator_desc':
                query = query.order_by(*_operator_order_columns(ascending=False))
            else:
                query = query.order_by(*_operator_order_columns(ascending=True))

            data_for_report = (query.limit(limit).all() if isinstance(limit, int) else query.all())
            report_title = "Unmatched Entries Report"

        elif report_type == 'problems':
            # Filters: problem_types, priorities, solution_status
            problem_types_str = request.args.get('problem_types', '')
            selected_types = [t.strip() for t in problem_types_str.split(',') if t.strip()]
            valid_problem_types = {'distance', 'unmatched', 'attributes', 'duplicates'}
            if selected_types:
                selected_types = [t for t in selected_types if t in valid_problem_types]
            else:
                selected_types = list(valid_problem_types)

            priorities_str = request.args.get('priorities', '')
            selected_priorities = []
            if priorities_str:
                for p in priorities_str.split(','):
                    p = p.strip()
                    if not p:
                        continue
                    try:
                        pi = int(p)
                        if pi in (1, 2, 3):
                            selected_priorities.append(pi)
                    except Exception:
                        continue

            solution_status_str = request.args.get('solution_status', '')
            solution_status = set([s.strip().lower() for s in solution_status_str.split(',') if s.strip()])
            # valid: 'solved', 'unsolved'; if none provided => include both

            query = db.session.query(Problem).join(StopsMatched)
            if selected_types:
                query = query.filter(Problem.problem_type.in_(selected_types))

            if selected_priorities:
                query = query.filter(Problem.priority.in_(selected_priorities))

            # Solution status filter
            if solution_status == {'solved'}:
                query = query.filter(Problem.solution.isnot(None), Problem.solution != '')
            elif solution_status == {'unsolved'}:
                query = query.filter((Problem.solution.is_(None)) | (Problem.solution == ''))
            else:
                # both or none selected => no filter
                pass

            # Operator filter (applies to StopsMatched -> AtlasStop)
            if atlas_operators:
                query = query.filter(StopsMatched.atlas_stop_details.has(AtlasStop.atlas_business_org_abbr.in_(atlas_operators)))

            # Sorting for problems
            # Join AtlasStop for operator sorts
            query = query.outerjoin(AtlasStop, StopsMatched.sloid == AtlasStop.sloid)

            if sort_param == 'priority_asc':
                query = query.order_by(db.func.coalesce(Problem.priority, 999).asc(), Problem.stop_id, Problem.problem_type)
            elif sort_param == 'priority_desc':
                query = query.order_by(db.func.coalesce(Problem.priority, 999).desc(), Problem.stop_id, Problem.problem_type)
            elif sort_param == 'operator_desc':
                query = query.order_by(*_operator_order_columns(ascending=False), Problem.stop_id, Problem.problem_type)
            else:
                query = query.order_by(*_operator_order_columns(ascending=True), Problem.stop_id, Problem.problem_type)

            # Eager load stop + atlas/osm details when rendering template
            query = query.options(
                joinedload(Problem.stop).joinedload(StopsMatched.atlas_stop_details),
                joinedload(Problem.stop).joinedload(StopsMatched.osm_node_details)
            )

            data_for_report = (query.limit(limit).all() if isinstance(limit, int) else query.all())
            report_title = "Problems Report"

        else:
            # distance: Top distance matched pairs
            query = StopsMatched.query.filter(StopsMatched.stop_type == 'matched')

            # Operator filter
            query = _apply_atlas_operator_filter(query)

            # Join AtlasStop for operator sorts
            query = query.outerjoin(AtlasStop, StopsMatched.sloid == AtlasStop.sloid)

            # Sorting
            if sort_param == 'distance_asc':
                query = query.filter(StopsMatched.distance_m != None).order_by(StopsMatched.distance_m.asc())
            elif sort_param == 'distance_desc':
                query = query.filter(StopsMatched.distance_m != None).order_by(StopsMatched.distance_m.desc())
            elif sort_param == 'operator_desc':
                query = query.order_by(*_operator_order_columns(ascending=False))
            else:
                query = query.order_by(*_operator_order_columns(ascending=True))

            query = optimize_query_for_endpoint(query, 'reports')
            data_for_report = (query.limit(limit).all() if isinstance(limit, int) else query.all())
            report_title = "Top Distance Matched Pairs"

        if data_for_report is None:
            data_for_report = []

        # CSV export
        if report_format == 'csv':
            si = StringIO()
            cw = csv.writer(si)

            if report_type == 'unmatched':
                # Unified columns for both sources, with blanks for N/A
                headers = [
                    'Source', 'ATLAS Sloid', 'Official Designation', 'ATLAS Operator',
                    'OSM Node ID', 'OSM Local Ref', 'OSM Name', 'UIC Ref'
                ]
                if 'atlas_coords' in include_fields:
                    headers.extend(['Atlas Lat', 'Atlas Lon'])
                if 'osm_coords' in include_fields:
                    headers.extend(['OSM Lat', 'OSM Lon'])
                cw.writerow(headers)
                for stop in data_for_report:
                    source = 'ATLAS' if stop.stop_type == 'atlas_unmatched' else 'OSM'
                    atlas_details = getattr(stop, 'atlas_stop_details', None)
                    osm_details = getattr(stop, 'osm_node_details', None)
                    row = [
                        source,
                        stop.sloid or 'N/A',
                        (atlas_details.atlas_designation_official if atlas_details and atlas_details.atlas_designation_official else 'N/A'),
                        (atlas_details.atlas_business_org_abbr if atlas_details and atlas_details.atlas_business_org_abbr else 'N/A'),
                        stop.osm_node_id or 'N/A',
                        (osm_details.osm_local_ref if osm_details and osm_details.osm_local_ref else 'N/A'),
                        (osm_details.osm_name if osm_details and osm_details.osm_name else 'N/A'),
                        ((stop.atlas_stop_details.uic_ref if stop.atlas_stop_details and stop.atlas_stop_details.uic_ref else (stop.osm_node_details.osm_uic_ref if stop.osm_node_details else None)) or 'N/A')
                    ]
                    if 'atlas_coords' in include_fields:
                        row.extend([
                            '{:.6f}'.format(stop.atlas_lat) if stop.atlas_lat is not None else 'N/A',
                            '{:.6f}'.format(stop.atlas_lon) if stop.atlas_lon is not None else 'N/A'
                        ])
                    if 'osm_coords' in include_fields:
                        row.extend([
                            '{:.6f}'.format(stop.osm_lat) if stop.osm_lat is not None else 'N/A',
                            '{:.6f}'.format(stop.osm_lon) if stop.osm_lon is not None else 'N/A'
                        ])
                    cw.writerow(row)

            elif report_type == 'problems':
                headers = [
                    'Problem Type', 'Priority', 'Solved', 'ATLAS Sloid', 'Official Designation',
                    'ATLAS Operator', 'OSM Node ID', 'Distance (m)', 'Matching Method', 'Solution'
                ]
                if 'atlas_coords' in include_fields:
                    headers.extend(['Atlas Lat', 'Atlas Lon'])
                if 'osm_coords' in include_fields:
                    headers.extend(['OSM Lat', 'OSM Lon'])
                cw.writerow(headers)
                for pr in data_for_report:
                    st = pr.stop
                    atlas_details = getattr(st, 'atlas_stop_details', None)
                    row = [
                        pr.problem_type,
                        pr.priority if pr.priority is not None else 'N/A',
                        'Yes' if pr.solution and str(pr.solution).strip() != '' else 'No',
                        st.sloid if st and st.sloid else 'N/A',
                        (atlas_details.atlas_designation_official if atlas_details and atlas_details.atlas_designation_official else 'N/A'),
                        (atlas_details.atlas_business_org_abbr if atlas_details and atlas_details.atlas_business_org_abbr else 'N/A'),
                        st.osm_node_id if st and st.osm_node_id else 'N/A',
                        ('{:.1f}'.format(st.distance_m) if st and st.distance_m is not None else 'N/A'),
                        st.match_type if st and st.match_type else 'N/A',
                        (pr.solution or '').strip()
                    ]
                    if 'atlas_coords' in include_fields:
                        row.extend([
                            '{:.6f}'.format(st.atlas_lat) if st and st.atlas_lat is not None else 'N/A',
                            '{:.6f}'.format(st.atlas_lon) if st and st.atlas_lon is not None else 'N/A'
                        ])
                    if 'osm_coords' in include_fields:
                        row.extend([
                            '{:.6f}'.format(st.osm_lat) if st and st.osm_lat is not None else 'N/A',
                            '{:.6f}'.format(st.osm_lon) if st and st.osm_lon is not None else 'N/A'
                        ])
                    cw.writerow(row)

            else:
                # distance
                headers = ['ATLAS Sloid', 'Official Designation', 'ATLAS Operator', 'OSM Node ID', 'Distance (m)', 'Matching Method']
                if 'atlas_coords' in include_fields:
                    headers.extend(['Atlas Lat', 'Atlas Lon'])
                if 'osm_coords' in include_fields:
                    headers.extend(['OSM Lat', 'OSM Lon'])
                cw.writerow(headers)
                for stop in data_for_report:
                    row = [
                        stop.sloid if stop.sloid else 'N/A',
                        stop.atlas_stop_details.atlas_designation_official if stop.atlas_stop_details and stop.atlas_stop_details.atlas_designation_official else 'N/A',
                        stop.atlas_stop_details.atlas_business_org_abbr if stop.atlas_stop_details and stop.atlas_stop_details.atlas_business_org_abbr else 'N/A',
                        stop.osm_node_id if stop.osm_node_id else 'N/A',
                        '{:.1f}'.format(stop.distance_m) if stop.distance_m is not None else 'N/A',
                        stop.match_type if stop.match_type else 'N/A'
                    ]
                    if 'atlas_coords' in include_fields:
                        row.extend([
                            '{:.6f}'.format(stop.atlas_lat) if stop.atlas_lat is not None else 'N/A',
                            '{:.6f}'.format(stop.atlas_lon) if stop.atlas_lon is not None else 'N/A'
                        ])
                    if 'osm_coords' in include_fields:
                        row.extend([
                            '{:.6f}'.format(stop.osm_lat) if stop.osm_lat is not None else 'N/A',
                            '{:.6f}'.format(stop.osm_lon) if stop.osm_lon is not None else 'N/A'
                        ])
                    cw.writerow(row)

            output = si.getvalue()
            response_filename_stem = f"{report_type}_{sort_param}"
            response = app.response_class(output, mimetype='text/csv')
            response.headers["Content-Disposition"] = f"attachment; filename={response_filename_stem}.csv"
            return response

        # PDF export using template
        pdf_filename_stem = f"{report_type}_{sort_param}"
        report_html = render_template(
            'reports/report.html',
            report_items=data_for_report,
            generated_at=datetime.now(),
            sort_order=sort_param,
            report_title=report_title,
            report_type=report_type,
            include_fields=include_fields
        )
        pdf = pdfkit.from_string(report_html, False)
        response = app.response_class(pdf, mimetype='application/pdf')
        response.headers["Content-Disposition"] = f"attachment; filename={pdf_filename_stem}.pdf"
        return response
    except Exception as e:
        app.logger.error(f"Error generating report: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500


