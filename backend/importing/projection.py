"""Project normalized wire records onto the review application's SQL model.

The bundle is source-neutral; the application's tables use the Swiss names of
its first deployment (``atlas_*``, ``sloid``). Swiss ``atlas:<sloid>`` keys
become plain SLOIDs, so stop URLs stay stable; other feeds keep their
namespaced keys.
"""

from types import SimpleNamespace as Record
import json

_SIDE = {"source": "atlas", "osm": "osm"}


def _renamed(row, names):
    return {names.get(key, key): value for key, value in row.items()}


def _project_routes(routes, ids):
    """Map the bundle's route records onto the application's route tables."""
    def source_id(key):
        return ids.get(key, key)

    def stop_call(row):
        values = _renamed(row, {
            "source_stop_key": "source_sloid", "source_stop_key_variants": "source_sloid_variants",
            "osm_node_id": "source_node_id", "station_ref": "uic_ref",
        })
        for field in ("source_sloid", "canonical_stop_key"):
            if values.get(field):
                values[field] = source_id(values[field])
        variants = values.get("source_sloid_variants")
        if variants:
            keys = json.loads(variants) if isinstance(variants, str) else variants
            values["source_sloid_variants"] = json.dumps([source_id(key) for key in keys])
        return values

    def family(row):
        values = _renamed(row, {"key": "source_family_id"})
        values["source"] = _SIDE[values.pop("side")]
        values["atlas_line_id"] = row["key"] if row["side"] == "source" else None
        return values

    def itinerary(row):
        values = _renamed(row, {"key": "source_itinerary_id"})
        values["source"] = _SIDE[values.pop("side")]
        return values

    return {
        "atlas_line_families": [_renamed(row, {"route_id": "atlas_line_id"}) for row in routes.get("source_routes", [])],
        "osm_route_relations": routes.get("osm_route_relations", []),
        "line_families": [family(row) for row in routes.get("line_families", [])],
        "itineraries": [itinerary(row) for row in routes.get("itineraries", [])],
        "stop_calls": [stop_call(row) for row in routes.get("stop_calls", [])],
        "line_family_matches": [_renamed(row, {"source_line_family_id": "atlas_line_family_id"})
                                for row in routes.get("line_family_matches", [])],
        "itinerary_matches": [_renamed(row, {"source_itinerary_id": "atlas_itinerary_id"})
                              for row in routes.get("itinerary_matches", [])],
        "matched_routes": routes.get("matched_routes", 0),
        "unknown_source_stop_references": routes.get("unknown_source_stop_references", 0),
    }


