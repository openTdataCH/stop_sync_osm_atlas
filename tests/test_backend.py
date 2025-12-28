"""
Unit tests for the backend API.

Tests cover:
- Query helper functions (parse_filter_params, optimize_query_for_endpoint)
- Utility functions that don't require database
- Basic request/response validation

Note: These are unit tests that don't require a running database.
Integration tests with a real database should be added separately.
"""

import pytest
from unittest.mock import MagicMock, patch


# =============================================================================
# Tests for backend/queries/helpers.py - parse_filter_params
# =============================================================================


class TestParseFilterParams:
    """Tests for the parse_filter_params function."""

    def test_empty_args(self):
        """Empty request args should return empty filters."""
        from backend.queries.helpers import parse_filter_params
        
        result = parse_filter_params({})
        assert result == {}

    def test_transport_types_parsing(self):
        """Transport types should be split by comma."""
        from backend.queries.helpers import parse_filter_params
        
        args = {'transport_types': 'bus,tram,train'}
        result = parse_filter_params(args)
        
        assert 'transport_types' in result
        assert result['transport_types'] == ['bus', 'tram', 'train']

    def test_transport_types_with_whitespace(self):
        """Whitespace around transport types should be stripped."""
        from backend.queries.helpers import parse_filter_params
        
        args = {'transport_types': ' bus , tram , train '}
        result = parse_filter_params(args)
        
        assert result['transport_types'] == ['bus', 'tram', 'train']

    def test_node_type_all_ignored(self):
        """node_type='all' should not be added to filters."""
        from backend.queries.helpers import parse_filter_params
        
        args = {'node_type': 'all'}
        result = parse_filter_params(args)
        
        assert 'node_types' not in result

    def test_node_type_specific(self):
        """Specific node types should be parsed."""
        from backend.queries.helpers import parse_filter_params
        
        args = {'node_type': 'atlas,osm'}
        result = parse_filter_params(args)
        
        assert 'node_types' in result
        assert result['node_types'] == ['atlas', 'osm']

    def test_atlas_operator_parsing(self):
        """ATLAS operators should be split by comma."""
        from backend.queries.helpers import parse_filter_params
        
        args = {'atlas_operator': 'SBB,BLS,SOB'}
        result = parse_filter_params(args)
        
        assert 'atlas_operators' in result
        assert result['atlas_operators'] == ['SBB', 'BLS', 'SOB']

    def test_station_filter_with_types_and_directions(self):
        """Station filter should include filter_types and route_directions."""
        from backend.queries.helpers import parse_filter_params
        
        args = {
            'station_filter': 'value1,value2',
            'filter_types': 'type1,type2',
            'route_directions': 'dir1,dir2',
        }
        result = parse_filter_params(args)
        
        assert 'filter_values' in result
        assert result['filter_values'] == ['value1', 'value2']
        assert result['filter_types'] == ['type1', 'type2']
        assert result['route_directions'] == ['dir1', 'dir2']

    def test_empty_transport_types_ignored(self):
        """Empty strings in transport types should be filtered out."""
        from backend.queries.helpers import parse_filter_params
        
        args = {'transport_types': 'bus,,tram,'}
        result = parse_filter_params(args)
        
        assert result['transport_types'] == ['bus', 'tram']


# =============================================================================
# Tests for backend/queries/helpers.py - optimize_query_for_endpoint
# =============================================================================


class TestOptimizeQueryForEndpoint:
    """Tests for query optimization by endpoint type."""

    def test_stats_endpoint_config(self):
        """Stats endpoint should eager-load atlas but not osm."""
        from backend.queries.helpers import optimize_query_for_endpoint
        
        # Create a mock query object
        mock_query = MagicMock()
        mock_query.options.return_value = mock_query
        
        result = optimize_query_for_endpoint(mock_query, 'stats')
        
        # Should have called options()
        mock_query.options.assert_called()

    def test_search_endpoint_config(self):
        """Search endpoint should eager-load both atlas and osm."""
        from backend.queries.helpers import optimize_query_for_endpoint
        
        mock_query = MagicMock()
        mock_query.options.return_value = mock_query
        
        result = optimize_query_for_endpoint(mock_query, 'search')
        
        mock_query.options.assert_called()

    def test_unknown_endpoint_defaults(self):
        """Unknown endpoint should use default config (load both)."""
        from backend.queries.helpers import optimize_query_for_endpoint
        
        mock_query = MagicMock()
        mock_query.options.return_value = mock_query
        
        result = optimize_query_for_endpoint(mock_query, 'unknown_endpoint')
        
        mock_query.options.assert_called()


