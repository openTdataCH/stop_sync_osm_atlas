"""Read-only itinerary comparisons using the published, resolved stop identities.

Keep the identity rules and LCS tie-breaking consistent with the matching engine,
without making the independent review application depend on the engine package.
"""

import json
from bisect import bisect_left
from collections import defaultdict
from heapq import heappush, heapreplace
from itertools import islice

from sqlalchemy import String, and_, cast, exists, func, or_, select

from backend.extensions import db
from backend.models import Itinerary, ItineraryMatch, LineFamily, StopCall


def _text(value):
    return str(value).strip() or None if value is not None else None


def _variants(call):
    try:
        values = json.loads(getattr(call, 'source_sloid_variants', None) or '[]')
    except (TypeError, ValueError):
        return []
    if not isinstance(values, list):
        return []
    return [text for value in values if (text := _text(value)) is not None]


def _identity(call):
    resolved = set(_variants(call))
    if source_sloid := _text(getattr(call, 'source_sloid', None)):
        resolved.add(source_sloid)
    return resolved, _text(getattr(call, 'uic_ref', None))


def _match_type(atlas, osm):
    atlas_ids, atlas_uic = atlas
    osm_ids, osm_uic = osm
    if atlas_ids and osm_ids:
        return 'resolved_sloid_match' if atlas_ids & osm_ids else None
    return 'uic_match' if atlas_uic and atlas_uic == osm_uic else None


def _serialize_stop(call, source):
    if source == 'atlas':
        ids = [getattr(call, 'source_sloid', None), *_variants(call),
               getattr(call, 'source_stop_id', None)]
    else:
        ids = [getattr(call, 'source_node_id', None)]
    return {
        'id': getattr(call, 'id', None),
        'stop_sequence': call.stop_sequence,
        'stop_label': _text(getattr(call, 'stop_label', None)) or 'Unnamed stop',
        'stop_ids': list(dict.fromkeys(text for value in ids if (text := _text(value)))),
        'uic_ref': _text(getattr(call, 'uic_ref', None)),
        'lat': getattr(call, 'stop_lat', None),
        'lon': getattr(call, 'stop_lon', None),
    }


def compare_stop_calls(atlas_calls, osm_calls, atlas_itinerary=None, osm_itinerary=None):
    """Align two ordered call sequences; preserve gaps and repeated visits.

    Traceback needs one byte per pair; scores only need the previous row. On
    equal scores the engine prefers a matching diagonal, then an ATLAS gap.
    """
    atlas_identities = [_identity(call) for call in atlas_calls]
    osm_identities = [_identity(call) for call in osm_calls]
    atlas_stops = [_serialize_stop(call, 'atlas') for call in atlas_calls]
    osm_stops = [_serialize_stop(call, 'osm') for call in osm_calls]
    width = len(osm_calls)
    trace = []
    previous = [0] * (width + 1)
    for atlas_identity in atlas_identities:
        current = [0]
        row_trace = bytearray(width)
        for j, osm_identity in enumerate(osm_identities):
            match_type = _match_type(atlas_identity, osm_identity)
            diagonal = previous[j] + bool(match_type)
            up, left = previous[j + 1], current[j]
            if match_type and diagonal >= up and diagonal >= left:
                current.append(diagonal)
                row_trace[j] = 1
            elif up >= left:
                current.append(up)
                row_trace[j] = 2
            else:
                current.append(left)
                row_trace[j] = 3
        previous = current
        trace.append(row_trace)

    rows = []
    i, j = len(atlas_calls), width
    while i or j:
        move = trace[i - 1][j - 1] if i and j else (2 if i else 3)
        if move == 1:
            rows.append({'atlas': atlas_stops[i - 1], 'osm': osm_stops[j - 1],
                         'match_type': _match_type(atlas_identities[i - 1], osm_identities[j - 1])})
            i -= 1
            j -= 1
        elif move == 2:
            rows.append({'atlas': atlas_stops[i - 1], 'osm': None, 'match_type': None})
            i -= 1
        else:
            rows.append({'atlas': None, 'osm': osm_stops[j - 1], 'match_type': None})
            j -= 1
    rows.reverse()

    has_pair = atlas_itinerary is not None and osm_itinerary is not None
    denominator = max(len(atlas_calls), len(osm_calls))
    ratio = previous[-1] / denominator if has_pair and denominator else None
    atlas_direction = _text(getattr(atlas_itinerary, 'direction_id', None))
    osm_direction = _text(getattr(osm_itinerary, 'direction_id', None))
    direction_status = 'unknown'
    if atlas_direction is not None and osm_direction is not None:
        direction_status = 'match' if atlas_direction == osm_direction else 'conflict'
    return {
        'rows': rows,
        'matched_stop_count': previous[-1],
        'atlas_stop_count': len(atlas_calls),
        'osm_stop_count': len(osm_calls),
        'stop_ratio': ratio,
        'percentage': round(ratio * 100, 1) if ratio is not None else None,
        'direction_status': direction_status,
    }


