from collections import defaultdict

from flask import Blueprint, request, jsonify, current_app as app
from sqlalchemy import case
from sqlalchemy.orm import joinedload
from backend.models import AtlasOperator, StopsMatched, AtlasStop, OsmNode, OsmStop, OsmStopMember, OsmRouteRelation
from backend.extensions import db, limiter
from backend.serializers.stops import format_stop_data
from backend.services.transport_routes import get_osm_routes_for_node, get_atlas_routes_for_sloid
from backend.queries.helpers import filtered_stops_query
from geoalchemy2.functions import ST_Intersects, ST_MakeEnvelope

# Create blueprint for data operations
data_bp = Blueprint('data', __name__)


def _viewport_condition(args):
    """In the map's viewport (min_lat, min_lon, max_lat, max_lon): the ATLAS point, or a matched pair's OSM position.

    The ATLAS point uses the indexed geometry; the OSM position keeps a pair on
    the map when the view holds only its OSM side.
    """
    min_lat, max_lat = float(args.get('min_lat')), float(args.get('max_lat'))
    min_lon, max_lon = float(args.get('min_lon')), float(args.get('max_lon'))
    return db.or_(
        ST_Intersects(StopsMatched.geom, ST_MakeEnvelope(min_lon, min_lat, max_lon, max_lat, 4326)),
        db.and_(
            StopsMatched.stop_type == 'matched',
            StopsMatched.osm_lat.between(min_lat, max_lat),
            StopsMatched.osm_lon.between(min_lon, max_lon),
        ),
    )


def osm_group_links(node_ids):
    """The links the map draws from each OSM element in ``node_ids`` to the rest of its stop unit.

    Returns {node_id: fields}. An element of a pair gets ``osm_group_partner``, the
    other element. An element of a two-sided stop gets ``osm_two_sided_links``:
    from the middle to each side, or from a side to the middle, never side to side.
    """
    node_ids = {node_id for node_id in node_ids if node_id}
    stop_ids = [stop_id for (stop_id,) in db.session.query(OsmStopMember.osm_stop_id)
                .filter(OsmStopMember.node_id.in_(sorted(node_ids)))] if node_ids else []
    if not stop_ids:
        return {}
    members = db.session.query(
        OsmStopMember.osm_stop_id, OsmStopMember.node_id, OsmStopMember.member_role, OsmStop.stop_kind, OsmStop.group_kind,
    ).join(OsmStop, OsmStopMember.osm_stop_id == OsmStop.id).filter(OsmStopMember.osm_stop_id.in_(stop_ids)).all()
    coordinates = {
        node_id: (lat, lon)
        for node_id, lat, lon in db.session.query(StopsMatched.osm_node_id, StopsMatched.osm_lat, StopsMatched.osm_lon)
        .filter(StopsMatched.osm_node_id.in_([member.node_id for member in members]), StopsMatched.osm_lat.isnot(None))
    }
    members_by_stop = defaultdict(list)
    for member in members:
        members_by_stop[member.osm_stop_id].append(member)

    links = {}
    for stop_members in members_by_stop.values():
        middle = next((member.node_id for member in stop_members if member.member_role == 'middle'), None)
        for member in stop_members:
            if member.node_id not in node_ids:
                continue
            partners = [other.node_id for other in stop_members if other.node_id != member.node_id]
            if member.stop_kind == 'pair' and partners:
                lat, lon = coordinates.get(partners[0], (None, None))
                links[member.node_id] = {'osm_group_partner': {
                    'partner_node_id': partners[0],
                    'group_type': member.group_kind,
                    'partner_osm_lat': lat,
                    'partner_osm_lon': lon,
                }}
            elif member.stop_kind == 'two_sided_stop':
                two_sided_links = [{
                    'partner_node_id': partner,
                    'partner_osm_lat': coordinates.get(partner, (None, None))[0],
                    'partner_osm_lon': coordinates.get(partner, (None, None))[1],
                    'is_middle': member.node_id == middle,
                    'partner_is_middle': partner == middle,
                } for partner in partners if middle in (member.node_id, partner)]
                if two_sided_links:
                    links[member.node_id] = {'osm_two_sided_links': two_sided_links}
    return links


