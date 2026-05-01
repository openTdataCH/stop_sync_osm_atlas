"""Unit tests for the current matching pipeline API."""

from __future__ import annotations

from collections import defaultdict

import pandas as pd
import pytest

from matching_and_import_db.models import AtlasNode, OsmNode
from matching_and_import_db.pipeline import MatchingContext, run_pipeline
from matching_and_import_db.predicates import BasePredicate
from matching_and_import_db.predicates.distance_matching import (
    NearestDistancePredicate,
    bipartite_match,
    bipartite_match_max_cardinality,
    GroupProximityPredicate,
)
from matching_and_import_db.predicates.exact_matching import ExactUicPredicate
from matching_and_import_db.predicates.name_matching import NameMatchPredicate
from matching_and_import_db.predicates.trio_distance_matching import TrioDistanceMatchingPredicate
from matching_and_import_db.predicates.route_matching_gtfs import RouteMatchPredicate
from matching_and_import_db.orchestrator import DEFAULT_PIPELINE
from matching_and_import_db.state import AtlasState, OsmState
from matching_and_import_db.utils.common import haversine_distance
from matching_and_import_db.utils.route_id import normalize_route_id


def _atlas_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _atlas_row(
    sloid: str,
    number: str,
    designation: str,
    designation_official: str,
    lat: float,
    lon: float,
) -> dict:
    return {
        'sloid': sloid,
        'number': number,
        'designation': designation,
        'designationOfficial': designation_official,
        'wgs84North': lat,
        'wgs84East': lon,
        'servicePointBusinessOrganisationAbbreviationEn': 'TEST',
    }


def _osm_entry(
    node_id: str,
    lat: float,
    lon: float,
    *,
    name: str | None = None,
    uic_ref: str | None = None,
    uic_name: str | None = None,
    local_ref: str | None = None,
    public_transport: str | None = 'stop_position',
    railway: str | None = None,
    aerialway: str | None = None,
) -> dict:
    tags: dict[str, str | None] = {}
    if public_transport is not None:
        tags['public_transport'] = public_transport
    if name is not None:
        tags['name'] = name
    if uic_name is not None:
        tags['uic_name'] = uic_name
    if uic_ref is not None:
        tags['uic_ref'] = uic_ref
    if railway is not None:
        tags['railway'] = railway
    if aerialway is not None:
        tags['aerialway'] = aerialway
    return {
        'node_id': node_id,
        'lat': lat,
        'lon': lon,
        'local_ref': local_ref,
        'tags': tags,
    }


def _build_ctx(
    atlas_rows: list[dict],
    osm_entries: list[dict],
    *,
    duplicate_sloid_map: dict[str, list[str]] | None = None,
    node_routes: dict[str, list[dict]] | None = None,
) -> MatchingContext:
    atlas_state = AtlasState(
        atlas_df=_atlas_df(atlas_rows),
        duplicate_sloid_map=duplicate_sloid_map or {},
        routes_by_sloid={},
    )

    xml_nodes = {(entry['lat'], entry['lon']): entry for entry in osm_entries}
    uic_ref_dict: dict[str, list[dict]] = defaultdict(list)
    name_index: dict[str, list[dict]] = defaultdict(list)
    for entry in osm_entries:
        tags = entry.get('tags', {})
        if tags.get('uic_ref'):
            uic_ref_dict[tags['uic_ref']].append(entry)
        if tags.get('name'):
            name_index[tags['name']].append(entry)

    osm_state = OsmState(
        xml_nodes=xml_nodes,
        uic_ref_dict=dict(uic_ref_dict),
        name_index=dict(name_index),
        node_routes=node_routes or {},
    )
    return MatchingContext(atlas=atlas_state, osm=osm_state, max_distance=50.0)


class SingleCommitPredicate(BasePredicate):
    def __init__(self, match_type: str, atlas_index: int, osm_id: str):
        super().__init__(name=match_type)
        self.match_type = match_type
        self.atlas_index = atlas_index
        self.osm_id = osm_id

    def run(self, ctx: MatchingContext) -> None:
        unmatched = ctx.atlas.get_unmatched_records()
        atlas_entry = unmatched[self.atlas_index]
        osm_entry = next(
            ctx.osm._wrap_entity(node_dict)
            for node_dict in ctx.osm._all_nodes.values()
            if node_dict['node_id'] == self.osm_id
        )
        ctx.commit(atlas_entry, osm_entry, self.match_type, 0.0, 'test')


