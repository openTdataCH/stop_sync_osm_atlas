"""Shared route-alignment helpers for stop matching and analysis."""

from __future__ import annotations

from typing import Iterable

from transport_matcher.core.route_state import RouteState


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


def build_source_gtfs_tokens(source_route_evidence: dict[str, list] | None) -> set[tuple[str, str]]:
    tokens: set[tuple[str, str]] = set()

    for entry in (source_route_evidence or {}).get('gtfs', []):
        direction_id = _normalize_direction_id(entry.get('direction_id'))
        if direction_id is None:
            continue

        route_id = entry.get('route_id')
        if route_id:
            route_id = str(route_id).strip()
            if route_id:
                tokens.add((route_id, direction_id))
                normalized = entry.get('route_id_normalized')
                if normalized:
                    tokens.add((normalized, direction_id))

        route_id_normalized = entry.get('route_id_normalized')
        if route_id_normalized:
            route_id_normalized = str(route_id_normalized).strip()
            if route_id_normalized:
                tokens.add((route_id_normalized, direction_id))

    return tokens


def build_source_direction_names(source_route_evidence: dict[str, list] | None) -> set[str]:
    return _normalize_text_values(
        entry.get('direction_name')
        for entry in (source_route_evidence or {}).get('gtfs', [])
    )


def build_osm_gtfs_tokens(
    node_routes: list[dict] | None,
    route_state: RouteState | None = None,
) -> set[tuple[str, str]]:
    tokens: set[tuple[str, str]] = set()
    route_state = route_state or RouteState()

    for route_entry in node_routes or []:
        direction_id = _normalize_direction_id(route_entry.get('direction_id', '0'))
        if direction_id is None:
            continue

        osm_rel_id = route_entry.get('relation_id')
        if osm_rel_id:
            source_route_id = route_state.get_source_route(str(osm_rel_id))
            if source_route_id:
                source_route_id = str(source_route_id).strip()
                if source_route_id:
                    tokens.add((source_route_id, direction_id))
                    normalized = route_entry.get('route_id_normalized')
                    if normalized:
                        tokens.add((normalized, direction_id))

        gtfs_route_id = route_entry.get('gtfs_route_id')
        if gtfs_route_id:
            gtfs_route_id = str(gtfs_route_id).strip()
            if gtfs_route_id:
                tokens.add((gtfs_route_id, direction_id))
                normalized = route_entry.get('route_id_normalized')
                if normalized:
                    tokens.add((normalized, direction_id))

    return tokens


def classify_route_alignment(
    source_route_evidence: dict[str, list] | None,
    osm_node_routes: list[dict] | None,
    osm_direction_names: Iterable[str] | None,
    route_state: RouteState | None = None,
) -> str:
    """Return the strongest alignment signal between one source stop and one OSM node.

    Possible results:
    - ``token_match``
    - ``token_contradiction``
    - ``direction_match``
    - ``direction_contradiction``
    - ``inconclusive``
    """
    source_tokens = build_source_gtfs_tokens(source_route_evidence)
    osm_tokens = build_osm_gtfs_tokens(osm_node_routes, route_state=route_state)
    if source_tokens and osm_tokens:
        if source_tokens & osm_tokens:
            return 'token_match'
        return 'token_contradiction'

    source_direction_names = build_source_direction_names(source_route_evidence)
    osm_direction_names = _normalize_text_values(osm_direction_names)
    if source_direction_names and osm_direction_names:
        if source_direction_names & osm_direction_names:
            return 'direction_match'
        return 'direction_contradiction'

    return 'inconclusive'