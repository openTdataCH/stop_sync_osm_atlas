"""
Pytest configuration and shared fixtures for stop_sync_osm_atlas tests.

This module provides:
- Common test fixtures for both matching pipeline and backend tests
- Synthetic test data generators
- Flask test client configuration
"""

import os
import sys
import pytest

# Ensure project root is in path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# =============================================================================
# Matching Pipeline Fixtures
# =============================================================================


@pytest.fixture
def sample_atlas_dataframe():
    """Create a sample ATLAS DataFrame for testing matching functions.
    
    Columns match the expected structure from the ATLAS CSV processing.
    """
    import pandas as pd
    return pd.DataFrame({
        'sloid': ['ch:1:sloid:1', 'ch:1:sloid:2', 'ch:1:sloid:3'],
        'number': ['8503000', '8507000', '8500010'],  # UIC refs
        'designation': ['1', '2', '3'],  # Platform/track designations
        'designationOfficial': ['Zürich HB', 'Bern', 'Basel SBB'],
        'wgs84North': [47.3769, 46.9481, 47.5476],
        'wgs84East': [8.5417, 7.4474, 7.5891],
        'uic_ref': ['8503000', '8507000', '8500010'],
        'servicePointBusinessOrganisationAbbreviationEn': ['SBB', 'SBB', 'SBB'],
    })


@pytest.fixture
def sample_osm_nodes():
    """Create sample OSM nodes dictionary for testing matching functions."""
    return {
        'osm_1': {
            'id': 'osm_1',
            'lat': 47.3770,
            'lon': 8.5418,
            'tags': {
                'name': 'Zürich HB',
                'uic_ref': '8503000',
                'railway': 'station',
                'public_transport': 'station',
            }
        },
        'osm_2': {
            'id': 'osm_2',
            'lat': 46.9482,
            'lon': 7.4475,
            'tags': {
                'name': 'Bern',
                'uic_ref': '8507000',
                'railway': 'station',
            }
        },
        'osm_3': {
            'id': 'osm_3',
            'lat': 47.5477,
            'lon': 7.5892,
            'tags': {
                'name': 'Basel SBB',
                'uic_ref': '8500010',
                'public_transport': 'stop_position',
            }
        },
        'osm_4': {
            'id': 'osm_4',
            'lat': 47.0000,
            'lon': 8.0000,
            'tags': {
                'name': 'Unmatched Stop',
                'aerialway': 'station',
            }
        }
    }


@pytest.fixture
def uic_index(sample_osm_nodes):
    """Create a UIC reference index from sample OSM nodes.
    
    The exact_matching module expects OSM nodes in this format:
    - 'node_id': string identifier
    - 'lat', 'lon': coordinates
    - 'tags': dict of OSM tags
    - 'local_ref': optional local reference
    """
    from collections import defaultdict
    index = defaultdict(list)
    for node_id, node in sample_osm_nodes.items():
        uic = node.get('tags', {}).get('uic_ref')
        if uic:
            # Transform to the format expected by exact_matching
            index[uic].append({
                'node_id': node['id'],
                'lat': node['lat'],
                'lon': node['lon'],
                'tags': node['tags'],
                'local_ref': node['tags'].get('local_ref'),
            })
    return dict(index)


@pytest.fixture
def name_index(sample_osm_nodes):
    """Create a name index from sample OSM nodes.
    
    The name_matching module expects OSM nodes in this format:
    - 'node_id': string identifier
    - 'lat', 'lon': coordinates
    - 'tags': dict of OSM tags
    - 'local_ref': optional local reference
    """
    from collections import defaultdict
    index = defaultdict(list)
    for node_id, node in sample_osm_nodes.items():
        name = node.get('tags', {}).get('name')
        if name:
            index[name].append({
                'node_id': node['id'],
                'lat': node['lat'],
                'lon': node['lon'],
                'tags': node['tags'],
                'local_ref': node['tags'].get('local_ref'),
            })
    return dict(index)


# =============================================================================
# Backend / Flask Fixtures
# =============================================================================


@pytest.fixture
def app():
    """Create Flask application configured for testing."""
    # Import here to avoid circular imports and allow test isolation
    os.environ['FLASK_ENV'] = 'testing'
    os.environ['TESTING'] = 'true'
    
    # Use in-memory SQLite for testing (no PostGIS needed for unit tests)
    os.environ['DATABASE_URI'] = 'sqlite:///:memory:'
    os.environ['USER_INPUT_DATABASE_URI'] = 'sqlite:///:memory:'
    os.environ['SECRET_KEY'] = 'test-secret-key'
    
    from backend.app import create_app
    
    app = create_app()
    app.config.update({
        'TESTING': True,
        'WTF_CSRF_ENABLED': False,
    })
    
    yield app


@pytest.fixture
def client(app):
    """Create a test client for the Flask application."""
    return app.test_client()


@pytest.fixture
def runner(app):
    """Create a test CLI runner for the Flask application."""
    return app.test_cli_runner()


# =============================================================================
# Utility Fixtures
# =============================================================================


@pytest.fixture
def osm_nodes_by_coord(sample_osm_nodes):
    """OSM nodes keyed by (lat, lon) as expected by the pipeline."""
    return {
        (node['lat'], node['lon']): {
            'node_id': node['id'],
            'lat': node['lat'],
            'lon': node['lon'],
            'tags': node['tags'],
            'local_ref': node['tags'].get('local_ref'),
        }
        for node in sample_osm_nodes.values()
    }


@pytest.fixture
def matching_context(sample_atlas_dataframe, osm_nodes_by_coord, uic_index, name_index):
    """Create a MatchingContext for predicate tests."""
    from matching_process.pipeline import MatchingContext
    return MatchingContext(
        atlas_df=sample_atlas_dataframe,
        osm_nodes=osm_nodes_by_coord,
        uic_ref_dict=uic_index,
        name_index=name_index,
        atlas_unmatched=sample_atlas_dataframe.copy(),
    )


@pytest.fixture
def known_coordinates():
    """Known coordinate pairs with pre-calculated distances for testing."""
    return {
        'zurich_bern': {
            'point1': (47.3769, 8.5417),  # Zürich
            'point2': (46.9481, 7.4474),  # Bern
            'expected_distance_km': 95.5,  # Approximate distance in km
            'tolerance_km': 1.0,
        },
        'same_point': {
            'point1': (47.0, 8.0),
            'point2': (47.0, 8.0),
            'expected_distance_km': 0.0,
            'tolerance_km': 0.001,
        },
        'short_distance': {
            'point1': (47.3769, 8.5417),
            'point2': (47.3770, 8.5418),
            'expected_distance_km': 0.015,  # ~15 meters
            'tolerance_km': 0.005,
        }
    }
