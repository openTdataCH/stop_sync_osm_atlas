from flask import Blueprint, request, jsonify, render_template, current_app as app, send_file
from backend.models import StopsMatched, Problem, AtlasStop
from backend.extensions import db, limiter
from sqlalchemy.orm import joinedload
from backend.queries.helpers import optimize_query_for_endpoint
from backend.services.request_payload import read_request_payload
from datetime import datetime
import csv
from io import StringIO
import threading
import time
import uuid
import os
import shutil
import tempfile
from sqlalchemy import case

from backend.services.async_export import (
    start_cleanup_thread,
    cleanup_stale_tasks,
    init_task,
    update_progress as ae_update_progress,
    set_task_status,
    complete_task,
    get_progress,
    get_completed_file,
    cancel_task as ae_cancel_task,
)

reports_bp = Blueprint('reports', __name__)

PROBLEM_REPORT_TYPES = (
    'distance',
    'unmatched',
    'attributes',
    'contradicts_route_matching',
    'duplicates',
)


def _copy_summary_pdf_to_temp(task_id):
    from backend.services.stats_export import ensure_stats_summary_pdf_generated

    source_path = ensure_stats_summary_pdf_generated(force=False)
    filename = f"stats_summary_{task_id[:8]}.pdf"
    dest_path = os.path.join(tempfile.gettempdir(), filename)
    shutil.copy2(source_path, dest_path)
    return dest_path, filename


def _send_summary_pdf_response(download_name='summary_operator_asc.pdf'):
    from backend.services.stats_export import ensure_stats_summary_pdf_generated

    pdf_path = ensure_stats_summary_pdf_generated(force=False)
    return send_file(
        pdf_path,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=download_name,
    )


def _normalize_report_type(report_type):
    normalized = (report_type or 'distance').strip().lower()
    if normalized in ('top_matches', 'exact_matches', 'name_matches'):
        return 'distance'
    return normalized


def _normalize_sort(report_type, sort_param):
    allowed = {
        'distance': {'operator_asc', 'operator_desc', 'distance_asc', 'distance_desc'},
        'unmatched': {'operator_asc', 'operator_desc'},
        'problems': {'operator_asc', 'operator_desc', 'priority_asc', 'priority_desc'},
        'summary': {'operator_asc'},
    }
    normalized_sort = (sort_param or '').strip().lower()
    if normalized_sort not in allowed.get(report_type, set()):
        return 'distance_desc' if report_type == 'distance' else ('priority_desc' if report_type == 'problems' else 'operator_asc')
    return normalized_sort


def _parse_include_fields(raw):
    include_fields_str = raw or ''
    return [field.strip() for field in include_fields_str.split(',') if field.strip()]


def _serialize_report_csv(data_for_report, report_type, include_fields):
    si = StringIO()
    writer = csv.writer(si)

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
        headers = ['Problem Type', 'Priority', 'ATLAS Sloid', 'Official Designation', 'ATLAS Operator', 'OSM Node ID', 'Distance (m)', 'Matching Method']
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
                st.sloid if st and st.sloid else 'N/A',
                (atlas_details.atlas_designation_official if atlas_details and atlas_details.atlas_designation_official else 'N/A'),
                (atlas_details.atlas_business_org_abbr if atlas_details and atlas_details.atlas_business_org_abbr else 'N/A'),
                st.osm_node_id if st and st.osm_node_id else 'N/A',
                ('{:.1f}'.format(st.distance_m) if st and st.distance_m is not None else 'N/A'),
                st.match_type if st and st.match_type else 'N/A',
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

    else:
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

    return si.getvalue()


def _render_report_pdf_bytes(data_for_report, report_type, include_fields, sort_order):
    if report_type == 'summary':
        raise ValueError("Summary PDF rendering is handled by stats_export.")

    report_title_map = {
        'distance': 'Top Distance Matched Pairs',
        'unmatched': 'Unmatched Entries Report',
        'problems': 'Problems Report',
    }
    from backend.services.stats_export import get_report_css_content
    css_content = get_report_css_content(['static/css/pages/reports.css'])
    
    report_title = report_title_map.get(report_type, 'OSM & ATLAS Report')

    report_html = render_template(
        'reports/report.html',
        report_items=data_for_report,
        generated_at=datetime.now(),
        sort_order=sort_order,
        report_title=report_title,
        report_type=report_type,
        include_fields=include_fields,
        css_content=css_content,
        pdf_assets_prefix='static/vendor/'
    )

    try:
        from weasyprint import HTML
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "WeasyPrint is required to generate PDF reports. Install web dependencies."
        ) from exc

    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return HTML(string=report_html, base_url=base_dir).write_pdf()


