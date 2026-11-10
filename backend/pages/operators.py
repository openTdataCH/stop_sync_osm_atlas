"""Operators page: ATLAS operators and how their stops are tagged in OSM, rendered as HTML."""
from flask import Blueprint, render_template, request

from backend.pages.pagination import bounded_int, page_range, per_page_choice
from backend.services import operator_coverage
from backend.services.url_query import canonical_query_redirect


operators_bp = Blueprint('operators', __name__)

OPERATOR_COVERAGE_LABELS = {
    operator_coverage.OPERATOR_COVERAGE_ALL: 'All',
    operator_coverage.OPERATOR_COVERAGE_HAS_OSM: 'With matched OSM operators',
    operator_coverage.OPERATOR_COVERAGE_NO_OSM: 'Without matched OSM operators',
}
OPERATORS_PER_PAGE_OPTIONS = [10, 20, 50, 100]
OPERATORS_DEFAULT_PER_PAGE = 20


def _normalize_coverage_filter(value: str | None) -> str:
    normalized = (value or '').strip().lower()
    if normalized in operator_coverage.OPERATOR_COVERAGE_FILTERS:
        return normalized
    return operator_coverage.OPERATOR_COVERAGE_ALL


@operators_bp.route('/operators')
def operators_page():
    coverage_filter = _normalize_coverage_filter(request.args.get('coverage'))
    q = (request.args.get('q') or '').strip()
    page = bounded_int(request.args.get('page'), 1, minimum=1)
    per_page = per_page_choice(request.args.get('per_page'), OPERATORS_PER_PAGE_OPTIONS, OPERATORS_DEFAULT_PER_PAGE, minimum=10)

    canonical_redirect = canonical_query_redirect(
        'operators.operators_page',
        (
            ('q', q or None),
            (
                'coverage',
                coverage_filter if coverage_filter != operator_coverage.OPERATOR_COVERAGE_ALL else None,
            ),
            (
                'per_page',
                per_page if per_page != OPERATORS_DEFAULT_PER_PAGE else None,
            ),
            ('page', page if page > 1 else None),
        ),
    )
    if canonical_redirect is not None:
        return canonical_redirect

    operator_rows, pagination = operator_coverage.load_operators_view(
        coverage_filter=coverage_filter,
        q=q,
        page=page,
        per_page=per_page,
    )
    range_start, range_end = page_range(pagination)
    return render_template(
        'pages/operators.html',
        active_view='operators',
        operator_rows=operator_rows,
        pagination=pagination,
        q=q,
        coverage_filter=coverage_filter,
        coverage_labels=OPERATOR_COVERAGE_LABELS,
        per_page=per_page,
        per_page_options=OPERATORS_PER_PAGE_OPTIONS,
        range_start=range_start,
        range_end=range_end,
    )
