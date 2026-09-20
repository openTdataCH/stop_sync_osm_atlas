"""Overpass acquisition for public-transport stops and their route relations."""
from __future__ import annotations

import os
from pathlib import Path
import time
from typing import Any


OVERPASS_URL = os.getenv("OVERPASS_API_URL", "https://overpass-api.de/api/interpreter")
OVERPASS_USER_AGENT = os.getenv(
    "OVERPASS_USER_AGENT",
    "transport-matcher/0.1 (+https://github.com/openTdataCH/stop_sync_osm_atlas)",
)
OVERPASS_HEADERS = {
    "Content-Type": "text/plain; charset=utf-8",
    "Accept": "application/osm3s+xml, text/xml, application/xml;q=0.9, */*;q=0.1",
    "User-Agent": OVERPASS_USER_AGENT,
}
OVERPASS_RETRY_STATUS_CODES = {502, 504}
OVERPASS_MAX_RETRIES = int(os.getenv("OVERPASS_MAX_RETRIES", "2"))
OVERPASS_RETRY_BACKOFF_SECONDS = float(os.getenv("OVERPASS_RETRY_BACKOFF_SECONDS", "5"))


def build_public_transport_query(country_code: str = "CH") -> str:
    """Return the Overpass QL query for an ISO 3166-1 alpha-2 area."""
    if not country_code.isalpha() or len(country_code) != 2:
        raise ValueError("country_code must be a two-letter ISO code")
    return f'''
        [out:xml][timeout:360];
        area["ISO3166-1"="{country_code.upper()}"]->.searchArea;

        (
            node(area.searchArea)["public_transport"~"platform|stop_position|station|halt|stop"];
            node(area.searchArea)["railway"="tram_stop"];
            node(area.searchArea)["amenity"="ferry_terminal"];
            node(area.searchArea)["amenity"="bus_station"];
            node(area.searchArea)["highway"="bus_stop"];
            node(area.searchArea)["railway"="halt"];
            node(area.searchArea)["railway"="station"];
            node(area.searchArea)["aerialway"="station"];
        )->.pt_nodes;

        (
            way(area.searchArea)["aerialway"="station"]["public_transport"="station"];
            way(area.searchArea)["uic_ref"];
        )->.candidate_ways;

        (
            relation(bn.pt_nodes)[type=route][route!=hiking];
            relation(bw.candidate_ways)[type=route][route!=hiking];
        )->.seed_routes;

        relation(br.seed_routes)[type=route_master]->.route_masters;

        (
            .seed_routes;
            relation(r.route_masters)[type=route][route!=hiking];
        )->.routes;

        .pt_nodes out body qt;
        .candidate_ways out body center qt;
        .routes out meta;
        .route_masters out meta;
    '''.strip()


def _raise_overpass_error(response: Any) -> None:
    preview = response.text[:400].replace("\n", " ").strip()
    raise RuntimeError(
        f"Overpass request failed ({response.status_code}) at {response.url}. "
        f"Response preview: {preview}"
    )


def query_overpass(
    session: Any = None,
    *,
    output_path: str | Path | None = "data/raw/osm_data.xml",
    country_code: str = "CH",
    overpass_url: str | None = None,
    headers: dict[str, str] | None = None,
    max_retries: int | None = None,
    retry_backoff_seconds: float | None = None,
) -> str:
    """Fetch one OSM XML snapshot; parsing is handled by adapter modules."""
    import requests

    client = session or requests
    request_body = build_public_transport_query(country_code).encode("utf-8")
    retries = OVERPASS_MAX_RETRIES if max_retries is None else max_retries
    backoff = OVERPASS_RETRY_BACKOFF_SECONDS if retry_backoff_seconds is None else retry_backoff_seconds
    response = None
    for attempt in range(retries + 1):
        response = client.post(
            overpass_url or OVERPASS_URL,
            data=request_body,
            headers=headers or OVERPASS_HEADERS,
            timeout=(30, 600),
        )
        if response.status_code == 200:
            break
        if response.status_code not in OVERPASS_RETRY_STATUS_CODES or attempt >= retries:
            _raise_overpass_error(response)
        time.sleep(backoff * (2 ** attempt))

    if response is None:
        raise RuntimeError("Overpass request did not produce a response")
    response.encoding = "utf-8"
    if output_path is not None:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(response.text, encoding="utf-8")
    return response.text
