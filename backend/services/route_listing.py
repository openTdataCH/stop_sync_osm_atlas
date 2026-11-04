"""Route listing queries: line-family summaries, filters, paging and the per-direction stop rows the routes pages show."""
import json
from collections import defaultdict

from flask import request
from sqlalchemy import String, cast, exists, func, literal, or_, select, union_all
from sqlalchemy.orm import aliased

from backend.db_errors import is_database_timeout_error, is_missing_table_error
from backend.extensions import db
from backend.models import (
    AtlasOperator,
    AtlasStop,
    Itinerary,
    ItineraryMatch,
    LineFamily,
    LineFamilyMatch,
    OsmNode,
    StopCall,
)
from backend.services.route_comparison import compare_stop_calls, load_best_overlaps


ROUTE_MATCH_ALL = 'all'
ROUTE_MATCHED = 'matched'
ROUTE_UNMATCHED = 'unmatched'
ROUTE_UNMATCHED_ATLAS = 'unmatched_atlas'
ROUTE_UNMATCHED_OSM = 'unmatched_osm'
ROUTE_MATCH_FILTERS = {
    ROUTE_MATCH_ALL,
    ROUTE_MATCHED,
    ROUTE_UNMATCHED,
    ROUTE_UNMATCHED_ATLAS,
    ROUTE_UNMATCHED_OSM,
}
ROUTES_RETRY_AFTER_SECONDS = 30


def parse_multi_filter(param_name: str) -> list[str]:
    selected = {
        item.strip()
        for raw_value in request.args.getlist(param_name)
        if raw_value
        for item in raw_value.split(',')
        if item.strip()
    }
    return sorted(selected)


def _osm_route_id_label(gtfs_route_id: str | None, display_route_id: str | None) -> str:
    if _clean_text(gtfs_route_id):
        return 'GTFS ID'
    if _clean_text(display_route_id):
        return 'Route ref'
    return 'Route ID'


def _clean_text(value):
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _deserialize_id_list(value):
    cleaned = _clean_text(value)
    if cleaned is None:
        return []
    try:
        parsed = json.loads(cleaned)
    except (TypeError, ValueError):
        parsed = cleaned
    if isinstance(parsed, list):
        seen = set()
        values = []
        for item in parsed:
            item_text = _clean_text(item)
            if item_text is None or item_text in seen:
                continue
            seen.add(item_text)
            values.append(item_text)
        return values
    return [cleaned]


def _group_stops_by_uic(direction_stops):
    if not direction_stops:
        return []

    grouped_by_uic = {}
    order = []
    for idx, stop in enumerate(direction_stops):
        uic = stop.get('uic_ref') or ''
        if uic not in grouped_by_uic:
            grouped_by_uic[uic] = {
                'uic_ref': uic,
                'stop_label': stop.get('stop_label') or '-',
                'members': [],
                'first_idx': idx,
            }
            order.append(uic)

        grouped_by_uic[uic]['members'].append(
            {
                **stop,
                'stop_ids': stop.get('stop_ids') or ([stop.get('stop_id')] if stop.get('stop_id') else []),
                'stop_label': stop.get('stop_label') or '-',
                'stop_sequence': stop.get('stop_sequence'),
                'lat': stop.get('lat'),
                'lon': stop.get('lon'),
            }
        )

    groups = [grouped_by_uic[uic] for uic in order]
    for group in groups:
        group['member_count'] = sum(max(len(member.get('stop_ids') or []), 1) for member in group['members'])
    return groups


def _direction_sort_key(direction_id):
    if direction_id is None:
        return (2, '')
    direction_text = str(direction_id).strip()
    if direction_text == '':
        return (2, '')
    if direction_text.lstrip('-').isdigit():
        return (0, int(direction_text))
    return (1, direction_text.lower())


def _variant_count(direction_groups):
    return len(direction_groups) if direction_groups else 0


def _count_route_variants(direction_groups):
    atlas_variant_count = sum(1 for group in direction_groups if group.get('has_atlas_variant'))
    osm_variant_count = sum(1 for group in direction_groups if group.get('has_osm_variant'))
    matched_variant_count = sum(1 for group in direction_groups if group.get('is_matched'))
    return atlas_variant_count, osm_variant_count, matched_variant_count


def _route_sort_key(route_item):
    return (
        0 if route_item.get('display_mode') == 'matched' else 1,
        (route_item.get('sort_route_id') or '').lower(),
        route_item.get('display_mode') or '',
    )


def load_available_atlas_operators() -> list[str]:
    rows = (
        db.session.query(AtlasOperator.atlas_business_org_abbr)
        .filter(AtlasOperator.atlas_business_org_abbr.isnot(None), AtlasOperator.atlas_business_org_abbr != '')
        .distinct()
        .order_by(AtlasOperator.atlas_business_org_abbr.asc())
        .all()
    )
    return [row[0] for row in rows if row and row[0]]


def load_available_osm_route_operators() -> list[str]:
    rows = (
        db.session.query(LineFamily.operator)
        .filter(LineFamily.source == 'osm', LineFamily.operator.isnot(None), LineFamily.operator != '')
        .distinct()
        .order_by(LineFamily.operator.asc())
        .all()
    )
    return [row[0] for row in rows if row and row[0]]


def _summary_value(family, column_name):
    if family is None:
        return literal(None)
    return getattr(family, column_name)