class TestUtils:
    def test_haversine_distance_same_point(self):
        assert haversine_distance(47.0, 8.0, 47.0, 8.0) == pytest.approx(0.0, abs=0.001)

    def test_normalize_route_id(self):
        assert normalize_route_id('route-j25') == 'route-jXX'
        assert normalize_route_id('route-j1-j2') == 'route-jXX-jXX'
        assert normalize_route_id('plain-route') == 'plain-route'

    def test_is_osm_station(self):
        assert OsmNode('n1', 47.0, 8.0, None, None, None, None, '', '', 'station', None, None, None, {}).is_station is True
        assert OsmNode('n2', 47.0, 8.0, None, None, None, None, '', '', 'stop_position', None, None, None, {}).is_station is False
        assert OsmNode('n3', 47.0, 8.0, None, None, None, None, '', '', None, None, None, 'station', {}).is_station is False


class TestDefaultPipeline:
    def test_default_pipeline_runs_full_nearest_distance_sequence(self):
        nearest_predicates = [
            predicate for predicate in DEFAULT_PIPELINE
            if isinstance(predicate, NearestDistancePredicate)
        ]

        assert [
            (predicate.mode, predicate.pass_label)
            for predicate in nearest_predicates
        ] == [
            ('single', 'first'),
            ('ratio', 'first'),
            ('single', 'second'),
        ]


class TestBipartiteMatch:
    def test_equal_size_conflict_free(self):
        atlas = [
            AtlasNode('a1', 47.0, 8.0, 'u1', '1', 'A', 'T'),
            AtlasNode('a2', 47.0005, 8.0005, 'u1', '2', 'A', 'T'),
        ]
        osm = [
            OsmNode('o1', 47.0001, 8.0001, None, 'A', None, 'u1', '', '', 'stop_position', None, None, None, {}),
            OsmNode('o2', 47.0006, 8.0006, None, 'A', None, 'u1', '', '', 'stop_position', None, None, None, {}),
        ]

        pairs = bipartite_match(atlas, osm, max_distance=100)
        assert len(pairs) == 2

    def test_unequal_size_returns_empty(self):
        atlas = [AtlasNode('a1', 47.0, 8.0, 'u1', '1', 'A', 'T')]
        osm = [
            OsmNode('o1', 47.0001, 8.0001, None, 'A', None, 'u1', '', '', 'stop_position', None, None, None, {}),
            OsmNode('o2', 47.1, 8.1, None, 'A', None, 'u1', '', '', 'stop_position', None, None, None, {}),
        ]

        assert bipartite_match(atlas, osm, max_distance=100) == []

    def test_max_cardinality_allows_partial_matching(self):
        atlas = [
            AtlasNode('a1', 47.0000, 8.0000, 'u1', '1', 'A', 'T'),
            AtlasNode('a2', 47.0005, 8.0005, 'u1', '2', 'A', 'T'),
            AtlasNode('a3', 47.0100, 8.0100, 'u1', '3', 'A', 'T'),
        ]
        osm = [
            OsmNode('o1', 47.0001, 8.0001, None, 'A', None, 'u1', '', '', 'stop_position', None, None, None, {}),
            OsmNode('o2', 47.0006, 8.0006, None, 'A', None, 'u1', '', '', 'stop_position', None, None, None, {}),
        ]

        pairs = bipartite_match_max_cardinality(atlas, osm, max_distance=100)
        assert len(pairs) == 2


class TestPipelineRunner:
    def test_empty_predicates_returns_all_unmatched(self):
        ctx = _build_ctx(
            [_atlas_row('s1', 'u1', '1', 'Stop 1', 47.0, 8.0)],
            [_osm_entry('o1', 47.0, 8.0, uic_ref='u1', name='Stop 1')],
        )

        output = run_pipeline([], ctx)

        assert output.matched == []
        assert [node.sloid for node in output.unmatched_atlas] == ['s1']

    def test_multiple_predicates_chain(self):
        ctx = _build_ctx(
            [
                _atlas_row('s1', 'u1', '1', 'Stop 1', 47.0, 8.0),
                _atlas_row('s2', 'u2', '2', 'Stop 2', 47.1, 8.1),
            ],
            [
                _osm_entry('o1', 47.0, 8.0, uic_ref='u1', name='Stop 1'),
                _osm_entry('o2', 47.1, 8.1, uic_ref='u2', name='Stop 2'),
            ],
        )

        output = run_pipeline(
            [
                SingleCommitPredicate('pred_a', 0, 'o1'),
                SingleCommitPredicate('pred_b', 0, 'o2'),
            ],
            ctx,
        )

        assert [record.match_type for record in output.matched] == ['pred_a', 'pred_b']
        assert len(output.unmatched_atlas) == 0


