from flask import Blueprint, request, jsonify, render_template, current_app as app
from sqlalchemy.orm import joinedload
from backend.models import db, Stop, AtlasStop, OsmNode
from backend.query_helpers import optimize_query_for_endpoint
from datetime import datetime
import pdfkit
import csv
from io import StringIO

# Create blueprint for reports
reports_bp = Blueprint('reports', __name__)

# ----------------------------
# API Endpoint: /api/generate_report
# ----------------------------
@reports_bp.route('/api/generate_report', methods=['GET'])
def generate_report():
    try:
        limit = int(request.args.get('limit', 10)) # Limit for number of pairs in duplicates report
        sort_param = request.args.get('sort', 'uic_asc') # Default sort for duplicates
        report_type = request.args.get('report_type', 'top_matches')
        report_format = request.args.get('format', 'pdf').lower()
        
        data_for_report = []
        report_title = "OSM & ATLAS Matching Report" # Default title

        if report_type == 'duplicates':
            report_title = "ATLAS Duplicate Stops Report"
            processed_pairs = set()
            
            # Fetch all stops that are marked as having a duplicate
            # We'll sort later after pairs are formed
            potential_duplicate_sources = optimize_query_for_endpoint(Stop.query, 'reports').filter(
                Stop.atlas_duplicate_sloid.isnot(None)
            ).all()

            for stop_a in potential_duplicate_sources:
                sloid_a = stop_a.sloid
                sloid_b_value = stop_a.atlas_duplicate_sloid

                if not sloid_b_value:
                    continue

                # Create a canonical representation of the pair for the set
                pair_key = tuple(sorted((sloid_a, sloid_b_value)))

                if pair_key in processed_pairs:
                    continue

                stop_b = optimize_query_for_endpoint(Stop.query, 'reports').filter(
                    Stop.sloid == sloid_b_value
                ).first()

                if stop_b:
                    # Ensure we have the correct A and B based on sorted order for consistent display if needed
                    # Though for this report, A and B are just labels for the two in the pair.
                    
                    data_for_report.append({
                        "uic_ref": stop_a.uic_ref, # Should be same for stop_b
                        "atlas_designation": stop_a.atlas_stop_details.atlas_designation if stop_a.atlas_stop_details else None, # Main designation, should be same
                        "sloid_A": sloid_a,
                        "designation_official_A": stop_a.atlas_stop_details.atlas_designation_official if stop_a.atlas_stop_details else None,
                        "sloid_B": stop_b.sloid, # Use stop_b.sloid to be sure
                        "designation_official_B": stop_b.atlas_stop_details.atlas_designation_official if stop_b.atlas_stop_details else None,
                    })
                    processed_pairs.add(pair_key)
            
            # Sort the collected pairs
            # Example sort: by UIC, then by the first SLOID in the pair
            if sort_param == 'uic_asc':
                 data_for_report.sort(key=lambda x: (x['uic_ref'] or '', x['sloid_A'] or ''))
            # Add other sort options if needed for duplicates
            
            # Apply limit to the number of pairs
            if limit and len(data_for_report) > limit:
                data_for_report = data_for_report[:limit]

        else: # Existing match reports
            query = Stop.query.filter(Stop.stop_type == 'matched')
            if report_type == 'exact_matches':
                query = query.filter(Stop.match_type == 'exact')
                report_title = "Top Exact Matches by Distance"
            elif report_type == 'name_matches':
                query = query.filter(Stop.match_type == 'name')
                report_title = "Top Name Matches by Distance"
            elif report_type == 'top_matches':
                report_title = "Top Matches by Distance"
            
            # Existing sort logic for match reports
            if sort_param == 'id_asc': # For match reports, this is stop.id
                query = query.order_by(Stop.id.asc())
            elif sort_param == 'distance_asc':
                query = query.filter(Stop.distance_m != None).order_by(Stop.distance_m.asc())
            elif sort_param == 'distance_desc': # Default for matches
                query = query.filter(Stop.distance_m != None).order_by(Stop.distance_m.desc())
            else: 
                query = query.order_by(Stop.distance_m.desc()) # Fallback for matches
            
            data_for_report = optimize_query_for_endpoint(query, 'reports').limit(limit).all()

        if data_for_report is None: # Should not happen if initialized
            data_for_report = []

        if report_format == 'csv':
            si = StringIO()
            cw = csv.writer(si)
            
            if report_type == 'duplicates':
                cw.writerow(['UIC Number', 'Designation', 'ATLAS Sloid A', 'Official Designation A', 'ATLAS Sloid B', 'Official Designation B'])
                for item in data_for_report: # data_for_report now contains dicts for pairs
                    cw.writerow([
                        item.get('uic_ref', 'N/A'),
                        item.get('atlas_designation', 'N/A'),
                        item.get('sloid_A', 'N/A'),
                        item.get('designation_official_A', 'N/A'),
                        item.get('sloid_B', 'N/A'),
                        item.get('designation_official_B', 'N/A'),
                    ])
            else: # Existing match reports CSV
                cw.writerow(['ATLAS Sloid', 'Official Designation', 'OSM Node ID', 'Distance (m)', 'Matching Method'])
                for stop in data_for_report: # data_for_report contains Stop objects here
                    cw.writerow([
                        stop.sloid if stop.sloid else 'N/A',
                        stop.atlas_stop_details.atlas_designation_official if stop.atlas_stop_details and stop.atlas_stop_details.atlas_designation_official else 'N/A',
                        stop.osm_node_id if stop.osm_node_id else 'N/A',
                        '{:.1f}'.format(stop.distance_m) if stop.distance_m is not None else 'N/A',
                        stop.match_type if stop.match_type else 'N/A'
                    ])
            
            output = si.getvalue()
            # Use report_type and sort_param for filename consistency
            response_filename_stem = f"{report_type}_{sort_param if report_type != 'duplicates' else 'uic_asc'}"
            response = app.response_class(output, mimetype='text/csv')
            response.headers["Content-Disposition"] = f"attachment; filename={response_filename_stem}.csv"
            return response

        # PDF Generation
        # Use report_type and sort_param for filename consistency
        pdf_filename_stem = f"{report_type}_{sort_param if report_type != 'duplicates' else 'uic_asc'}"
        report_html = render_template('report.html', 
                                     report_items=data_for_report,
                                     generated_at=datetime.now(), 
                                     sort_order=sort_param, # Pass the actual sort parameter used
                                     report_title=report_title,
                                     report_type=report_type)
        pdf = pdfkit.from_string(report_html, False)
        response = app.response_class(pdf, mimetype='application/pdf')
        response.headers["Content-Disposition"] = f"attachment; filename={pdf_filename_stem}.pdf"
        return response
    except Exception as e:
        app.logger.error(f"Error generating report: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500 