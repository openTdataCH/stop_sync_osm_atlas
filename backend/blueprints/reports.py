from flask import Blueprint, request, jsonify, render_template, current_app as app, send_file
from backend.models import StopsMatched, Problem, AtlasStop
from backend.extensions import db, limiter
from sqlalchemy.orm import joinedload
from backend.queries.helpers import optimize_query_for_endpoint
from backend.services.problem_filters import VISIBLE_PROBLEM_TYPES
from backend.services.request_payload import read_request_payload
from datetime import datetime
import csv
from io import StringIO
import time
import os
import shutil
import tempfile
from sqlalchemy import case

from backend.services.async_export import (
    start_task,
    update_progress as ae_update_progress,
    set_task_status,
    get_progress,
    get_completed_file,
    cancel_task,
)

reports_bp = Blueprint('reports', __name__)



def _copy_summary_pdf_to_temp(task_id):
    from backend.services.stats_export import ensure_stats_summary_pdf_generated

    source_path = ensure_stats_summary_pdf_generated()
    filename = f"stats_summary_{task_id[:8]}.pdf"
    dest_path = os.path.join(tempfile.gettempdir(), filename)
    shutil.copy2(source_path, dest_path)
    return dest_path, filename


def _normalize_report_type(report_type):
    return (report_type or 'distance').strip().lower()


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


_CSV_HEADERS = {
    'unmatched': ['Source', 'ATLAS Sloid', 'Official Designation', 'ATLAS Operator', 'OSM Node ID', 'OSM Local Ref', 'OSM Name', 'UIC Ref'],
    'problems': ['Problem Type', 'Priority', 'ATLAS Sloid', 'Official Designation', 'ATLAS Operator', 'OSM Node ID', 'Distance (m)', 'Matching Method'],
    'distance': ['ATLAS Sloid', 'Official Designation', 'ATLAS Operator', 'OSM Node ID', 'Distance (m)', 'Matching Method'],
}
_CSV_COORDINATES = {
    'atlas_coords': (('Atlas Lat', 'atlas_lat'), ('Atlas Lon', 'atlas_lon')),
    'osm_coords': (('OSM Lat', 'osm_lat'), ('OSM Lon', 'osm_lon')),
}


def _csv_coordinates(include_fields):
    """(header, Stop attribute) of each coordinate column the user asked for, in report order."""
    return [column for field, columns in _CSV_COORDINATES.items() if field in include_fields for column in columns]


def _csv_row(item, report_type):
    """The columns before the coordinates. ``item`` is a Problem in problems reports and a Stop otherwise."""
    stop = item.stop if report_type == 'problems' else item
    atlas = getattr(stop, 'atlas_stop_details', None)
    sloid = stop.sloid if stop and stop.sloid else 'N/A'
    designation = atlas.atlas_designation_official if atlas and atlas.atlas_designation_official else 'N/A'
    operator = atlas.atlas_business_org_abbr if atlas and atlas.atlas_business_org_abbr else 'N/A'
    osm_node_id = stop.osm_node_id if stop and stop.osm_node_id else 'N/A'
    if report_type == 'unmatched':
        osm = stop.osm_node_details
        uic_ref = atlas.uic_ref if atlas and atlas.uic_ref else (osm.osm_uic_ref if osm else None)
        return ['ATLAS' if stop.stop_type == 'atlas_unmatched' else 'OSM', sloid, designation, operator, osm_node_id,
                osm.osm_local_ref if osm and osm.osm_local_ref else 'N/A',
                osm.osm_name if osm and osm.osm_name else 'N/A',
                uic_ref or 'N/A']
    row = [sloid, designation, operator, osm_node_id,
           '{:.1f}'.format(stop.distance_m) if stop and stop.distance_m is not None else 'N/A',
           stop.match_type if stop and stop.match_type else 'N/A']
    if report_type == 'problems':
        return [item.problem_type, item.priority if item.priority is not None else 'N/A', *row]
    return row