def _route_summary_columns(display_mode, atlas_family, osm_family, line_family_match_id):
    atlas_display_id = _summary_value(atlas_family, 'display_route_id')
    osm_display_id = _summary_value(osm_family, 'display_route_id')
    return [
        literal(display_mode).label('display_mode'),
        literal(0 if display_mode == 'matched' else 1).label('sort_priority'),
        func.coalesce(
            func.nullif(func.trim(atlas_display_id), ''),
            func.nullif(func.trim(osm_display_id), ''),
            '',
        ).label('sort_route_id'),
        _summary_value(atlas_family, 'id').label('atlas_family_id'),
        _summary_value(osm_family, 'id').label('osm_family_id'),
        (
            line_family_match_id
            if line_family_match_id is not None
            else literal(None)
        ).label('line_family_match_id'),
        _summary_value(atlas_family, 'source_family_id').label('atlas_source_family_id'),
        atlas_display_id.label('atlas_display_route_id'),
        _summary_value(atlas_family, 'ref').label('atlas_ref'),
        _summary_value(atlas_family, 'public_name').label('atlas_public_name'),
        _summary_value(atlas_family, 'route_type').label('atlas_route_type'),
        _summary_value(atlas_family, 'family_origin').label('atlas_family_origin'),
        _summary_value(atlas_family, 'operator').label('atlas_operator'),
        _summary_value(atlas_family, 'operator_wikidata').label('atlas_operator_wikidata'),
        _summary_value(atlas_family, 'network').label('atlas_network'),
        _summary_value(atlas_family, 'network_wikidata').label('atlas_network_wikidata'),
        _summary_value(atlas_family, 'gtfs_route_id').label('atlas_gtfs_route_id'),
        _summary_value(atlas_family, 'normalized_route_id').label('atlas_normalized_route_id'),
        _summary_value(atlas_family, 'atlas_line_id').label('atlas_line_id'),
        _summary_value(osm_family, 'route_master_id').label('osm_route_master_id'),
        _summary_value(osm_family, 'representative_relation_id').label('osm_representative_relation_id'),
        _summary_value(osm_family, 'gtfs_route_id').label('osm_gtfs_route_id'),
        osm_display_id.label('osm_display_route_id'),
        _summary_value(osm_family, 'public_name').label('osm_public_name'),
        _summary_value(osm_family, 'ref').label('osm_ref'),
        _summary_value(osm_family, 'route_type').label('osm_route_type'),
        _summary_value(osm_family, 'family_origin').label('osm_family_origin'),
        _summary_value(osm_family, 'operator').label('osm_operator'),
        _summary_value(osm_family, 'operator_wikidata').label('osm_operator_wikidata'),
        _summary_value(osm_family, 'network').label('osm_network'),
        _summary_value(osm_family, 'network_wikidata').label('osm_network_wikidata'),
        _summary_value(osm_family, 'normalized_route_id').label('osm_normalized_route_id'),
        (
            _summary_value(osm_family, 'is_non_gtfs')
            if osm_family is not None
            else literal(False)
        ).label('is_non_gtfs'),
    ]


def _build_route_summary_subquery():
    matched_atlas = aliased(LineFamily, name='matched_atlas_family')
    matched_osm = aliased(LineFamily, name='matched_osm_family')
    unmatched_atlas = aliased(LineFamily, name='unmatched_atlas_family')
    unmatched_osm = aliased(LineFamily, name='unmatched_osm_family')

    matched_rows = (
        select(*_route_summary_columns(
            'matched',
            matched_atlas,
            matched_osm,
            LineFamilyMatch.id,
        ))
        .select_from(LineFamilyMatch)
        .join(matched_atlas, matched_atlas.id == LineFamilyMatch.atlas_line_family_id)
        .join(matched_osm, matched_osm.id == LineFamilyMatch.osm_line_family_id)
        .where(
            matched_atlas.source == 'atlas',
            matched_osm.source == 'osm',
        )
    )
    unmatched_atlas_rows = (
        select(*_route_summary_columns('atlas_only', unmatched_atlas, None, None))
        .select_from(unmatched_atlas)
        .where(
            unmatched_atlas.source == 'atlas',
            ~exists(
                select(LineFamilyMatch.id).where(
                    LineFamilyMatch.atlas_line_family_id == unmatched_atlas.id
                )
            ),
        )
    )
    unmatched_osm_rows = (
        select(*_route_summary_columns('osm_only', None, unmatched_osm, None))
        .select_from(unmatched_osm)
        .where(
            unmatched_osm.source == 'osm',
            ~exists(
                select(LineFamilyMatch.id).where(
                    LineFamilyMatch.osm_line_family_id == unmatched_osm.id
                )
            ),
        )
    )

    return union_all(
        matched_rows,
        unmatched_atlas_rows,
        unmatched_osm_rows,
    ).subquery('route_summaries')


def _route_search_condition(summary, query_text):
    search_columns = [
        summary.c.atlas_source_family_id,
        summary.c.atlas_ref,
        summary.c.atlas_public_name,
        summary.c.osm_display_route_id,
        summary.c.osm_public_name,
        summary.c.osm_route_master_id,
        summary.c.osm_representative_relation_id,
    ]
    normalized_query = query_text.lower()
    return or_(*[
        func.lower(func.coalesce(cast(column, String), '')).contains(
            normalized_query,
            autoescape=True,
        )
        for column in search_columns
    ])


def _atlas_operator_family_ids_statement(atlas_operators):
    return (
        select(Itinerary.line_family_id)
        .select_from(Itinerary)
        .join(StopCall, StopCall.itinerary_id == Itinerary.id)
        .join(AtlasStop, AtlasStop.sloid == StopCall.source_sloid)
        .where(
            Itinerary.source == 'atlas',
            AtlasStop.atlas_business_org_abbr.in_(atlas_operators),
        )
        .distinct()
    )


