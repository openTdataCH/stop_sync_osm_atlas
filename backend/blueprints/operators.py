from collections import defaultdict

from flask import Blueprint, render_template, request
from sqlalchemy import case, func, inspect, literal, or_

from backend.db_errors import is_missing_column_error, is_missing_table_error
from backend.extensions import db
from backend.models import AtlasOperator, AtlasStop, OsmNode, StopsMatched
from backend.services.url_query import canonical_query_redirect


operators_bp = Blueprint('operators', __name__)

OPERATOR_COVERAGE_ALL = 'all'
OPERATOR_COVERAGE_HAS_OSM = 'has_osm_matches'
OPERATOR_COVERAGE_NO_OSM = 'no_osm_matches'
OPERATOR_COVERAGE_FILTERS = {
    OPERATOR_COVERAGE_ALL,
    OPERATOR_COVERAGE_HAS_OSM,
    OPERATOR_COVERAGE_NO_OSM,
}
OPERATOR_COVERAGE_LABELS = {
    OPERATOR_COVERAGE_ALL: 'All',
    OPERATOR_COVERAGE_HAS_OSM: 'With matched OSM operators',
    OPERATOR_COVERAGE_NO_OSM: 'Without matched OSM operators',
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
    if normalized in OPERATOR_COVERAGE_FILTERS:
        return normalized
    return OPERATOR_COVERAGE_ALL


def _supports_osm_operator_wikidata() -> bool:
    try:
        bind = db.session.get_bind()
        columns = inspect(bind).get_columns(OsmNode.__tablename__)
    except Exception as exc:
        if is_missing_table_error(exc):
            return False
        raise

    return any(column.get('name') == 'osm_operator_wikidata' for column in columns)


def _matched_osm_operator_subquery():
    return (
        db.session.query(StopsMatched.id)
        .join(AtlasStop, AtlasStop.sloid == StopsMatched.sloid)
        .join(OsmNode, StopsMatched.osm_node_id == OsmNode.osm_node_id)
        .filter(StopsMatched.stop_type == 'matched')
        .filter(AtlasStop.atlas_business_org_abbr == AtlasOperator.atlas_business_org_abbr)
        .filter(OsmNode.osm_operator.isnot(None))
        .filter(OsmNode.osm_operator != '')
    )


def _operator_search_condition(q: str, supports_osm_operator_wikidata: bool):
    pattern = f'%{q}%'
    osm_search_terms = [OsmNode.osm_operator.ilike(pattern)]
    if supports_osm_operator_wikidata:
        osm_search_terms.append(OsmNode.osm_operator_wikidata.ilike(pattern))

    matched_osm_search = (
        db.session.query(StopsMatched.id)
        .join(AtlasStop, AtlasStop.sloid == StopsMatched.sloid)
        .join(OsmNode, StopsMatched.osm_node_id == OsmNode.osm_node_id)
        .filter(StopsMatched.stop_type == 'matched')
        .filter(AtlasStop.atlas_business_org_abbr == AtlasOperator.atlas_business_org_abbr)
        .filter(or_(*osm_search_terms))
        .exists()
    )

    return or_(
        AtlasOperator.atlas_business_org_abbr.ilike(pattern),
        AtlasOperator.atlas_business_org_name.ilike(pattern),
        AtlasOperator.sboid.ilike(pattern),
        matched_osm_search,
    )


def _load_atlas_stop_counts(operator_abbrs: list[str]) -> dict[str, int]:
    if not operator_abbrs:
        return {}

    rows = (
        db.session.query(
            AtlasStop.atlas_business_org_abbr,
            func.count(AtlasStop.sloid),
        )
        .filter(AtlasStop.atlas_business_org_abbr.in_(operator_abbrs))
        .group_by(AtlasStop.atlas_business_org_abbr)
        .all()
    )
    return {abbr: int(count or 0) for abbr, count in rows if abbr}


def _load_match_counts(operator_abbrs: list[str], supports_osm_operator_wikidata: bool) -> dict[str, dict[str, int]]:
    if not operator_abbrs:
        return {}

    missing_osm_operator_wikidata_count = literal(0)
    if supports_osm_operator_wikidata:
        missing_osm_operator_wikidata_count = func.sum(
            case(
                (
                    or_(OsmNode.osm_operator_wikidata.is_(None), OsmNode.osm_operator_wikidata == ''),
                    1,
                ),
                else_=0,
            )
        )

    rows = (
        db.session.query(
            AtlasStop.atlas_business_org_abbr.label('atlas_business_org_abbr'),
            func.count(StopsMatched.id).label('matched_stop_count'),
            func.sum(
                case(
                    (
                        or_(OsmNode.osm_operator.is_(None), OsmNode.osm_operator == ''),
                        1,
                    ),
                    else_=0,
                )
            ).label('missing_osm_operator_count'),
            missing_osm_operator_wikidata_count.label('missing_osm_operator_wikidata_count'),
        )
        .join(StopsMatched, AtlasStop.sloid == StopsMatched.sloid)
        .outerjoin(OsmNode, StopsMatched.osm_node_id == OsmNode.osm_node_id)
        .filter(StopsMatched.stop_type == 'matched')
        .filter(AtlasStop.atlas_business_org_abbr.in_(operator_abbrs))
        .group_by(AtlasStop.atlas_business_org_abbr)
        .all()
    )

    result = {}
    for row in rows:
        abbr = row.atlas_business_org_abbr
        if not abbr:
            continue
        result[abbr] = {
            'matched_stop_count': int(row.matched_stop_count or 0),
            'missing_osm_operator_count': int(row.missing_osm_operator_count or 0),
            'missing_osm_operator_wikidata_count': int(row.missing_osm_operator_wikidata_count or 0),
        }
    return result


def _load_osm_operators(operator_abbrs: list[str]) -> dict[str, list[dict[str, int | str]]]:
    if not operator_abbrs:
        return {}

    rows = (
        db.session.query(
            AtlasStop.atlas_business_org_abbr.label('atlas_business_org_abbr'),
            OsmNode.osm_operator.label('osm_operator'),
            func.count(StopsMatched.id).label('matched_stop_count'),
        )
        .join(StopsMatched, AtlasStop.sloid == StopsMatched.sloid)
        .join(OsmNode, StopsMatched.osm_node_id == OsmNode.osm_node_id)
        .filter(StopsMatched.stop_type == 'matched')
        .filter(AtlasStop.atlas_business_org_abbr.in_(operator_abbrs))
        .filter(OsmNode.osm_operator.isnot(None))
        .filter(OsmNode.osm_operator != '')
        .group_by(AtlasStop.atlas_business_org_abbr, OsmNode.osm_operator)
        .order_by(
            AtlasStop.atlas_business_org_abbr.asc(),
            func.count(StopsMatched.id).desc(),
            OsmNode.osm_operator.asc(),
        )
        .all()
    )

    grouped_rows: dict[str, list[dict[str, int | str]]] = defaultdict(list)
    for row in rows:
        abbr = row.atlas_business_org_abbr
        if not abbr or not row.osm_operator:
            continue
        grouped_rows[abbr].append({
            'osm_operator': row.osm_operator,
            'matched_stop_count': int(row.matched_stop_count or 0),
        })
    return dict(grouped_rows)


def _load_osm_operators_wikidata(operator_abbrs: list[str], supports_osm_operator_wikidata: bool) -> dict[str, list[dict[str, int | str]]]:
    if not operator_abbrs or not supports_osm_operator_wikidata:
        return {}

    rows = (
        db.session.query(
            AtlasStop.atlas_business_org_abbr.label('atlas_business_org_abbr'),
            OsmNode.osm_operator_wikidata.label('osm_operator_wikidata'),
            func.count(StopsMatched.id).label('matched_stop_count'),
        )
        .join(StopsMatched, AtlasStop.sloid == StopsMatched.sloid)
        .join(OsmNode, StopsMatched.osm_node_id == OsmNode.osm_node_id)
        .filter(StopsMatched.stop_type == 'matched')
        .filter(AtlasStop.atlas_business_org_abbr.in_(operator_abbrs))
        .filter(OsmNode.osm_operator_wikidata.isnot(None))
        .filter(OsmNode.osm_operator_wikidata != '')
        .group_by(AtlasStop.atlas_business_org_abbr, OsmNode.osm_operator_wikidata)
        .order_by(
            AtlasStop.atlas_business_org_abbr.asc(),
            func.count(StopsMatched.id).desc(),
            OsmNode.osm_operator_wikidata.asc(),
        )
        .all()
    )

    grouped_rows: dict[str, list[dict[str, int | str]]] = defaultdict(list)
    for row in rows:
        abbr = row.atlas_business_org_abbr
        if not abbr or not row.osm_operator_wikidata:
            continue
        grouped_rows[abbr].append({
            'osm_operator_wikidata': row.osm_operator_wikidata,
            'matched_stop_count': int(row.matched_stop_count or 0),
        })
    return dict(grouped_rows)


def _build_operator_row(operator, stop_counts, match_counts, osm_operators, osm_operators_wikidata, supports_osm_operator_wikidata):
    abbr = operator.atlas_business_org_abbr
    operator_matches = osm_operators.get(abbr, [])
    wikidata_matches = osm_operators_wikidata.get(abbr, [])
    match_summary = match_counts.get(abbr, {})
    atlas_stop_count = stop_counts.get(abbr, 0)
    matched_stop_count = match_summary.get('matched_stop_count', 0)
    missing_osm_operator_count = match_summary.get('missing_osm_operator_count', 0)
    missing_osm_operator_wikidata_count = match_summary.get('missing_osm_operator_wikidata_count', 0)

    return {
        'atlas_business_org_abbr': abbr,
        'atlas_business_org_name': operator.atlas_business_org_name or abbr,
        'atlas_business_org_name_secondary': operator.atlas_business_org_name if operator.atlas_business_org_name and operator.atlas_business_org_name != abbr else None,
        'sboid': operator.sboid,
        'atlas_stop_count': atlas_stop_count,
        'matched_stop_count': matched_stop_count,
        'unmatched_atlas_stop_count': max(atlas_stop_count - matched_stop_count, 0),
        'missing_osm_operator_count': missing_osm_operator_count,
        'missing_osm_operator_wikidata_count': missing_osm_operator_wikidata_count,
        'osm_operator_count': len(operator_matches),
        'osm_operator_wikidata_count': len(wikidata_matches),
        'supports_osm_operator_wikidata': supports_osm_operator_wikidata,
        'has_osm_matches': bool(operator_matches) or bool(wikidata_matches),
        'has_matched_stops': matched_stop_count > 0,
        'osm_operators': operator_matches,
        'osm_operators_wikidata': wikidata_matches,
    }


def _load_operators_view(coverage_filter, q, page, per_page):
    supports_osm_operator_wikidata = _supports_osm_operator_wikidata()
    query = AtlasOperator.query
    has_osm_matches = _matched_osm_operator_subquery().exists()

    if coverage_filter == OPERATOR_COVERAGE_HAS_OSM:
        query = query.filter(has_osm_matches)
    elif coverage_filter == OPERATOR_COVERAGE_NO_OSM:
        query = query.filter(~has_osm_matches)

    if q:
        query = query.filter(_operator_search_condition(q, supports_osm_operator_wikidata))

    pagination = (
        query.order_by(
            func.lower(func.coalesce(AtlasOperator.atlas_business_org_name, AtlasOperator.atlas_business_org_abbr)).asc(),
            AtlasOperator.atlas_business_org_abbr.asc(),
        )
        .paginate(page=page, per_page=per_page, error_out=False)
    )

    operator_abbrs = [operator.atlas_business_org_abbr for operator in pagination.items if operator.atlas_business_org_abbr]
    stop_counts = _load_atlas_stop_counts(operator_abbrs)
    match_counts = _load_match_counts(operator_abbrs, supports_osm_operator_wikidata)
    osm_operators = _load_osm_operators(operator_abbrs)
    osm_operators_wikidata = _load_osm_operators_wikidata(operator_abbrs, supports_osm_operator_wikidata)

    operator_rows = [
        _build_operator_row(
            operator,
            stop_counts,
            match_counts,
            osm_operators,
            osm_operators_wikidata,
            supports_osm_operator_wikidata,
        )
        for operator in pagination.items
    ]
    return operator_rows, pagination, supports_osm_operator_wikidata


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
                coverage_filter if coverage_filter != OPERATOR_COVERAGE_ALL else None,
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
        load_result = _load_operators_view(
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
