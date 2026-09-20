"""Project normalized wire records onto the review application's SQL model.

Legacy ATLAS column names stay local to this consumer. Generic feeds use their
namespaced keys; the Swiss deployment retains existing SLOID URLs.
"""

from types import SimpleNamespace as Record
import json


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
    routes = {row["kind"]: row["value"] for row in bundle["routes"]}
    # Resolve exported source keys only in known source-reference fields.
    for values in routes.values():
        if isinstance(values, list):
            for row in values:
                if isinstance(row, dict):
                    for field in ("resolved_sloid", "source_sloid", "canonical_stop_key"):
                        if row.get(field) in ids:
                            row[field] = ids[row[field]]
                    for field in ("source_sloid_variants", "resolved_sloid_variants"):
                        value = row.get(field)
                        if value:
                            variants = json.loads(value) if isinstance(value, str) else value
                            mapped = [ids.get(key, key) for key in variants]
                            row[field] = json.dumps(mapped) if isinstance(value, str) else mapped
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