class TestCurrentPredicates:
    def test_exact_uic_predicate_single_candidate(self):
        ctx = _build_ctx(
            [_atlas_row('s1', '8503000', '1', 'Zürich HB', 47.3769, 8.5417)],
            [_osm_entry('osm_1', 47.3770, 8.5418, uic_ref='8503000', name='Zürich HB')],
        )

        ExactUicPredicate().run(ctx)

        assert [(record.atlas_node.sloid, record.osm_node.node_id, record.match_type) for record in ctx.all_matches] == [
            ('s1', 'osm_1', 'exact')
        ]
        expected_dist = haversine_distance(47.3769, 8.5417, 47.3770, 8.5418)
        assert ctx.all_matches[0].distance_m == pytest.approx(expected_dist, abs=0.001)

    def test_name_match_predicate_refines_by_local_ref(self):
        ctx = _build_ctx(
            [_atlas_row('s1', '8503000', '2', 'Zürich HB', 47.3769, 8.5417)],
            [
                _osm_entry('osm_a', 47.3770, 8.5418, name='Zürich HB', local_ref='1'),
                _osm_entry('osm_b', 47.3771, 8.5419, name='Zürich HB', local_ref='2'),
            ],
        )

        NameMatchPredicate().run(ctx)

        assert len(ctx.all_matches) == 1
        assert ctx.all_matches[0].osm_node.node_id == 'osm_b'
        assert ctx.all_matches[0].match_type == 'name'

    def test_route_match_predicate_matches_by_gtfs_tokens(self):
        ctx = _build_ctx(
            [_atlas_row('s1', '8503000', '1', 'Zürich HB', 47.3769, 8.5417)],
            [_osm_entry('osm_1', 47.3770, 8.5418, uic_ref='8503000', name='Zürich HB')],
            node_routes={
                'osm_1': [
                    {'gtfs_route_id': '91-9-I-j26-1', 'direction_id': '0', 'route_name': 'Tram 9'},
                ],
            },
        )
        ctx.atlas._routes_by_sloid = {
            's1': {
                'gtfs': [
                    {
                        'route_id_normalized': '91-9-I-jXX-1',
                        'direction_id': '0',
                        'direction_name': 'Heuried -> Hirzenbach',
                    },
                ],
            }
        }

        RouteMatchPredicate().run(ctx)

        assert len(ctx.all_matches) == 1
        assert ctx.all_matches[0].osm_node.node_id == 'osm_1'
        assert ctx.all_matches[0].match_type == 'route_gtfs_gtfs'

    def test_group_proximity_partial_matching_leaves_far_outlier_unmatched(self):
        ctx = _build_ctx(
            [
                _atlas_row('s1', 'u1', '1', 'Hub', 47.0000000, 8.0000000),
                _atlas_row('s2', 'u1', '2', 'Hub', 47.0005000, 8.0005000),
                _atlas_row('s3', 'u1', '3', 'Hub', 47.0050000, 8.0050000),
            ],
            [
                _osm_entry('o1', 47.0000600, 8.0000600, uic_ref='u1', uic_name='Hub', name='Hub'),
                _osm_entry('o2', 47.0005600, 8.0005600, uic_ref='u1', uic_name='Hub', name='Hub'),
            ],
        )

        GroupProximityPredicate().run(ctx)

        matched_sloids = {r.atlas_node.sloid for r in ctx.all_matches}
        assert matched_sloids == {'s1', 's2'}
        assert ctx.all_matches[0].match_type.startswith('distance_matching_1_')
        assert ctx.all_matches[1].match_type.startswith('distance_matching_1_')
        assert 's3' not in matched_sloids


