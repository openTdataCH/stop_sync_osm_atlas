import os

from sqlalchemy import case, func

from backend.extensions import db
from backend.models import AtlasStop, GtfsStopIdentityResolution, GtfsStopRaw, StopsMatched
from backend.services.stats_export import load_stats_from_file


GTFS_STOP_ID_SLOID_DETAIL_ZOOM = int(os.getenv('GTFS_STOP_ID_SLOID_DETAIL_ZOOM', '11'))
GTFS_STOP_ID_SLOID_DETAIL_LIMIT = int(os.getenv('GTFS_STOP_ID_SLOID_DETAIL_LIMIT', '5000'))
GTFS_STOP_ID_SLOID_OVERVIEW_LIMIT = int(os.getenv('GTFS_STOP_ID_SLOID_OVERVIEW_LIMIT', '3000'))
GTFS_STOP_ID_SLOID_POPUP_PREVIEW_LIMIT = 8


def _round_pct(numerator, denominator, digits=1):
    if not denominator:
        return 0.0
    return round((numerator / denominator) * 100, digits)


def _build_match_count_subqueries():
    gtfs_counts = (
        db.session.query(
            GtfsStopIdentityResolution.stop_id.label('stop_id'),
            func.count(GtfsStopIdentityResolution.id).label('match_count'),
        )
        .filter(GtfsStopIdentityResolution.resolved_sloid.isnot(None))
        .group_by(GtfsStopIdentityResolution.stop_id)
        .subquery()
    )
    atlas_counts = (
        db.session.query(
            GtfsStopIdentityResolution.resolved_sloid.label('sloid'),
            func.count(GtfsStopIdentityResolution.id).label('match_count'),
        )
        .filter(GtfsStopIdentityResolution.resolved_sloid.isnot(None))
        .group_by(GtfsStopIdentityResolution.resolved_sloid)
        .subquery()
    )
    return gtfs_counts, atlas_counts


def _build_gtfs_coordinate_subquery():
    return (
        db.session.query(
            GtfsStopRaw.stop_id.label('stop_id'),
            GtfsStopRaw.stop_lat.label('gtfs_stop_lat'),
            GtfsStopRaw.stop_lon.label('gtfs_stop_lon'),
        )
        .filter(GtfsStopRaw.stop_lat.isnot(None), GtfsStopRaw.stop_lon.isnot(None))
        .subquery()
    )


def _build_atlas_coordinate_subquery():
    ranked_rows = (
        db.session.query(
            StopsMatched.sloid.label('sloid'),
            StopsMatched.atlas_lat.label('atlas_lat'),
            StopsMatched.atlas_lon.label('atlas_lon'),
            func.row_number().over(
                partition_by=StopsMatched.sloid,
                order_by=(
                    case((StopsMatched.stop_type == 'matched', 0), else_=1),
                    StopsMatched.id.asc(),
                ),
            ).label('coord_rank'),
        )
        .filter(StopsMatched.sloid.isnot(None))
        .filter(StopsMatched.atlas_lat.isnot(None))
        .filter(StopsMatched.atlas_lon.isnot(None))
        .subquery()
    )

    return (
        db.session.query(
            ranked_rows.c.sloid.label('sloid'),
            ranked_rows.c.atlas_lat.label('atlas_lat'),
            ranked_rows.c.atlas_lon.label('atlas_lon'),
        )
        .filter(ranked_rows.c.coord_rank == 1)
        .subquery()
    )


