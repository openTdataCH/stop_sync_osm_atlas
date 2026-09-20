"""Swiss ATLAS policy, including the legacy ordered allocation behavior."""
import re
from . import MatchingProfile, ReferenceRule


def normalize_route_id(route_id):
    if route_id is None:
        return None
    text = str(route_id).strip()
    return re.sub(r'-j\d+', '-jXX', text) if text else None


SWITZERLAND = MatchingProfile(
    profile_id='switzerland',
    station_reference_matching=True,
    problem_name_tags=('uic_name',),
    preserve_name_alias_multiplicity=True,
    distance_priority_exempt_operators=('SBB',),
    osm_grouping=True,
    itinerary_require_direction=True,
    name_match_max_distance=None,
    reference_rules=(ReferenceRule('uic', 'uic_ref', scope='station', source_namespace='atlas'),),
    capabilities=('stops', 'problems', 'routes'),
)
