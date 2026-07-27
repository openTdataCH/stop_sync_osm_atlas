from flask import Flask, render_template, request, redirect, url_for
import logging
import os

# Import the modular components
from backend.extensions import db, limiter, migrate
from backend.blueprints.data import data_bp
from backend.blueprints.reports import reports_bp
from backend.blueprints.search import search_bp
from backend.blueprints.stats import stats_bp
from backend.blueprints.problems import problems_bp
from backend.blueprints.docs import docs_bp
from backend.blueprints.system import system_bp
from backend.blueprints.operators import operators_bp
from backend.blueprints.routes import routes_bp
from backend.services.time_utils import format_zurich_display_timestamp


def _bounded_env_int(name, default, *, minimum, maximum):
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def _database_engine_options(database_uri):
    if not database_uri.startswith(('postgresql:', 'postgresql+')):
        return {}

    connect_timeout_seconds = _bounded_env_int(
        'WEB_DB_CONNECT_TIMEOUT_SECONDS',
        5,
        minimum=1,
        maximum=60,
    )
    lock_timeout_ms = _bounded_env_int(
        'WEB_DB_LOCK_TIMEOUT_MS',
        3000,
        minimum=100,
        maximum=120_000,
    )
    statement_timeout_ms = _bounded_env_int(
        'WEB_DB_STATEMENT_TIMEOUT_MS',
        25_000,
        minimum=1000,
        maximum=300_000,
    )
    return {
        'pool_pre_ping': True,
        'connect_args': {
            'connect_timeout': connect_timeout_seconds,
            'options': (
                f'-c lock_timeout={lock_timeout_ms} '
                f'-c statement_timeout={statement_timeout_ms}'
            ),
        },
    }


def create_app():
    app = Flask(__name__, template_folder='../templates', static_folder='../static')
    app.add_template_filter(format_zurich_display_timestamp, 'format_zurich_display_timestamp')

    database_uri = os.getenv('DATABASE_URI', 'postgresql+psycopg://stops_user:1234@localhost:5432/import_db')
    app.config['SQLALCHEMY_DATABASE_URI'] = database_uri
    engine_options = _database_engine_options(database_uri)
    if engine_options:
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = engine_options
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    logging.getLogger('werkzeug').setLevel(logging.WARNING)

    db.init_app(app)
    limiter.init_app(app)
    migrate.init_app(app, db)

    # Register blueprints
    app.register_blueprint(data_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(search_bp)
    app.register_blueprint(stats_bp)
    app.register_blueprint(problems_bp)
    app.register_blueprint(docs_bp)
    app.register_blueprint(system_bp)
    app.register_blueprint(operators_bp)
    app.register_blueprint(routes_bp)
    @app.before_request
    def enforce_https():
        if os.getenv('FORCE_HTTPS', 'false').lower() == 'true':
            # Check X-Forwarded-Proto for proxies, or fallback to request.is_secure
            if request.headers.get('X-Forwarded-Proto', 'http') == 'http' and not request.is_secure:
                url = request.url.replace('http://', 'https://', 1)
                return redirect(url, code=301)

    @app.context_processor
    def inject_stats_metadata():
        from backend.services.stats_export import load_stats_from_file
        from backend.services.pipeline_status import get_status

        stats = load_stats_from_file() or {}
        pipeline_status = get_status()
        return {
            'last_pipeline_data_import_ended_at': pipeline_status.get('last_pipeline_data_import_ended_at') or stats.get('data_updated_at'),
            'stats_computed_at': stats.get('stats_computed_at') or stats.get('generated_at'),
            'pipeline_next_run_at': pipeline_status.get('next_run_at'),
        }

    @app.route('/')
    def index():
        return render_template('pages/index.html')

    @app.route('/problems')
    def problems():
        return render_template('pages/problems.html')

    @app.route('/data')
    def data_index():
        return redirect(url_for('data_analytics'))

    @app.route('/data/analytics', endpoint='data_analytics')
    @app.route('/data/export', endpoint='data_reports')
    def data_page():
        from backend.services.stats_export import load_stats_from_file
        stats = load_stats_from_file()

        # Determine which view to show based on the URL
        active_view = 'reports' if request.path.endswith('/export') else 'analytics'

        # Read priority breakdown from stats.json (populated by pipeline)
        problem_breakdown = {}
        if stats and 'problems' in stats and 'by_priority' in stats['problems']:
            raw = stats['problems']['by_priority']
            # JSON keys are strings; convert to int for template usage
            problem_breakdown = {int(k): v for k, v in raw.items()}

        return render_template(
            'pages/data.html',
            stats=stats,
            problem_breakdown=problem_breakdown,
            active_view=active_view
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