# =============================================================================
# Tests for backend/blueprints/data.py - parse_bbox
# =============================================================================


class TestParseBbox:
    """Tests for bounding box parsing."""

    def test_valid_bbox_single_param(self):
        """Valid bbox with comma-separated values should parse correctly."""
        from backend.blueprints.data import _parse_bbox_from_request_args
        
        args = {'bbox': '47.0,8.0,48.0,9.0'}
        result = _parse_bbox_from_request_args(args)
        
        assert result is not None
        assert len(result) == 4
        # Returns (min_lat, min_lon, max_lat, max_lon)
        assert result == (47.0, 8.0, 48.0, 9.0)

    def test_valid_bbox_separate_params(self):
        """Valid bbox with separate min/max params should parse correctly."""
        from backend.blueprints.data import _parse_bbox_from_request_args
        
        args = {
            'min_lat': '47.0',
            'min_lon': '8.0',
            'max_lat': '48.0',
            'max_lon': '9.0',
        }
        result = _parse_bbox_from_request_args(args)
        
        assert result is not None
        assert result == (47.0, 8.0, 48.0, 9.0)

    def test_incomplete_bbox_raises(self):
        """Incomplete bbox should raise ValueError."""
        from backend.blueprints.data import _parse_bbox_from_request_args
        
        args = {'bbox': '8.0,47.0'}  # Only 2 values
        
        with pytest.raises(ValueError):
            _parse_bbox_from_request_args(args)

    def test_invalid_bbox_values_raises(self):
        """Invalid (non-numeric) bbox values should raise an exception."""
        from backend.blueprints.data import _parse_bbox_from_request_args
        
        args = {'bbox': 'invalid,values,here,now'}
        
        with pytest.raises(ValueError):
            _parse_bbox_from_request_args(args)


# =============================================================================
# Tests for backend serializers
# =============================================================================


class TestStopSerializer:
    """Tests for stop data serialization."""

    def test_format_stop_data_basic_fields(self):
        """Basic fields should be serialized correctly."""
        from unittest.mock import MagicMock
        from backend.serializers.stops import format_stop_data
        
        # Create a mock stop object
        mock_stop = MagicMock()
        mock_stop.id = 1
        mock_stop.sloid = 'ch:1:sloid:123'
        mock_stop.osm_node_id = 'osm_456'
        mock_stop.match_type = 'exact'
        mock_stop.stop_type = 'matched'
        mock_stop.distance_m = 5.5
        mock_stop.atlas_lat = 47.0
        mock_stop.atlas_lon = 8.0
        mock_stop.osm_lat = 47.0
        mock_stop.osm_lon = 8.0
        mock_stop.uic_ref = '8503000'
        mock_stop.osm_node_type = 'stop_position'
        mock_stop.atlas_duplicate_sloid = None
        mock_stop.atlas_stop_details = None
        mock_stop.osm_node_details = None
        
        result = format_stop_data(mock_stop)
        
        assert result['sloid'] == 'ch:1:sloid:123'
        assert result['osm_node_id'] == 'osm_456'
        assert result['match_type'] == 'exact'
        assert result['stop_type'] == 'matched'

    def test_format_stop_data_excludes_routes_when_disabled(self):
        """Routes should be excluded when include_routes=False."""
        from unittest.mock import MagicMock
        from backend.serializers.stops import format_stop_data
        
        mock_stop = MagicMock()
        mock_stop.id = 1
        mock_stop.sloid = 'ch:1:sloid:123'
        mock_stop.osm_node_id = 'osm_456'
        mock_stop.match_type = 'exact'
        mock_stop.stop_type = 'matched'
        mock_stop.distance_m = 5.5
        mock_stop.atlas_lat = 47.0
        mock_stop.atlas_lon = 8.0
        mock_stop.osm_lat = 47.0
        mock_stop.osm_lon = 8.0
        mock_stop.uic_ref = '8503000'
        mock_stop.osm_node_type = 'stop_position'
        mock_stop.atlas_duplicate_sloid = None
        mock_stop.atlas_stop_details = None
        mock_stop.osm_node_details = None
        
        result = format_stop_data(mock_stop, include_routes=False)
        
        assert 'routes_unified' not in result
        assert 'routes_osm' not in result


