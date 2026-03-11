from flask import Flask, render_template, redirect, url_for
import logging
import os

# Import the modular components
from backend.extensions import db, limiter, talisman, migrate
from backend.blueprints.data import data_bp
from backend.blueprints.reports import reports_bp
from backend.blueprints.search import search_bp
from backend.blueprints.stats import stats_bp
from backend.blueprints.problems import problems_bp
from backend.blueprints.docs import docs_bp

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
