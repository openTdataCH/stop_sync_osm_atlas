"""
Pytest configuration and shared fixtures for stop_sync_osm_atlas tests.

This module provides:
- Independent review application fixtures
- Flask test client configuration
"""

import os
import sys
import pytest

# Ensure project root is in path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Ensure tests are independent from external Redis availability.
os.environ['RATELIMIT_STORAGE_URI'] = 'memory://'
os.environ['STATE_BACKEND'] = 'memory'


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
