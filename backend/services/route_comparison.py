"""Itinerary comparisons using the published, resolved stop identities.

Keep the identity rules and LCS tie-breaking consistent with the matching engine,
without making the independent review application depend on the engine package.
Live comparisons read the database; ``compute_best_overlaps`` runs on import
rows before publication.
"""

import json
from bisect import bisect_left
from collections import Counter, defaultdict
from heapq import heappush, heapreplace
from itertools import islice

from sqlalchemy import String, and_, cast, exists, func, or_, select
from sqlalchemy.orm import aliased

from backend.extensions import db
from backend.models import Itinerary, ItineraryBestOverlap, ItineraryMatch, LineFamily, StopCall


def _text(value):
    return str(value).strip() or None if value is not None else None


def _variant_values(raw):
    """Variant SLOIDs from stored JSON text, or from an already decoded list."""
    if not isinstance(raw, list):
        try:
            raw = json.loads(raw or '[]')
        except (TypeError, ValueError):
            return []
    if not isinstance(raw, list):
        return []
    return [text for value in raw if (text := _text(value)) is not None]


def _variants(call):
    return _variant_values(getattr(call, 'source_sloid_variants', None))


def _identity_values(source_sloid, source_sloid_variants, uic_ref):
    resolved = set(_variant_values(source_sloid_variants))
    if source_sloid := _text(source_sloid):
        resolved.add(source_sloid)
    return resolved, _text(uic_ref)


def _identity(call):
    return _identity_values(getattr(call, 'source_sloid', None),
                            getattr(call, 'source_sloid_variants', None),
                            getattr(call, 'uic_ref', None))


def _match_type(atlas, osm):
    atlas_ids, atlas_uic = atlas
    osm_ids, osm_uic = osm
    if atlas_ids and osm_ids:
        return 'resolved_sloid_match' if atlas_ids & osm_ids else None
    return 'uic_match' if atlas_uic and atlas_uic == osm_uic else None


def _serialize_stop(call, source, position=None):
    if source == 'atlas':
        ids = [getattr(call, 'source_sloid', None), *_variants(call),
               getattr(call, 'source_stop_id', None)]
    else:
        ids = [getattr(call, 'source_node_id', None)]
    return {
        'id': getattr(call, 'id', None),
        # 1-based order within the variant; OSM stop_sequence follows relation
        # member positions, which skip platforms and are not a stop count.
        'position': position,
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
    atlas_stops = [_serialize_stop(call, 'atlas', position) for position, call in enumerate(atlas_calls, 1)]
    osm_stops = [_serialize_stop(call, 'osm', position) for position, call in enumerate(osm_calls, 1)]
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
        'source_itinerary_id': _text(itinerary.source_itinerary_id),
        'is_matched': bool(is_matched),
    }


def _saved_counterparts(source, itinerary_ids):
    """Other-source variants each itinerary is the saved match of, keyed by ID.

    Matches are unique per pair, not per side, so an itinerary can have several.
    """
    result = {itinerary_id: [] for itinerary_id in itinerary_ids}
    if not result:
        return result
    own, other = ((ItineraryMatch.atlas_itinerary_id, ItineraryMatch.osm_itinerary_id) if source == 'atlas'
                  else (ItineraryMatch.osm_itinerary_id, ItineraryMatch.atlas_itinerary_id))
    rows = (db.session.query(own, Itinerary, LineFamily)
            .join(Itinerary, Itinerary.id == other)
            .join(LineFamily, LineFamily.id == Itinerary.line_family_id)
            .filter(own.in_(result)).order_by(own, Itinerary.id).all())
    for itinerary_id, itinerary, family in rows:
        counterpart = _metadata(itinerary, family, True)
        counterpart['label'] = _route_label(counterpart)
        result[itinerary_id].append(counterpart)
    return result


def _with_counterparts(source, items):
    counterparts = _saved_counterparts(source, {item['id'] for item in items if item['is_matched']})
    for item in items:
        item['matched_with'] = counterparts.get(item['id'], [])
    return items