def _write_report_file(filepath, data_for_report, report_type, report_format, include_fields, sort_order):
    if report_format == 'csv':
        output = _serialize_report_csv(data_for_report, report_type, include_fields)
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            f.write(output)
        return

    pdf_bytes = _render_report_pdf_bytes(data_for_report, report_type, include_fields, sort_order)
    with open(filepath, 'wb') as f:
        f.write(pdf_bytes)


# Removed local threading/cleanup logic in favor of async_export service


def update_progress(task_id, processed, total, start_time=None):
    """Update progress for a report generation task"""
    ae_update_progress(task_id, processed, total, start_time)
    print(f"Progress {task_id}: {processed}/{total}")


def generate_report_data(params, task_id=None):
    """Generate report data, optionally with progress tracking."""
    try:
        start_time = time.time()
        
        # Parse parameters (similar to existing function)
        limit_raw = str(params.get('limit', '10') or '10').strip().lower()
        limit = None if limit_raw == 'all' else int(limit_raw)
        report_type = _normalize_report_type(params.get('report_type', 'distance'))
        report_format = str(params.get('format', 'pdf')).strip().lower()
        sort_param = _normalize_sort(report_type, params.get('sort', 'operator_asc'))

        if report_type == 'summary':
            raise ValueError("Summary exports are handled by stats_export.")
        
        atlas_operator_str = params.get('atlas_operator', '')
        atlas_operators = [op.strip() for op in atlas_operator_str.split(',') if op and op.strip()]

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
            if selected_types:
                selected_types = [t for t in selected_types if t in PROBLEM_REPORT_TYPES]
            else:
                selected_types = list(PROBLEM_REPORT_TYPES)

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

            query = db.session.query(Problem).join(StopsMatched)
            if selected_types:
                query = query.filter(Problem.problem_type.in_(selected_types))
            if selected_priorities:
                query = query.filter(Problem.priority.in_(selected_priorities))
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
        actual_total = min(limit, total_count) if limit is not None else total_count

        if report_format == 'pdf' and report_type != 'summary' and actual_total > 2000:
            raise ValueError(f"Cannot generate a PDF with {actual_total} entries due to memory constraints. Please reduce your limit or export as CSV instead.")

        if task_id is not None:
            update_progress(task_id, 0, actual_total, start_time)
        
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
            if task_id is not None:
                current_prog = get_progress(task_id)
                if current_prog is None:
                    return None  # cancelled
                
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
                
            if task_id is not None:
                update_progress(task_id, min(offset, actual_total), actual_total, start_time)
            
            # Small delay to allow cancellation
            time.sleep(0.01)
        
        if task_id is not None:
            update_progress(task_id, len(all_data), actual_total, start_time)
        return all_data, report_type
        
    except Exception as e:
        if task_id is not None:
            set_task_status(task_id, 'error', str(e))
        print(f"Error in generate_report_data: {e}")
        return None


