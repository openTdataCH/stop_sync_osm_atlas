from flask import current_app as app

from backend.extensions import db
from backend.models import Itinerary, ItineraryMatch, LineFamily, LineFamilyMatch, StopCall

from backend.services.source_config import normalize_route_search_id


def _clean_text(value):
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _build_atlas_route_payload(row):
    return {
        'route_id': row.source_family_id,
        'direction_id': row.direction_id,
        'route_name_short': _clean_text(row.ref),
        'route_name_long': _clean_text(row.public_name),
    }


def _build_osm_route_payload(row):
    return {
        'route_id': row.display_route_id,
        'display_route_id': row.display_route_id,
        'internal_route_id': row.source_itinerary_id,
        'direction_id': row.direction_id,
        'route_name': _clean_text(row.public_name) or _clean_text(row.ref) or _clean_text(row.display_route_id),
    }


def _get_atlas_routes_for_stop_values(values, stop_column):
    normalized_values = sorted({str(value).strip() for value in (values or []) if str(value).strip()})
    if not normalized_values:
        return {}

    try:
        rows = (
            db.session.query(
                stop_column.label('stop_key'),
                LineFamily.source_family_id,
                Itinerary.direction_id,
                LineFamily.ref,
                LineFamily.public_name,
            )
            .join(Itinerary, Itinerary.line_family_id == LineFamily.id)
            .join(StopCall, StopCall.itinerary_id == Itinerary.id)
            .filter(LineFamily.source == 'atlas', stop_column.in_(normalized_values))
            .distinct()
            .order_by(stop_column.asc(), LineFamily.source_family_id.asc(), Itinerary.direction_id.asc())
            .all()
        )

        routes_by_stop = {value: [] for value in normalized_values}
        for row in rows:
            routes_by_stop.setdefault(str(row.stop_key), []).append(_build_atlas_route_payload(row))
        return routes_by_stop
    except Exception as exc:
        # A failed SQL statement leaves PostgreSQL's transaction unusable.
        # This helper intentionally degrades to an empty route list, so it must
        # also restore the session before the popup response continues.
        db.session.rollback()
        app.logger.error(f"Error fetching ATLAS routes for stops {normalized_values}: {exc}")
        return {value: [] for value in normalized_values}


def get_atlas_routes_for_sloids(sloids):
    return _get_atlas_routes_for_stop_values(sloids, StopCall.source_sloid)


def get_atlas_routes_for_gtfs_stop_ids(stop_ids):
    return _get_atlas_routes_for_stop_values(stop_ids, StopCall.source_stop_id)


def get_osm_routes_for_nodes(osm_node_ids):
    normalized_node_ids = sorted({str(node_id).strip() for node_id in (osm_node_ids or []) if str(node_id).strip()})
    if not normalized_node_ids:
        return {}

    try:
        rows = (
            db.session.query(
                StopCall.source_node_id,
                LineFamily.display_route_id,
                Itinerary.source_itinerary_id,
                Itinerary.direction_id,
                LineFamily.public_name,
                LineFamily.ref,
            )
            .join(Itinerary, Itinerary.line_family_id == LineFamily.id)
            .join(StopCall, StopCall.itinerary_id == Itinerary.id)
            .filter(LineFamily.source == 'osm', StopCall.source_node_id.in_(normalized_node_ids))
            .distinct()
            .order_by(StopCall.source_node_id.asc(), LineFamily.display_route_id.asc(), Itinerary.direction_id.asc())
            .all()
        )

        routes_by_node_id = {node_id: [] for node_id in normalized_node_ids}
        for row in rows:
            routes_by_node_id.setdefault(row.source_node_id, []).append(_build_osm_route_payload(row))
        return routes_by_node_id
    except Exception as exc:
        app.logger.error(f"Error fetching routes for osm_node_ids {normalized_node_ids}: {exc}")
        return {node_id: [] for node_id in normalized_node_ids}


def get_atlas_routes_for_sloid(sloid):
    if not sloid:
        return []
    return get_atlas_routes_for_sloids([sloid]).get(str(sloid), [])


def get_osm_routes_for_node(osm_node_id):
    if not osm_node_id:
        return []
    return get_osm_routes_for_nodes([osm_node_id]).get(str(osm_node_id), [])