def _matched_expression(source):
    column = (ItineraryMatch.atlas_itinerary_id if source == 'atlas'
              else ItineraryMatch.osm_itinerary_id)
    return exists(select(ItineraryMatch.id).where(column == Itinerary.id))


def _metadata(itinerary, family, is_matched):
    return {
        'id': itinerary.id,
        'family_id': family.id,
        'route_id': (_text(family.display_route_id) or _text(family.ref)
                     or family.source_family_id),
        'route_name': (_text(family.public_name) or _text(family.ref)
                       or _text(family.display_route_id) or family.source_family_id),
        'display_name': (_text(itinerary.display_name) or _text(itinerary.representative_headsign)
                         or itinerary.source_itinerary_id),
        'direction_id': _text(itinerary.direction_id),
        'is_matched': bool(is_matched),
    }


def _itineraries_query(source):
    return (db.session.query(Itinerary, LineFamily, _matched_expression(source).label('is_matched'))
            .join(LineFamily, LineFamily.id == Itinerary.line_family_id)
            .filter(Itinerary.source == source, LineFamily.source == source,
                    LineFamily.is_non_gtfs.is_(False)))


def build_route_comparison(atlas_itinerary_id=None, osm_itinerary_id=None):
    metadata = {'atlas': None, 'osm': None}
    itineraries = {'atlas': None, 'osm': None}
    calls = {'atlas': [], 'osm': []}
    for source, itinerary_id in [('atlas', atlas_itinerary_id), ('osm', osm_itinerary_id)]:
        if itinerary_id is None:
            continue
        row = _itineraries_query(source).filter(Itinerary.id == itinerary_id).first()
        if row is None:
            raise LookupError(f'{source.upper()} itinerary not found.')
        itinerary, family, is_matched = row
        metadata[source] = _metadata(itinerary, family, is_matched)
        itineraries[source] = itinerary
        calls[source] = (db.session.query(StopCall).filter(StopCall.itinerary_id == itinerary_id)
                         .order_by(StopCall.stop_sequence, StopCall.id).all())
    is_saved_match = False
    if atlas_itinerary_id is not None and osm_itinerary_id is not None:
        is_saved_match = db.session.query(exists(select(ItineraryMatch.id).where(
            ItineraryMatch.atlas_itinerary_id == atlas_itinerary_id,
            ItineraryMatch.osm_itinerary_id == osm_itinerary_id,
        ))).scalar()
    return {
        **metadata,
        **compare_stop_calls(calls['atlas'], calls['osm'], itineraries['atlas'], itineraries['osm']),
        'is_saved_match': bool(is_saved_match),
    }


def _options_query(source, *, q='', unmatched=True):
    query = _itineraries_query(source)
    if unmatched:
        query = query.filter(~_matched_expression(source))
    if q:
        columns = [LineFamily.source_family_id, LineFamily.display_route_id, LineFamily.ref,
                   LineFamily.public_name, LineFamily.operator, LineFamily.gtfs_route_id,
                   LineFamily.route_master_id, Itinerary.source_itinerary_id,
                   Itinerary.display_name, Itinerary.representative_headsign]
        query = query.filter(or_(*[
            func.lower(func.coalesce(cast(column, String), '')).contains(q.lower(), autoescape=True)
            for column in columns
        ]))
    return query


def list_comparison_options(source, *, q='', unmatched=True, page=1, per_page=30, anchor_id=None,
                            fixed_itinerary_id=None):
    if fixed_itinerary_id is not None:
        return _ranked_comparison_options(
            source, fixed_itinerary_id, q=q, unmatched=unmatched, page=page,
            per_page=per_page, anchor_id=anchor_id,
        )
    query = _options_query(source, q=q, unmatched=unmatched)
    total = query.count()
    pages = (total + per_page - 1) // per_page
    route_order = func.lower(func.coalesce(LineFamily.display_route_id, LineFamily.ref,
                                          LineFamily.source_family_id, ''))
    itinerary_order = func.lower(func.coalesce(Itinerary.display_name, ''))
    if anchor_id is not None and not q:
        anchor = query.with_entities(route_order, itinerary_order).filter(Itinerary.id == anchor_id).first()
        if anchor is not None:
            preceding = query.filter(or_(
                route_order < anchor[0],
                and_(route_order == anchor[0], itinerary_order < anchor[1]),
                and_(route_order == anchor[0], itinerary_order == anchor[1], Itinerary.id < anchor_id),
            )).count()
            page = preceding // per_page + 1
    page = min(page, pages or 1)
    rows = (query.order_by(route_order, itinerary_order, Itinerary.id)
            .offset((page - 1) * per_page).limit(per_page).all())
    return {
        'items': [_metadata(itinerary, family, is_matched) for itinerary, family, is_matched in rows],
        'page': page,
        'pages': pages,
        'total': total,
    }


