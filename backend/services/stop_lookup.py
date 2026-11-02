"""Find map entries by their stable identifiers.

Serves the public /api/lookup endpoint and the summary that a stop permalink
carries in its HTML. Identifiers use the permalink form: osm=node/<id> or
way/<id>, sloid=<SLOID>, plus uic_ref=<station number> for the API.
See documentation/2.10 Public API.md.
"""

import re
from urllib.parse import quote

from flask import current_app
from sqlalchemy import or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload, selectinload

from backend.extensions import db
from backend.models import AtlasStop, DatasetPublication, OsmNode, StopsMatched

LOOKUP_PARAMS = ('osm', 'sloid', 'uic_ref')
PAGE_PARAMS = ('osm', 'sloid')
# A safety cap: the largest stations have a few dozen map entries.
MAX_RESULTS = 200
OSM_ID_PATTERN = re.compile(r'(node|way)/(\d+)')


class InvalidLookup(ValueError):
    pass


def parse_lookup(args, params=LOOKUP_PARAMS):
    """Return the identifiers given in ``args`` as {param: value}."""
    query = {key: args.get(key, '').strip() for key in params if args.get(key, '').strip()}
    if not query:
        raise InvalidLookup('Give osm=node/<id> or osm=way/<id>, sloid=<id> or uic_ref=<station number>.')
    if 'osm' in query and not OSM_ID_PATTERN.fullmatch(query['osm']):
        raise InvalidLookup(f"osm must be node/<id> or way/<id>, as on openstreetmap.org, not {query['osm']!r}.")
    return query


def stored_osm_id(osm_id):
    """'node/123' -> '123' and 'way/45' -> 'way_45', as the database stores them."""
    kind, number = OSM_ID_PATTERN.fullmatch(osm_id).groups()
    return number if kind == 'node' else f'way_{number}'


def public_osm_id(stored_id):
    """'123' -> 'node/123' and 'way_45' -> 'way/45', as openstreetmap.org writes them."""
    return f'way/{stored_id[4:]}' if stored_id.startswith('way_') else f'node/{stored_id}'


def find_stops(query):
    """Return (rows, truncated): every map entry with all the given identifiers, closest first."""
    rows = StopsMatched.query.options(
        joinedload(StopsMatched.atlas_stop_details),
        joinedload(StopsMatched.osm_node_details).undefer(OsmNode.osm_tags),
        selectinload(StopsMatched.problems),
    )
    if 'osm' in query:
        rows = rows.filter(StopsMatched.osm_node_id == stored_osm_id(query['osm']))
    if 'sloid' in query:
        rows = rows.filter(StopsMatched.sloid == query['sloid'])
    if 'uic_ref' in query:
        uic_ref = query['uic_ref']
        rows = rows.filter(or_(
            StopsMatched.sloid.in_(select(AtlasStop.sloid).where(AtlasStop.uic_ref == uic_ref)),
            StopsMatched.osm_node_id.in_(select(OsmNode.osm_node_id).where(OsmNode.osm_uic_ref == uic_ref)),
        ))
    rows = rows.order_by(
        StopsMatched.distance_m.asc().nulls_last(),
        StopsMatched.sloid,
        StopsMatched.osm_node_id,
    ).limit(MAX_RESULTS + 1).all()
    return rows[:MAX_RESULTS], len(rows) > MAX_RESULTS


def snapshot_info():
    """The published snapshot the rows come from, or None before the first import."""
    publication = DatasetPublication.query.first()
    if publication is None:
        return None
    manifest = publication.manifest or {}
    return {
        'run_id': publication.run_id,
        'generated_at': manifest.get('generated_at'),
        'attribution': (manifest.get('metadata') or {}).get('attribution'),
    }