def _load_atlas_operator_map(family_ids):
    if not family_ids:
        return {}

    rows = (
        db.session.query(Itinerary.line_family_id, AtlasStop.atlas_business_org_abbr)
        .join(StopCall, StopCall.itinerary_id == Itinerary.id)
        .join(AtlasStop, AtlasStop.sloid == StopCall.source_sloid)
        .filter(
            Itinerary.source == 'atlas',
            Itinerary.line_family_id.in_(family_ids),
            AtlasStop.atlas_business_org_abbr.isnot(None),
            AtlasStop.atlas_business_org_abbr != '',
        )
        .distinct()
        .all()
    )
    operators_by_family: dict[int, set[str]] = defaultdict(set)
    for family_id, operator in rows:
        operators_by_family[family_id].add(operator)
    return {
        family_id: sorted(operators)
        for family_id, operators in operators_by_family.items()
    }


def _route_item_from_summary(row, atlas_operator_map):
    atlas_route_short_name = _clean_text(row.atlas_ref)
    atlas_route_long_name = _clean_text(row.atlas_public_name)
    if (
        atlas_route_short_name
        and atlas_route_long_name
        and atlas_route_short_name == atlas_route_long_name
    ):
        atlas_route_long_name = None

    is_non_gtfs = bool(row.is_non_gtfs)
    if row.display_mode == 'matched':
        match_label = 'Matched'
    elif row.display_mode == 'atlas_only':
        match_label = 'Unmatched ATLAS'
    else:
        match_label = 'Non-GTFS OSM' if is_non_gtfs else 'Unmatched OSM'

    osm_display_route_id = _clean_text(row.osm_display_route_id)
    osm_gtfs_route_id = _clean_text(row.osm_gtfs_route_id)
    osm_representative_relation_id = _clean_text(row.osm_representative_relation_id)
    atlas_source_family_id = _clean_text(row.atlas_source_family_id)

    return {
        'display_mode': row.display_mode,
        'is_matched': row.display_mode == 'matched',
        'match_label': match_label,
        'sort_route_id': _clean_text(row.sort_route_id) or '',
        'atlas_family_id': row.atlas_family_id,
        'osm_family_id': row.osm_family_id,
        'line_family_match_id': row.line_family_match_id,
        'atlas_route_id': row.atlas_source_family_id,
        'atlas_route_display_id': _clean_text(row.atlas_display_route_id),
        'atlas_route_short_name': atlas_route_short_name,
        'atlas_route_long_name': atlas_route_long_name,
        'atlas_route_name': _clean_text(row.atlas_public_name) or _clean_text(row.atlas_display_route_id),
        'atlas_route_type': _clean_text(row.atlas_route_type),
        'atlas_family_origin': _clean_text(row.atlas_family_origin),
        'atlas_route_operator': _clean_text(row.atlas_operator),
        'atlas_operator_wikidata': _clean_text(row.atlas_operator_wikidata),
        'atlas_network': _clean_text(row.atlas_network),
        'atlas_network_wikidata': _clean_text(row.atlas_network_wikidata),
        'atlas_gtfs_route_id': _clean_text(row.atlas_gtfs_route_id),
        'atlas_normalized_route_id': _clean_text(row.atlas_normalized_route_id),
        'atlas_line_id': _clean_text(row.atlas_line_id),
        'atlas_operators': atlas_operator_map.get(row.atlas_family_id, []),
        'osm_route_master_id': _clean_text(row.osm_route_master_id),
        'osm_route_id': osm_representative_relation_id,
        'osm_representative_relation_id': osm_representative_relation_id,
        'osm_gtfs_route_id': osm_gtfs_route_id,
        'osm_route_display_id': osm_display_route_id,
        'osm_route_id_label': _osm_route_id_label(osm_gtfs_route_id, osm_display_route_id),
        'osm_route_name': (
            _clean_text(row.osm_public_name)
            or _clean_text(row.osm_ref)
            or osm_display_route_id
        ),
        'osm_ref': _clean_text(row.osm_ref),
        'osm_route_type': _clean_text(row.osm_route_type),
        'osm_family_origin': _clean_text(row.osm_family_origin),
        'osm_operator': _clean_text(row.osm_operator),
        'osm_operator_wikidata': _clean_text(row.osm_operator_wikidata),
        'osm_network': _clean_text(row.osm_network),
        'osm_network_wikidata': _clean_text(row.osm_network_wikidata),
        'osm_normalized_route_id': _clean_text(row.osm_normalized_route_id),
        'is_non_gtfs': is_non_gtfs,
        'primary_route_id': atlas_source_family_id or osm_display_route_id,
    }


def _route_listing_statement(
    summary,
    *,
    q='',
    matched_filter=ROUTE_MATCH_ALL,
    atlas_operators=None,
    osm_operators=None,
    non_gtfs_only=False,
):
    """The route cards a listing shows, before ordering and paging."""
    statement = select(summary)

    if non_gtfs_only:
        statement = statement.where(summary.c.is_non_gtfs.is_(True))
    else:
        statement = statement.where(summary.c.is_non_gtfs.is_(False))

    display_modes_by_filter = {
        ROUTE_MATCHED: ('matched',),
        ROUTE_UNMATCHED: ('atlas_only', 'osm_only'),
        ROUTE_UNMATCHED_ATLAS: ('atlas_only',),
        ROUTE_UNMATCHED_OSM: ('osm_only',),
    }
    display_modes = display_modes_by_filter.get(matched_filter)
    if display_modes:
        statement = statement.where(summary.c.display_mode.in_(display_modes))

    atlas_operators = atlas_operators or []
    if atlas_operators:
        statement = statement.where(
            summary.c.atlas_family_id.in_(
                _atlas_operator_family_ids_statement(atlas_operators)
            )
        )

    osm_operators = osm_operators or []
    if osm_operators:
        statement = statement.where(summary.c.osm_operator.in_(osm_operators))

    if q:
        statement = statement.where(_route_search_condition(summary, q))
    return statement