def _fetch_balanced_rows(matched_query, unmatched_query, active_limit):
    if active_limit <= 0:
        return [], False

    matched_rows = matched_query.limit(active_limit + 1).all()
    unmatched_rows = unmatched_query.limit(active_limit + 1).all()

    preferred_matched = max(1, active_limit // 2)
    preferred_unmatched = active_limit - preferred_matched

    matched_take = min(len(matched_rows), preferred_matched)
    unmatched_take = min(len(unmatched_rows), preferred_unmatched)
    remaining = active_limit - matched_take - unmatched_take

    if remaining > 0:
        extra_matched = min(max(len(matched_rows) - matched_take, 0), remaining)
        matched_take += extra_matched
        remaining -= extra_matched
    if remaining > 0:
        extra_unmatched = min(max(len(unmatched_rows) - unmatched_take, 0), remaining)
        unmatched_take += extra_unmatched

    capped = len(matched_rows) > matched_take or len(unmatched_rows) > unmatched_take
    return matched_rows[:matched_take] + unmatched_rows[:unmatched_take], capped


def build_gtfs_stop_id_sloid_summary():
    gtfs_coords = _build_gtfs_coordinate_subquery()
    atlas_coords = _build_atlas_coordinate_subquery()

    total_gtfs_stops = db.session.query(func.count(GtfsStopRaw.stop_id)).scalar() or 0
    matched_gtfs_stops = (
        db.session.query(func.count(func.distinct(GtfsStopIdentityResolution.stop_id)))
        .filter(GtfsStopIdentityResolution.resolved_sloid.isnot(None))
        .scalar()
        or 0
    )
    total_atlas_stops = db.session.query(func.count(AtlasStop.sloid)).scalar() or 0
    matched_atlas_stops = (
        db.session.query(func.count(func.distinct(GtfsStopIdentityResolution.resolved_sloid)))
        .filter(GtfsStopIdentityResolution.resolved_sloid.isnot(None))
        .scalar()
        or 0
    )

    assignment_counts = {
        'original_stop_id': 0,
        'strict': 0,
        'coordinate_proximity': 0,
        'unique_number_fallback': 0,
        'total': 0,
    }
    for resolution_method, count in (
        db.session.query(GtfsStopIdentityResolution.resolution_method, func.count(GtfsStopIdentityResolution.id))
        .filter(GtfsStopIdentityResolution.resolved_sloid.isnot(None))
        .group_by(GtfsStopIdentityResolution.resolution_method)
        .all()
    ):
        normalized_method = str(resolution_method or '').strip().lower()
        if normalized_method == 'unique_number':
            assignment_counts['unique_number_fallback'] = int(count)
        elif normalized_method == 'uic_platform':
            assignment_counts['strict'] = int(count)
        elif normalized_method in assignment_counts:
            assignment_counts[normalized_method] = int(count)
        assignment_counts['total'] += int(count)

    stats = load_stats_from_file() or {}
    gtfs_stats = stats.get('gtfs_atlas') or {}
    if assignment_counts['total'] == 0 and gtfs_stats.get('assignments'):
        assignment_counts.update(gtfs_stats['assignments'])

    return {
        'algorithm_version': gtfs_stats.get('algorithm_version'),
        'total_gtfs_stops': int(total_gtfs_stops),
        'matched_gtfs_stops': int(matched_gtfs_stops),
        'unmatched_gtfs_stops': max(int(total_gtfs_stops) - int(matched_gtfs_stops), 0),
        'gtfs_coverage_percent': _round_pct(matched_gtfs_stops, total_gtfs_stops, digits=2),
        'total_atlas_stops': int(total_atlas_stops),
        'matched_atlas_stops': int(matched_atlas_stops),
        'unmatched_atlas_stops': max(int(total_atlas_stops) - int(matched_atlas_stops), 0),
        'atlas_coverage_percent': _round_pct(matched_atlas_stops, total_atlas_stops, digits=1),
        'assignments': assignment_counts,
    }


def build_gtfs_stop_id_sloid_map_payload(min_lat, min_lon, max_lat, max_lon, zoom):
    active_limit = GTFS_STOP_ID_SLOID_OVERVIEW_LIMIT if zoom < GTFS_STOP_ID_SLOID_DETAIL_ZOOM else GTFS_STOP_ID_SLOID_DETAIL_LIMIT
    gtfs_counts, atlas_counts = _build_match_count_subqueries()
    gtfs_coords = _build_gtfs_coordinate_subquery()
    atlas_coords = _build_atlas_coordinate_subquery()

    gtfs_match_count = func.coalesce(gtfs_counts.c.match_count, 0)
    atlas_match_count = func.coalesce(atlas_counts.c.match_count, 0)

    gtfs_base = (
        db.session.query(
            GtfsStopRaw.stop_id.label('stop_id'),
            GtfsStopRaw.stop_name.label('stop_name'),
            GtfsStopRaw.uic_number.label('uic_number'),
            GtfsStopRaw.local_ref.label('local_ref'),
            GtfsStopRaw.normalized_local_ref.label('normalized_local_ref'),
            gtfs_coords.c.gtfs_stop_lat.label('stop_lat'),
            gtfs_coords.c.gtfs_stop_lon.label('stop_lon'),
            gtfs_match_count.label('match_count'),
        )
        .join(gtfs_coords, gtfs_coords.c.stop_id == GtfsStopRaw.stop_id)
        .outerjoin(gtfs_counts, gtfs_counts.c.stop_id == GtfsStopRaw.stop_id)
        .filter(
            gtfs_coords.c.gtfs_stop_lat >= min_lat,
            gtfs_coords.c.gtfs_stop_lat <= max_lat,
            gtfs_coords.c.gtfs_stop_lon >= min_lon,
            gtfs_coords.c.gtfs_stop_lon <= max_lon,
        )
    )
    atlas_base = (
        db.session.query(
            AtlasStop.sloid.label('sloid'),
            AtlasStop.uic_ref.label('uic_ref'),
            AtlasStop.atlas_designation.label('atlas_designation'),
            AtlasStop.atlas_designation_official.label('atlas_designation_official'),
            AtlasStop.atlas_business_org_abbr.label('atlas_business_org_abbr'),
            AtlasStop.duplicate_group_sloids.label('duplicate_group_sloids'),
            atlas_coords.c.atlas_lat.label('atlas_lat'),
            atlas_coords.c.atlas_lon.label('atlas_lon'),
            atlas_match_count.label('match_count'),
        )
        .join(atlas_coords, atlas_coords.c.sloid == AtlasStop.sloid)
        .outerjoin(atlas_counts, atlas_counts.c.sloid == AtlasStop.sloid)
        .filter(
            atlas_coords.c.atlas_lat >= min_lat,
            atlas_coords.c.atlas_lat <= max_lat,
            atlas_coords.c.atlas_lon >= min_lon,
            atlas_coords.c.atlas_lon <= max_lon,
        )
    )

    gtfs_rows, gtfs_capped = _fetch_balanced_rows(
        gtfs_base.filter(gtfs_match_count > 0).order_by(GtfsStopRaw.uic_number.asc(), GtfsStopRaw.stop_id.asc()),
        gtfs_base.filter(gtfs_match_count == 0).order_by(GtfsStopRaw.uic_number.asc(), GtfsStopRaw.stop_id.asc()),
        active_limit,
    )
    atlas_rows, atlas_capped = _fetch_balanced_rows(
        atlas_base.filter(atlas_match_count > 0).order_by(AtlasStop.uic_ref.asc(), AtlasStop.sloid.asc()),
        atlas_base.filter(atlas_match_count == 0).order_by(AtlasStop.uic_ref.asc(), AtlasStop.sloid.asc()),
        active_limit,
    )

    gtfs_stop_ids = [row.stop_id for row in gtfs_rows]
    atlas_sloids = [row.sloid for row in atlas_rows]

    match_rows = []
    if gtfs_stop_ids and atlas_sloids:
        match_rows = (
            db.session.query(GtfsStopIdentityResolution)
            .filter(
                GtfsStopIdentityResolution.stop_id.in_(gtfs_stop_ids),
                GtfsStopIdentityResolution.resolved_sloid.in_(atlas_sloids),
            )
            .order_by(
                GtfsStopIdentityResolution.resolution_method.asc(),
                GtfsStopIdentityResolution.resolved_sloid.asc(),
                GtfsStopIdentityResolution.stop_id.asc(),
            )
            .all()
        )

    return {
        'gtfs_stops': [
            {
                'stop_id': row.stop_id,
                'stop_name': row.stop_name,
                'uic_number': row.uic_number,
                'local_ref': row.local_ref,
                'normalized_local_ref': row.normalized_local_ref,
                'stop_lat': row.stop_lat,
                'stop_lon': row.stop_lon,
                'match_status': 'matched' if int(row.match_count or 0) > 0 else 'unmatched',
                'matched_sloid_count': int(row.match_count or 0),
            }
            for row in gtfs_rows
        ],
        'atlas_stops': [
            {
                'sloid': row.sloid,
                'uic_ref': row.uic_ref,
                'atlas_designation': row.atlas_designation,
                'atlas_designation_official': row.atlas_designation_official,
                'atlas_business_org_abbr': row.atlas_business_org_abbr,
                'atlas_lat': row.atlas_lat,
                'atlas_lon': row.atlas_lon,
                'match_status': 'matched' if int(row.match_count or 0) > 0 else 'unmatched',
                'matched_gtfs_count': int(row.match_count or 0),
                'has_atlas_duplicate': bool(row.duplicate_group_sloids),
            }
            for row in atlas_rows
        ],
        'matches': [
            {
                'stop_id': match.stop_id,
                'sloid': match.resolved_sloid,
                'match_method': match.resolution_method,
                'distance_m': match.distance_m,
                'gtfs_stop_lat': match.gtfs_stop_lat,
                'gtfs_stop_lon': match.gtfs_stop_lon,
                'atlas_lat': match.atlas_lat,
                'atlas_lon': match.atlas_lon,
            }
            for match in match_rows
        ],
        'meta': {
            'zoom': zoom,
            'detail_zoom': GTFS_STOP_ID_SLOID_DETAIL_ZOOM,
            'detail_limit': GTFS_STOP_ID_SLOID_DETAIL_LIMIT,
            'overview_limit': GTFS_STOP_ID_SLOID_OVERVIEW_LIMIT,
            'overview_mode': zoom < GTFS_STOP_ID_SLOID_DETAIL_ZOOM,
            'gtfs_capped': gtfs_capped,
            'atlas_capped': atlas_capped,
            'gtfs_returned': len(gtfs_rows),
            'atlas_returned': len(atlas_rows),
            'matches_returned': len(match_rows),
        },
    }


def build_gtfs_stop_popup(stop_id):
    stop = db.session.get(GtfsStopRaw, stop_id)
    if stop is None:
        return None

    atlas_coords = _build_atlas_coordinate_subquery()
    stop_lat = stop.stop_lat
    stop_lon = stop.stop_lon

    matched_rows = (
        db.session.query(GtfsStopIdentityResolution, AtlasStop)
        .join(AtlasStop, AtlasStop.sloid == GtfsStopIdentityResolution.resolved_sloid)
        .filter(GtfsStopIdentityResolution.stop_id == stop_id, GtfsStopIdentityResolution.resolved_sloid.isnot(None))
        .order_by(GtfsStopIdentityResolution.resolution_method.asc(), AtlasStop.sloid.asc())
        .limit(GTFS_STOP_ID_SLOID_POPUP_PREVIEW_LIMIT)
        .all()
    )
    matched_count = (
        db.session.query(func.count(GtfsStopIdentityResolution.id))
        .filter(GtfsStopIdentityResolution.stop_id == stop_id, GtfsStopIdentityResolution.resolved_sloid.isnot(None))
        .scalar()
        or 0
    )

    candidate_rows = (
        db.session.query(
            AtlasStop,
            atlas_coords.c.atlas_lat.label('atlas_lat'),
            atlas_coords.c.atlas_lon.label('atlas_lon'),
        )
        .outerjoin(atlas_coords, atlas_coords.c.sloid == AtlasStop.sloid)
        .filter(AtlasStop.uic_ref == stop.uic_number)
        .order_by(AtlasStop.sloid.asc())
        .limit(GTFS_STOP_ID_SLOID_POPUP_PREVIEW_LIMIT)
        .all()
    )
    candidate_count = db.session.query(func.count(AtlasStop.sloid)).filter(AtlasStop.uic_ref == stop.uic_number).scalar() or 0

    return {
        'entity_type': 'gtfs',
        'stop_id': stop.stop_id,
        'stop_name': stop.stop_name,
        'uic_number': stop.uic_number,
        'local_ref': stop.local_ref,
        'normalized_local_ref': stop.normalized_local_ref,
        'stop_lat': stop_lat,
        'stop_lon': stop_lon,
        'matched_sloid_count': int(matched_count),
        'candidate_atlas_count': int(candidate_count),
        'matched_sloids': [
            {
                'sloid': atlas_stop.sloid,
                'atlas_designation': atlas_stop.atlas_designation,
                'atlas_designation_official': atlas_stop.atlas_designation_official,
                'atlas_business_org_abbr': atlas_stop.atlas_business_org_abbr,
                'atlas_lat': match.atlas_lat,
                'atlas_lon': match.atlas_lon,
                'match_method': match.resolution_method,
                'distance_m': match.distance_m,
            }
            for match, atlas_stop in matched_rows
        ],
        'candidate_atlas': [
            {
                'sloid': atlas_stop.sloid,
                'atlas_designation': atlas_stop.atlas_designation,
                'atlas_designation_official': atlas_stop.atlas_designation_official,
                'atlas_business_org_abbr': atlas_stop.atlas_business_org_abbr,
                'atlas_lat': atlas_lat,
                'atlas_lon': atlas_lon,
            }
            for atlas_stop, atlas_lat, atlas_lon in candidate_rows
        ],
    }


def build_atlas_stop_popup(sloid):
    atlas_coords = _build_atlas_coordinate_subquery()
    stop = db.session.get(AtlasStop, sloid)
    if stop is None:
        return None

    stop_coords = (
        db.session.query(atlas_coords.c.atlas_lat, atlas_coords.c.atlas_lon)
        .filter(atlas_coords.c.sloid == sloid)
        .first()
    )
    atlas_lat = stop_coords.atlas_lat if stop_coords else None
    atlas_lon = stop_coords.atlas_lon if stop_coords else None

    matched_rows = (
        db.session.query(GtfsStopIdentityResolution, GtfsStopRaw)
        .join(GtfsStopRaw, GtfsStopRaw.stop_id == GtfsStopIdentityResolution.stop_id)
        .filter(GtfsStopIdentityResolution.resolved_sloid == sloid)
        .order_by(GtfsStopIdentityResolution.resolution_method.asc(), GtfsStopRaw.stop_id.asc())
        .limit(GTFS_STOP_ID_SLOID_POPUP_PREVIEW_LIMIT)
        .all()
    )
    matched_count = (
        db.session.query(func.count(GtfsStopIdentityResolution.id))
        .filter(GtfsStopIdentityResolution.resolved_sloid == sloid)
        .scalar()
        or 0
    )

    same_uic_rows = (
        db.session.query(GtfsStopRaw)
        .filter(GtfsStopRaw.uic_number == stop.uic_ref)
        .order_by(GtfsStopRaw.stop_id.asc())
        .limit(GTFS_STOP_ID_SLOID_POPUP_PREVIEW_LIMIT)
        .all()
    )
    same_uic_count = db.session.query(func.count(GtfsStopRaw.stop_id)).filter(GtfsStopRaw.uic_number == stop.uic_ref).scalar() or 0

    return {
        'entity_type': 'atlas',
        'sloid': stop.sloid,
        'uic_ref': stop.uic_ref,
        'atlas_designation': stop.atlas_designation,
        'atlas_designation_official': stop.atlas_designation_official,
        'atlas_business_org_abbr': stop.atlas_business_org_abbr,
        'atlas_lat': atlas_lat,
        'atlas_lon': atlas_lon,
        'matched_gtfs_count': int(matched_count),
        'same_uic_gtfs_count': int(same_uic_count),
        'matched_gtfs': [
            {
                'stop_id': gtfs_stop.stop_id,
                'stop_name': gtfs_stop.stop_name,
                'local_ref': gtfs_stop.local_ref,
                'normalized_local_ref': gtfs_stop.normalized_local_ref,
                'stop_lat': match.gtfs_stop_lat,
                'stop_lon': match.gtfs_stop_lon,
                'match_method': match.resolution_method,
                'distance_m': match.distance_m,
            }
            for match, gtfs_stop in matched_rows
        ],
        'same_uic_gtfs': [
            {
                'stop_id': gtfs_stop.stop_id,
                'stop_name': gtfs_stop.stop_name,
                'local_ref': gtfs_stop.local_ref,
                'normalized_local_ref': gtfs_stop.normalized_local_ref,
                'stop_lat': gtfs_stop.stop_lat,
                'stop_lon': gtfs_stop.stop_lon,
            }
            for gtfs_stop in same_uic_rows
        ],
    }