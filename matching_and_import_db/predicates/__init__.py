from matching_and_import_db.predicates.exact_matching import exact_uic
from matching_and_import_db.predicates.name_matching import name_match
from matching_and_import_db.predicates.distance_matching import (
    group_proximity,
    local_ref_distance,
    nearest_distance,
)
from matching_and_import_db.predicates.route_matching_unified import route_match
from matching_and_import_db.predicates.postpass_matching import (
    postpass_unique_uic,
    duplicate_propagation,
    manual_match,
)

__all__ = [
    "exact_uic",
    "name_match",
    "group_proximity",
    "local_ref_distance",
    "nearest_distance",
    "route_match",
    "postpass_unique_uic",
    "duplicate_propagation",
    "manual_match",
]