def _route_listing_order(summary):
    return (
        summary.c.sort_priority.asc(),
        func.lower(summary.c.sort_route_id).asc(),
        summary.c.display_mode.asc(),
        summary.c.atlas_family_id.asc(),
        summary.c.osm_family_id.asc(),
    )


def query_route_page(*, page, per_page, **filters):
    summary = _build_route_summary_subquery()
    statement = _route_listing_statement(summary, **filters)

    total = db.session.execute(
        select(func.count()).select_from(statement.order_by(None).subquery())
    ).scalar_one()

    page_rows = db.session.execute(
        statement
        .order_by(*_route_listing_order(summary))
        .offset((page - 1) * per_page)
        .limit(per_page)
    ).all()

    atlas_family_ids = {
        row.atlas_family_id
        for row in page_rows
        if row.atlas_family_id is not None
    }
    atlas_operator_map = _load_atlas_operator_map(atlas_family_ids)
    return [
        _route_item_from_summary(row, atlas_operator_map)
        for row in page_rows
    ], total


def locate_route_variant_page(*, atlas_variant, osm_variant, per_page, **filters):
    """The listing page whose card shows the linked variant, or None.

    A variant belongs to the card of its line family; a matched variant names
    both families and so the matched card.
    """
    family_ids = {}
    for source, source_itinerary_id in (('atlas', atlas_variant), ('osm', osm_variant)):
        if not source_itinerary_id:
            continue
        family_id = db.session.execute(
            select(Itinerary.line_family_id).where(
                Itinerary.source == source,
                Itinerary.source_itinerary_id == source_itinerary_id,
            )
        ).scalar()
        if family_id is None:
            return None
        family_ids[source] = family_id
    if not family_ids:
        return None

    summary = _build_route_summary_subquery()
    ranked = (
        _route_listing_statement(summary, **filters)
        .add_columns(func.row_number().over(order_by=_route_listing_order(summary)).label('position'))
        .subquery()
    )
    conditions = []
    if 'atlas' in family_ids:
        conditions.append(ranked.c.atlas_family_id == family_ids['atlas'])
    if 'osm' in family_ids:
        conditions.append(ranked.c.osm_family_id == family_ids['osm'])
    position = db.session.execute(
        select(ranked.c.position).where(*conditions).order_by(ranked.c.position).limit(1)
    ).scalar()
    return None if position is None else (position - 1) // per_page + 1


def _load_line_family_rows(source: str):
    return (
        db.session.query(
            LineFamily.id.label('id'),
            LineFamily.source_family_id.label('source_family_id'),
            LineFamily.family_origin.label('family_origin'),
            LineFamily.route_type.label('route_type'),
            LineFamily.display_route_id.label('display_route_id'),
            LineFamily.public_name.label('public_name'),
            LineFamily.ref.label('ref'),
            LineFamily.operator.label('operator'),
            LineFamily.operator_wikidata.label('operator_wikidata'),
            LineFamily.network.label('network'),
            LineFamily.network_wikidata.label('network_wikidata'),
            LineFamily.is_non_gtfs.label('is_non_gtfs'),
            LineFamily.gtfs_route_id.label('gtfs_route_id'),
            LineFamily.normalized_route_id.label('normalized_route_id'),
            LineFamily.atlas_line_id.label('atlas_line_id'),
            LineFamily.route_master_id.label('route_master_id'),
            LineFamily.representative_relation_id.label('representative_relation_id'),
        )
        .filter(LineFamily.source == source)
        .all()
    )


