from flask import Flask, render_template
import logging
import os

from datetime import timedelta

# Import the modular components
from backend.extensions import db, login_manager, csrf, limiter, talisman, migrate
from backend.blueprints.data import data_bp
from backend.blueprints.reports import reports_bp
from backend.blueprints.search import search_bp
from backend.blueprints.stats import stats_bp
from backend.blueprints.problems import problems_bp
from backend.blueprints.auth import auth_bp
from backend.services.audit import record_auth_event
from backend.auth_models import User

app = Flask(__name__, template_folder='../templates', static_folder='../static')

app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URI', 'mysql+pymysql://stops_user:1234@localhost:3306/stops_db')
app.config['SQLALCHEMY_BINDS'] = {
    'auth': os.getenv('AUTH_DATABASE_URI', 'mysql+pymysql://stops_user:1234@localhost:3306/auth_db'),
}
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Security/session settings
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'change-this-in-production')
app.config['REMEMBER_COOKIE_DURATION'] = timedelta(days=14)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.getenv('SESSION_COOKIE_SECURE', 'false').lower() == 'true'

logging.getLogger('werkzeug').setLevel(logging.WARNING)

db.init_app(app)
login_manager.init_app(app)
login_manager.login_view = 'auth.login'
csrf.init_app(app)
limiter.init_app(app)
# Keep CSP relaxed for current CDN-heavy frontend; enforce HTTPS conditionally via env
talisman.init_app(app, content_security_policy=None, force_https=os.getenv('FORCE_HTTPS', 'false').lower() == 'true')
migrate.init_app(app, db)

@app.context_processor
def inject_turnstile():
    return {'TURNSTILE_SITE_KEY': os.getenv('TURNSTILE_SITE_KEY', '')}

@login_manager.user_loader
def load_user(user_id):
    try:
        return db.session.get(User, int(user_id))
    except Exception:
        return None

@login_manager.unauthorized_handler
def unauthorized():
    from flask import request, redirect, url_for, jsonify
    # Return JSON for API/AJAX requests to avoid HTML redirects breaking clients
    wants_json = request.is_json or request.accept_mimetypes['application/json'] >= request.accept_mimetypes['text/html'] or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    if wants_json:
        return jsonify({'authenticated': False, 'error': 'Login required'}), 401
    return redirect(url_for('auth.login'))

# Register blueprints
app.register_blueprint(data_bp)
app.register_blueprint(reports_bp)
app.register_blueprint(search_bp)
app.register_blueprint(stats_bp)
app.register_blueprint(problems_bp)
app.register_blueprint(auth_bp)

# Exempt legacy JSON APIs from CSRF for now (forms remain protected). Problems endpoints require CSRF.
csrf.exempt(data_bp)
csrf.exempt(reports_bp)
csrf.exempt(search_bp)
csrf.exempt(stats_bp)

@app.route('/')
def index():
    # Render from new structured pages path
    return render_template('pages/index.html')

@app.route('/map_snapshot')
def map_snapshot():
    return render_template('pages/map_snapshot.html')

@app.route('/problems')
def problems():
    # Render from new structured pages path
    return render_template('pages/problems.html')

@app.route('/persistent_data')
def persistent_data():
    # Render from new structured pages path
    return render_template('pages/persistent_data.html')

@app.route('/reports')
def reports_page():
    return render_template('pages/reports.html')

# Flask-Login signal hooks as a safety net to capture login/logout events
try:
    from flask_login import user_logged_in, user_logged_out

    @user_logged_in.connect_via(app)
    def _on_user_logged_in(sender, user):
        try:
            record_auth_event(event_type='login_success', user=user)
        except Exception:
            pass

    @user_logged_out.connect_via(app)
    def _on_user_logged_out(sender, user):
        try:
            record_auth_event(event_type='logout', user=user)
        except Exception:
            pass
except Exception:
    # If signals are not available for any reason, ignore
    pass

if __name__ == '__main__':
    @app.errorhandler(404)
    def not_found(e):
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def server_error(e):
        return render_template('errors/500.html'), 500

    app.run(host='0.0.0.0', port=5001, debug=True)