def route_family_ids(route_id):
    """GTFS and OSM line families a route filter names, with the families linked to them.

    A line can have several links, so the GTFS lines linked to the same OSM
    line come along: the two timetable routes of one public line show together.
    """
    normalized_input = normalize_route_search_id(route_id) if route_id else None
    direct_family_rows = (
        db.session.query(LineFamily.id, LineFamily.source)
        .filter(
            db.or_(
                LineFamily.source_family_id == route_id,
                LineFamily.display_route_id == route_id,
                LineFamily.gtfs_route_id == route_id,
                LineFamily.representative_relation_id == route_id,
                LineFamily.normalized_route_id == normalized_input,
            )
        )
        .all()
    )

    atlas_family_ids = {row.id for row in direct_family_rows if row.source == 'atlas'}
    osm_family_ids = {row.id for row in direct_family_rows if row.source == 'osm'}

    if atlas_family_ids:
        matched_osm_ids = (
            db.session.query(LineFamilyMatch.osm_line_family_id)
            .filter(LineFamilyMatch.atlas_line_family_id.in_(atlas_family_ids))
            .all()
        )
        osm_family_ids |= {row.osm_line_family_id for row in matched_osm_ids}

    if osm_family_ids:
        matched_atlas_ids = (
            db.session.query(LineFamilyMatch.atlas_line_family_id)
            .filter(LineFamilyMatch.osm_line_family_id.in_(osm_family_ids))
            .all()
        )
        atlas_family_ids |= {row.atlas_line_family_id for row in matched_atlas_ids}
    return atlas_family_ids, osm_family_ids


def _year_free_key(key):
    """An ATLAS itinerary key without its timetable year: the key starts with the GTFS route_id."""
    route_id, separator, rest = key.partition(':')
    return (normalize_route_search_id(route_id) or route_id) + separator + rest


def find_variant_itineraries(variants):
    """The itineraries a variant selection names: ``{'atlas': key, 'osm': key}``.

    The keys are the routes page's ``atlas_variant`` (the ATLAS itinerary id)
    and ``osm_variant`` (the OSM route relation id). An exact ATLAS key wins;
    otherwise it is matched with the timetable year ignored, so a link
    survives a new timetable. Returns ``{'atlas': Itinerary | None, 'osm': ...}``.
    """
    found = {'atlas': None, 'osm': None}
    for source in found:
        key = _clean_text((variants or {}).get(source))
        if key is None:
            continue
        base = db.session.query(Itinerary).filter(Itinerary.source == source)
        itinerary = base.filter(Itinerary.source_itinerary_id == key).first()
        if itinerary is None and source == 'atlas' and ':' in key:
            wanted = _year_free_key(key)
            suffix = key[key.index(':'):]
            candidates = base.filter(Itinerary.source_itinerary_id.endswith(suffix, autoescape=True)).all()
            itinerary = max((candidate for candidate in candidates
                             if _year_free_key(candidate.source_itinerary_id) == wanted),
                            key=lambda candidate: candidate.id, default=None)
        found[source] = itinerary
    return found


def _stops_of_itineraries(itinerary_query):
    """Distinct ATLAS SLOIDs and OSM nodes called by the itineraries of a query."""
    calls = (
        db.session.query(StopCall.source_sloid, StopCall.source_node_id, Itinerary.source)
        .join(Itinerary, Itinerary.id == StopCall.itinerary_id)
        .filter(itinerary_query)
    )
    atlas_sloids, osm_nodes = set(), set()
    for sloid, node_id, source in calls.distinct():
        if source == 'atlas' and sloid:
            atlas_sloids.add(sloid)
        elif source == 'osm' and node_id:
            osm_nodes.add(node_id)
    return atlas_sloids, osm_nodes


def get_stops_for_route(route_id, direction=None, variants=None):
    """Stops of a route filter: the whole line, one direction, or chosen variants.

    ``variants`` (``{'atlas': key, 'osm': key}``, see ``find_variant_itineraries``)
    narrows the filter to exactly those itineraries, whatever their line, and
    the direction no longer applies. A selection whose keys name nothing
    matches no stop: it never widens to the whole line.
    """
    try:
        if variants is not None:
            itinerary_ids = [itinerary.id for itinerary in find_variant_itineraries(variants).values() if itinerary]
            condition = Itinerary.id.in_(itinerary_ids)
        else:
            atlas_family_ids, osm_family_ids = route_family_ids(route_id)
            condition = db.or_(
                db.and_(Itinerary.source == 'atlas', Itinerary.line_family_id.in_(atlas_family_ids)),
                db.and_(Itinerary.source == 'osm', Itinerary.line_family_id.in_(osm_family_ids)),
            )
            if direction:
                condition = db.and_(condition, Itinerary.direction_id == direction)
        atlas_sloids, osm_nodes = _stops_of_itineraries(condition)

        app.logger.info(
            f"Found {len(osm_nodes)} OSM nodes and {len(atlas_sloids)} ATLAS sloids for route {route_id}"
            + (f" with direction {direction}" if direction and variants is None else '')
            + (f" in variants {variants}" if variants is not None else '')
        )
        return {
            'osm_nodes': list(osm_nodes),
            'atlas_sloids': list(atlas_sloids),
        }
    except Exception as exc:
        app.logger.error(f"Error retrieving stops for route {route_id}: {exc}")
        return {'osm_nodes': [], 'atlas_sloids': []}