def _load_route_page_data():
    atlas_generic_rows = _load_line_family_rows('atlas')
    osm_generic_rows = _load_line_family_rows('osm')
    atlas_generic_by_id = {row.id: row for row in atlas_generic_rows}
    osm_generic_by_id = {row.id: row for row in osm_generic_rows}

    operator_rows = (
        db.session.query(Itinerary.line_family_id, AtlasStop.atlas_business_org_abbr)
        .join(StopCall, StopCall.itinerary_id == Itinerary.id)
        .join(AtlasStop, AtlasStop.sloid == StopCall.source_sloid)
        .filter(Itinerary.source == 'atlas', AtlasStop.atlas_business_org_abbr.isnot(None), AtlasStop.atlas_business_org_abbr != '')
        .distinct()
        .all()
    )
    atlas_operator_map: dict[int, list[str]] = defaultdict(list)
    for line_family_id, operator in operator_rows:
        atlas_operator_map[line_family_id].append(operator)
    for line_family_id in list(atlas_operator_map.keys()):
        atlas_operator_map[line_family_id] = sorted(set(atlas_operator_map[line_family_id]))

    match_rows = db.session.query(LineFamilyMatch).all()
    matched_atlas_ids = {row.atlas_line_family_id for row in match_rows}
    matched_osm_ids = {row.osm_line_family_id for row in match_rows}

    route_items = []
    for match_row in match_rows:
        atlas_family = atlas_generic_by_id.get(match_row.atlas_line_family_id)
        osm_family = osm_generic_by_id.get(match_row.osm_line_family_id)
        if atlas_family is None or osm_family is None:
            continue
        atlas_route_short_name = _clean_text(atlas_family.ref)
        atlas_route_long_name = _clean_text(atlas_family.public_name)
        if atlas_route_short_name and atlas_route_long_name and atlas_route_short_name == atlas_route_long_name:
            atlas_route_long_name = None
        route_items.append({
            'display_mode': 'matched',
            'is_matched': True,
            'match_label': 'Matched',
            'sort_route_id': _clean_text(atlas_family.display_route_id) or _clean_text(osm_family.display_route_id) or '',
            'atlas_family_id': atlas_family.id,
            'osm_family_id': osm_family.id,
            'line_family_match_id': match_row.id,
            'atlas_route_id': atlas_family.source_family_id,
            'atlas_route_display_id': _clean_text(atlas_family.display_route_id),
            'atlas_route_short_name': atlas_route_short_name,
            'atlas_route_long_name': atlas_route_long_name,
            'atlas_route_name': _clean_text(atlas_family.public_name) or _clean_text(atlas_family.display_route_id),
            'atlas_route_type': _clean_text(atlas_family.route_type),
            'atlas_family_origin': _clean_text(atlas_family.family_origin),
            'atlas_route_operator': _clean_text(atlas_family.operator),
            'atlas_operator_wikidata': _clean_text(atlas_family.operator_wikidata),
            'atlas_network': _clean_text(atlas_family.network),
            'atlas_network_wikidata': _clean_text(atlas_family.network_wikidata),
            'atlas_gtfs_route_id': _clean_text(atlas_family.gtfs_route_id),
            'atlas_normalized_route_id': _clean_text(atlas_family.normalized_route_id),
            'atlas_line_id': _clean_text(atlas_family.atlas_line_id),
            'atlas_operators': atlas_operator_map.get(atlas_family.id, []),
            'osm_route_master_id': _clean_text(osm_family.route_master_id),
            'osm_route_id': _clean_text(osm_family.representative_relation_id),
            'osm_representative_relation_id': _clean_text(osm_family.representative_relation_id),
            'osm_gtfs_route_id': _clean_text(osm_family.gtfs_route_id),
            'osm_route_display_id': _clean_text(osm_family.display_route_id),
            'osm_route_id_label': _osm_route_id_label(osm_family.gtfs_route_id, osm_family.display_route_id),
            'osm_route_name': _clean_text(osm_family.public_name) or _clean_text(osm_family.ref) or _clean_text(osm_family.display_route_id),
            'osm_ref': _clean_text(osm_family.ref),
            'osm_route_type': _clean_text(osm_family.route_type),
            'osm_family_origin': _clean_text(osm_family.family_origin),
            'osm_operator': _clean_text(osm_family.operator),
            'osm_operator_wikidata': _clean_text(osm_family.operator_wikidata),
            'osm_network': _clean_text(osm_family.network),
            'osm_network_wikidata': _clean_text(osm_family.network_wikidata),
            'osm_normalized_route_id': _clean_text(osm_family.normalized_route_id),
            'is_non_gtfs': getattr(osm_family, 'is_non_gtfs', False),
            'primary_route_id': _clean_text(atlas_family.source_family_id) or _clean_text(osm_family.display_route_id),
        })

    for atlas_family in atlas_generic_rows:
        if atlas_family.id in matched_atlas_ids:
            continue
        atlas_route_short_name = _clean_text(atlas_family.ref)
        atlas_route_long_name = _clean_text(atlas_family.public_name)
        if atlas_route_short_name and atlas_route_long_name and atlas_route_short_name == atlas_route_long_name:
            atlas_route_long_name = None
        route_items.append({
            'display_mode': 'atlas_only',
            'is_matched': False,
            'match_label': 'Unmatched ATLAS',
            'sort_route_id': _clean_text(atlas_family.display_route_id) or '',
            'atlas_family_id': atlas_family.id,
            'osm_family_id': None,
            'line_family_match_id': None,
            'atlas_route_id': atlas_family.source_family_id,
            'atlas_route_display_id': _clean_text(atlas_family.display_route_id),
            'atlas_route_short_name': atlas_route_short_name,
            'atlas_route_long_name': atlas_route_long_name,
            'atlas_route_name': _clean_text(atlas_family.public_name) or _clean_text(atlas_family.display_route_id),
            'atlas_route_type': _clean_text(atlas_family.route_type),
            'atlas_family_origin': _clean_text(atlas_family.family_origin),
            'atlas_route_operator': _clean_text(atlas_family.operator),
            'atlas_operator_wikidata': _clean_text(atlas_family.operator_wikidata),
            'atlas_network': _clean_text(atlas_family.network),
            'atlas_network_wikidata': _clean_text(atlas_family.network_wikidata),
            'atlas_gtfs_route_id': _clean_text(atlas_family.gtfs_route_id),
            'atlas_normalized_route_id': _clean_text(atlas_family.normalized_route_id),
            'atlas_line_id': _clean_text(atlas_family.atlas_line_id),
            'atlas_operators': atlas_operator_map.get(atlas_family.id, []),
            'osm_route_master_id': None,
            'osm_route_id': None,
            'osm_representative_relation_id': None,
            'osm_gtfs_route_id': None,
            'osm_route_display_id': None,
            'osm_route_id_label': 'Route ID',
            'osm_route_name': None,
            'osm_ref': None,
            'osm_route_type': None,
            'osm_family_origin': None,
            'osm_operator': None,
            'osm_operator_wikidata': None,
            'osm_network': None,
            'osm_network_wikidata': None,
            'osm_normalized_route_id': None,
            'is_non_gtfs': False,
            'primary_route_id': _clean_text(atlas_family.source_family_id),
        })

    for osm_family in osm_generic_rows:
        if osm_family.id in matched_osm_ids:
            continue
        route_items.append({
            'display_mode': 'osm_only',
            'is_matched': False,
            'match_label': 'Non-GTFS OSM' if getattr(osm_family, 'is_non_gtfs', False) else 'Unmatched OSM',
            'sort_route_id': _clean_text(osm_family.display_route_id) or '',
            'atlas_family_id': None,
            'osm_family_id': osm_family.id,
            'line_family_match_id': None,
            'atlas_route_id': None,
            'atlas_route_display_id': None,
            'atlas_route_short_name': None,
            'atlas_route_long_name': None,
            'atlas_route_name': None,
            'atlas_route_type': None,
            'atlas_family_origin': None,
            'atlas_route_operator': None,
            'atlas_operator_wikidata': None,
            'atlas_network': None,
            'atlas_network_wikidata': None,
            'atlas_gtfs_route_id': None,
            'atlas_normalized_route_id': None,
            'atlas_line_id': None,
            'atlas_operators': [],
            'osm_route_master_id': _clean_text(osm_family.route_master_id),
            'osm_route_id': _clean_text(osm_family.representative_relation_id),
            'osm_representative_relation_id': _clean_text(osm_family.representative_relation_id),
            'osm_gtfs_route_id': _clean_text(osm_family.gtfs_route_id),
            'osm_route_display_id': _clean_text(osm_family.display_route_id),
            'osm_route_id_label': _osm_route_id_label(osm_family.gtfs_route_id, osm_family.display_route_id),
            'osm_route_name': _clean_text(osm_family.public_name) or _clean_text(osm_family.ref) or _clean_text(osm_family.display_route_id),
            'osm_ref': _clean_text(osm_family.ref),
            'osm_route_type': _clean_text(osm_family.route_type),
            'osm_family_origin': _clean_text(osm_family.family_origin),
            'osm_operator': _clean_text(osm_family.operator),
            'osm_operator_wikidata': _clean_text(osm_family.operator_wikidata),
            'osm_network': _clean_text(osm_family.network),
            'osm_network_wikidata': _clean_text(osm_family.network_wikidata),
            'osm_normalized_route_id': _clean_text(osm_family.normalized_route_id),
            'is_non_gtfs': getattr(osm_family, 'is_non_gtfs', False),
            'primary_route_id': _clean_text(osm_family.display_route_id),
        })

    return route_items