def _route_label(metadata):
    """Same wording as ``routeLabel`` in routes-comparison.js."""
    parts = [metadata['route_id'], metadata['route_name'], metadata['display_name']]
    if metadata['direction_id'] is not None:
        parts.append(f"Direction {metadata['direction_id']}")
    return ' · '.join(dict.fromkeys(part for part in parts if part)) or f"Itinerary {metadata['id']}"


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
        metadata[source] = _with_counterparts(source, [_metadata(itinerary, family, is_matched)])[0]
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
                            fixed_itinerary_id=None, shared_only=False):
    if fixed_itinerary_id is not None:
        return _ranked_comparison_options(
            source, fixed_itinerary_id, q=q, unmatched=unmatched, page=page,
            per_page=per_page, anchor_id=anchor_id, shared_only=shared_only,
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
        'items': _with_counterparts(source, [_metadata(itinerary, family, is_matched)
                                             for itinerary, family, is_matched in rows]),
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


def _index_identities(entries):
    """Map each identity to the keys of the calls carrying it.

    Keys are call positions for one itinerary, or itinerary IDs for a whole
    source; ``_matching_positions`` then answers "which keys match this call".
    """
    resolved, uics, unresolved_uics = defaultdict(set), defaultdict(set), defaultdict(set)
    for key, (ids, uic) in entries:
        for identity in ids:
            resolved[identity].add(key)
        if uic:
            uics[uic].add(key)
            if not ids:
                unresolved_uics[uic].add(key)
    return resolved, uics, unresolved_uics


def _identity_index(identities):
    return _index_identities(enumerate(identities))


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


def _potential_candidate_ids(query, fixed):
    resolved_ids, uics = set(), set()
    for ids, uic in fixed:
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


def _rank_candidates(fixed, query, limit):
    """Scan every possible overlap, loading sequences in bounded batches.

    Return the requested prefix and how many candidates share at least one
    stop. A shared-identity upper bound skips LCS scoring when a candidate
    cannot enter the prefix.
    """
    heap, shared = [], 0
    if limit <= 0:
        return heap, shared
    candidate_ids = _potential_candidate_ids(query, fixed)
    while batch := list(islice(candidate_ids, 200)):
        for candidate_id, identities in _load_identities([row[0] for row in batch]).items():
            index = _identity_index(identities)
            positions = [_matching_positions(identity, index) for identity in fixed]
            possible_positions = set().union(*positions) if positions else set()
            upper_count = min(sum(bool(items) for items in positions), len(possible_positions))
            if not upper_count:
                continue
            # One shared stop always gives an ordered match of at least one.
            shared += 1
            denominator = max(len(fixed), len(identities))
            if len(heap) == limit and (upper_count / denominator, upper_count, -candidate_id) <= heap[0]:
                continue
            matched = _ordered_match_count(positions)
            key = (matched / denominator, matched, -candidate_id)
            if len(heap) < limit:
                heappush(heap, key)
            elif key > heap[0]:
                heapreplace(heap, key)
    return sorted(heap, reverse=True), shared


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
    items = _with_counterparts(source, [_metadata(itinerary, family, matched)
                                        for itinerary, family, matched in rows])
    metadata = {item['id']: item for item in items}
    counts = dict(db.session.query(StopCall.itinerary_id, func.count(StopCall.id))
                  .filter(StopCall.itinerary_id.in_(candidate_ids))
                  .group_by(StopCall.itinerary_id).all())
    return metadata, counts


def _scored_item(key, metadata, counts, fixed_count):
    candidate_id = -key[2]
    ratio = key[0] if fixed_count or counts.get(candidate_id, 0) else None
    return {
        **metadata[candidate_id],
        'stop_ratio': ratio,
        'percentage': round(ratio * 100, 1) if ratio is not None else None,
        'matched_stop_count': key[1],
    }


def _ranked_comparison_options(source, fixed_id, *, q, unmatched, page, per_page, anchor_id,
                               shared_only=False):
    """Rank candidates by overlap with the fixed itinerary.

    ``shared_only`` lists only candidates sharing at least one stop, and counts
    only those; otherwise every candidate is listed, zero overlaps last.
    """
    fixed_source = _fixed_sources([fixed_id])[fixed_id]
    if fixed_source == source:
        raise ValueError('The selected itinerary must be from the opposite source.')
    fixed = _load_identities([fixed_id])[fixed_id]
    query = _options_query(source, q=q, unmatched=unmatched)
    anchored = anchor_id is not None and not q
    if shared_only:
        # The prefix holds every shared candidate when a page is out of range.
        ranking, total = _rank_candidates(fixed, query, query.count() if anchored else page * per_page)
        pages = (total + per_page - 1) // per_page
        page = min(page, pages or 1)
    else:
        total = query.count()
        pages = (total + per_page - 1) // per_page
        page = min(page, pages or 1)
        limit = total if anchored else min(page * per_page, total)
        ranking = _fill_zero_scores(_rank_candidates(fixed, query, limit)[0], query, limit)
    if anchored:
        anchor_index = next((index for index, key in enumerate(ranking) if -key[2] == anchor_id), None)
        if anchor_index is not None:
            page = anchor_index // per_page + 1
    selected = ranking[(page - 1) * per_page:page * per_page]
    metadata, counts = _ranked_metadata(source, {-key[2] for key in selected})
    return {
        'items': [_scored_item(key, metadata, counts, len(fixed)) for key in selected],
        'page': page, 'pages': pages, 'total': total,
    }


# ---------------------------------------------------------------------------
# Best overlap per itinerary, computed once per import
# ---------------------------------------------------------------------------

def _best_counterpart(fixed, side_index, sequences):
    """Highest-scoring key over every itinerary of the indexed side, or None.

    Only itineraries sharing at least one stop with ``fixed`` are candidates.
    Each gets an upper bound (fixed calls matching any of its calls, capped by
    its length); they are scored exactly in descending bound order until the
    next bound cannot beat the best exact key found so far.
    """
    shared = Counter()
    for identity in fixed:
        shared.update(_matching_positions(identity, side_index))
    bounds = []
    for candidate_id, count in shared.items():
        candidate_length = len(sequences[candidate_id])
        count = min(count, candidate_length)
        bounds.append((count / max(len(fixed), candidate_length), count, -candidate_id))
    bounds.sort(reverse=True)
    best = None
    for bound in bounds:
        if best is not None and bound < best:
            break
        candidate = sequences[-bound[2]]
        index = _identity_index(candidate)
        matched = _ordered_match_count([_matching_positions(identity, index) for identity in fixed])
        key = (matched / max(len(fixed), len(candidate)), matched, bound[2])
        if best is None or key > best:
            best = key
    return best


def compute_best_overlaps(line_families, itineraries, stop_calls):
    """Rows for ``itinerary_best_overlaps`` from the import payload.

    Covers every itinerary the live comparison accepts: ATLAS or OSM, in a
    family of the same source that is not marked non-GTFS. The counterpart is
    searched across all such itineraries of the other source, matched or not,
    with the live ranking: matched stops in order / longer stop count, then
    more matched stops, then the lower itinerary ID.
    """
    family_sources = {row['id']: row['source'] for row in line_families if not row.get('is_non_gtfs')}
    sources = {row['id']: row['source'] for row in itineraries
               if row['source'] in ('atlas', 'osm') and family_sources.get(row['line_family_id']) == row['source']}
    calls = defaultdict(list)
    for row in stop_calls:
        if row['itinerary_id'] in sources:
            calls[row['itinerary_id']].append(row)
    sequences = {}
    for itinerary_id in sources:
        ordered = sorted(calls.pop(itinerary_id, ()), key=lambda row: (row['stop_sequence'], row.get('id') or 0))
        # Tuples keep the identities of a national dataset compact in memory.
        sequences[itinerary_id] = [
            (tuple(ids), uic) for ids, uic in (
                _identity_values(row.get('source_sloid'), row.get('source_sloid_variants'), row.get('uic_ref'))
                for row in ordered
            )
        ]
    side_indexes = {
        source: _index_identities(
            (itinerary_id, identity)
            for itinerary_id, sequence in sequences.items() if sources[itinerary_id] == source
            for identity in sequence
        )
        for source in ('atlas', 'osm')
    }
    rows = []
    for itinerary_id in sorted(sequences):
        other_source = 'osm' if sources[itinerary_id] == 'atlas' else 'atlas'
        best = _best_counterpart(sequences[itinerary_id], side_indexes[other_source], sequences)
        rows.append({
            'itinerary_id': itinerary_id,
            'best_itinerary_id': -best[2] if best else None,
            'matched_stop_count': best[1] if best else 0,
            'stop_ratio': best[0] if best else None,
        })
    return rows


def load_best_overlaps(itinerary_ids):
    """Stored best overlaps for route cards, keyed by itinerary ID.

    An ID without an entry belongs to a snapshot imported before overlaps were
    stored; ``candidate_label`` is None when no other-side itinerary shares a stop.
    """
    if not itinerary_ids:
        return {}
    candidate = aliased(Itinerary)
    rows = (db.session.query(ItineraryBestOverlap, candidate, LineFamily)
            .outerjoin(candidate, candidate.id == ItineraryBestOverlap.best_itinerary_id)
            .outerjoin(LineFamily, LineFamily.id == candidate.line_family_id)
            .filter(ItineraryBestOverlap.itinerary_id.in_(itinerary_ids)).all())
    return {
        overlap.itinerary_id: {
            'candidate_id': overlap.best_itinerary_id,
            'percentage': round(overlap.stop_ratio * 100, 1) if overlap.stop_ratio is not None else None,
            'matched_stop_count': overlap.matched_stop_count,
            'candidate_label': (_route_label(_metadata(itinerary, family, False))
                                if itinerary is not None else None),
        }
        for overlap, itinerary, family in rows
    }
