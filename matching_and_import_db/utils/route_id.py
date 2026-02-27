"""Shared route-ID helpers used across the pipeline."""
import re

_YEAR_CODE_RE = re.compile(r'-j\d+')


def normalize_route_id(route_id):
    """Normalize a GTFS route_id by replacing year codes like -j24, -j25 with -jXX."""
    if not route_id:
        return None
    return _YEAR_CODE_RE.sub('-jXX', str(route_id))