_DIRECTION_ORDER = {'0': 0, '1': 1}


def _variant_summary(itinerary):
    return {
        'key': itinerary.source_itinerary_id,
        'name': (_clean_text(itinerary.display_name) or _clean_text(itinerary.representative_headsign)
                 or itinerary.source_itinerary_id),
        'direction_id': _clean_text(itinerary.direction_id),
        'stop_count': itinerary.canonical_stop_count,
    }


def _route_filter_value(family_id):
    """The route filter value of a line: the GTFS line, or an OSM line linked to none.

    An OSM line linked to several GTFS lines takes the first; the filter then
    shows every line linked to it (``route_family_ids``).
    """
    family = db.session.get(LineFamily, family_id)
    if family.source == 'osm':
        linked = (db.session.query(LineFamily)
                  .join(LineFamilyMatch, LineFamilyMatch.atlas_line_family_id == LineFamily.id)
                  .filter(LineFamilyMatch.osm_line_family_id == family.id)
                  .order_by(LineFamily.id).first())
        family = linked or family
    return family.source_family_id


def _bounds(itinerary_ids):
    south, west, north, east = (
        db.session.query(db.func.min(StopCall.stop_lat), db.func.min(StopCall.stop_lon),
                         db.func.max(StopCall.stop_lat), db.func.max(StopCall.stop_lon))
        .filter(StopCall.itinerary_id.in_(itinerary_ids)).one()
    )
    return [[south, west], [north, east]] if south is not None and west is not None else None


def list_route_variants(route_id=None, variants=None):
    """The variants of a line, for the map's route filter.

    Engine pairs come first in each direction, as one entry, then the variants
    left unpaired. ``variants`` (see ``find_variant_itineraries``) names a
    selection: the answer describes it and, without ``route_id``, its line is
    the ATLAS variant's, else the OSM variant's. Raises LookupError when
    nothing is found.
    """
    found = find_variant_itineraries(variants) if variants else {'atlas': None, 'osm': None}
    if variants and not any(found.values()):
        raise LookupError('Route variant not found.')
    if route_id is None:
        route_id = _route_filter_value((found['atlas'] or found['osm']).line_family_id)
    atlas_family_ids, osm_family_ids = route_family_ids(route_id)
    itineraries = (
        db.session.query(Itinerary)
        .filter(db.or_(
            db.and_(Itinerary.source == 'atlas', Itinerary.line_family_id.in_(atlas_family_ids)),
            db.and_(Itinerary.source == 'osm', Itinerary.line_family_id.in_(osm_family_ids)),
        ))
        .all()
    )
    if not itineraries and not any(found.values()):
        raise LookupError('Route not found.')

    by_id = {itinerary.id: itinerary for itinerary in itineraries}
    pairs = (
        db.session.query(ItineraryMatch.atlas_itinerary_id, ItineraryMatch.osm_itinerary_id)
        .filter(ItineraryMatch.atlas_itinerary_id.in_(by_id), ItineraryMatch.osm_itinerary_id.in_(by_id))
        .order_by(ItineraryMatch.id).all()
    ) if by_id else []
    entries, paired = [], set()
    for atlas_id, osm_id in pairs:
        paired.update((atlas_id, osm_id))
        entries.append({'atlas': by_id[atlas_id], 'osm': by_id[osm_id]})
    for itinerary in itineraries:
        if itinerary.id not in paired:
            entries.append({'atlas': itinerary if itinerary.source == 'atlas' else None,
                            'osm': itinerary if itinerary.source == 'osm' else None})

    def order(entry):
        first = entry['atlas'] or entry['osm']
        direction = _clean_text(first.direction_id)
        return (_DIRECTION_ORDER.get(direction, 2), entry['atlas'] is None or entry['osm'] is None,
                entry['atlas'] is None, _variant_summary(first)['name'].lower(), first.id)

    selected_ids = [itinerary.id for itinerary in found.values() if itinerary]
    return {
        'route_id': route_id,
        'variants': [{
            'direction_id': _clean_text((entry['atlas'] or entry['osm']).direction_id),
            'atlas': _variant_summary(entry['atlas']) if entry['atlas'] else None,
            'osm': _variant_summary(entry['osm']) if entry['osm'] else None,
        } for entry in sorted(entries, key=order)],
        'selected': {source: _variant_summary(itinerary) if itinerary else None
                     for source, itinerary in found.items()} if variants else None,
        'bounds': _bounds(selected_ids) if selected_ids else None,
    }
