"""Name and number suggestions for the map's search box.

The index has one entry per source station: the stops that share a station
number (``uic_ref``), or a single stop when it has none. The OSM names of the
station's matched elements, and of unmatched OSM elements that carry its
number, are other names of the station, so it is found under any of them.
Every other named OSM element without a match is an entry of its own.
Picking an entry adds the same search filter as typing its number.

Names are compared without case, accents or punctuation: "zurich hb" finds
"Zürich HB". The index is built from the published snapshot on the first
request and rebuilt when another snapshot is published.
See documentation/2.2 Filters and Search logic.md.
"""

import re
import threading
import unicodedata
from dataclasses import dataclass, field

from backend.extensions import db
from backend.models import AtlasStop, DatasetPublication, OsmNode, StopsMatched
from backend.services.stop_lookup import public_osm_id

MIN_QUERY_LENGTH = 2
DEFAULT_LIMIT = 8
MAX_LIMIT = 20
# OSM elements without a source counterpart. Middles of two-sided stops
# (effectively_matched) belong to a matched stop and are left out.
OSM_ONLY_TYPES = ('osm_unmatched', 'osm_disused')

# How a query met an entry, best first: its number, its display name, another name.
BY_REF, BY_NAME, BY_OTHER_NAME = 0, 1, 2

_NON_WORD = re.compile(r'[^0-9a-z]+')


def normalize(text):
    """'Zürich, HB' -> 'zurich hb': lower case, no accents, words split on punctuation."""
    decomposed = unicodedata.normalize('NFKD', text or '')
    plain = ''.join(char for char in decomposed if not unicodedata.combining(char))
    return _NON_WORD.sub(' ', plain.casefold()).strip()


@dataclass
class Entry:
    kind: str           # the search token it adds: 'station', 'atlas' or 'osm'
    value: str          # the token's value, as the search filter expects it
    ref: str            # the identifier shown next to the name
    name: str
    side: str           # 'source' or 'osm'
    stops: int = 0      # source stops of a station
    stop_type: str = ''
    # (normalized name, its words, name): the display name first
    names: list = field(default_factory=list)
    # Every normalized name and the reference, for a quick first test.
    haystack: str = ''

    def add_name(self, name):
        normalized = normalize(name)
        if normalized and all(normalized != known for known, _, _ in self.names):
            self.names.append((normalized, tuple(normalized.split()), name))


def build_index():
    """Every searchable entry of the published snapshot."""
    rows = db.session.query(
        StopsMatched.sloid,
        StopsMatched.osm_node_id,
        StopsMatched.stop_type,
        AtlasStop.uic_ref,
        AtlasStop.atlas_designation_official,
        OsmNode.osm_name,
        OsmNode.osm_uic_ref,
    ).outerjoin(AtlasStop, AtlasStop.sloid == StopsMatched.sloid) \
     .outerjoin(OsmNode, OsmNode.osm_node_id == StopsMatched.osm_node_id) \
     .order_by(StopsMatched.sloid, StopsMatched.osm_node_id) \
     .all()

    stations = {}
    station_stops = {}
    osm_only = []
    for sloid, osm_node_id, stop_type, uic_ref, source_name, osm_name, osm_uic_ref in rows:
        if sloid:
            key = uic_ref or sloid
            if key not in stations:
                stations[key] = Entry(
                    kind='station' if uic_ref else 'atlas', value=key, ref=key, name=source_name or key,
                    side='source',
                )
                stations[key].add_name(source_name or key)
                station_stops[key] = set()
            station_stops[key].add(sloid)
            if osm_name:
                stations[key].add_name(osm_name)
        elif osm_node_id and osm_name and stop_type in OSM_ONLY_TYPES:
            osm_only.append((osm_node_id, stop_type, osm_name, osm_uic_ref))

    entries = []
    for osm_node_id, stop_type, osm_name, osm_uic_ref in osm_only:
        station = stations.get(osm_uic_ref) if osm_uic_ref else None
        if station is not None and station.kind == 'station':
            # The station's search filter also keeps OSM elements with its number.
            station.add_name(osm_name)
            continue
        entry = Entry(kind='osm', value=osm_node_id, ref=public_osm_id(osm_node_id), name=osm_name,
                      side='osm', stop_type=stop_type)
        entry.add_name(osm_name)
        entries.append(entry)
    for key, station in stations.items():
        station.stops = len(station_stops[key])
    entries = list(stations.values()) + entries
    for entry in entries:
        entry.haystack = '\n'.join([normalized for normalized, _, _ in entry.names] + [entry.ref.casefold()])
    return entries


def name_rank(normalized_name, name_words, query, words):
    """0 same name, 1 starts with the query, 2 each query word starts a word, 3 contains it; None otherwise."""
    if normalized_name == query:
        return 0
    if normalized_name.startswith(query):
        return 1
    if all(any(word.startswith(part) for word in name_words) for part in words):
        return 2
    if len(query) >= 3 and query in normalized_name:
        return 3
    return None


def best_match(entry, raw_query, query, words):
    """(rank, how, other name) for the entry's best match, or None.

    ``how`` is BY_REF, BY_NAME or BY_OTHER_NAME; ``other name`` is the OSM
    name that matched when it is not the display name.
    """
    best = None
    ref = entry.ref.casefold()
    if ref.startswith(raw_query):
        best = (0 if ref == raw_query else 1, BY_REF, None)
    for position, (normalized_name, name_words, name) in enumerate(entry.names):
        rank = name_rank(normalized_name, name_words, query, words)
        if rank is None:
            continue
        candidate = (rank, BY_NAME, None) if position == 0 else (rank, BY_OTHER_NAME, name)
        if best is None or candidate[:2] < best[:2]:
            best = candidate
    return best


def search(entries, raw_query, limit=DEFAULT_LIMIT):
    """The best ``limit`` entries for the query, as JSON-ready dicts.

    Order: rank (same name or number, then starts with, then a word starts
    with, then contains), source stations before OSM elements, display names
    before other names; then stations by number, names by length.
    """
    raw_query = (raw_query or '').strip().casefold()
    query = normalize(raw_query)
    if len(query) < MIN_QUERY_LENGTH:
        return []
    words = query.split()
    found = []
    for entry in entries:
        if not all(word in entry.haystack for word in words) and raw_query not in entry.haystack:
            continue
        match = best_match(entry, raw_query, query, words)
        if match is None:
            continue
        rank, how, other_name = match
        order = entry.ref if how == BY_REF else ''
        found.append(((rank, entry.side != 'source', how, order, len(entry.name), entry.name, entry.ref),
                      entry, other_name))
    found.sort(key=lambda item: item[0])
    return [serialize(entry, other_name) for _, entry, other_name in found[:limit]]


def serialize(entry, other_name):
    result = {
        'kind': entry.kind,
        'value': entry.value,
        'ref': entry.ref,
        'name': entry.name,
        'side': entry.side,
        'matched_name': other_name,
    }
    if entry.side == 'source':
        result['stops'] = entry.stops
    else:
        result['stop_type'] = entry.stop_type
    return result


_lock = threading.Lock()
_cache = {'run_id': None, 'entries': None}


def current_entries():
    """The index of the published snapshot, built once per snapshot and process."""
    run_id = db.session.query(DatasetPublication.run_id).scalar()
    if run_id is None:
        # No published snapshot to key a cache on: read the tables as they are.
        return build_index()
    with _lock:
        if _cache['run_id'] != run_id:
            _cache['entries'] = build_index()
            _cache['run_id'] = run_id
        return _cache['entries']


def suggest(raw_query, limit=DEFAULT_LIMIT):
    return search(current_entries(), raw_query, limit)