def _fixed_sources(itinerary_ids):
    rows = (db.session.query(Itinerary.id, Itinerary.source)
            .join(LineFamily, LineFamily.id == Itinerary.line_family_id)
            .filter(Itinerary.id.in_(itinerary_ids), Itinerary.source.in_(['atlas', 'osm']),
                    LineFamily.source == Itinerary.source, LineFamily.is_non_gtfs.is_(False)).all())
    sources = dict(rows)
    if len(sources) != len(set(itinerary_ids)):
        raise LookupError('A selected itinerary was not found.')
    return sources


def _load_identities(itinerary_ids):
    calls = {itinerary_id: [] for itinerary_id in itinerary_ids}
    rows = (db.session.query(StopCall.itinerary_id, StopCall.source_sloid,
                             StopCall.source_sloid_variants, StopCall.uic_ref)
            .filter(StopCall.itinerary_id.in_(itinerary_ids))
            .order_by(StopCall.itinerary_id, StopCall.stop_sequence, StopCall.id))
    for row in rows.yield_per(2000):
        calls[row.itinerary_id].append(_identity(row))
    return calls


def _identity_index(identities):
    resolved, uics, unresolved_uics = defaultdict(set), defaultdict(set), defaultdict(set)
    for position, (ids, uic) in enumerate(identities):
        for identity in ids:
            resolved[identity].add(position)
        if uic:
            uics[uic].add(position)
            if not ids:
                unresolved_uics[uic].add(position)
    return resolved, uics, unresolved_uics


def _matching_positions(identity, index):
    ids, uic = identity
    resolved, uics, unresolved_uics = index
    positions = set()
    for resolved_id in ids:
        positions.update(resolved.get(resolved_id, ()))
    if uic:
        positions.update((unresolved_uics if ids else uics).get(uic, ()))
    return positions


def _ordered_match_count(position_sets):
    """Exact sparse LCS: decreasing positions prevent one stop being reused."""
    tails = []
    for positions in position_sets:
        for position in sorted(positions, reverse=True):
            index = bisect_left(tails, position)
            if index == len(tails):
                tails.append(position)
            else:
                tails[index] = position
    return len(tails)


def _potential_candidate_ids(query, fixed_calls):
    resolved_ids, uics = set(), set()
    for identities in fixed_calls.values():
        for ids, uic in identities:
            resolved_ids.update(ids)
            if uic:
                uics.add(uic)
    conditions = []
    if resolved_ids:
        conditions.extend([
            StopCall.source_sloid.in_(resolved_ids),
            # Variants are JSON text, including older publications. Conservatively
            # include variant-bearing calls, then parse/validate their identities
            # in Python; casting malformed historical JSON must not break review.
            and_(StopCall.source_sloid_variants.isnot(None),
                 StopCall.source_sloid_variants.notin_(['', '[]', 'null'])),
        ])
    if uics:
        conditions.append(StopCall.uic_ref.in_(uics))
    if not conditions:
        return iter(())
    return iter(query.with_entities(Itinerary.id)
                .join(StopCall, StopCall.itinerary_id == Itinerary.id)
                .filter(or_(*conditions)).distinct().order_by(Itinerary.id).yield_per(1000))


def _rank_candidates(fixed_calls, query, *, limit=1, visible_ids=None):
    """Scan every possible overlap, loading sequences in bounded batches.

    Keep only the requested prefix and global best. A shared-identity upper
    bound skips LCS scoring when a candidate cannot improve either result.
    """
    rankings = {itinerary_id: [] for itinerary_id in fixed_calls}
    best = {itinerary_id: None for itinerary_id in fixed_calls}
    candidate_ids = _potential_candidate_ids(query, fixed_calls)
    while batch := list(islice(candidate_ids, 200)):
        candidates = _load_identities([row[0] for row in batch])
        for candidate_id, identities in candidates.items():
            index = _identity_index(identities)
            visible = visible_ids is None or candidate_id in visible_ids
            for itinerary_id, fixed in fixed_calls.items():
                positions = [_matching_positions(identity, index) for identity in fixed]
                possible_positions = set().union(*positions) if positions else set()
                upper_count = min(sum(bool(items) for items in positions), len(possible_positions))
                if not upper_count:
                    continue
                denominator = max(len(fixed), len(identities))
                upper_key = (upper_count / denominator, upper_count, -candidate_id)
                heap = rankings[itinerary_id]
                can_rank = visible and limit > 0 and (len(heap) < limit or upper_key > heap[0])
                can_be_best = best[itinerary_id] is None or upper_key > best[itinerary_id]
                if not can_rank and not can_be_best:
                    continue
                matched = _ordered_match_count(positions)
                key = (matched / denominator, matched, -candidate_id)
                if can_rank:
                    if len(heap) < limit:
                        heappush(heap, key)
                    elif key > heap[0]:
                        heapreplace(heap, key)
                if best[itinerary_id] is None or key > best[itinerary_id]:
                    best[itinerary_id] = key
    return {key: sorted(heap, reverse=True) for key, heap in rankings.items()}, best


