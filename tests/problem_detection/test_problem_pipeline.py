"""
Tests for the problem detection pipeline.

Tests cover:
- Individual predicates (distance, attributes, unmatched, duplicates)
- ProblemContext construction
- Pipeline runner integration
- Edge cases (missing data, empty inputs)
"""

import pytest
from matching_process.problem_detection.context import ProblemContext
from matching_process.problem_detection.result import ProblemResult
from matching_process.problem_detection.pipeline import (
    run_problem_pipeline,
    STOP_PROBLEM_PIPELINE,
)
from matching_process.problem_detection.predicates.distance import distance_problem, _compute_priority
from matching_process.problem_detection.predicates.attributes import attributes_problem
from matching_process.problem_detection.predicates.unmatched import unmatched_problem
from matching_process.problem_detection.predicates.duplicates import duplicates_problem


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def empty_ctx():
    """A ProblemContext with no data."""
    return ProblemContext()


@pytest.fixture
def sample_base_data():
    """Minimal base_data with a few matched, unmatched_atlas, and unmatched_osm records."""
    return {
        'matched': [
            {
                'sloid': 'ch:1:sloid:100',
                'number': '8503000',
                'csv_lat': 47.3769,
                'csv_lon': 8.5417,
                'osm_node_id': 'osm_1',
                'osm_lat': 47.3770,
                'osm_lon': 8.5418,
                'osm_uic_ref': '8503000',
                'osm_local_ref': '1',
                'osm_public_transport': 'platform',
                'distance_m': 12.0,
                'match_type': 'exact_uic',
                'csv_business_org_abbr': 'SBB',
                'csv_designation_official': 'Zurich HB',
                'osm_uic_name': 'Zurich HB',
                'csv_designation': '1',
                'osm_operator': 'SBB',
            },
            {
                'sloid': 'ch:1:sloid:101',
                'number': '8503000',
                'csv_lat': 47.3768,
                'csv_lon': 8.5416,
                'osm_node_id': 'osm_2',
                'osm_lat': 47.3771,
                'osm_lon': 8.5420,
                'osm_uic_ref': '8503000',
                'osm_local_ref': '2',
                'osm_public_transport': 'platform',
                'distance_m': 40.0,
                'match_type': 'distance',
                'csv_business_org_abbr': 'BLS',
                'csv_designation_official': 'Zurich HB',
                'osm_uic_name': 'Zurich HB',
                'csv_designation': '2',
                'osm_operator': 'BLS',
            },
        ],
        'unmatched_atlas': [
            {
                'sloid': 'ch:1:sloid:200',
                'number': '8509999',
                'wgs84North': 46.0,
                'wgs84East': 7.0,
            },
        ],
        'unmatched_osm': [
            {
                'node_id': 'osm_99',
                'lat': 46.5,
                'lon': 7.5,
                'tags': {'uic_ref': '8509999', 'public_transport': 'platform'},
            },
        ],
    }


@pytest.fixture
def built_ctx(sample_base_data):
    """A ProblemContext built from sample_base_data."""
    dup_sloid_map = {'ch:1:sloid:100': ['ch:1:sloid:100', 'ch:1:sloid:101']}
    return ProblemContext.build(sample_base_data, dup_sloid_map)


# =============================================================================
# Distance predicate
# =============================================================================

