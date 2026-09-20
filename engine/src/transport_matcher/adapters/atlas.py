"""Swiss ATLAS normalization and its source-specific duplicate policy."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import pandas as pd

from transport_matcher.core.models import Reference, SourceStop
from transport_matcher.core.state import SourceState
from .route_products import scope_source_stop_keys, source_route_evidence


def atlas_records(frame: pd.DataFrame, *, namespace: str = 'atlas') -> list[SourceStop]:
    """Convert Swiss columns to generic source records, preserving native identity."""
    required = {'sloid', 'wgs84North', 'wgs84East'}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f'ATLAS input lacks required columns: {sorted(missing)}')
    def text(value):
        return '' if pd.isna(value) else str(value).strip()
    records = []
    for row in frame.to_dict('records'):
        source_id = text(row.get('sloid'))
        if not source_id:
            raise ValueError('ATLAS input has an empty SLOID')
        uic = text(row.get('number'))
        records.append(SourceStop(
            namespace=namespace, source_id=source_id,
            lat=float(row['wgs84North']), lon=float(row['wgs84East']),
            name=text(row.get('designationOfficial')),
            platform_code=text(row.get('designation')), station_ref=uic,
            operator=text(row.get('servicePointBusinessOrganisationAbbreviationEn')),
            operator_id=text(row.get('servicePointBusinessOrganisation')),
            operator_name=text(row.get('servicePointBusinessOrganisationDescriptionEn')),
            references=tuple([Reference('sloid', source_id, 'stop')] + ([Reference('uic', uic, 'station')] if uic else [])),
            extensions={'switzerland': {'sloid': source_id}},
        ))
    return records


def atlas_state(records: list[SourceStop], route_data: dict | None = None) -> SourceState:
    groups = defaultdict(list)
    for stop in records:
        if stop.station_ref and stop.platform_code:
            groups[(stop.station_ref, stop.platform_code)].append(stop.key)
    duplicate_keys = {}
    for group in groups.values():
        if len(group) > 1:
            members = sorted(group)
            duplicate_keys.update({key: members for key in members})
    normalized_routes = scope_source_stop_keys(route_data or {}, {stop.source_id: stop.key for stop in records})
    known_keys = {stop.key for stop in records}
    evidence = {key: value for key, value in source_route_evidence(normalized_routes).items() if key in known_keys}
    return SourceState(records, duplicate_key_map=duplicate_keys, route_evidence_by_key=evidence)


def read_atlas(path: str | Path, *, route_data: dict | None = None, namespace: str = 'atlas') -> SourceState:
    return atlas_state(atlas_records(pd.read_csv(path, sep=';', dtype=str), namespace=namespace), route_data)