def project_bundle(bundle):
    source_rows = {row["key"]: row for row in bundle["source_stops"]}
    ids = {
        key: row["source_id"] if row["namespace"] == "atlas" else key
        for key, row in source_rows.items()
    }
    if len(set(ids.values())) != len(ids):
        raise ValueError("Source identifiers collide in the review projection")
    sources = {
        key: Record(
            sloid=ids[key], lat=row["lat"], lon=row["lon"],
            uic_ref=row.get("station_ref", ""), designation=row.get("platform_code", ""),
            designation_official=row.get("name", ""), business_org_abbr=row.get("operator", ""),
            business_org_id=row.get("operator_id", ""), business_org_name=row.get("operator_name", ""),
        ) for key, row in source_rows.items()
    }
    osm = {}
    for row in bundle["osm_nodes"]:
        values = {key: value for key, value in row.items() if key != "key"}
        values["is_station"] = (
            row.get("public_transport") != "stop_position" and row.get("aerialway") != "station"
            and (row.get("public_transport") == "station" or row.get("railway") == "station")
        )
        osm[row["key"]] = Record(**values)
    matches = [Record(
        atlas_node=sources[row["source_key"]], osm_node=osm[row["osm_key"]],
        match_type=row["method"], distance_m=row["distance_m"], notes=row.get("notes", ""),
        problems=[Record(**p) for p in row.get("problems", [])],
    ) for row in bundle["matches"]]
    matches_by_pair, matches_by_source, matches_by_osm = {}, {}, {}
    for row, match in zip(bundle["matches"], matches):
        source_key, osm_id = row["source_key"], str(match.osm_node.node_id)
        matches_by_pair[(source_key, osm_id)] = match
        matches_by_source.setdefault(source_key, []).append(match)
        matches_by_osm.setdefault(osm_id, []).append(match)
    duplicates, units = {}, []
    for row in bundle["groups"]:
        if row["side"] == "source":
            members = [ids[key] for key in row["members"]]
            duplicates.update({member: members for member in members})
        else:
            units.append(Record(
                stop_kind=row["stop_kind"], group_kind=row.get("group_kind"),
                representative_node_id=row["representative_node_id"],
                members=[Record(**member) for member in row["members"]],
            ))
    source_problems, osm_problems = {}, {}
    for row in bundle["problems"]:
        problem = Record(problem_type=row["problem_type"], priority=row["priority"])
        # A general detection can add diagnostics beyond embedded match rows.
        # With both sides specified, apply only to existing indicated pairs;
        # a detection on one side applies to that entity's existing matches.
        source_keys, osm_ids = row.get("source_keys", []), row.get("osm_ids", [])
        if source_keys and osm_ids:
            affected = [matches_by_pair[(key, str(node_id))]
                        for key in source_keys for node_id in osm_ids
                        if (key, str(node_id)) in matches_by_pair]
        elif source_keys:
            affected = [match for key in source_keys for match in matches_by_source.get(key, [])]
        else:
            affected = [match for node_id in osm_ids for match in matches_by_osm.get(str(node_id), [])]
        for match in affected:
            if not any(p.problem_type == problem.problem_type and p.priority == problem.priority for p in match.problems):
                match.problems.append(problem)
        if not row.get("osm_ids"):
            for key in row.get("source_keys", []):
                source_problems.setdefault(key, []).append(problem)
        if not row.get("source_keys"):
            for node_id in row.get("osm_ids", []):
                osm_problems.setdefault(str(node_id), []).append(problem)
    unmatched_source, unmatched_osm = [], []
    source_map, osm_map, isolated_source, isolated_osm, effectively_matched = {}, {}, set(), set(), set()
    for row in bundle["unmatched"]:
        if row["side"] == "source":
            node = sources[row["key"]]
            unmatched_source.append(node)
            isolated = bool(row.get("isolated"))
            source_map[id(node)] = {
                "is_isolated": isolated, "match_type": "no_nearby_counterpart" if isolated else None,
                "problems": source_problems.get(row["key"], []),
            }
            if isolated:
                isolated_source.add(node.sloid)
        else:
            node = osm[row["key"]]
            unmatched_osm.append(node)
            osm_map[id(node)] = osm_problems.get(str(node.node_id), [])
            if row.get("isolated"):
                isolated_osm.add(str(node.node_id))
            if row.get("effectively_matched"):
                effectively_matched.add(str(node.node_id))
    extensions = {row["kind"]: row["value"] for row in bundle["extensions"]}
    routes = _project_routes({row["kind"]: row["value"] for row in bundle["routes"]}, ids)
    result = Record(
        matched=matches, unmatched_atlas=unmatched_source, unmatched_osm=unmatched_osm,
        duplicate_sloid_map=duplicates, osm_stop_units=units, all_osm_nodes=list(osm.values()),
        effectively_matched_osm_ids=effectively_matched, isolated_osm_ids=isolated_osm,
        osm_node_routes=extensions.get("route_evidence", {}).get("osm", {}),
        gtfs_stops=extensions.get("gtfs_stops", []), gtfs_atlas_state=extensions.get("gtfs_atlas_state", []),
        gtfs_atlas_stats=extensions.get("gtfs_atlas_stats", {}),
        quality_metrics=extensions.get("quality_metrics", {}),
        atlas_filtering=extensions.get("atlas_filtering", {}),
    )
    problems = {
        "problem_ctx": Record(duplicate_osm_group_map=extensions.get("duplicate_osm_group_map", {})),
        "matched_problem_map": {id(match): match.problems for match in matches},
        "unmatched_atlas_problem_map": source_map, "unmatched_osm_problem_map": osm_map,
        "no_nearby_osm_sloids": isolated_source,
    }
    return result, problems, {"route_write_payload": routes}