def _route_matches_filters(route_item, q, atlas_operators, osm_operators, matched_filter):
    if matched_filter == ROUTE_MATCHED and route_item['display_mode'] != 'matched':
        return False
    if matched_filter == ROUTE_UNMATCHED and route_item['display_mode'] == 'matched':
        return False
    if matched_filter == ROUTE_UNMATCHED_ATLAS and route_item['display_mode'] != 'atlas_only':
        return False
    if matched_filter == ROUTE_UNMATCHED_OSM and route_item['display_mode'] != 'osm_only':
        return False

    if atlas_operators:
        route_atlas_operators = set(route_item.get('atlas_operators', []))
        if not route_atlas_operators.intersection(atlas_operators):
            return False
    if osm_operators:
        osm_operator = route_item.get('osm_operator')
        if osm_operator not in osm_operators:
            return False

    if q:
        haystack = [
            route_item.get('atlas_route_id'),
            route_item.get('atlas_route_short_name'),
            route_item.get('atlas_route_long_name'),
            route_item.get('atlas_route_name'),
            route_item.get('osm_route_display_id'),
            route_item.get('osm_route_name'),
            route_item.get('osm_route_master_id'),
            route_item.get('osm_route_id'),
            route_item.get('osm_representative_relation_id'),
        ]
        query_text = q.lower()
        if not any(query_text in str(value).lower() for value in haystack if value):
            return False

    return True


def _partition_route_items(route_items):
    gtfs_route_items = []
    non_gtfs_route_items = []
    for item in route_items:
        if item.get('is_non_gtfs'):
            non_gtfs_route_items.append(item)
        else:
            gtfs_route_items.append(item)
    return gtfs_route_items, non_gtfs_route_items