class TestStaleCandidateRegression:
    def test_nearest_distance_does_not_reuse_consumed_group_representative(self):
        ctx = _build_ctx(
            [
                _atlas_row('s1', 'u1', '', 'Stop', 47.0000000, 8.0000000),
                _atlas_row('s2', 'u1', '', 'Stop', 47.0002100, 8.0002100),
                _atlas_row('s3', 'u1', '', 'Stop', 47.0003250, 8.0003250),
            ],
            [
                _osm_entry('rep_a', 47.0000100, 8.0000100, uic_ref='u1', name='Stop', railway='tram_stop'),
                _osm_entry('sib_a', 47.0000150, 8.0000150, uic_ref='u1', name='Stop'),
                _osm_entry('rep_b', 47.0002200, 8.0002200, uic_ref='u1', name='Stop', railway='tram_stop'),
                _osm_entry('sib_b', 47.0002250, 8.0002250, uic_ref='u1', name='Stop'),
            ],
        )

        ctx.osm._group_representative = {
            'sib_a': 'rep_a',
            'sib_b': 'rep_b',
        }
        ctx.osm._group_siblings = {
            'rep_a': ('osm_pair_tram', [ctx.osm._to_osm_node(ctx.osm._all_nodes[(47.0000150, 8.0000150)])]),
            'rep_b': ('osm_pair_tram', [ctx.osm._to_osm_node(ctx.osm._all_nodes[(47.0002250, 8.0002250)])]),
        }

        run_pipeline(
            [
                NearestDistancePredicate(mode='single', pass_label='first'),
                NearestDistancePredicate(mode='ratio', pass_label='first'),
                NearestDistancePredicate(mode='single', pass_label='second'),
            ],
            ctx,
        )

        matched_pairs = [(record.atlas_node.sloid, record.osm_node.node_id, record.match_type) for record in ctx.all_matches]

        assert any(
            sloid == 's2' and osm_node_id == 'rep_b' and match_type in {'distance_matching_3a', 'distance_matching_3b', 'distance_matching_3a_second_pass'}
            for sloid, osm_node_id, match_type in matched_pairs
        )
        assert ('s3', 'rep_b', 'distance_matching_3a') not in matched_pairs
        assert ('s3', 'rep_b', 'distance_matching_3a_second_pass') not in matched_pairs
        assert 's3' not in {record.atlas_node.sloid for record in ctx.all_matches}

        assert haversine_distance(47.0003250, 8.0003250, 47.0002200, 8.0002200) < 50