@reports_bp.route('/api/generate_report_async', methods=['POST'])
@limiter.limit("10/hour")
def generate_report_async():
    """Start async report generation"""
    try:
        start_cleanup_thread()
        cleanup_stale_tasks()

        data = read_request_payload(request)
        if not data:
            return jsonify({"error": "No data provided"}), 400

        report_type = _normalize_report_type(data.get('report_type', 'distance'))
        report_format = str(data.get('format', 'pdf')).strip().lower()
        if report_type not in {'distance', 'unmatched', 'problems', 'summary'}:
            return jsonify({"error": "Invalid report_type provided"}), 400
        if report_type == 'summary' and report_format != 'pdf':
            return jsonify({"error": "Summary report only supports PDF format"}), 400

        task_id = str(uuid.uuid4())
        init_task(task_id)
        
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
            if get_progress(task_id) is None:
                return
            set_task_status(task_id, 'processing')
            
            report_type = _normalize_report_type(params.get('report_type', 'distance'))
            report_format = params.get('format', 'pdf').lower()
            
            if report_type == 'summary' and report_format == 'pdf':
                dest_path, filename = _copy_summary_pdf_to_temp(task_id)
                complete_task(task_id, dest_path, filename)
                ae_update_progress(task_id, 1, 1)
                return

            if report_type == 'summary':
                raise ValueError("Summary report only supports PDF format")

            # Proceed normally for customized reports
            result = generate_report_data(params, task_id)
            if result is None:
                return  # Cancelled or error
                
            data_for_report, _ = result
            report_format = params.get('format', 'pdf').lower()
            include_fields = _parse_include_fields(params.get('include_fields', ''))
            sort_param = _normalize_sort(report_type, params.get('sort', 'operator_asc'))
            
            # Generate file
            temp_dir = tempfile.gettempdir()
            filename_stem = f"{report_type}_{sort_param}_{task_id[:8]}"
            extension = 'csv' if report_format == 'csv' else 'pdf'
            filename = f"{filename_stem}.{extension}"
            filepath = os.path.join(temp_dir, filename)

            # Data collection is complete; file rendering/writing may still take time.
            set_task_status(task_id, 'finalizing')

            _write_report_file(
                filepath,
                data_for_report,
                report_type,
                report_format,
                include_fields,
                sort_param,
            )
            
            # Store completed report
            complete_task(task_id, filepath, filename)

        except Exception as e:
            set_task_status(task_id, 'error', str(e))
            flask_app.logger.error(f"Background report generation error: {str(e)}")


@reports_bp.route('/api/report_progress/<task_id>', methods=['GET'])
# Keep this higher so older clients polling at 500ms don't stall on 429.
@limiter.limit("240/minute")
def get_report_progress(task_id):
    """Get progress of report generation"""
    progress = get_progress(task_id)
    if not progress:
        return jsonify({"error": "Task not found"}), 404
    return jsonify(progress)


@reports_bp.route('/api/download_report/<task_id>', methods=['GET'])
@limiter.limit("20/minute")  
def download_report(task_id):
    """Download completed report"""
    task_info = get_completed_file(task_id)
    if not task_info:
        return jsonify({"error": "Report not found"}), 404
    
    filepath = task_info['file_path']
    filename = task_info['filename']
    
    if not os.path.exists(filepath):
        return jsonify({"error": "Report file not found"}), 404
    
    try:
        mimetype = 'application/pdf' if filename.endswith('.pdf') else 'text/csv'
        response = send_file(
            filepath,
            mimetype=mimetype,
            as_attachment=True,
            download_name=filename,
        )

        return response
        
    except Exception as e:
        app.logger.error(f"Error downloading report: {str(e)}")
        return jsonify({"error": str(e)}), 500


@reports_bp.route('/api/cancel_report/<task_id>', methods=['POST'])
@limiter.limit("60/minute")
def cancel_report(task_id):
    """Cancel report generation"""
    ae_cancel_task(task_id)
    return jsonify({"status": "cancelled"})


@reports_bp.route('/api/generate_report', methods=['GET'])
@limiter.limit("20/day")
def generate_report():
    try:
        report_type = _normalize_report_type(request.args.get('report_type', 'distance'))
        report_format = (request.args.get('format', 'pdf') or 'pdf').lower()
        sort_param = _normalize_sort(report_type, request.args.get('sort', 'operator_asc'))
        include_fields = _parse_include_fields(request.args.get('include_fields', ''))

        if report_type == 'summary':
            if report_format != 'pdf':
                return jsonify({"status": "error", "message": "Summary report only supports PDF format"}), 400
            return _send_summary_pdf_response(download_name=f"summary_{sort_param}.pdf")

        result = generate_report_data(request.args)
        if result is None:
            return jsonify({"status": "error", "message": "Could not generate report data."}), 500

        data_for_report, report_type = result
        sort_param = _normalize_sort(report_type, request.args.get('sort', 'operator_asc'))

        if report_format == 'csv':
            output = _serialize_report_csv(data_for_report, report_type, include_fields)
            response = app.response_class(output, mimetype='text/csv')
            response.headers["Content-Disposition"] = f"attachment; filename={report_type}_{sort_param}.csv"
            return response

        pdf = _render_report_pdf_bytes(data_for_report, report_type, include_fields, sort_param)
        response = app.response_class(pdf, mimetype='application/pdf')
        response.headers["Content-Disposition"] = f"attachment; filename={report_type}_{sort_param}.pdf"
        return response
    except Exception as e:
        app.logger.error(f"Error generating report: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500


