from backend.importing import importer as importer_mod
from backend.importing.bundle import read_bundle
from backend.importing.projection import project_bundle
from pathlib import Path
import pytest


def test_build_fast_insert_payloads_normalizes_blank_atlas_operator_abbr():
    bundle = read_bundle(Path(__file__).resolve().parents[1] / 'tests/fixtures/result-v1')
    for row in bundle['source_stops']:
        row['operator'] = '   '
    result, problems, routes = project_bundle(bundle)
    payload = importer_mod.build_fast_insert_payloads(result, problems, routes)
    assert all(row['atlas_business_org_abbr'] is None for row in payload['atlas_stops'])
    assert payload['atlas_operators'] == []


def test_partial_database_publication_is_rejected():
    from backend.jobs.job_types import PipelineRunType
    with pytest.raises(ValueError, match='complete snapshot'):
        importer_mod.import_to_database({}, PipelineRunType.ATLAS_CACHED)


def test_validate_refresh_payloads_rejects_empty_stop_rows():
    try:
        importer_mod._validate_refresh_payloads({'stops_matched': []})
    except RuntimeError as exc:
        assert 'payload contains no stops_matched rows' in str(exc)
    else:
        raise AssertionError('Expected empty stops_matched payload to be rejected')


def test_filter_gtfs_identity_rows_drops_unknown_resolved_sloids():
    rows = importer_mod._filter_gtfs_identity_rows_to_known_sloids(
        [
            {
                'stop_id': 'stop-1',
                'resolved_sloid': 'known-sloid',
                'resolution_method': 'original_stop_id',
                'confidence': 1.0,
                'details_json': {},
            },
            {
                'stop_id': 'stop-2',
                'resolved_sloid': 'missing-sloid',
                'resolution_method': 'original_stop_id',
                'confidence': 1.0,
                'distance_m': 3.0,
                'atlas_lat': 46.0,
                'atlas_lon': 7.0,
                'details_json': {'platform_code': '1'},
            },
            {
                'stop_id': 'stop-3',
                'resolved_sloid': 'also-missing-sloid',
                'resolution_method': 'original_stop_id',
                'confidence': 1.0,
                'details_json': "{'platform_code': '2'}",
            },
        ],
        {'known-sloid'},
    )

    assert rows[0]['resolved_sloid'] == 'known-sloid'
    assert rows[1]['resolved_sloid'] is None
    assert rows[1]['resolution_method'] == 'unmatched'
    assert rows[1]['confidence'] == 0.0
    assert rows[1]['atlas_lat'] is None
    assert rows[1]['details_json']['dropped_resolved_sloid'] == 'missing-sloid'
    assert rows[2]['resolved_sloid'] is None
    assert rows[2]['details_json']['platform_code'] == '2'
    assert rows[2]['details_json']['dropped_resolved_sloid'] == 'also-missing-sloid'



def test_sql_route_projection_drops_portable_evidence_fields():
    from pathlib import Path
    from backend.importing.bundle import read_bundle
    from backend.importing.projection import project_bundle
    from backend.importing.importer import build_fast_insert_payloads
    result, problems, routes = project_bundle(read_bundle(Path(__file__).parent / 'fixtures/result-v1'))
    routes['route_write_payload']['osm_route_relations'] = [{'relation_id': '123', 'gtfs_route_id': 'R',
                                    'route_id_normalized': 'normalized-R', 'is_non_gtfs': False}]
    payload = build_fast_insert_payloads(result, problems, routes)
    assert payload['osm_route_relations'] == [{'relation_id': '123', 'gtfs_route_id': 'R'}]
    assert routes['route_write_payload']['osm_route_relations'][0]['route_id_normalized'] == 'normalized-R'