class TestOsmGroupingPolicy:
    def test_uic_grouping_uses_perfect_count_branch_with_15m_reciprocal_pairs(self):
        ctx = _build_ctx(
            [
                _atlas_row('s1', 'u_pc', '1', 'Stop PC', 47.0, 8.0),
                _atlas_row('s2', 'u_pc', '2', 'Stop PC', 47.0001, 8.0001),
                _atlas_row('s3', 'u_pc', '3', 'Stop PC', 47.0002, 8.0002),
            ],
            [
                _osm_entry('platform_1', 47.0000000, 8.0000000, uic_ref='u_pc', public_transport='platform'),
                _osm_entry('platform_2', 47.0005000, 8.0005000, uic_ref='u_pc', public_transport='platform'),
                _osm_entry('platform_3', 47.0010000, 8.0010000, uic_ref='u_pc', public_transport='platform'),
                _osm_entry('stop_1', 47.0000900, 8.0000900, uic_ref='u_pc', public_transport='stop_position'),
                _osm_entry('stop_2', 47.0005900, 8.0005900, uic_ref='u_pc', public_transport='stop_position'),
                _osm_entry('stop_3', 47.0010900, 8.0010900, uic_ref='u_pc', public_transport='stop_position'),
            ],
        )

        ctx.osm.build_groups(atlas_uic_counts={'u_pc': 3})

        assert len(ctx.osm._group_representative) == 3
        assert all(
            ctx.osm._group_siblings[rep_id][0] == 'osm_pair_uic_equal_15m'
            for rep_id in ['platform_1', 'platform_2', 'platform_3']
            if rep_id in ctx.osm._group_siblings
        )

    def test_uic_perfect_count_uses_filtered_atlas_count_only(self):
        ctx = _build_ctx(
            [
                _atlas_row('s_near_1', 'u_filtered', '1', 'Filtered Stop', 47.0000000, 8.0000000),
                _atlas_row('s_near_2', 'u_filtered', '2', 'Filtered Stop', 47.0001000, 8.0001000),
                _atlas_row('s_far_1', 'u_filtered', '3', 'Filtered Stop', 47.0100000, 8.0100000),
                _atlas_row('s_far_2', 'u_filtered', '4', 'Filtered Stop', 47.0110000, 8.0110000),
            ],
            [
                _osm_entry('platform_a', 47.0000100, 8.0000100, uic_ref='u_filtered', public_transport='platform'),
                _osm_entry('stop_a', 47.0000200, 8.0000200, uic_ref='u_filtered', public_transport='stop_position'),
                _osm_entry('platform_b', 47.0001200, 8.0001200, uic_ref='u_filtered', public_transport='platform'),
                _osm_entry('stop_b', 47.0001300, 8.0001300, uic_ref='u_filtered', public_transport='stop_position'),
            ],
        )

        # Original atlas_count is 4, but only two ATLAS rows are close to same-UIC OSM.
        ctx.osm.build_groups(
            atlas_uic_counts={'u_filtered': 4},
            atlas_uic_nearest_osm_distances={'u_filtered': [2.0, 3.0, 250.0, 270.0]},
        )

        assert len(ctx.osm._group_representative) == 2
        assert all(
            entry[0] == 'osm_pair_uic_equal_15m'
            for entry in ctx.osm._group_siblings.values()
        )

    def test_name_grouping_uses_perfect_count_branch_with_15m_reciprocal_pairs(self):
        ctx = _build_ctx(
            [
                _atlas_row('s1', 'u_name_pc', '1', 'Name PC', 47.0, 8.0),
                _atlas_row('s2', 'u_name_pc', '2', 'Name PC', 47.0001, 8.0001),
            ],
            [
                _osm_entry('platform_name_1', 47.1000000, 8.1000000, name='Name PC', uic_name='Name PC', public_transport='platform'),
                _osm_entry('platform_name_2', 47.1006000, 8.1006000, name='Name PC', uic_name='Name PC', public_transport='platform'),
                _osm_entry('stop_name_1', 47.1000800, 8.1000800, name='Name PC', uic_name='Name PC', public_transport='stop_position'),
                _osm_entry('stop_name_2', 47.1006800, 8.1006800, name='Name PC', uic_name='Name PC', public_transport='stop_position'),
            ],
        )

        ctx.osm.build_groups(
            atlas_uic_counts={'u_name_pc': 2},
            atlas_designation_to_uic={'Name PC': 'u_name_pc'},
        )

        assert len(ctx.osm._group_representative) == 2
        assert all(
            entry[0] == 'osm_pair_name_equal_15m'
            for entry in ctx.osm._group_siblings.values()
        )

    def test_tram_grouping_uses_perfect_count_branch_with_15m_reciprocal_pairs(self):
        ctx = _build_ctx(
            [
                _atlas_row('s1', 'u_tram_pc', '1', 'Tram PC', 47.0, 8.0),
                _atlas_row('s2', 'u_tram_pc', '2', 'Tram PC', 47.0001, 8.0001),
            ],
            [
                _osm_entry('tram_1', 47.2000000, 8.2000000, uic_ref='u_tram_pc', railway='tram_stop', public_transport=None),
                _osm_entry('tram_2', 47.2007000, 8.2007000, uic_ref='u_tram_pc', railway='tram_stop', public_transport=None),
                _osm_entry('stop_tram_1', 47.2000900, 8.2000900, uic_ref='u_tram_pc', public_transport='stop_position'),
                _osm_entry('stop_tram_2', 47.2007900, 8.2007900, uic_ref='u_tram_pc', public_transport='stop_position'),
            ],
        )

        ctx.osm.build_groups(atlas_uic_counts={'u_tram_pc': 2})

        assert len(ctx.osm._group_representative) == 2
        assert all(
            entry[0] == 'osm_pair_tram_equal_15m'
            for entry in ctx.osm._group_siblings.values()
        )

    def test_uic_grouping_accepts_incomplete_relaxed_pairs(self):
        ctx = _build_ctx(
            [_atlas_row('s1', 'u1', '1', 'Stop', 47.0, 8.0)],
            [
                _osm_entry('platform_1', 47.0000000, 8.0000000, uic_ref='u1', public_transport='platform'),
                _osm_entry('stop_1', 47.0000100, 8.0000100, uic_ref='u1', public_transport='stop_position'),
                _osm_entry('stop_extra', 47.0010000, 8.0010000, uic_ref='u1', public_transport='stop_position'),
            ],
        )

        ctx.osm.build_groups(atlas_uic_counts={'u1': 3})

        assert ctx.osm._group_representative == {'stop_1': 'platform_1'}
        assert ctx.osm._group_siblings['platform_1'][0] == 'osm_pair_uic'

    def test_name_grouping_accepts_incomplete_relaxed_pairs(self):
        ctx = _build_ctx(
            [_atlas_row('s1', 'u_name', '1', 'Name Stop', 47.0, 8.0)],
            [
                _osm_entry('platform_name', 47.1000000, 8.1000000, name='Name Stop', uic_name='Name Stop', public_transport='platform'),
                _osm_entry('stop_name', 47.1000100, 8.1000100, name='Name Stop', uic_name='Name Stop', public_transport='stop_position'),
                _osm_entry('stop_name_extra', 47.1010000, 8.1010000, name='Name Stop', uic_name='Name Stop', public_transport='stop_position'),
            ],
        )

        ctx.osm.build_groups(
            atlas_uic_counts={'u_name': 3},
            atlas_designation_to_uic={'Name Stop': 'u_name'},
        )

        assert ctx.osm._group_representative == {'stop_name': 'platform_name'}
        assert ctx.osm._group_siblings['platform_name'][0] == 'osm_pair_name'

    def test_tram_grouping_accepts_incomplete_relaxed_pairs_without_outlier_logic(self):
        ctx = _build_ctx(
            [_atlas_row('s1', 'u_tram', '1', 'Tram Stop', 47.0, 8.0)],
            [
                _osm_entry('tram_1', 47.2000000, 8.2000000, uic_ref='u_tram', railway='tram_stop', public_transport=None),
                _osm_entry('stop_tram_1', 47.2000100, 8.2000100, uic_ref='u_tram', public_transport='stop_position'),
                _osm_entry('stop_tram_extra', 47.2010000, 8.2010000, uic_ref='u_tram', public_transport='stop_position'),
            ],
        )

        ctx.osm.build_groups(
            atlas_uic_counts={'u_tram': 3},
            atlas_uic_nearest_osm_distances={'u_tram': [35.0, 10.0, 9.0]},
        )

        assert ctx.osm._group_representative == {'stop_tram_1': 'tram_1'}
        assert ctx.osm._group_siblings['tram_1'][0] == 'osm_pair_tram'

    def test_grouped_lookup_inherits_uic_ref_from_sibling(self):
        ctx = _build_ctx(
            [_atlas_row('s1', 'u_anchor', '1', 'Anchor Name', 47.0, 8.0)],
            [
                _osm_entry('platform_anchor', 47.0000000, 8.0000000, name='Anchor Name', public_transport='platform'),
                _osm_entry('stop_anchor', 47.0000100, 8.0000100, uic_ref='u_anchor', uic_name='Anchor Name', name='Anchor Name', public_transport='stop_position'),
            ],
        )

        ctx.osm.build_groups(
            atlas_uic_counts={'u_anchor': 1},
            atlas_designation_to_uic={'Anchor Name': 'u_anchor'},
        )

        grouped = ctx.osm.get_all_unmatched_grouped('uic_ref')
        assert 'u_anchor' in grouped
        assert any(entity.node_id == 'platform_anchor' for entity in grouped['u_anchor'])


