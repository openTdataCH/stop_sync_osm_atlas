"""Main pages: the map, the problems page, the data pages and the error pages, rendered as HTML."""
from flask import Blueprint, redirect, render_template, request, url_for

from backend.services.stop_lookup import linked_stop


pages_bp = Blueprint('pages', __name__)


@pages_bp.route('/')
def index():
    return render_template('pages/index.html', linked_stop=linked_stop(request.args))


@pages_bp.route('/problems')
def problems():
    return render_template('pages/problems.html', linked_stop=linked_stop(request.args))


@pages_bp.route('/data')
def data_index():
    return redirect(url_for('pages.data_analytics'))


@pages_bp.route('/data/analytics', endpoint='data_analytics')
@pages_bp.route('/data/export', endpoint='data_reports')
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


@pages_bp.app_errorhandler(404)
def not_found(e):
    return render_template(
        'errors/404.html',
        seo_robots='noindex,nofollow',
    ), 404


@pages_bp.app_errorhandler(500)
def server_error(e):
    return render_template(
        'errors/500.html',
        seo_robots='noindex,nofollow',
    ), 500
