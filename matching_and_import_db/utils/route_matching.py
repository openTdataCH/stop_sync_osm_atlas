"""Shared route-alignment helpers for stop matching and analysis."""

from __future__ import annotations

from typing import Iterable

from matching_and_import_db.route_state import RouteState
from matching_and_import_db.utils.route_id import normalize_route_id


def _normalize_direction_id(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() == 'nan':
        return None
    return text


def _normalize_text_values(values: Iterable[str] | None) -> set[str]:
    if not values:
        return set()
    return {
        str(value).strip()
        for value in values
        if value is not None and str(value).strip()
    }


def build_atlas_gtfs_tokens(atlas_route_evidence: dict[str, list] | None) -> set[tuple[str, str]]:
    tokens: set[tuple[str, str]] = set()

    for entry in (atlas_route_evidence or {}).get('gtfs', []):
        direction_id = _normalize_direction_id(entry.get('direction_id'))
        if direction_id is None:
            continue

        route_id = entry.get('route_id')
        if route_id:
            route_id = str(route_id).strip()
            if route_id:
                tokens.add((route_id, direction_id))
                normalized = normalize_route_id(route_id)
                if normalized:
                    tokens.add((normalized, direction_id))

        route_id_normalized = entry.get('route_id_normalized')
        if route_id_normalized:
            route_id_normalized = str(route_id_normalized).strip()
            if route_id_normalized:
                tokens.add((route_id_normalized, direction_id))

    return tokens


def build_atlas_direction_names(atlas_route_evidence: dict[str, list] | None) -> set[str]:
    return _normalize_text_values(
        entry.get('direction_name')
        for entry in (atlas_route_evidence or {}).get('gtfs', [])
    )


def build_osm_gtfs_tokens(
    node_routes: list[dict] | None,
    route_state: RouteState | None = None,
) -> set[tuple[str, str]]:
    tokens: set[tuple[str, str]] = set()
    route_state = route_state or RouteState.get_instance()

    for route_entry in node_routes or []:
        direction_id = _normalize_direction_id(route_entry.get('direction_id', '0'))
        if direction_id is None:
            continue

        osm_rel_id = route_entry.get('relation_id')
        if osm_rel_id:
            atlas_route_id = route_state.get_atlas_route(str(osm_rel_id))
            if atlas_route_id:
                atlas_route_id = str(atlas_route_id).strip()
                if atlas_route_id:
                    tokens.add((atlas_route_id, direction_id))
                    normalized = normalize_route_id(atlas_route_id)
                    if normalized:
                        tokens.add((normalized, direction_id))

        gtfs_route_id = route_entry.get('gtfs_route_id')
        if gtfs_route_id:
            gtfs_route_id = str(gtfs_route_id).strip()
            if gtfs_route_id:
                tokens.add((gtfs_route_id, direction_id))
                normalized = normalize_route_id(gtfs_route_id)
                if normalized:
                    tokens.add((normalized, direction_id))

    return tokens


def classify_route_alignment(
    atlas_route_evidence: dict[str, list] | None,
    osm_node_routes: list[dict] | None,
    osm_direction_names: Iterable[str] | None,
    route_state: RouteState | None = None,
) -> str:
    """Return the strongest alignment signal between one ATLAS stop and one OSM node.

    Possible results:
    - ``token_match``
    - ``token_contradiction``
    - ``direction_match``
    - ``direction_contradiction``
    - ``inconclusive``
    """
    atlas_tokens = build_atlas_gtfs_tokens(atlas_route_evidence)
    osm_tokens = build_osm_gtfs_tokens(osm_node_routes, route_state=route_state)
    if atlas_tokens and osm_tokens:
        if atlas_tokens & osm_tokens:
            return 'token_match'
        return 'token_contradiction'

    atlas_direction_names = build_atlas_direction_names(atlas_route_evidence)
    osm_direction_names = _normalize_text_values(osm_direction_names)
    if atlas_direction_names and osm_direction_names:
        if atlas_direction_names & osm_direction_names:
            return 'direction_match'
        return 'direction_contradiction'

    return 'inconclusive'