def _distinct_values(column):
    """The distinct non-empty values of ``column``, sorted, as {"operators": [...], "total": n}."""
    try:
        values = [value for (value,) in db.session.query(column)
                  .filter(column.isnot(None), column != '').distinct().order_by(column)]
        return jsonify({"operators": values, "total": len(values)})
    except Exception as exc:
        app.logger.error("Error listing %s: %s", column, exc)
        return jsonify({"error": str(exc)}), 500


@data_bp.route('/api/atlas_operators', methods=['GET'])
@limiter.limit("60/minute")
def get_atlas_operators():
    return _distinct_values(AtlasOperator.atlas_business_org_abbr)


@data_bp.route('/api/osm_operators', methods=['GET'])
@limiter.limit("60/minute")
def get_osm_operators():
    return _distinct_values(OsmNode.osm_operator)


@data_bp.route('/api/osm_operator_wikidata', methods=['GET'])
@limiter.limit("60/minute")
def get_osm_operator_wikidata():
    return _distinct_values(OsmNode.osm_operator_wikidata)


@data_bp.route('/api/osm_route_operators', methods=['GET'])
@limiter.limit("60/minute")
def get_osm_route_operators():
    return _distinct_values(OsmRouteRelation.operator)


@data_bp.route('/api/data', methods=['GET'])
@limiter.limit("60/minute")
def get_data():
    try:
        include_meta_raw = request.args.get('include_meta', '')
        include_meta = str(include_meta_raw).strip().lower() in ('1', 'true', 'yes', 'y')

        offset_raw = request.args.get('offset', 0)
        limit_raw = request.args.get('limit')
        try:
            offset = int(offset_raw)
        except Exception:
            offset = 0
        # Treat missing/invalid/non-positive/"all" as no explicit limit
        limit = None
        if limit_raw is not None:
            if isinstance(limit_raw, str) and limit_raw.lower() == 'all':
                limit = None
            else:
                try:
                    limit_val = int(limit_raw)
                    if limit_val > 0:
                        limit = limit_val
                except Exception:
                    limit = None

        query = filtered_stops_query(request.args).filter(_viewport_condition(request.args))
        # Eager-load only required details to avoid N+1 queries.
        query = query.options(
            joinedload(StopsMatched.osm_node_details).load_only(OsmNode.osm_node_type),
            joinedload(StopsMatched.atlas_stop_details).load_only(AtlasStop.duplicate_group_sloids)
        )

        # If a limit is applied (mid/low zoom caps), ensure results are stable across requests
        # and prioritize unmatched rows first to reduce "disappearing/reappearing" markers.
        if limit is not None:
            stop_type_rank = case(
                (StopsMatched.stop_type == 'atlas_unmatched', 0),
                (StopsMatched.stop_type == 'osm_unmatched', 1),
                (StopsMatched.stop_type == 'effectively_matched', 2),
                (StopsMatched.stop_type == 'matched', 3),
                (StopsMatched.stop_type == 'osm_disused', 4),
                else_=9,
            )
            query = query.order_by(stop_type_rank.asc(), StopsMatched.id.asc())

        query = query.offset(offset)
        has_more = False
        if limit is not None:
            # Fetch one extra row so we can tell whether the response was capped.
            query = query.limit(limit + 1)
        stops = query.all()
        if limit is not None and len(stops) > limit:
            has_more = True
            stops = stops[:limit]

        regular_stops = []
        for stop in stops:
            lat = stop.atlas_lat if stop.atlas_lat is not None else stop.osm_lat
            lon = stop.atlas_lon if stop.atlas_lon is not None else stop.osm_lon
            regular_stops.append({
                "id": stop.id,
                "sloid": stop.sloid,
                "stop_type": stop.stop_type,
                "match_type": stop.match_type,
                "osm_node_id": stop.osm_node_id,
                "atlas_lat": stop.atlas_lat,
                "atlas_lon": stop.atlas_lon,
                "osm_lat": stop.osm_lat,
                "osm_lon": stop.osm_lon,
                "distance_m": stop.distance_m,
                "lat": lat,
                "lon": lon,
                "has_atlas_duplicate": bool(stop.atlas_stop_details and stop.atlas_stop_details.duplicate_group_sloids),
                "osm_node_type": stop.osm_node_details.osm_node_type if stop.osm_node_details else None
            })
        # Enrich any OSM-backed stop with pair partners and two-sided stop links.
        links = osm_group_links(stop['osm_node_id'] for stop in regular_stops)
        for stop_entry in regular_stops:
            stop_entry.update(links.get(stop_entry['osm_node_id'], {}))

        if include_meta:
            return jsonify({
                "stops": regular_stops,
                "meta": {
                    "offset": offset,
                    "limit": limit,
                    "returned": len(regular_stops),
                    "has_more": has_more
                }
            })

        return jsonify(regular_stops)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@data_bp.route('/api/stop_popup', methods=['GET'])
