"""Compatibility imports for the former combined OSM module.

New code should import network acquisition from
``transport_matcher.acquisition.overpass`` and route parsing from
``transport_matcher.adapters.osm_routes``.
"""
from __future__ import annotations

from pathlib import Path

from transport_matcher.acquisition import overpass as _overpass
from .osm_routes import process_osm_routes_data


OVERPASS_URL = _overpass.OVERPASS_URL
OVERPASS_USER_AGENT = _overpass.OVERPASS_USER_AGENT
OVERPASS_HEADERS = dict(_overpass.OVERPASS_HEADERS)
OVERPASS_RETRY_STATUS_CODES = _overpass.OVERPASS_RETRY_STATUS_CODES
OVERPASS_MAX_RETRIES = _overpass.OVERPASS_MAX_RETRIES
OVERPASS_RETRY_BACKOFF_SECONDS = _overpass.OVERPASS_RETRY_BACKOFF_SECONDS
time = _overpass.time


def ensure_data_dirs() -> None:
    for path in (Path("data/raw"), Path("data/processed"), Path("data/debug")):
        path.mkdir(parents=True, exist_ok=True)


def query_overpass(session=None, *, output_path="data/raw/osm_data.xml", country_code="CH", overpass_url=None):
    return _overpass.query_overpass(
        session,
        output_path=output_path,
        country_code=country_code,
        overpass_url=overpass_url or OVERPASS_URL,
        headers=OVERPASS_HEADERS,
        max_retries=OVERPASS_MAX_RETRIES,
        retry_backoff_seconds=OVERPASS_RETRY_BACKOFF_SECONDS,
    )


def main() -> None:
    process_osm_routes_data(query_overpass(), "data/processed/")


if __name__ == "__main__":
    main()