class TestDistancePredicate:

    def test_matched_below_threshold_no_problem(self, empty_ctx):
        stop = {'stop_type': 'matched', 'distance_m': 10.0, 'csv_business_org_abbr': 'SBB'}
        assert distance_problem(empty_ctx, stop) == []

    def test_matched_p3_sbb_over_25m(self, empty_ctx):
        stop = {'stop_type': 'matched', 'distance_m': 30.0, 'csv_business_org_abbr': 'SBB'}
        results = distance_problem(empty_ctx, stop)
        assert len(results) == 1
        assert results[0].priority == 3

    def test_matched_p2_non_sbb_over_25m(self, empty_ctx):
        stop = {'stop_type': 'matched', 'distance_m': 50.0, 'csv_business_org_abbr': 'BLS'}
        results = distance_problem(empty_ctx, stop)
        assert len(results) == 1
        assert results[0].priority == 2

    def test_matched_p1_non_sbb_over_80m(self, empty_ctx):
        stop = {'stop_type': 'matched', 'distance_m': 100.0, 'csv_business_org_abbr': 'PostAuto'}
        results = distance_problem(empty_ctx, stop)
        assert len(results) == 1
        assert results[0].priority == 1

    def test_p3_any_operator_15_to_25m(self, empty_ctx):
        stop = {'stop_type': 'matched', 'distance_m': 20.0, 'csv_business_org_abbr': 'SBB'}
        results = distance_problem(empty_ctx, stop)
        assert len(results) == 1
        assert results[0].priority == 3

    def test_sbb_exactly_25m_p3(self, empty_ctx):
        """25.0m with SBB: not > 25 for SBB rule, but hits > 15 and <= 25 rule -> P3."""
        stop = {'stop_type': 'matched', 'distance_m': 25.0, 'csv_business_org_abbr': 'SBB'}
        results = distance_problem(empty_ctx, stop)
        assert len(results) == 1
        assert results[0].priority == 3

    def test_non_sbb_exactly_15m_no_problem(self, empty_ctx):
        stop = {'stop_type': 'matched', 'distance_m': 15.0, 'csv_business_org_abbr': 'BLS'}
        assert distance_problem(empty_ctx, stop) == []

    def test_skips_non_matched(self, empty_ctx):
        stop = {'stop_type': 'atlas_unmatched', 'distance_m': 100.0}
        assert distance_problem(empty_ctx, stop) == []

    def test_missing_distance(self, empty_ctx):
        stop = {'stop_type': 'matched', 'distance_m': None}
        assert distance_problem(empty_ctx, stop) == []


class TestComputePriority:

    def test_sbb_tolerance(self):
        assert _compute_priority(30.0, 'SBB') == 3
        assert _compute_priority(30.0, ' sbb ') == 3  # whitespace / case insensitive

    def test_non_sbb_thresholds(self):
        assert _compute_priority(100.0, 'BLS') == 1
        assert _compute_priority(50.0, 'BLS') == 2
        assert _compute_priority(20.0, 'BLS') == 3
        assert _compute_priority(10.0, 'BLS') is None

    def test_boundary_values(self):
        # P1 boundary: > 80 triggers P1 for non-SBB
        assert _compute_priority(80.0, 'BLS') == 2   # 80 is NOT > 80, falls into P2 (> 25 and <= 80)
        assert _compute_priority(80.01, 'BLS') == 1   # just above -> P1
        # P2 boundary: > 25 triggers P2 for non-SBB
        assert _compute_priority(25.0, 'BLS') == 3    # 25 is NOT > 25, falls into P3 (> 15 and <= 25)
        assert _compute_priority(25.01, 'BLS') == 2   # just above -> P2
        # P3 boundary: > 15 triggers P3
        assert _compute_priority(15.0, 'BLS') is None  # 15 is NOT > 15
        assert _compute_priority(15.01, 'BLS') == 3   # just above -> P3


# =============================================================================
# Attributes predicate
# =============================================================================