@limiter.limit("120/minute")
def get_stop_popup():
    try:
        stop_id = request.args.get('stop_id', type=int)
        # Route maps know a stop by its source id, not by its stops_matched row.
        sloid = (request.args.get('sloid') or '').strip()
        osm_node_id = (request.args.get('osm_node_id') or '').strip()
        view_type = request.args.get('view_type', type=str)
        query = StopsMatched.query.options(
            joinedload(StopsMatched.atlas_stop_details),
            joinedload(StopsMatched.osm_node_details).undefer(OsmNode.osm_tags)
        )
        if stop_id:
            query = query.filter(StopsMatched.id == stop_id)
        elif sloid or osm_node_id:
            column = StopsMatched.sloid if sloid else StopsMatched.osm_node_id
            # A source stop can have several rows; a matched one shows the pair.
            query = query.filter(column == (sloid or osm_node_id)).order_by(
                case((StopsMatched.stop_type == 'matched', 0), else_=1), StopsMatched.id)
        else:
            return jsonify({"error": "stop_id, sloid or osm_node_id is required"}), 400
        stop = query.first()
        if not stop:
            return jsonify({"error": "StopsMatched not found"}), 404
        enriched = format_stop_data(stop, include_routes=True, include_osm_tags=True)
        if stop.stop_type == 'matched' and stop.sloid:
            matched_rows = StopsMatched.query.options(
                joinedload(StopsMatched.osm_node_details).undefer(OsmNode.osm_tags),
                joinedload(StopsMatched.atlas_stop_details)
            ).filter(StopsMatched.sloid == stop.sloid, StopsMatched.stop_type == 'matched').all()
            atlas_lat = stop.atlas_lat
            atlas_lon = stop.atlas_lon
            if atlas_lat is None or atlas_lon is None:
                for r in matched_rows:
                    if r.atlas_lat is not None and r.atlas_lon is not None:
                        atlas_lat, atlas_lon = r.atlas_lat, r.atlas_lon
                        break
            enriched["atlas_lat"] = atlas_lat
            enriched["atlas_lon"] = atlas_lon
            osm_matches = []
            for r in matched_rows:
                if r.osm_node_id and r.osm_lat is not None and r.osm_lon is not None:
                    osm_details = r.osm_node_details
                    osm_matches.append({
                        "osm_id": r.id,
                        "osm_node_id": r.osm_node_id,
                        "osm_local_ref": osm_details.osm_local_ref if osm_details else None,
                        "osm_network": osm_details.osm_network if osm_details else None,
                        "osm_operator": osm_details.osm_operator if osm_details else None,
                        "osm_public_transport": osm_details.osm_public_transport if osm_details else None,
                        "osm_railway": osm_details.osm_railway if osm_details else None,
                        "osm_amenity": osm_details.osm_amenity if osm_details else None,
                        "osm_aerialway": osm_details.osm_aerialway if osm_details else None,
                        "osm_name": osm_details.osm_name if osm_details else None,
                        "osm_uic_name": osm_details.osm_uic_name if osm_details else None,
                        "osm_uic_ref": osm_details.osm_uic_ref if osm_details else None,
                        "osm_operator_wikidata": osm_details.osm_operator_wikidata if osm_details else None,
                        "osm_network_wikidata": osm_details.osm_network_wikidata if osm_details else None,
                        "osm_lat": r.osm_lat,
                        "osm_lon": r.osm_lon,
                        "distance_m": r.distance_m,
                        "match_type": r.match_type,
                        "has_osm_duplicate": bool(osm_details and osm_details.duplicate_group_node_ids),
                        "osm_node_type": osm_details.osm_node_type if osm_details else None,
                        "osm_tags": osm_details.osm_tags if osm_details else None,
                        "routes_osm": get_osm_routes_for_node(r.osm_node_id),
                    })
            if osm_matches:
                enriched["osm_matches"] = osm_matches
            # Include OSM pair and two-sided stop partners from stop-unit membership.
            enriched.update(osm_group_links([stop.osm_node_id]).get(stop.osm_node_id, {}))
        if view_type == 'osm' and stop.osm_node_id:
            same_osm_rows = StopsMatched.query.options(
                joinedload(StopsMatched.atlas_stop_details)
            ).filter(StopsMatched.osm_node_id == stop.osm_node_id, StopsMatched.stop_type == 'matched').all()
            if len(same_osm_rows) > 1:
                osm_details = stop.osm_node_details
                osm_centric = {
                    "id": stop.id,
                    "stop_type": 'matched',
                    "is_osm_node": True,
                    "match_type": stop.match_type,
                    "osm_node_id": stop.osm_node_id,
                    "osm_name": osm_details.osm_name if osm_details else None,
                    "osm_uic_name": osm_details.osm_uic_name if osm_details else None,
                    "osm_uic_ref": osm_details.osm_uic_ref if osm_details else None,
                    "osm_local_ref": osm_details.osm_local_ref if osm_details else None,
                    "osm_network": osm_details.osm_network if osm_details else None,
                    "osm_operator": osm_details.osm_operator if osm_details else None,
                    "osm_public_transport": osm_details.osm_public_transport if osm_details else None,
                    "osm_amenity": osm_details.osm_amenity if osm_details else None,
                    "osm_aerialway": osm_details.osm_aerialway if osm_details else None,
                    "osm_railway": osm_details.osm_railway if osm_details else None,
                    "osm_lat": stop.osm_lat,
                    "osm_lon": stop.osm_lon,
                    "osm_node_type": osm_details.osm_node_type if osm_details else None,
                    "osm_operator_wikidata": osm_details.osm_operator_wikidata if osm_details else None,
                    "osm_network_wikidata": osm_details.osm_network_wikidata if osm_details else None,
                    "osm_tags": enriched.get("osm_tags"),
                    "uic_ref": osm_details.osm_uic_ref if osm_details else None,
                    "routes_osm": get_osm_routes_for_node(stop.osm_node_id),
                    "atlas_matches": []
                }
                for r in same_osm_rows:
                    atlas = r.atlas_stop_details
                    osm_centric["atlas_matches"].append({
                        "id": r.id,
                        "sloid": r.sloid,
                        "uic_ref": atlas.uic_ref if atlas else None,
                        "atlas_designation": atlas.atlas_designation if atlas else None,
                        "atlas_designation_official": atlas.atlas_designation_official if atlas else None,
                        "atlas_business_org_abbr": atlas.atlas_business_org_abbr if atlas else None,
                        "atlas_lat": r.atlas_lat,
                        "atlas_lon": r.atlas_lon,
                        "distance_m": r.distance_m,
                        "match_type": r.match_type,
                        "routes_atlas": get_atlas_routes_for_sloid(r.sloid) if r.sloid else [],
                    })
                return jsonify({"stop": osm_centric})
        return jsonify({"stop": enriched})
    except Exception as e:
        app.logger.error(f"Error fetching stop popup: {e}")
        return jsonify({"error": str(e)}), 500

