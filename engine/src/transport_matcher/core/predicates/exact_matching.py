"""Exact matching through profile-approved, scoped identifier mappings."""
from collections import defaultdict

from transport_matcher.core.predicates import BasePredicate
from transport_matcher.core.utils.common import haversine_distance


class ExactReferencePredicate(BasePredicate):
    """Preserve station one-to-many allocation; require explicit reference compatibility."""

    def run(self, ctx):
        for rule in ctx.profile.reference_rules:
            candidates_by_value = ctx.osm.get_all_unmatched_grouped(rule.osm_tag)
            groups = defaultdict(list)
            for stop in ctx.source.get_unmatched_records():
                for reference in stop.references:
                    if reference.namespace == rule.namespace and reference.scope == rule.scope and (
                        rule.source_namespace is None or stop.namespace == rule.source_namespace
                    ):
                        groups[(stop.namespace, reference.value)].append((stop, reference))
            for (_, value), entries in sorted(groups.items()):
                entries = [(stop, reference) for stop, reference in entries if stop.key not in ctx.source.matched_ids]
                if not entries:
                    continue
                candidates = candidates_by_value.get(value, [])
                candidates = [node for node in candidates if not ctx.osm.is_used(node.node_id)
                              and rule.accepts(entries[0][0], entries[0][1], node)]
                if not candidates:
                    continue
                if rule.scope != 'station' and len(entries) > 1:
                    ctx.diagnostics.append({
                        'code': 'ambiguous_exact_reference', 'stage': self.name,
                        'source_keys': sorted(stop.key for stop, _ in entries),
                        'reference_namespace': rule.namespace, 'reference_value': value,
                        'reason': 'Multiple source stops declare the same stop-scoped identifier.',
                    })
                    continue
                # Station anchors intentionally support multiple links (Swiss legacy behavior).
                if rule.scope == 'station' and len(candidates) == 1:
                    for stop, _ in entries:
                        self._commit(ctx, stop, candidates[0], rule, value, 'Single OSM element for station reference')
                elif rule.scope == 'station' and len(entries) == 1:
                    for osm in candidates:
                        self._commit(ctx, entries[0][0], osm, rule, value, 'Single source stop matched to multiple OSM elements')
                else:
                    for stop, _ in entries:
                        available = [osm for osm in candidates if not ctx.osm.is_used(osm.node_id)]
                        if rule.scope != 'station' and len(available) == 1:
                            chosen = available[0]
                        else:
                            compatible = [osm for osm in available if stop.platform_code and (osm.local_ref or '').strip().lower() == stop.platform_code.strip().lower()]
                            chosen = compatible[0] if compatible and (rule.scope == 'station' or len(compatible) == 1) else None
                        if chosen:
                            self._commit(ctx, stop, chosen, rule, value, 'Exact compatible reference and platform code')

    @staticmethod
    def _commit(ctx, stop, osm, rule, value, notes):
        before = len(ctx.all_matches)
        ctx.commit(source_node=stop, osm_node=osm, match_type='exact',
                   distance_m=haversine_distance(stop.lat, stop.lon, osm.lat, osm.lon), notes=notes)
        ctx.all_matches[before].evidence.update({
            'reference': {'namespace': rule.namespace, 'value': value, 'scope': rule.scope},
            'osm_tag': rule.osm_tag,
            'source_namespace': stop.namespace,
        })


# Import compatibility for predicate contributors; this runs the same scoped implementation.
ExactUicPredicate = ExactReferencePredicate