def _load_detail_maps(page_items):
    selected_family_ids = {
        family_id
        for item in page_items
        for family_id in (item.get('atlas_family_id'), item.get('osm_family_id'))
        if family_id is not None
    }
    selected_match_ids = {item['line_family_match_id'] for item in page_items if item.get('line_family_match_id') is not None}

    itineraries = db.session.query(Itinerary).filter(Itinerary.line_family_id.in_(selected_family_ids)).all() if selected_family_ids else []
    itinerary_by_id = {row.id: row for row in itineraries}

    stop_calls = db.session.query(StopCall).filter(StopCall.itinerary_id.in_(itinerary_by_id.keys())).all() if itinerary_by_id else []
    stop_calls_by_itinerary: dict[int, list[StopCall]] = defaultdict(list)
    for stop_call in stop_calls:
        stop_calls_by_itinerary[stop_call.itinerary_id].append(stop_call)
    for stop_call_list in stop_calls_by_itinerary.values():
        stop_call_list.sort(key=lambda row: (row.stop_sequence, row.id))

    itinerary_matches = db.session.query(ItineraryMatch).filter(ItineraryMatch.line_family_match_id.in_(selected_match_ids)).all() if selected_match_ids else []
    itinerary_matches_by_family_match: dict[int, list[ItineraryMatch]] = defaultdict(list)
    for itinerary_match in itinerary_matches:
        itinerary_matches_by_family_match[itinerary_match.line_family_match_id].append(itinerary_match)
    for match_list in itinerary_matches_by_family_match.values():
        match_list.sort(key=lambda row: (_direction_sort_key(itinerary_by_id.get(row.atlas_itinerary_id).direction_id if itinerary_by_id.get(row.atlas_itinerary_id) else None), row.id))

    itineraries_by_family: dict[int, list[Itinerary]] = defaultdict(list)
    for itinerary in itineraries:
        itineraries_by_family[itinerary.line_family_id].append(itinerary)
    for itinerary_list in itineraries_by_family.values():
        itinerary_list.sort(key=lambda row: (_direction_sort_key(row.direction_id), row.id))

    # Fetch StopsMatched data for all sloids and osm_node_ids in the stop calls to avoid N+1
    page_sloids = {c.source_sloid for c in stop_calls if c.source_sloid}
    page_osm_nodes = {c.source_node_id for c in stop_calls if c.source_node_id}
    
    stops_matched_lookup = {}
    if page_sloids or page_osm_nodes:
        from backend.models import StopsMatched
        matched_rows = db.session.query(
            StopsMatched.sloid,
            StopsMatched.stop_type,
            StopsMatched.atlas_lat,
            StopsMatched.atlas_lon,
            StopsMatched.osm_node_id,
            StopsMatched.osm_lat,
            StopsMatched.osm_lon,
        ).filter(
            or_(
                StopsMatched.sloid.in_(page_sloids) if page_sloids else False,
                StopsMatched.osm_node_id.in_(page_osm_nodes) if page_osm_nodes else False
            )
        ).all()

        atlas_duplicate_lookup = {
            sloid: bool(duplicate_group_sloids)
            for sloid, duplicate_group_sloids in db.session.query(
                AtlasStop.sloid,
                AtlasStop.duplicate_group_sloids,
            ).filter(AtlasStop.sloid.in_(page_sloids)).all()
        } if page_sloids else {}

        osm_node_type_lookup = {
            osm_node_id: osm_node_type
            for osm_node_id, osm_node_type in db.session.query(
                OsmNode.osm_node_id,
                OsmNode.osm_node_type,
            ).filter(OsmNode.osm_node_id.in_(page_osm_nodes)).all()
        } if page_osm_nodes else {}
        
        # Build lookup maps
        # Note: a sloid or node_id might appear in multiple rows if matched to different things,
        # but for markers we just need the stop_type.
        for row in matched_rows:
            if row.sloid:
                stops_matched_lookup[f"atlas_{row.sloid}"] = {
                    'stop_type': row.stop_type,
                    'atlas_lat': row.atlas_lat,
                    'atlas_lon': row.atlas_lon,
                    'osm_node_id': row.osm_node_id,
                    'osm_lat': row.osm_lat,
                    'osm_lon': row.osm_lon,
                    'has_atlas_duplicate': atlas_duplicate_lookup.get(row.sloid, False),
                }
            if row.osm_node_id:
                stops_matched_lookup[f"osm_{row.osm_node_id}"] = {
                    'stop_type': row.stop_type,
                    'osm_lat': row.osm_lat,
                    'osm_lon': row.osm_lon,
                    'osm_node_type': osm_node_type_lookup.get(row.osm_node_id),
                }

    return itinerary_by_id, stop_calls_by_itinerary, itinerary_matches_by_family_match, itineraries_by_family, stops_matched_lookup


def _serialize_stop_calls(stop_calls, source_kind, matched_lookup=None):
    serialized = []
    matched_lookup = matched_lookup or {}
    for stop_call in stop_calls:
        stop_ids = []
        if source_kind == 'atlas':
            stop_ids = _deserialize_id_list(stop_call.source_sloid_variants)
            if not stop_ids and stop_call.source_sloid:
                stop_ids = [stop_call.source_sloid]
        elif stop_call.source_node_id:
            stop_ids = [stop_call.source_node_id]
            
        stop_id = stop_call.source_sloid if source_kind == 'atlas' else stop_call.source_node_id
        match_info = matched_lookup.get(f"{source_kind}_{stop_id}") if stop_id else None
        
        serialized.append({
            'stop_id': stop_id,
            'stop_ids': stop_ids,
            'uic_ref': stop_call.uic_ref,
            'stop_label': stop_call.stop_label,
            'stop_sequence': stop_call.stop_sequence,
            'lat': stop_call.stop_lat,
            'lon': stop_call.stop_lon,
            'stop_type': match_info.get('stop_type') if match_info else (f"{source_kind}_unmatched"),
            'has_atlas_duplicate': match_info.get('has_atlas_duplicate', False) if match_info else False,
            'osm_node_type': match_info.get('osm_node_type') if match_info else None,
            'osm_lat': match_info.get('osm_lat') if match_info and source_kind == 'atlas' else None,
            'osm_lon': match_info.get('osm_lon') if match_info and source_kind == 'atlas' else None,
            'atlas_lat': match_info.get('atlas_lat') if match_info and source_kind == 'osm' else None,
            'atlas_lon': match_info.get('atlas_lon') if match_info and source_kind == 'osm' else None,
        })
    return serialized


