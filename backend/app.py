# app.py
from flask import Flask, render_template
import logging
import os

# Import the modular components
from backend.models import init_db
from backend.app_data import data_bp
from backend.app_reports import reports_bp
from backend.app_search import search_bp
from backend.app_stats import stats_bp
from backend.app_problems import problems_bp

app = Flask(__name__, template_folder='../templates', static_folder='../static')

# Configure database
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URI', 'mysql+pymysql://stops_user:1234@localhost:3306/stops_db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Configure logging to reduce noise
# Suppress werkzeug request logs but keep error logs
logging.getLogger('werkzeug').setLevel(logging.WARNING)

# Initialize database
init_db(app)

# Register blueprints
app.register_blueprint(data_bp)
app.register_blueprint(reports_bp)
app.register_blueprint(search_bp)
app.register_blueprint(stats_bp)
app.register_blueprint(problems_bp)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/map_snapshot')
def map_snapshot():
    return render_template('map_snapshot.html')

@app.route('/problems')
def problems():
    return render_template('problems.html')

@app.route('/persistent_data')
def persistent_data():
    return render_template('persistent_data.html')

if __name__ == '__main__':
    # Make sure the app runs on 0.0.0.0 to be accessible from outside the container
    # The port is already handled by EXPOSE in Dockerfile and port mapping in docker-compose
    app.run(host='0.0.0.0', port=5001, debug=True)