class TestNearestDistanceMultiPass:
    def test_second_single_pass_can_match_after_ratio_consumes_competitor(self):
        ctx = _build_ctx(
            [
                _atlas_row('s_target', 'u_aerial', '', 'Aerial', 46.11343836621, 7.30420757178),
                _atlas_row('s_competitor', 'u_aerial', '', 'Aerial', 46.1136200, 7.3044000),
            ],
            [
                _osm_entry(
                    'way_208449383',
                    46.1133230,
                    7.3042299,
                    public_transport='station',
                    aerialway='station',
                ),
                _osm_entry(
                    'way_208449401',
                    46.1136516,
                    7.3044201,
                    public_transport='station',
                    aerialway='station',
                ),
            ],
        )

        run_pipeline(
            [
                NearestDistancePredicate(mode='single', pass_label='first'),
                NearestDistancePredicate(mode='ratio', pass_label='first'),
                NearestDistancePredicate(mode='single', pass_label='second'),
            ],
            ctx,
        )

        by_sloid = {record.atlas_node.sloid: record for record in ctx.all_matches}

        assert by_sloid['s_competitor'].osm_node.node_id == 'way_208449401'
        assert by_sloid['s_competitor'].match_type == 'distance_matching_3b'

        assert by_sloid['s_target'].osm_node.node_id == 'way_208449383'
        assert by_sloid['s_target'].match_type == 'distance_matching_3a_second_pass'


