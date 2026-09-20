# Matching Result Bundle — Schema 1

A bundle is an immutable directory containing `manifest.json` and nine UTF-8 JSON Lines files compressed with gzip. Each line is one JSON object. Empty sections are present as empty gzip streams. No Python pickle, ORM objects, source file paths required for reading, or database credentials cross the boundary.

The package version (`engine_version`) and file interface (`schema_version`) are independent. Schema 1 readers reject unsupported schema versions. Additive optional metadata may be ignored; changing the meaning or required shape of a field requires a new schema version and consumer support. The example fixture in the review repo, `tests/fixtures/result-v1`, is a consumer compatibility fixture.

## Manifest

```json
{
  "schema_version": 1,
  "engine_version": "0.1.0",
  "run_id": "a-unique-run-identifier",
  "generated_at": "2026-09-11T12:00:00+00:00",
  "profile_id": "generic",
  "metadata": {
    "capabilities": ["stops", "problems"],
    "profile": {},
    "inputs": [],
    "summary": {}
  },
  "files": {
    "source_stops": {
      "name": "source_stops.jsonl.gz",
      "rows": 2,
      "bytes": 123,
      "sha256": "sha256-of-the-compressed-file"
    }
  }
}
```

The example abbreviates `files`: all nine entries listed below are required. File names are fixed and cannot contain paths. `bytes` and `sha256` describe compressed bytes; `rows` counts decoded objects. Input content fingerprints, attribution, available capabilities and the complete profile configuration belong in `metadata`. The source adapters provide provenance for the inputs they actually use.

## Records

| Section | Required meaning and principal fields |
|---|---|
| `source_stops` | One row per source identity: `key`, `namespace`, `source_id`, `lat`, `lon`, `name`, `platform_code`, `station_ref`, `operator`, `operator_id`, `operator_name`, `references`, `parent_id`, `stop_kind`, `extensions`. |
| `osm_nodes` | Supported positioned OSM elements: `key`, `node_id`, `element_type`, `lat`, `lon`, `tags`, projected tag fields including `name`, `local_ref`, `uic_ref`, `uic_name`, `public_transport`, `railway`, `amenity`, `aerialway`, `network`, `operator`, plus optional normalized `station_reference`. |
| `matches` | One row per source/OSM pair: `source_key`, `osm_key`, `method`, `distance_m`, `notes`, `evidence`, `problems`. |
| `unmatched` | `side` (`source` or `osm`), entity `key`, boolean `isolated`; OSM rows also include boolean `effectively_matched`. |
| `groups` | Source duplicate groups and OSM physical stop units, described below. |
| `problems` | Stable `problem_id`, `problem_type`, priority 1–3, affected `source_keys` and `osm_ids`, structured `evidence`. |
| `routes` | `{ "kind": "section-name", "value": ... }` entries for complete route comparison structures. |
| `extensions` | `{ "kind": "extension-name", "value": ... }` entries for source-specific details and additional diagnostics. |
| `diagnostics` | Machine-readable diagnostic `code` and stage/reason or other explanatory fields; includes missing optional route evidence. |

Source keys equal `namespace + ':' + source_id`; namespaces contain no colon. `references` is an array of `{namespace, value, scope}` objects. Identical raw IDs from different feeds remain distinct. Coordinates are finite WGS84 latitude/longitude; `(0, 0)` is valid, not a missing-data sentinel.

OSM keys include type: `osm:node:123`, `osm:way:123`, `osm:relation:123`. Schema 1 preserves the existing adapter's `node_id` convention: ways use `way_123` and relations use `relation_123` so grouped member references remain unambiguous. `element_type` and `key` preserve the actual OSM identity. Positioned station ways retain the adapter's representative point; this format does not imply full polygon geometry conflation.

`station_reference` is an optional normalized value selected by the profile's `osm_station_ref_tag`. It is separate from the original `tags` and projected `uic_ref`, which are preserved. Consumers displaying source data should use the original tag fields; matching analysis can inspect the normalized reference alongside the exported profile configuration. Older schema-1 fixtures may omit this optional field.

A match links existing entities and has a non-negative finite distance. Multiple links from either side are permitted where an enabled policy accepts them. Repeated identical pairs are invalid. Every entity appears in either matches or unmatched, never both. `effectively_matched` records a trio middle whose two sides were matched; it does not invent a source match for that middle.

## Groups and problems

A source group has `side: "source"`, representative `key`, `kind: "duplicate"`, and a `members` array of source keys from the same dataset. Groups are disjoint.

An OSM group has `side: "osm"`, `stop_kind` (`single`, `pair`, `trio`), `group_kind`, `representative_node_id`, and `members` containing `node_id`/`member_role`. Valid roles are `single`; `pair_a`/`pair_b`; or `trio_middle`/two `trio_side` members. Every positioned OSM element belongs to exactly one stop unit.

Matched `problems` contain problem code, priority and duplicate flags. The top-level problem section also contains stable affected-entity keys and structured evidence. A problem ID is based on its code and affected entities; evidence can change without changing that identity. A future review workflow should compare the evidence when deciding whether a prior review still applies.

## Routes and extensions

Schema 1 route section names are `atlas_line_families`, `osm_route_relations`, `line_families`, `itineraries`, `stop_calls`, `line_family_matches`, `itinerary_matches`, and summary counters such as `matched_routes` and `skipped_sloids`. The `atlas_*` and `*_sloid` names in this initial route projection preserve the original app schema; they represent the configured source side even for a generic GTFS feed. Source reference values are always engine source keys. Consumers translate these names to their own storage model.

Families, itineraries, calls and their matches have local integer IDs valid within that bundle. Itineraries refer to family IDs; ordered calls refer to itinerary IDs. Stop calls carry explicit `source_sloid`/JSON-encoded `source_sloid_variants` or `source_node_id`, position, label and sequence. Family/itinerary match records refer to their matching source and OSM sides. These IDs are not stable review identities across runs; use source entity keys for that purpose. The detailed route record fields are defined by the pure producer in `src/transport_matcher/routes.py` and validated by `results/validation.py`.

Built-in extensions:

- `route_evidence`: source route memberships, OSM route memberships and OSM direction names used during matching.
- `duplicate_osm_group_map`: diagnostic duplicate membership, distinct from physical stop units.
- `quality_metrics`: computed matching quality summaries.
- `gtfs_stops`, `gtfs_atlas_state`, `gtfs_atlas_stats`, `atlas_filtering`: optional Swiss identity and acquisition details.
- `gtfs_source`: optional generic-feed source details.

Capability names used by the review application are `routes` and `gtfs_identity`. Dataset runners advertise them only when the corresponding route records or Swiss GTFS identity payload are available; core capabilities include `stops` and `problems`.

Route and extension `value` fields may contain a complete list, so one JSONL line can represent an entire named collection. Schema 1 streams the top-level entity/match/problem rows, but route/extension collections are decoded as whole values. Consumers should account for that memory use when selecting an input size.

The application must not rebuild missing optional extensions from local raw files. Capability-aware deployments hide unsupported source-specific views.

## Publication and consumer guarantees

The producer validates the complete domain result, writes a temporary directory, validates serialized references/hashes/counts, then publishes the directory with an exclusive rename. Existing destinations are rejected, including concurrent attempts. Exclusive atomic publication is supported on Linux with `renameat2`, macOS with `renamex_np`, and Windows; unsupported platforms fail before publication. A failed write is never presented as a completed result.

The consumer independently verifies schema, file integrity and entity references before preparing insert rows. It stages rows under actual PostGIS constraints and transactionally publishes the snapshot. A database schema change does not automatically require a bundle schema change.