class TestAttributesPredicate:

    def test_no_mismatches(self, empty_ctx):
        stop = {
            'stop_type': 'matched',
            'number': '8503000', 'osm_uic_ref': '8503000',
            'csv_designation_official': 'Bern', 'osm_uic_name': 'Bern',
            'csv_designation': '1', 'osm_local_ref': '1',
            'csv_business_org_abbr': 'SBB', 'osm_operator': 'SBB',
        }
        assert attributes_problem(empty_ctx, stop) == []

    def test_uic_mismatch_p1(self, empty_ctx):
        stop = {
            'stop_type': 'matched',
            'number': '8503000', 'osm_uic_ref': '8503001',
        }
        results = attributes_problem(empty_ctx, stop)
        assert len(results) == 1
        assert results[0].priority == 1

    def test_name_mismatch_p1(self, empty_ctx):
        stop = {
            'stop_type': 'matched',
            'number': '', 'osm_uic_ref': '',
            'csv_designation_official': 'Bern', 'osm_uic_name': 'Thun',
        }
        results = attributes_problem(empty_ctx, stop)
        assert len(results) == 1
        assert results[0].priority == 1

    def test_local_ref_mismatch_p2(self, empty_ctx):
        stop = {
            'stop_type': 'matched',
            'number': '', 'osm_uic_ref': '',
            'csv_designation_official': '', 'osm_uic_name': '',
            'csv_designation': '1A', 'osm_local_ref': '1B',
        }
        results = attributes_problem(empty_ctx, stop)
        assert len(results) == 1
        assert results[0].priority == 2

    def test_operator_mismatch_p3(self, empty_ctx):
        stop = {
            'stop_type': 'matched',
            'number': '', 'osm_uic_ref': '',
            'csv_designation_official': '', 'osm_uic_name': '',
            'csv_designation': '', 'osm_local_ref': '',
            'csv_business_org_abbr': 'SBB', 'osm_operator': 'BLS',
        }
        results = attributes_problem(empty_ctx, stop)
        assert len(results) == 1
        assert results[0].priority == 3

    def test_case_insensitive_name(self, empty_ctx):
        stop = {
            'stop_type': 'matched',
            'number': '', 'osm_uic_ref': '',
            'csv_designation_official': 'Bern', 'osm_uic_name': 'bern',
        }
        assert attributes_problem(empty_ctx, stop) == []

    def test_highest_severity_wins(self, empty_ctx):
        """When multiple mismatches exist, the highest severity (lowest number) is returned."""
        stop = {
            'stop_type': 'matched',
            'number': '8503000', 'osm_uic_ref': '8503001',  # P1
            'csv_designation': '1A', 'osm_local_ref': '1B',  # P2
            'csv_business_org_abbr': 'SBB', 'osm_operator': 'BLS',  # P3
        }
        results = attributes_problem(empty_ctx, stop)
        assert len(results) == 1
        assert results[0].priority == 1  # highest severity wins

    def test_skips_non_matched(self, empty_ctx):
        stop = {'stop_type': 'osm_unmatched', 'number': '8503000', 'osm_uic_ref': '8503001'}
        assert attributes_problem(empty_ctx, stop) == []

    def test_skips_when_one_side_empty(self, empty_ctx):
        stop = {
            'stop_type': 'matched',
            'number': '8503000', 'osm_uic_ref': '',  # OSM side empty
        }
        assert attributes_problem(empty_ctx, stop) == []


# =============================================================================
# Unmatched predicate
# =============================================================================

class TestUnmatchedPredicate:

    def test_atlas_unmatched_p1_no_uic_in_osm(self, built_ctx):
        """ATLAS stop whose UIC has zero OSM counterparts -> P1."""
        stop = {
            'stop_type': 'atlas_unmatched',
            'number': '9999999',  # UIC not in any OSM node
            'wgs84North': 47.0,
            'wgs84East': 8.0,
        }
        results = unmatched_problem(built_ctx, stop)
        assert len(results) == 1
        assert results[0].priority == 1

    def test_atlas_unmatched_p3_has_nearby(self, built_ctx):
        """ATLAS stop close to OSM data with matching UIC -> P3."""
        stop = {
            'stop_type': 'atlas_unmatched',
            'number': '8503000',  # UIC present in OSM
            'wgs84North': 47.3769,  # close to osm_1
            'wgs84East': 8.5417,
        }
        results = unmatched_problem(built_ctx, stop)
        assert len(results) == 1
        assert results[0].priority == 3

    def test_osm_unmatched_returns_problem(self, built_ctx):
        stop = {
            'stop_type': 'osm_unmatched',
            'lat': 46.5,
            'lon': 7.5,
            'tags': {'uic_ref': '8509999'},
        }
        results = unmatched_problem(built_ctx, stop)
        assert len(results) == 1
        assert results[0].problem_type == 'unmatched'

    def test_matched_skipped(self, built_ctx):
        stop = {'stop_type': 'matched'}
        assert unmatched_problem(built_ctx, stop) == []


# =============================================================================
# Duplicates predicate
# =============================================================================

