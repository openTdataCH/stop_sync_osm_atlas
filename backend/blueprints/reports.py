from flask import Blueprint, request, jsonify, render_template, current_app as app
from backend.models import Stop, Problem, AtlasStop
from backend.extensions import db, limiter
from sqlalchemy.orm import joinedload
from backend.query_helpers import optimize_query_for_endpoint
from datetime import datetime
import pdfkit
import csv
from io import StringIO

reports_bp = Blueprint('reports', __name__)


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

        # Common filters
        atlas_operator_str = request.args.get('atlas_operator', '')
        atlas_operators = [op.strip() for op in atlas_operator_str.split(',') if op and op.strip()]

        data_for_report = []
        report_title = "OSM & ATLAS Report"

        def _apply_atlas_operator_filter(query):
            if not atlas_operators:
                return query
            return query.filter(Stop.atlas_stop_details.has(AtlasStop.atlas_business_org_abbr.in_(atlas_operators)))

        if report_type == 'unmatched':
            # sources: 'atlas', 'osm' (both by default)
            sources_str = request.args.get('sources', 'atlas,osm')
            sources = set([s.strip().lower() for s in sources_str.split(',') if s.strip()])
            valid_sources = {'atlas', 'osm'}
            sources = sources.intersection(valid_sources) or {'atlas', 'osm'}

            query = Stop.query
            if sources == {'atlas', 'osm'}:
                query = query.filter(Stop.stop_type.in_(['unmatched', 'osm']))
            elif 'atlas' in sources:
                query = query.filter(Stop.stop_type == 'unmatched')
            else:
                query = query.filter(Stop.stop_type == 'osm')

            # Operator filter applies only where ATLAS data exists; .has() will naturally drop OSM-only
            query = _apply_atlas_operator_filter(query)

            # For unmatched we may need both atlas and osm details in template; use 'data' for full eager load
            query = optimize_query_for_endpoint(query, 'data')

            # Join AtlasStop for operator sorting
            query = query.outerjoin(AtlasStop, Stop.sloid == AtlasStop.sloid)
            if sort_param == 'operator_desc':
                # DESC NULLS LAST: MySQL compatible
                query = query.order_by(db.func.isnull(AtlasStop.atlas_business_org_abbr), AtlasStop.atlas_business_org_abbr.desc())
            else:
                # ASC NULLS FIRST: MySQL compatible
                query = query.order_by(db.func.isnull(AtlasStop.atlas_business_org_abbr), AtlasStop.atlas_business_org_abbr.asc())

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

            query = db.session.query(Problem).join(Stop)
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

            # Operator filter (applies to Stop -> AtlasStop)
            if atlas_operators:
                query = query.filter(Stop.atlas_stop_details.has(AtlasStop.atlas_business_org_abbr.in_(atlas_operators)))

            # Sorting for problems
            # Join AtlasStop for operator sorts
            query = query.outerjoin(AtlasStop, Stop.sloid == AtlasStop.sloid)

            if sort_param == 'priority_asc':
                query = query.order_by(db.func.coalesce(Problem.priority, 999).asc(), Problem.stop_id, Problem.problem_type)
            elif sort_param == 'priority_desc':
                query = query.order_by(db.func.coalesce(Problem.priority, 999).desc(), Problem.stop_id, Problem.problem_type)
            elif sort_param == 'operator_desc':
                # DESC NULLS LAST: MySQL compatible
                query = query.order_by(db.func.isnull(AtlasStop.atlas_business_org_abbr), AtlasStop.atlas_business_org_abbr.desc(), Problem.stop_id, Problem.problem_type)
            else:
                # ASC NULLS FIRST: MySQL compatible
                query = query.order_by(db.func.isnull(AtlasStop.atlas_business_org_abbr), AtlasStop.atlas_business_org_abbr.asc(), Problem.stop_id, Problem.problem_type)

            # Eager load stop + atlas/osm details when rendering template
            query = query.options(
                joinedload(Problem.stop).joinedload(Stop.atlas_stop_details),
                joinedload(Problem.stop).joinedload(Stop.osm_node_details)
            )

            data_for_report = (query.limit(limit).all() if isinstance(limit, int) else query.all())
            report_title = "Problems Report"

        else:
            # distance: Top distance matched pairs
            query = Stop.query.filter(Stop.stop_type == 'matched')

            # Operator filter
            query = _apply_atlas_operator_filter(query)

            # Join AtlasStop for operator sorts
            query = query.outerjoin(AtlasStop, Stop.sloid == AtlasStop.sloid)

            # Sorting
            if sort_param == 'distance_asc':
                query = query.filter(Stop.distance_m != None).order_by(Stop.distance_m.asc())
            elif sort_param == 'distance_desc':
                query = query.filter(Stop.distance_m != None).order_by(Stop.distance_m.desc())
            elif sort_param == 'operator_desc':
                # DESC NULLS LAST: MySQL compatible
                query = query.order_by(db.func.isnull(AtlasStop.atlas_business_org_abbr), AtlasStop.atlas_business_org_abbr.desc())
            else:
                # ASC NULLS FIRST: MySQL compatible
                query = query.order_by(db.func.isnull(AtlasStop.atlas_business_org_abbr), AtlasStop.atlas_business_org_abbr.asc())

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
                cw.writerow([
                    'Source', 'ATLAS Sloid', 'Official Designation', 'ATLAS Operator',
                    'OSM Node ID', 'OSM Local Ref', 'OSM Name', 'UIC Ref'
                ])
                for stop in data_for_report:
                    source = 'ATLAS' if stop.stop_type == 'unmatched' else 'OSM'
                    atlas_details = getattr(stop, 'atlas_stop_details', None)
                    osm_details = getattr(stop, 'osm_node_details', None)
                    cw.writerow([
                        source,
                        stop.sloid or 'N/A',
                        (atlas_details.atlas_designation_official if atlas_details and atlas_details.atlas_designation_official else 'N/A'),
                        (atlas_details.atlas_business_org_abbr if atlas_details and atlas_details.atlas_business_org_abbr else 'N/A'),
                        stop.osm_node_id or 'N/A',
                        (osm_details.osm_local_ref if osm_details and osm_details.osm_local_ref else 'N/A'),
                        (osm_details.osm_name if osm_details and osm_details.osm_name else 'N/A'),
                        (stop.uic_ref or 'N/A')
                    ])

            elif report_type == 'problems':
                cw.writerow([
                    'Problem Type', 'Priority', 'Solved', 'ATLAS Sloid', 'Official Designation',
                    'ATLAS Operator', 'OSM Node ID', 'Distance (m)', 'Matching Method', 'Solution'
                ])
                for pr in data_for_report:
                    st = pr.stop
                    atlas_details = getattr(st, 'atlas_stop_details', None)
                    cw.writerow([
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
                    ])

            else:
                # distance
                cw.writerow(['ATLAS Sloid', 'Official Designation', 'ATLAS Operator', 'OSM Node ID', 'Distance (m)', 'Matching Method'])
                for stop in data_for_report:
                    cw.writerow([
                        stop.sloid if stop.sloid else 'N/A',
                        stop.atlas_stop_details.atlas_designation_official if stop.atlas_stop_details and stop.atlas_stop_details.atlas_designation_official else 'N/A',
                        stop.atlas_stop_details.atlas_business_org_abbr if stop.atlas_stop_details and stop.atlas_stop_details.atlas_business_org_abbr else 'N/A',
                        stop.osm_node_id if stop.osm_node_id else 'N/A',
                        '{:.1f}'.format(stop.distance_m) if stop.distance_m is not None else 'N/A',
                        stop.match_type if stop.match_type else 'N/A'
                    ])

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
            report_type=report_type
        )
        pdf = pdfkit.from_string(report_html, False)
        response = app.response_class(pdf, mimetype='application/pdf')
        response.headers["Content-Disposition"] = f"attachment; filename={pdf_filename_stem}.pdf"
        return response
    except Exception as e:
        app.logger.error(f"Error generating report: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500