class TestOsmTrioMatching:
    def test_trio_commit_does_not_propagate_middle_node(self):
        ctx = _build_ctx(
            [
                _atlas_row('a1', 'u_trio', '1', 'Trio Stop', 47.3000000, 8.3000000),
                _atlas_row('a2', 'u_trio', '2', 'Trio Stop', 47.3002000, 8.3002000),
            ],
            [
                _osm_entry('side_rep', 47.3000000, 8.3000000, uic_ref='u_trio', public_transport='platform'),
                _osm_entry('middle', 47.3001000, 8.3001000, uic_ref='u_trio', public_transport='stop_position'),
                _osm_entry('side_other', 47.3002000, 8.3002000, uic_ref='u_trio', public_transport='platform'),
            ],
        )
        ctx.osm.build_groups(atlas_uic_counts={'u_trio': 2})

        rep_entity = next(e for e in ctx.osm.get_by_uic('u_trio') if e.node_id == 'side_other' or e.node_id == 'side_rep')
        atlas_entry = next(e for e in ctx.atlas.get_unmatched_records() if e.sloid == 'a1')

        ctx.commit(atlas_entry, rep_entity, 'exact', 0.0, 'test trio propagation guard')

        osm_group_prop_records = [r for r in ctx.all_matches if r.match_type == 'osm_group_propagation']
        assert osm_group_prop_records == []
        assert ctx.osm.is_used('middle') is False

    def test_trio_stage_matches_two_side_nodes_and_leaves_middle_unmatched(self):
        ctx = _build_ctx(
            [
                _atlas_row('a1', 'u_trio', '1', 'Trio Stop', 47.4000000, 8.4000000),
                _atlas_row('a2', 'u_trio', '2', 'Trio Stop', 47.4003000, 8.4003000),
            ],
            [
                _osm_entry('side_1', 47.4001000, 8.4001000, uic_ref='u_trio', public_transport='platform'),
                _osm_entry('middle', 47.4001500, 8.4001500, uic_ref='u_trio', public_transport='stop_position'),
                _osm_entry('side_2', 47.4002000, 8.4002000, uic_ref='u_trio', public_transport='platform'),
            ],
        )
        ctx.osm.build_groups(atlas_uic_counts={'u_trio': 2})

        run_pipeline([TrioDistanceMatchingPredicate(), ExactUicPredicate(), NameMatchPredicate()], ctx)

        trio_records = [r for r in ctx.all_matches if r.match_type == 'distance_matching_trio']
        matched_osm_ids = {r.osm_node.node_id for r in trio_records}

        assert len(trio_records) == 2
        assert matched_osm_ids == {'side_1', 'side_2'}
        assert ctx.osm.is_used('middle') is False
        assert 'middle' in {n.node_id for n in ctx.osm.get_unmatched_nodes()}

    def test_non_local_trio_is_not_registered_and_can_fall_back_to_pair_grouping(self):
        ctx = _build_ctx(
            [
                _atlas_row('a1', 'u_trio', '1', 'Trio Stop', 47.5000000, 8.5000000),
                _atlas_row('a2', 'u_trio', '2', 'Trio Stop', 47.5003000, 8.5003000),
            ],
            [
                _osm_entry('side_near', 47.5001100, 8.5001100, uic_ref='u_trio', public_transport='platform'),
                _osm_entry('middle', 47.5001000, 8.5001000, uic_ref='u_trio', public_transport='stop_position'),
                _osm_entry('side_far', 47.5015000, 8.5015000, uic_ref='u_trio', public_transport='platform'),
            ],
        )

        ctx.osm.build_groups(atlas_uic_counts={'u_trio': 2})

        assert ctx.osm.get_trio_representatives() == []
        assert ctx.osm._group_representative == {'middle': 'side_near'}
        assert ctx.osm._group_siblings['side_near'][0] == 'osm_pair_uic'
        assert {entity.node_id for entity in ctx.osm.get_by_uic('u_trio')} == {'side_near', 'side_far'}