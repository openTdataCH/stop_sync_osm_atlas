from flask import Flask, request, redirect
import gzip
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
from backend.blueprints.quality import quality_bp
from backend.blueprints.system import system_bp
from backend.blueprints.routes import routes_bp
from backend.blueprints.seo import seo_bp, seo_template_context
from backend.pages.main import pages_bp
from backend.pages.operators import operators_bp
from backend.pages.routes import route_pages_bp
from backend.services import pipeline_status
from backend.services.time_utils import format_zurich_display_timestamp
from backend.services.source_config import load_review_config, effective_review_config
from backend.version import APP_VERSION

# Smaller JSON saves too few bytes to be worth compressing.
JSON_GZIP_MIN_BYTES = 1024


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
    app.config['REVIEW_CONFIG'] = load_review_config()
    app.context_processor(lambda: {
        'review_config': effective_review_config(),
        'app_version': APP_VERSION,
    })
    app.add_template_filter(format_zurich_display_timestamp, 'format_zurich_display_timestamp')
    app.config['SITE_URL'] = 'https://atlas.osm.ch'

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
    app.register_blueprint(quality_bp)
    app.register_blueprint(system_bp)
    app.register_blueprint(operators_bp)
    app.register_blueprint(routes_bp)
    app.register_blueprint(seo_bp)
    app.register_blueprint(pages_bp)
    app.register_blueprint(route_pages_bp)

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

        stats = load_stats_from_file() or {}
        status = pipeline_status.get_status()
        return {
            'last_pipeline_data_import_ended_at': status.get('last_pipeline_data_import_ended_at'),
            'stats_computed_at': stats.get('stats_computed_at'),
            'pipeline_next_run_at': status.get('next_run_at'),
            'pipeline_status': status,
        }

    app.context_processor(seo_template_context)

    @app.after_request
    def discourage_non_page_indexing(response):
        if (
            request.path.startswith('/api/')
            or 400 <= response.status_code < 500
        ):
            response.headers['X-Robots-Tag'] = 'noindex, nofollow'
        return response

    @app.after_request
    def gzip_json(response):
        # A map view loads up to several hundred kB of stop JSON, which gzip
        # makes about seven times smaller. The server in front compresses
        # pages and scripts but not JSON, so the app does it.
        if (
            response.mimetype != 'application/json'
            or response.status_code != 200
            or response.direct_passthrough
            or response.is_streamed
            or 'Content-Encoding' in response.headers
        ):
            return response
        body = response.get_data()
        if len(body) < JSON_GZIP_MIN_BYTES:
            return response
        response.vary.add('Accept-Encoding')
        if request.accept_encodings['gzip']:
            # zlib's default level: level 9 takes twice as long for 3% less.
            response.set_data(gzip.compress(body, compresslevel=6))
            response.headers['Content-Encoding'] = 'gzip'
        return response

    return app


app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=os.getenv('FLASK_DEBUG', '0') == '1')