def _serialize_report_csv(data_for_report, report_type, include_fields):
    si = StringIO()
    writer = csv.writer(si)
    coordinates = _csv_coordinates(include_fields)
    writer.writerow(_CSV_HEADERS.get(report_type, _CSV_HEADERS['distance']) + [header for header, _ in coordinates])
    for item in data_for_report:
        stop = item.stop if report_type == 'problems' else item
        values = [getattr(stop, name, None) for _, name in coordinates]
        writer.writerow(_csv_row(item, report_type) + ['N/A' if value is None else '{:.6f}'.format(value) for value in values])
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
    css_content = get_report_css_content(['static/css/src/01-settings/tokens.css', 'static/css/pages/reports.css'])
    
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

    from weasyprint import HTML

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
                selected_types = [t for t in selected_types if t in VISIBLE_PROBLEM_TYPES]
            else:
                selected_types = list(VISIBLE_PROBLEM_TYPES)

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
    """Start a data export or the summary PDF; /api/exports/<task_id>/… follows it."""
    try:
        data = read_request_payload(request)
        if not data:
            return jsonify({"error": "No data provided"}), 400

        report_type = _normalize_report_type(data.get('report_type', 'distance'))
        report_format = str(data.get('format', 'pdf')).strip().lower()
        if report_type not in {'distance', 'unmatched', 'problems', 'summary'}:
            return jsonify({"error": "Invalid report_type provided"}), 400
        if report_type == 'summary' and report_format != 'pdf':
            return jsonify({"error": "Summary report only supports PDF format"}), 400

        return jsonify({"task_id": start_task(_write_report, data), "status": "started"})

    except Exception as e:
        app.logger.error(f"Error starting async report: {str(e)}")
        return jsonify({"error": str(e)}), 500


def _write_report(task_id, params):
    """Write the export file of a task; None when it was cancelled or failed."""
    report_type = _normalize_report_type(params.get('report_type', 'distance'))
    if report_type == 'summary':
        return _copy_summary_pdf_to_temp(task_id)

    result = generate_report_data(params, task_id)
    if result is None:
        return None  # Cancelled, or the error is recorded

    data_for_report, _ = result
    report_format = str(params.get('format', 'pdf')).strip().lower()
    include_fields = _parse_include_fields(params.get('include_fields', ''))
    sort_param = _normalize_sort(report_type, params.get('sort', 'operator_asc'))
    extension = 'csv' if report_format == 'csv' else 'pdf'
    filename = f"{report_type}_{sort_param}_{task_id[:8]}.{extension}"
    filepath = os.path.join(tempfile.gettempdir(), filename)

    # Data collection is complete; file rendering/writing may still take time.
    set_task_status(task_id, 'finalizing')
    _write_report_file(filepath, data_for_report, report_type, report_format, include_fields, sort_param)
    return filepath, filename


# Every export (data, summary and documentation PDF) is followed through these.
@reports_bp.route('/api/exports/<task_id>/progress', methods=['GET'])
@limiter.limit("240/minute")
def export_progress(task_id):
    progress = get_progress(task_id)
    if not progress:
        return jsonify({"error": "Task not found"}), 404
    return jsonify(progress)


@reports_bp.route('/api/exports/<task_id>/download', methods=['GET'])
@limiter.limit("20/minute")
def export_download(task_id):
    task_info = get_completed_file(task_id)
    if not task_info or not os.path.exists(task_info['file_path']):
        return jsonify({"error": "File not found"}), 404
    # The type follows the name: .pdf or .csv.
    return send_file(task_info['file_path'], as_attachment=True, download_name=task_info['filename'])


@reports_bp.route('/api/exports/<task_id>/cancel', methods=['POST'])
@limiter.limit("60/minute")
def export_cancel(task_id):
    cancel_task(task_id)
    return jsonify({"status": "cancelled"})
