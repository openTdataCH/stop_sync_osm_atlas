from flask import Flask, render_template, redirect, url_for, request
import logging
import os
from sqlalchemy import or_

# Import the modular components
from backend.extensions import db, limiter, talisman, migrate
from backend.blueprints.data import data_bp
from backend.blueprints.reports import reports_bp
from backend.blueprints.search import search_bp
from backend.blueprints.stats import stats_bp
from backend.blueprints.problems import problems_bp
from backend.blueprints.docs import docs_bp


def _direction_sort_key(direction_id):
    """Sort directions: numeric first, then text, empty last."""
    if direction_id is None:
        return (2, "")

    direction_text = str(direction_id).strip()
    if direction_text == "":
        return (2, "")

    if direction_text.lstrip('-').isdigit():
        return (0, int(direction_text))

    return (1, direction_text.lower())


def _bounded_int(value, default, minimum=None, maximum=None):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default

    if minimum is not None and parsed < minimum:
        parsed = minimum
    if maximum is not None and parsed > maximum:
        parsed = maximum

    return parsed

def create_app():
    app = Flask(__name__, template_folder='../templates', static_folder='../static')

    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URI', 'postgresql+psycopg://stops_user:1234@localhost:5432/import_db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    logging.getLogger('werkzeug').setLevel(logging.WARNING)

    db.init_app(app)
    limiter.init_app(app)
    # Keep CSP relaxed for current CDN-heavy frontend; enforce HTTPS conditionally via env
    talisman.init_app(app, content_security_policy=None, force_https=os.getenv('FORCE_HTTPS', 'false').lower() == 'true')
    migrate.init_app(app, db)

    # Register blueprints
    app.register_blueprint(data_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(search_bp)
    app.register_blueprint(stats_bp)
    app.register_blueprint(problems_bp)
    app.register_blueprint(docs_bp)

    @app.route('/')
    def index():
        return render_template('pages/index.html')

    @app.route('/map_snapshot')
    def map_snapshot():
        return render_template('pages/map_snapshot.html')

    @app.route('/problems')
    def problems():
        return render_template('pages/problems.html')

    @app.route('/reports')
    def reports_page():
        return render_template('pages/reports.html')

    @app.route('/stats')
    def stats_page():
        from backend.services.stats_export import load_stats_from_file
        stats = load_stats_from_file()

        # Read priority breakdown from stats.json (populated by pipeline)
        problem_breakdown = {}
        if stats and 'problems' in stats and 'by_priority' in stats['problems']:
            raw = stats['problems']['by_priority']
            # JSON keys are strings; convert to int for template usage
            problem_breakdown = {int(k): v for k, v in raw.items()}

        return render_template('pages/stats.html', stats=stats, problem_breakdown=problem_breakdown)

    @app.route('/routes')
    def routes_page():
        from backend.models import RoutesMatched, RouteAtlasStops, RouteOsmStops, AtlasStop, OsmNode

        def load_atlas_route_stops(atlas_route_ids):
            if not atlas_route_ids:
                return {}

            rows = (
                db.session.query(
                    RouteAtlasStops.atlas_route_id,
                    RouteAtlasStops.direction_id,
                    RouteAtlasStops.sloid,
                    RouteAtlasStops.stop_sequence,
                    AtlasStop.atlas_designation_official,
                    AtlasStop.atlas_designation,
                )
                .outerjoin(AtlasStop, RouteAtlasStops.sloid == AtlasStop.sloid)
                .filter(RouteAtlasStops.atlas_route_id.in_(atlas_route_ids))
                .order_by(
                    RouteAtlasStops.atlas_route_id.asc(),
                    RouteAtlasStops.direction_id.asc(),
                    RouteAtlasStops.stop_sequence.asc(),
                    RouteAtlasStops.id.asc(),
                )
                .all()
            )

            grouped = {}
            for row in rows:
                route_key = row.atlas_route_id
                direction_key = "" if row.direction_id is None else str(row.direction_id)
                route_bucket = grouped.setdefault(route_key, {})
                direction_bucket = route_bucket.setdefault(direction_key, [])
                stop_label = row.atlas_designation_official or row.atlas_designation or row.sloid
                direction_bucket.append(
                    {
                        "stop_id": row.sloid,
                        "stop_label": stop_label,
                        "stop_sequence": row.stop_sequence,
                    }
                )

            return grouped

        def load_osm_route_stops(osm_route_ids):
            if not osm_route_ids:
                return {}

            rows = (
                db.session.query(
                    RouteOsmStops.osm_route_id,
                    RouteOsmStops.direction_id,
                    RouteOsmStops.osm_node_id,
                    RouteOsmStops.stop_sequence,
                    OsmNode.osm_name,
                    OsmNode.osm_uic_name,
                    OsmNode.osm_local_ref,
                )
                .outerjoin(OsmNode, RouteOsmStops.osm_node_id == OsmNode.osm_node_id)
                .filter(RouteOsmStops.osm_route_id.in_(osm_route_ids))
                .order_by(
                    RouteOsmStops.osm_route_id.asc(),
                    RouteOsmStops.direction_id.asc(),
                    RouteOsmStops.stop_sequence.asc(),
                    RouteOsmStops.id.asc(),
                )
                .all()
            )

            grouped = {}
            for row in rows:
                route_key = row.osm_route_id
                direction_key = "" if row.direction_id is None else str(row.direction_id)
                route_bucket = grouped.setdefault(route_key, {})
                direction_bucket = route_bucket.setdefault(direction_key, [])
                stop_label = row.osm_name or row.osm_uic_name or row.osm_local_ref or row.osm_node_id
                direction_bucket.append(
                    {
                        "stop_id": row.osm_node_id,
                        "stop_label": stop_label,
                        "stop_sequence": row.stop_sequence,
                    }
                )

            return grouped

        q = (request.args.get('q') or '').strip()
        page = _bounded_int(request.args.get('page'), default=1, minimum=1)
        per_page = _bounded_int(request.args.get('per_page'), default=20, minimum=5, maximum=100)

        matched_routes_query = RoutesMatched.query
        if q:
            like_pattern = f"%{q}%"
            matched_routes_query = matched_routes_query.filter(
                or_(
                    RoutesMatched.atlas_route_id.ilike(like_pattern),
                    RoutesMatched.osm_route_id.ilike(like_pattern),
                )
            )

        matched_routes_page = (
            matched_routes_query
            .order_by(RoutesMatched.atlas_route_id.asc(), RoutesMatched.osm_route_id.asc())
            .paginate(page=page, per_page=per_page, error_out=False)
        )

        atlas_route_ids = sorted({item.atlas_route_id for item in matched_routes_page.items if item.atlas_route_id})
        osm_route_ids = sorted({item.osm_route_id for item in matched_routes_page.items if item.osm_route_id})

        atlas_stops_by_route = load_atlas_route_stops(atlas_route_ids)
        osm_stops_by_route = load_osm_route_stops(osm_route_ids)

        route_rows = []
        for matched in matched_routes_page.items:
            atlas_directions = atlas_stops_by_route.get(matched.atlas_route_id, {})
            osm_directions = osm_stops_by_route.get(matched.osm_route_id, {})

            all_directions = set(atlas_directions.keys()) | set(osm_directions.keys())
            direction_groups = []
            for direction_id in sorted(all_directions, key=_direction_sort_key):
                direction_groups.append(
                    {
                        "direction_id": direction_id,
                        "atlas_stops": atlas_directions.get(direction_id, []),
                        "osm_stops": osm_directions.get(direction_id, []),
                    }
                )

            route_rows.append(
                {
                    "atlas_route_id": matched.atlas_route_id,
                    "atlas_route_name": matched.atlas_route_id,
                    "osm_route_id": matched.osm_route_id,
                    "osm_route_name": matched.osm_route_id,
                    "direction_groups": direction_groups,
                }
            )

        if matched_routes_page.total > 0:
            range_start = ((matched_routes_page.page - 1) * matched_routes_page.per_page) + 1
            range_end = range_start + len(matched_routes_page.items) - 1
        else:
            range_start = 0
            range_end = 0

        return render_template(
            'pages/routes.html',
            route_rows=route_rows,
            pagination=matched_routes_page,
            q=q,
            per_page=per_page,
            range_start=range_start,
            range_end=range_end,
        )

    @app.errorhandler(404)
    def not_found(e):
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def server_error(e):
        return render_template('errors/500.html'), 500

    return app


app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=os.getenv('FLASK_DEBUG', '0') == '1')