def serialize_stop(row):
    source = row.atlas_stop_details
    osm = row.osm_node_details
    result = {
        'stop_type': row.stop_type,
        'match_type': row.match_type,
        'distance_m': round(row.distance_m, 1) if row.distance_m is not None else None,
        'source': None,
        'osm': None,
        'problems': [
            {'type': problem.problem_type, 'priority': problem.priority}
            for problem in sorted(row.problems, key=lambda p: (p.priority or 99, p.problem_type))
        ],
    }
    if row.sloid:
        result['source'] = {
            'sloid': row.sloid,
            'name': source.atlas_designation_official if source else None,
            'designation': source.atlas_designation if source else None,
            'uic_ref': source.uic_ref if source else None,
            'operator': source.atlas_business_org_abbr if source else None,
            'lat': row.atlas_lat,
            'lon': row.atlas_lon,
            'map_url': f"/?sloid={quote(row.sloid, safe=':')}",
        }
    if row.osm_node_id:
        osm_id = public_osm_id(row.osm_node_id)
        result['osm'] = {
            'id': osm_id,
            'url': f'https://www.openstreetmap.org/{osm_id}',
            'name': osm.osm_name if osm else None,
            'uic_ref': osm.osm_uic_ref if osm else None,
            'local_ref': osm.osm_local_ref if osm else None,
            'operator': osm.osm_operator if osm else None,
            'network': osm.osm_network if osm else None,
            'lat': row.osm_lat,
            'lon': row.osm_lon,
            'tags': osm.osm_tags if osm else None,
            'map_url': f'/?osm={osm_id}',
        }
    return result


def lookup_payload(query):
    rows, truncated = find_stops(query)
    return {
        'query': query,
        'source_label': current_app.config['REVIEW_CONFIG']['source_label'],
        'snapshot': snapshot_info(),
        'count': len(rows),
        'truncated': truncated,
        'results': [serialize_stop(row) for row in rows],
    }


def linked_stop(args):
    """Title, description and API link of the stop a page link names, or None.

    Pages render this into their HTML, so a client that does not run
    JavaScript (a link preview, a fetch tool) still learns what the link shows.
    """
    try:
        query = parse_lookup(args, PAGE_PARAMS)
        rows, _ = find_stops(query)
    except InvalidLookup:
        return None
    except SQLAlchemyError:
        # The page still works without the summary; its script loads the stop.
        current_app.logger.warning('Linked stop summary unavailable', exc_info=True)
        db.session.rollback()
        return None
    if not rows:
        return None

    source_label = current_app.config['REVIEW_CONFIG']['source_label']
    stops = [serialize_stop(row) for row in rows]
    # The link names one side; the rows' other sides are its matches.
    side, other_side = ('osm', 'source') if 'sloid' not in query else ('source', 'osm')
    labels = {'source': source_label, 'osm': 'OSM'}

    def identifier(stop_side, element):
        return element['id'] if stop_side == 'osm' else element['sloid']

    def describe(stop_side, element):
        name = f' "{element["name"]}"' if element['name'] else ''
        return f'{labels[stop_side]} {identifier(stop_side, element)}{name}'

    linked = stops[0][side]
    matches = [
        describe(other_side, stop[other_side]) + (f' ({stop["distance_m"]} m)' if stop['distance_m'] is not None else '')
        for stop in stops if stop[other_side]
    ]
    if matches:
        description = f'{describe(side, linked)} is matched to {", ".join(matches)}.'
    else:
        description = f'{describe(side, linked)} has no direct {labels[other_side]} match (stop type {stops[0]["stop_type"]}).'
    problems = sorted({(p['priority'] or 99, p['type']) for stop in stops for p in stop['problems']})
    if problems:
        description += ' Problems: ' + ', '.join(f'{kind} P{priority}' for priority, kind in problems) + '.'

    return {
        'title': f'{linked["name"]} · {identifier(side, linked)}' if linked['name'] else identifier(side, linked),
        'description': description,
        'api_url': '/api/lookup?' + '&'.join(f'{key}={quote(value, safe=":/")}' for key, value in query.items()),
    }