class TestDuplicatesPredicate:

    def test_atlas_duplicate(self):
        ctx = ProblemContext(
            duplicate_sloid_map={'sloid_a': ['sloid_a', 'sloid_b']},
        )
        stop = {'sloid': 'sloid_a', 'osm_node_id': None}
        results = duplicates_problem(ctx, stop)
        assert len(results) == 1
        assert results[0].priority == 2
        assert results[0].has_atlas_duplicate is True

    def test_osm_duplicate(self):
        ctx = ProblemContext(
            duplicate_osm_node_ids={'n1', 'n2'},
            duplicate_osm_group_map={'n1': ['n1', 'n2'], 'n2': ['n1', 'n2']},
        )
        stop = {'sloid': 'sloid_x', 'osm_node_id': 'n1'}
        results = duplicates_problem(ctx, stop)
        assert len(results) == 1
        assert results[0].priority == 3
        assert results[0].has_osm_duplicate is True

    def test_osm_duplicate_takes_precedence(self):
        """When both ATLAS and OSM duplicates apply, OSM wins."""
        ctx = ProblemContext(
            duplicate_sloid_map={'sloid_a': ['sloid_a', 'sloid_b']},
            duplicate_osm_node_ids={'n1'},
            duplicate_osm_group_map={'n1': ['n1', 'n2']},
        )
        stop = {'sloid': 'sloid_a', 'osm_node_id': 'n1'}
        results = duplicates_problem(ctx, stop)
        assert len(results) == 1
        assert results[0].has_osm_duplicate is True
        assert results[0].has_atlas_duplicate is False

    def test_no_duplicates(self):
        ctx = ProblemContext()
        stop = {'sloid': 'sloid_x', 'osm_node_id': 'n_unique'}
        assert duplicates_problem(ctx, stop) == []


# =============================================================================
# ProblemContext.build()
# =============================================================================

class TestProblemContextBuild:

    def test_builds_osm_kdtree(self, built_ctx):
        assert built_ctx.osm_kdtree is not None
        assert len(built_ctx.osm_points) > 0

    def test_builds_atlas_kdtree(self, built_ctx):
        assert built_ctx.atlas_kdtree is not None
        assert len(built_ctx.atlas_points) > 0

    def test_uic_counts(self, built_ctx):
        # 2 matched records + 1 unmatched_atlas have number='8503000' (2) and '8509999' (1)
        assert built_ctx.atlas_count_by_uic['8503000'] == 2
        assert built_ctx.atlas_count_by_uic['8509999'] == 1

    def test_osm_uic_counts(self, built_ctx):
        # 2 matched with osm_uic_ref='8503000', 1 unmatched_osm with uic_ref='8509999'
        assert built_ctx.osm_count_by_uic['8503000'] == 2
        assert built_ctx.osm_count_by_uic['8509999'] == 1

    def test_osm_platform_counts(self, built_ctx):
        # Both matched have osm_public_transport='platform', unmatched_osm also 'platform'
        assert built_ctx.osm_platform_count_by_uic['8503000'] == 2
        assert built_ctx.osm_platform_count_by_uic['8509999'] == 1

    def test_duplicate_sloid_map_preserved(self, built_ctx):
        assert 'ch:1:sloid:100' in built_ctx.duplicate_sloid_map

    def test_osm_duplicates_detected(self, sample_base_data):
        """Two OSM nodes with same (uic_ref, local_ref) and platform type -> duplicate."""
        data = {
            'matched': [
                {
                    'osm_node_id': 'n_a', 'osm_uic_ref': '8500010',
                    'osm_local_ref': '1', 'osm_public_transport': 'platform',
                    'osm_lat': 47.0, 'osm_lon': 8.0, 'csv_lat': 47.0, 'csv_lon': 8.0,
                    'number': '8500010',
                },
                {
                    'osm_node_id': 'n_b', 'osm_uic_ref': '8500010',
                    'osm_local_ref': '1', 'osm_public_transport': 'platform',
                    'osm_lat': 47.0001, 'osm_lon': 8.0001, 'csv_lat': 47.0, 'csv_lon': 8.0,
                    'number': '8500010',
                },
            ],
            'unmatched_atlas': [],
            'unmatched_osm': [],
        }
        ctx = ProblemContext.build(data, {})
        assert 'n_a' in ctx.duplicate_osm_node_ids
        assert 'n_b' in ctx.duplicate_osm_node_ids
        assert ctx.duplicate_osm_group_map['n_a'] == ['n_a', 'n_b']

    def test_empty_base_data(self):
        ctx = ProblemContext.build({'matched': [], 'unmatched_atlas': [], 'unmatched_osm': []}, {})
        assert ctx.osm_kdtree is None
        assert ctx.atlas_kdtree is None
        assert ctx.atlas_count_by_uic == {}

    def test_nearest_osm_distance(self, built_ctx):
        # Query near osm_1 (47.3770, 8.5418) — should be very close
        dist = built_ctx.nearest_osm_distance(47.3770, 8.5418)
        assert dist is not None
        assert dist < 5  # within 5 meters

    def test_nearest_atlas_distance(self, built_ctx):
        dist = built_ctx.nearest_atlas_distance(47.3769, 8.5417)
        assert dist is not None
        assert dist < 5


