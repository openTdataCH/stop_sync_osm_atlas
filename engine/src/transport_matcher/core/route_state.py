"""Route equivalence for one run, built from normalized in-memory records."""
from dataclasses import dataclass, field


@dataclass
class RouteState:
    osm_route_to_source_route: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_records(cls, source_routes=(), osm_routes=()):
        source_routes = list(source_routes)
        route_ids = {str(row['route_id']) for row in source_routes if row.get('route_id')}
        normalized = {}
        for row in source_routes:
            key = row.get('route_id_normalized')
            if key and row.get('route_id'):
                normalized.setdefault(str(key), []).append(str(row.get('route_id')))
        mapping = {}
        for row in osm_routes:
            route_id = row.get('gtfs_route_id')
            relation_id = row.get('relation_id')
            if not route_id or not relation_id:
                continue
            if str(route_id) in route_ids:
                mapping[str(relation_id)] = str(route_id)
            else:
                candidates = normalized.get(str(row.get('route_id_normalized', '')), [])
                if len(candidates) == 1:
                    mapping[str(relation_id)] = candidates[0]
        return cls(mapping)

    def get_source_route(self, osm_relation_id):
        return self.osm_route_to_source_route.get(str(osm_relation_id))
