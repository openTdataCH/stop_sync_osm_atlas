from matching_and_import_db.database import importer as importer_mod
from matching_and_import_db.models import AtlasNode, MatchingOutput


class _DummyProblemContext:
    duplicate_osm_group_map = {}

    def nearest_osm_distance(self, *_args, **_kwargs):
        return None


def test_build_fast_insert_payloads_normalizes_blank_atlas_operator_abbr(monkeypatch):
    monkeypatch.setattr(importer_mod, 'run_problem_pipeline', lambda *args, **kwargs: [])
    monkeypatch.setattr(importer_mod, '_build_gtfs_insert_payloads', lambda: ([], []))

    atlas_node = AtlasNode(
        sloid='ch:1:sloid:test',
        lat=47.0,
        lon=8.0,
        uic_ref='8500000',
        designation='1',
        designation_official='Test Stop',
        business_org_abbr='   ',
        business_org_id='',
        business_org_name='',
    )

    result = MatchingOutput(
        matched=[],
        unmatched_atlas=[atlas_node],
        unmatched_osm=[],
        duplicate_sloid_map={},
        osm_stop_units=[],
        all_osm_nodes=[],
    )

    payload = importer_mod.build_fast_insert_payloads(
        result,
        {
            'problem_ctx': _DummyProblemContext(),
            'matched_problem_map': {},
            'unmatched_atlas_problem_map': {},
            'unmatched_osm_problem_map': {},
        },
        route_artifacts={
            'all_route_data': {},
            'route_write_payload': {
                'route_osm_stops': [],
                'route_atlas_stops': [],
                'routes_matched': [],
                'atlas_routes': [],
                'atlas_route_directions': [],
                'osm_routes': [],
                'osm_route_tags': [],
                'route_problems': [],
                'matched_routes': 0,
            },
        },
    )

    assert payload['atlas_stops'][0]['atlas_business_org_abbr'] is None
    assert payload['atlas_operators'] == []