# =============================================================================
# Pipeline runner integration
# =============================================================================

class TestRunProblemPipeline:

    def test_matched_with_distance_problem(self, built_ctx):
        stop = {
            'stop_type': 'matched',
            'distance_m': 50.0,
            'csv_business_org_abbr': 'BLS',
            'number': '8503000', 'osm_uic_ref': '8503000',
            'sloid': 'ch:1:sloid:100',
            'osm_node_id': 'osm_1',
        }
        results = run_problem_pipeline(STOP_PROBLEM_PIPELINE, built_ctx, stop)
        types = {r.problem_type for r in results}
        assert 'distance' in types
        # Also has ATLAS duplicate since sloid is in duplicate_sloid_map,
        # but OSM duplicate check runs first — osm_1 is not in OSM duplicate set
        # so ATLAS duplicate should fire
        assert 'duplicates' in types

    def test_matched_clean(self, built_ctx):
        stop = {
            'stop_type': 'matched',
            'distance_m': 5.0,
            'csv_business_org_abbr': 'SBB',
            'number': '8503000', 'osm_uic_ref': '8503000',
            'csv_designation_official': 'X', 'osm_uic_name': 'X',
            'csv_designation': '1', 'osm_local_ref': '1',
            'osm_operator': 'SBB',
            'sloid': 'unrelated_sloid',
            'osm_node_id': 'unrelated_node',
        }
        results = run_problem_pipeline(STOP_PROBLEM_PIPELINE, built_ctx, stop)
        assert results == []

    def test_atlas_unmatched(self, built_ctx):
        stop = {
            'stop_type': 'atlas_unmatched',
            'number': '9999999',
            'wgs84North': 46.0,
            'wgs84East': 7.0,
            'sloid': 'sloid_orphan',
        }
        results = run_problem_pipeline(STOP_PROBLEM_PIPELINE, built_ctx, stop)
        types = {r.problem_type for r in results}
        assert 'unmatched' in types
        assert 'distance' not in types
        assert 'attributes' not in types

    def test_osm_unmatched(self, built_ctx):
        stop = {
            'stop_type': 'osm_unmatched',
            'lat': 46.5,
            'lon': 7.5,
            'tags': {'uic_ref': '9999999'},
            'osm_node_id': 'osm_orphan',
        }
        results = run_problem_pipeline(STOP_PROBLEM_PIPELINE, built_ctx, stop)
        types = {r.problem_type for r in results}
        assert 'unmatched' in types

    def test_predicate_exception_is_caught(self, built_ctx):
        """A failing predicate shouldn't crash the pipeline."""
        def bad_predicate(ctx, stop):
            raise RuntimeError("boom")

        results = run_problem_pipeline(
            [bad_predicate, distance_problem],
            built_ctx,
            {'stop_type': 'matched', 'distance_m': 100.0, 'csv_business_org_abbr': 'X'},
        )
        # distance_problem still runs despite bad_predicate crashing
        assert len(results) == 1
        assert results[0].problem_type == 'distance'


# =============================================================================
# ProblemResult dataclass
# =============================================================================

class TestProblemResult:

    def test_frozen(self):
        r = ProblemResult(problem_type='distance', priority=1)
        with pytest.raises(AttributeError):
            r.priority = 2

    def test_defaults(self):
        r = ProblemResult(problem_type='distance', priority=1)
        assert r.has_atlas_duplicate is False
        assert r.has_osm_duplicate is False
