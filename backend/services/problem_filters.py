"""Problem filters shared by the Problems page and the map.

The Problems page narrows its list by problem type, priority and a drawn
area; the map keeps the stops that have such a problem. Both read the same
parameters: problem_type, priority and, on the Problems page, bbox.
See documentation/2.4 Problems Page.md and documentation/2.2 Filters and Search logic.md.
"""

from sqlalchemy import and_, or_

from backend.models import Problem, StopsMatched

VISIBLE_PROBLEM_TYPES = (
    'distance',
    'unmatched',
    'attributes',
    'contradicts_route_matching',
    'duplicates',
    'disused',
    'identifier',
)


def csv_values(raw_value):
    return [item.strip() for item in str(raw_value or '').split(',') if item.strip()]


def parse_problem_types(raw_value):
    """The listed problem types; empty for none or "all". The old name "isolated" is "unmatched"."""
    return [
        'unmatched' if value == 'isolated' else value
        for value in csv_values(raw_value)
        if value != 'all'
    ]


def parse_priorities(raw_value):
    """The listed priorities 1 to 3 as numbers; anything else is ignored."""
    return [int(value) for value in csv_values(raw_value) if value in ('1', '2', '3')]


def parse_area(raw_value):
    """bbox "west,south,east,north" in degrees as a tuple, None when absent.

    Raises ValueError for anything else, so a malformed link is refused
    instead of silently showing every problem.
    """
    if not raw_value:
        return None
    parts = csv_values(raw_value)
    if len(parts) != 4:
        raise ValueError('bbox must be west,south,east,north in degrees.')
    try:
        west, south, east, north = (float(part) for part in parts)
    except ValueError:
        raise ValueError('bbox must be west,south,east,north in degrees.') from None
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ValueError('bbox needs west < east within -180..180 and south < north within -90..90.')
    return west, south, east, north


def area_condition(area):
    """The map entry lies in the area: its ATLAS or its OSM position is inside."""
    west, south, east, north = area

    def inside(lat, lon):
        return and_(lat.between(south, north), lon.between(west, east))

    return or_(inside(StopsMatched.atlas_lat, StopsMatched.atlas_lon),
               inside(StopsMatched.osm_lat, StopsMatched.osm_lon))


def has_problem_condition(problem_types, priorities):
    """The map entry has one problem of the given types (any visible type when empty) and priorities."""
    conditions = [Problem.problem_type.in_(problem_types or VISIBLE_PROBLEM_TYPES)]
    if priorities:
        conditions.append(Problem.priority.in_(priorities))
    return StopsMatched.problems.any(and_(*conditions))