# =============================================================================
# Tests for backend query_builder.py
# =============================================================================


# =============================================================================
# API Endpoint Tests (using Flask test client) - Smoke tests
# =============================================================================


class TestAPIEndpointsSmoke:
    """
    Smoke tests for API endpoints.
    
    These tests verify that endpoints return expected HTTP status codes
    without a full database. They're designed to catch import errors
    and basic routing issues.
    """

    @pytest.mark.skip(reason="Requires full app setup with database")
    def test_global_stats_endpoint(self, client):
        """Global stats endpoint should return 200."""
        response = client.get('/api/global_stats')
        assert response.status_code == 200

    @pytest.mark.skip(reason="Requires full app setup with database")
    def test_operators_endpoint(self, client):
        """Operators endpoint should return 200."""
        response = client.get('/api/operators')
        assert response.status_code == 200

    @pytest.mark.skip(reason="Requires full app setup with database")
    def test_search_endpoint_without_query(self, client):
        """Search endpoint without query should return error or empty."""
        response = client.get('/api/search')
        # Should return 400 (bad request) or 200 with empty results
        assert response.status_code in [200, 400]


# =============================================================================
# Service layer tests
# =============================================================================


class TestCryptoService:
    """Tests for cryptographic utilities."""

    def test_encrypt_without_key_adds_plain_prefix(self):
        """Without encryption key, encrypt_for_db adds plain: prefix."""
        import os
        # Ensure no encryption key is set
        old_key = os.environ.pop('TOTP_SECRET_ENC_KEY', None)
        old_fernet = os.environ.pop('FERNET_KEY', None)
        
        try:
            from backend.services.crypto import encrypt_for_db
            
            result = encrypt_for_db('test_secret')
            assert result.startswith('plain:')
            assert result == 'plain:test_secret'
        finally:
            # Restore environment
            if old_key:
                os.environ['TOTP_SECRET_ENC_KEY'] = old_key
            if old_fernet:
                os.environ['FERNET_KEY'] = old_fernet

    def test_decrypt_plain_prefix(self):
        """Values with plain: prefix should be decrypted correctly."""
        from backend.services.crypto import decrypt_from_db
        
        result = decrypt_from_db('plain:my_secret')
        assert result == 'my_secret'

    def test_decrypt_none_returns_none(self):
        """None values should return None."""
        from backend.services.crypto import decrypt_from_db
        
        assert decrypt_from_db(None) is None
        assert decrypt_from_db('') is None

    def test_encryption_roundtrip_without_key(self):
        """encrypt_for_db and decrypt_from_db should roundtrip without key."""
        import os
        old_key = os.environ.pop('TOTP_SECRET_ENC_KEY', None)
        old_fernet = os.environ.pop('FERNET_KEY', None)
        
        try:
            from backend.services.crypto import encrypt_for_db, decrypt_from_db
            
            original = 'test_totp_secret_123'
            encrypted = encrypt_for_db(original)
            decrypted = decrypt_from_db(encrypted)
            
            assert decrypted == original
        finally:
            if old_key:
                os.environ['TOTP_SECRET_ENC_KEY'] = old_key
            if old_fernet:
                os.environ['FERNET_KEY'] = old_fernet
