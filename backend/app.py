from flask import Flask, render_template
import logging
import os

from datetime import timedelta

# Import the modular components
from backend.extensions import db, login_manager, csrf, limiter, talisman
from backend.blueprints.data import data_bp
from backend.blueprints.reports import reports_bp
from backend.blueprints.search import search_bp
from backend.blueprints.stats import stats_bp
from backend.blueprints.problems import problems_bp
from backend.blueprints.auth import auth_bp
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

@login_manager.user_loader
def load_user(user_id):
    try:
        return db.session.get(User, int(user_id))
    except Exception:
        return None

# Register blueprints
app.register_blueprint(data_bp)
app.register_blueprint(reports_bp)
app.register_blueprint(search_bp)
app.register_blueprint(stats_bp)
app.register_blueprint(problems_bp)
app.register_blueprint(auth_bp)

# Exempt legacy JSON APIs from CSRF for now (forms remain protected). We will later gate APIs behind auth
# and add proper CSRF handling in JS clients.
csrf.exempt(data_bp)
csrf.exempt(reports_bp)
csrf.exempt(search_bp)
csrf.exempt(stats_bp)
csrf.exempt(problems_bp)

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

if __name__ == '__main__':
    # Ensure auth tables exist on startup without touching analytical data tables
    with app.app_context():
        try:
            db.create_all()
        except Exception as e:
            app.logger.error(f"Failed to create auth tables: {e}")
    @app.errorhandler(404)
    def not_found(e):
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def server_error(e):
        return render_template('errors/500.html'), 500

    app.run(host='0.0.0.0', port=5001, debug=True)