def _fill_zero_scores(ranking, query, limit):
    if len(ranking) >= limit:
        return ranking
    query = query.with_entities(Itinerary.id)
    if ranking:
        query = query.filter(~Itinerary.id.in_([-key[2] for key in ranking]))
    rows = query.order_by(Itinerary.id).limit(limit - len(ranking)).all()
    return ranking + [(0.0, 0, -row[0]) for row in rows]


def _ranked_metadata(source, candidate_ids):
    if not candidate_ids:
        return {}, {}
    rows = _itineraries_query(source).filter(Itinerary.id.in_(candidate_ids)).all()
    metadata = {itinerary.id: _metadata(itinerary, family, matched)
                for itinerary, family, matched in rows}
    counts = dict(db.session.query(StopCall.itinerary_id, func.count(StopCall.id))
                  .filter(StopCall.itinerary_id.in_(candidate_ids))
                  .group_by(StopCall.itinerary_id).all())
    return metadata, counts


def _scored_item(key, metadata, counts, fixed_count):
    if key is None:
        return None
    candidate_id = -key[2]
    ratio = key[0] if fixed_count or counts.get(candidate_id, 0) else None
    return {
        **metadata[candidate_id],
        'stop_ratio': ratio,
        'percentage': round(ratio * 100, 1) if ratio is not None else None,
        'matched_stop_count': key[1],
    }


def _ranked_comparison_options(source, fixed_id, *, q, unmatched, page, per_page, anchor_id):
    fixed_source = _fixed_sources([fixed_id])[fixed_id]
    if fixed_source == source:
        raise ValueError('The selected itinerary must be from the opposite source.')
    fixed_calls = _load_identities([fixed_id])
    all_query = _options_query(source, unmatched=unmatched)
    query = _options_query(source, q=q, unmatched=unmatched)
    total = query.count()
    pages = (total + per_page - 1) // per_page
    page = min(page, pages or 1)
    limit = total if anchor_id is not None and not q else min(page * per_page, total)
    visible_ids = {row[0] for row in query.with_entities(Itinerary.id).all()} if q else None
    rankings, best = _rank_candidates(fixed_calls, all_query, limit=limit, visible_ids=visible_ids)
    ranking = _fill_zero_scores(rankings[fixed_id], query, limit)
    if anchor_id is not None and not q:
        anchor_index = next((index for index, key in enumerate(ranking) if -key[2] == anchor_id), None)
        if anchor_index is not None:
            page = anchor_index // per_page + 1
    selected = ranking[(page - 1) * per_page:page * per_page]
    best_key = best[fixed_id]
    if best_key is None:
        best_key = next(iter(_fill_zero_scores([], all_query, 1)), None)
    ids = {-key[2] for key in selected}
    if best_key is not None:
        ids.add(-best_key[2])
    metadata, counts = _ranked_metadata(source, ids)
    fixed_count = len(fixed_calls[fixed_id])
    return {
        'items': [_scored_item(key, metadata, counts, fixed_count) for key in selected],
        'best': _scored_item(best_key, metadata, counts, fixed_count),
        'page': page, 'pages': pages, 'total': total,
    }


def best_comparison_options(itinerary_ids):
    """Batch summary badges, sharing identity scans and sequence reads by side."""
    sources = _fixed_sources(itinerary_ids)
    fixed_calls = _load_identities(itinerary_ids)
    results = {}
    for source in ('atlas', 'osm'):
        selected_calls = {key: fixed_calls[key] for key, fixed_source in sources.items() if fixed_source != source}
        if not selected_calls:
            continue
        query = _options_query(source, unmatched=False)
        _, best = _rank_candidates(selected_calls, query, limit=0)
        fallback = next(iter(_fill_zero_scores([], query, 1)), None) if None in best.values() else None
        best = {key: value if value is not None else fallback for key, value in best.items()}
        ids = {-value[2] for value in best.values() if value is not None}
        metadata, counts = _ranked_metadata(source, ids)
        results.update({
            str(key): _scored_item(value, metadata, counts, len(selected_calls[key]))
            for key, value in best.items()
        })
    return {'items': results}
