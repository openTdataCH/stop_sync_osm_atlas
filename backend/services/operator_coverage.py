"""Operator coverage: per ATLAS operator, its stops, their OSM matches and the OSM operator tags on them."""
from collections import defaultdict

from sqlalchemy import case, func, or_

from backend.extensions import db
from backend.models import AtlasOperator, AtlasStop, OsmNode, StopsMatched


OPERATOR_COVERAGE_ALL = 'all'
OPERATOR_COVERAGE_HAS_OSM = 'has_osm_matches'
OPERATOR_COVERAGE_NO_OSM = 'no_osm_matches'
OPERATOR_COVERAGE_FILTERS = {
    OPERATOR_COVERAGE_ALL,
    OPERATOR_COVERAGE_HAS_OSM,
    OPERATOR_COVERAGE_NO_OSM,
}


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


def _operator_search_condition(q: str):
    pattern = f'%{q}%'
    matched_osm_search = (
        db.session.query(StopsMatched.id)
        .join(AtlasStop, AtlasStop.sloid == StopsMatched.sloid)
        .join(OsmNode, StopsMatched.osm_node_id == OsmNode.osm_node_id)
        .filter(StopsMatched.stop_type == 'matched')
        .filter(AtlasStop.atlas_business_org_abbr == AtlasOperator.atlas_business_org_abbr)
        .filter(or_(OsmNode.osm_operator.ilike(pattern), OsmNode.osm_operator_wikidata.ilike(pattern)))
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


def _distinct_osm_stop_count(condition=None):
    """Count each matched OSM stop once, even when it matches several ATLAS stops."""
    if condition is None:
        return func.count(func.distinct(StopsMatched.osm_node_id))
    return func.count(func.distinct(case((condition, StopsMatched.osm_node_id))))


def _load_match_counts(operator_abbrs: list[str]) -> dict[str, dict[str, int]]:
    if not operator_abbrs:
        return {}

    rows = (
        db.session.query(
            AtlasStop.atlas_business_org_abbr.label('atlas_business_org_abbr'),
            func.count(func.distinct(StopsMatched.sloid)).label('matched_atlas_stop_count'),
            _distinct_osm_stop_count().label('matched_osm_stop_count'),
            _distinct_osm_stop_count(
                or_(OsmNode.osm_operator.is_(None), OsmNode.osm_operator == '')
            ).label('missing_osm_operator_count'),
            _distinct_osm_stop_count(
                or_(OsmNode.osm_operator_wikidata.is_(None), OsmNode.osm_operator_wikidata == '')
            ).label('missing_osm_operator_wikidata_count'),
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
            'matched_atlas_stop_count': int(row.matched_atlas_stop_count or 0),
            'matched_osm_stop_count': int(row.matched_osm_stop_count or 0),
            'missing_osm_operator_count': int(row.missing_osm_operator_count or 0),
            'missing_osm_operator_wikidata_count': int(row.missing_osm_operator_wikidata_count or 0),
        }
    return result


def _load_osm_values(operator_abbrs: list[str], column) -> dict[str, list[dict[str, int | str]]]:
    """Per ATLAS operator, each value of the OSM tag ``column`` on its matched OSM stops, most frequent first."""
    if not operator_abbrs:
        return {}

    osm_stop_count = _distinct_osm_stop_count()
    rows = (
        db.session.query(AtlasStop.atlas_business_org_abbr, column, osm_stop_count)
        .join(StopsMatched, AtlasStop.sloid == StopsMatched.sloid)
        .join(OsmNode, StopsMatched.osm_node_id == OsmNode.osm_node_id)
        .filter(StopsMatched.stop_type == 'matched')
        .filter(AtlasStop.atlas_business_org_abbr.in_(operator_abbrs))
        .filter(column.isnot(None))
        .filter(column != '')
        .group_by(AtlasStop.atlas_business_org_abbr, column)
        .order_by(AtlasStop.atlas_business_org_abbr.asc(), osm_stop_count.desc(), column.asc())
        .all()
    )

    grouped_rows: dict[str, list[dict[str, int | str]]] = defaultdict(list)
    for abbr, value, count in rows:
        if abbr and value:
            grouped_rows[abbr].append({column.key: value, 'matched_stop_count': int(count or 0)})
    return dict(grouped_rows)


def _operator_tag_status(matched_osm_stop_count: int, osm_operator_count: int, missing_osm_operator_count: int) -> tuple[str, str]:
    """Summarize how consistently matched OSM stops carry an operator tag."""
    if matched_osm_stop_count == 0:
        return 'no-matches', 'No matched stops'
    if osm_operator_count == 0:
        return 'untagged', 'Not tagged'
    if osm_operator_count > 1:
        return 'mixed', f'{osm_operator_count} different values'
    if missing_osm_operator_count > 0:
        return 'partial', 'Partly tagged'
    return 'consistent', 'Consistent'


def _build_operator_row(operator, stop_counts, match_counts, osm_operators, osm_operators_wikidata):
    abbr = operator.atlas_business_org_abbr
    operator_matches = osm_operators.get(abbr, [])
    wikidata_matches = osm_operators_wikidata.get(abbr, [])
    match_summary = match_counts.get(abbr, {})
    atlas_stop_count = stop_counts.get(abbr, 0)
    matched_atlas_stop_count = match_summary.get('matched_atlas_stop_count', 0)
    matched_osm_stop_count = match_summary.get('matched_osm_stop_count', 0)
    missing_osm_operator_count = match_summary.get('missing_osm_operator_count', 0)
    missing_osm_operator_wikidata_count = match_summary.get('missing_osm_operator_wikidata_count', 0)
    tag_status, tag_status_label = _operator_tag_status(
        matched_osm_stop_count,
        len(operator_matches),
        missing_osm_operator_count,
    )

    return {
        'atlas_business_org_abbr': abbr,
        'atlas_business_org_name': operator.atlas_business_org_name or abbr,
        'atlas_business_org_name_secondary': operator.atlas_business_org_name if operator.atlas_business_org_name and operator.atlas_business_org_name != abbr else None,
        'sboid': operator.sboid,
        'atlas_stop_count': atlas_stop_count,
        'matched_atlas_stop_count': matched_atlas_stop_count,
        'matched_osm_stop_count': matched_osm_stop_count,
        'unmatched_atlas_stop_count': max(atlas_stop_count - matched_atlas_stop_count, 0),
        'missing_osm_operator_count': missing_osm_operator_count,
        'missing_osm_operator_wikidata_count': missing_osm_operator_wikidata_count,
        'osm_operator_count': len(operator_matches),
        'osm_operator_wikidata_count': len(wikidata_matches),
        'has_osm_matches': bool(operator_matches) or bool(wikidata_matches),
        'has_matched_stops': matched_osm_stop_count > 0,
        'tag_status': tag_status,
        'tag_status_label': tag_status_label,
        'osm_operators': operator_matches,
        'osm_operators_wikidata': wikidata_matches,
    }


def load_operators_view(coverage_filter, q, page, per_page):
    query = AtlasOperator.query
    has_osm_matches = _matched_osm_operator_subquery().exists()

    if coverage_filter == OPERATOR_COVERAGE_HAS_OSM:
        query = query.filter(has_osm_matches)
    elif coverage_filter == OPERATOR_COVERAGE_NO_OSM:
        query = query.filter(~has_osm_matches)

    if q:
        query = query.filter(_operator_search_condition(q))

    pagination = (
        query.order_by(
            func.lower(func.coalesce(AtlasOperator.atlas_business_org_name, AtlasOperator.atlas_business_org_abbr)).asc(),
            AtlasOperator.atlas_business_org_abbr.asc(),
        )
        .paginate(page=page, per_page=per_page, error_out=False)
    )

    operator_abbrs = [operator.atlas_business_org_abbr for operator in pagination.items if operator.atlas_business_org_abbr]
    stop_counts = _load_atlas_stop_counts(operator_abbrs)
    match_counts = _load_match_counts(operator_abbrs)
    osm_operators = _load_osm_values(operator_abbrs, OsmNode.osm_operator)
    osm_operators_wikidata = _load_osm_values(operator_abbrs, OsmNode.osm_operator_wikidata)

    operator_rows = [
        _build_operator_row(
            operator,
            stop_counts,
            match_counts,
            osm_operators,
            osm_operators_wikidata,
        )
        for operator in pagination.items
    ]
    return operator_rows, pagination
