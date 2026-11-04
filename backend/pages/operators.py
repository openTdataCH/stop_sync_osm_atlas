"""Operators page: ATLAS operators and how their stops are tagged in OSM, rendered as HTML."""
from flask import Blueprint, render_template, request

from backend.db_errors import is_missing_column_error, is_missing_table_error
from backend.extensions import db
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


class _EmptyPagination:
    def __init__(self, page, per_page):
        self.page = page
        self.per_page = per_page
        self.total = 0
        self.pages = 0
        self.has_prev = False
        self.has_next = False
        self.prev_num = 1
        self.next_num = 1

    def iter_pages(self, **_kwargs):
        return []


def _bounded_int(raw_value, default, minimum, maximum=None):
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return default

    if value < minimum:
        return minimum
    if maximum is not None and value > maximum:
        return maximum
    return value


def _compute_page_range(pagination):
    if pagination.total <= 0:
        return 0, 0

    range_start = (pagination.page - 1) * pagination.per_page + 1
    range_end = min(range_start + pagination.per_page - 1, pagination.total)
    return range_start, range_end


def _normalize_coverage_filter(value: str | None) -> str:
    normalized = (value or '').strip().lower()
    if normalized in operator_coverage.OPERATOR_COVERAGE_FILTERS:
        return normalized
    return operator_coverage.OPERATOR_COVERAGE_ALL


@operators_bp.route('/operators')
def operators_page():
    coverage_filter = _normalize_coverage_filter(request.args.get('coverage'))
    q = (request.args.get('q') or '').strip()
    page = _bounded_int(request.args.get('page'), default=1, minimum=1)
    requested_per_page = _bounded_int(
        request.args.get('per_page'),
        default=OPERATORS_DEFAULT_PER_PAGE,
        minimum=10,
        maximum=100,
    )
    per_page = (
        requested_per_page
        if requested_per_page in OPERATORS_PER_PAGE_OPTIONS
        else OPERATORS_DEFAULT_PER_PAGE
    )

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

    try:
        load_result = operator_coverage.load_operators_view(
            coverage_filter=coverage_filter,
            q=q,
            page=page,
            per_page=per_page,
        )
        if len(load_result) == 3:
            operator_rows, pagination, supports_osm_operator_wikidata = load_result
        else:
            operator_rows, pagination = load_result
            supports_osm_operator_wikidata = True
    except Exception as exc:
        if not (is_missing_table_error(exc) or is_missing_column_error(exc)):
            raise

        db.session.rollback()
        operator_rows = []
        pagination = _EmptyPagination(page=page, per_page=per_page)
        supports_osm_operator_wikidata = False

    range_start, range_end = _compute_page_range(pagination)
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
        supports_osm_operator_wikidata=supports_osm_operator_wikidata,
    )