def _build_direction_group(atlas_itinerary, osm_itinerary, atlas_calls, osm_calls, matched_lookup=None):
    direction_id = atlas_itinerary.direction_id if atlas_itinerary is not None else (osm_itinerary.direction_id if osm_itinerary is not None else None)
    direction_label = None
    representative_headsign = None
    atlas_headsign = None
    osm_to_name = None
    if atlas_itinerary is not None:
        direction_label = atlas_itinerary.display_name
        representative_headsign = atlas_itinerary.representative_headsign
        atlas_headsign = atlas_itinerary.representative_headsign
    if direction_label is None and osm_itinerary is not None:
        direction_label = osm_itinerary.display_name
    if representative_headsign is None and osm_itinerary is not None:
        representative_headsign = osm_itinerary.representative_headsign
    if osm_itinerary is not None:
        osm_to_name = _clean_text(getattr(osm_itinerary, 'to_name', None)) or _clean_text(getattr(osm_itinerary, 'representative_headsign', None))

    atlas_stops = _serialize_stop_calls(atlas_calls, 'atlas', matched_lookup)
    osm_stops = _serialize_stop_calls(osm_calls, 'osm', matched_lookup)
    is_matched = atlas_itinerary is not None and osm_itinerary is not None
    if is_matched:
        match_label = 'Matched variant'
        match_status = 'matched'
    elif atlas_itinerary is not None:
        match_label = 'Unmatched ATLAS variant'
        match_status = 'unmatched-atlas'
    else:
        match_label = 'Unmatched OSM variant'
        match_status = 'unmatched-osm'

    return {
        'direction_id': direction_id,
        'direction_label': direction_label,
        'representative_headsign': representative_headsign,
        'atlas_headsign': atlas_headsign,
        'osm_to_name': osm_to_name,
        'atlas_source_itinerary_id': _clean_text(getattr(atlas_itinerary, 'source_itinerary_id', None)),
        'osm_relation_id': _clean_text(osm_itinerary.source_itinerary_id) if osm_itinerary is not None else None,
        'atlas_itinerary_id': getattr(atlas_itinerary, 'id', None),
        'osm_itinerary_id': getattr(osm_itinerary, 'id', None),
        # One-sided for an unmatched variant: its own stops, with no percentage.
        'stop_comparison': compare_stop_calls(atlas_calls, osm_calls, atlas_itinerary, osm_itinerary),
        'best_overlap': None,
        'atlas_uic_groups': _group_stops_by_uic(atlas_stops),
        'osm_uic_groups': _group_stops_by_uic(osm_stops),
        'has_atlas_variant': atlas_itinerary is not None,
        'has_osm_variant': osm_itinerary is not None,
        'is_matched': is_matched,
        'match_label': match_label,
        'match_status': match_status,
    }


def build_route_rows(page_items):
    itinerary_by_id, stop_calls_by_itinerary, itinerary_matches_by_family_match, itineraries_by_family, stops_matched_lookup = _load_detail_maps(page_items)
    route_rows = []

    for item in page_items:
        direction_groups = []
        matched_atlas_itinerary_ids = set()
        matched_osm_itinerary_ids = set()

        if item.get('line_family_match_id') is not None:
            for itinerary_match in itinerary_matches_by_family_match.get(item['line_family_match_id'], []):
                atlas_itinerary = itinerary_by_id.get(itinerary_match.atlas_itinerary_id)
                osm_itinerary = itinerary_by_id.get(itinerary_match.osm_itinerary_id)
                if atlas_itinerary is None or osm_itinerary is None:
                    continue
                matched_atlas_itinerary_ids.add(atlas_itinerary.id)
                matched_osm_itinerary_ids.add(osm_itinerary.id)
                direction_groups.append(
                    _build_direction_group(
                        atlas_itinerary,
                        osm_itinerary,
                        stop_calls_by_itinerary.get(atlas_itinerary.id, []),
                        stop_calls_by_itinerary.get(osm_itinerary.id, []),
                        stops_matched_lookup
                    )
                )

        if item.get('atlas_family_id') is not None:
            for itinerary in itineraries_by_family.get(item['atlas_family_id'], []):
                if itinerary.id in matched_atlas_itinerary_ids:
                    continue
                direction_groups.append(
                    _build_direction_group(
                        itinerary,
                        None,
                        stop_calls_by_itinerary.get(itinerary.id, []),
                        [],
                        stops_matched_lookup
                    )
                )
        if item.get('osm_family_id') is not None:
            for itinerary in itineraries_by_family.get(item['osm_family_id'], []):
                if itinerary.id in matched_osm_itinerary_ids:
                    continue
                direction_groups.append(
                    _build_direction_group(
                        None,
                        itinerary,
                        [],
                        stop_calls_by_itinerary.get(itinerary.id, []),
                        stops_matched_lookup
                    )
                )

        direction_groups.sort(key=lambda group: (
            not group['is_matched'],
            _direction_sort_key(group['direction_id']),
            group['direction_label'] or '',
        ))
        atlas_variant_count, osm_variant_count, matched_variant_count = _count_route_variants(direction_groups)

        map_filter = None
        has_geolocated_stops = any(
            member.get('lat') is not None and member.get('lon') is not None
            for direction_group in direction_groups
            for uic_group in (direction_group.get('atlas_uic_groups', []) + direction_group.get('osm_uic_groups', []))
            for member in uic_group.get('members', [])
        )
        if has_geolocated_stops and item.get('primary_route_id'):
            map_filter = {
                'station_filter': item['primary_route_id'],
                'filter_types': 'route',
                'route_directions': '',
            }

        route_rows.append({
            **item,
            'atlas_operators_summary': ', '.join(item.get('atlas_operators', [])) if item.get('atlas_operators') else None,
            'direction_groups': direction_groups,
            'variant_count': _variant_count(direction_groups),
            'atlas_variant_count': atlas_variant_count,
            'osm_variant_count': osm_variant_count,
            'matched_variant_count': matched_variant_count,
            'map_filter': map_filter,
        })

    return route_rows


def attach_best_overlaps(route_rows):
    """Give each unmatched variant its stored best overlap with the other source."""
    groups = [group for row in route_rows for group in row['direction_groups'] if not group['is_matched']]
    overlaps = load_best_overlaps({group['atlas_itinerary_id'] or group['osm_itinerary_id'] for group in groups})
    for group in groups:
        group['best_overlap'] = overlaps.get(group['atlas_itinerary_id'] or group['osm_itinerary_id'])


def recover_database_error(exc) -> str:
    """Roll back after a missing route table or a database timeout and say which: 'missing' or 'busy'.

    Any other error is raised again.
    """
    if is_missing_table_error(exc):
        db.session.rollback()
        return 'missing'
    if is_database_timeout_error(exc):
        db.session.rollback()
        return 'busy'
    raise exc
