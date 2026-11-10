"""Unit tests for the pagination validator (validate_pagination)."""

import pytest


class TestValidatePagination:
    """Tests for the validate_pagination function."""

    def test_valid_pagination(self):
        """Valid page and limit should return unchanged."""
        from backend.services.validators import validate_pagination
        
        page, limit = validate_pagination(1, 50, max_limit=100)
        
        assert page == 1
        assert limit == 50

    def test_pagination_with_strings(self):
        """String inputs should be converted to integers."""
        from backend.services.validators import validate_pagination
        
        page, limit = validate_pagination('3', '25', max_limit=100)
        
        assert page == 3
        assert limit == 25

    def test_default_page(self):
        """None page should default to 1."""
        from backend.services.validators import validate_pagination
        
        page, limit = validate_pagination(None, 50, max_limit=100)
        
        assert page == 1

    def test_default_limit(self):
        """None limit should use default_limit."""
        from backend.services.validators import validate_pagination
        
        page, limit = validate_pagination(1, None, max_limit=100, default_limit=25)
        
        assert limit == 25

    def test_page_less_than_one_raises(self):
        """Page less than 1 should raise ValueError."""
        from backend.services.validators import validate_pagination
        
        with pytest.raises(ValueError, match="Page must be >= 1"):
            validate_pagination(0, 50)

    def test_negative_page_raises(self):
        """Negative page should raise ValueError."""
        from backend.services.validators import validate_pagination
        
        with pytest.raises(ValueError, match="Page must be >= 1"):
            validate_pagination(-5, 50)

    def test_negative_limit_raises(self):
        """Negative limit should raise ValueError."""
        from backend.services.validators import validate_pagination
        
        with pytest.raises(ValueError, match="Limit must be >= 1"):
            validate_pagination(1, -10)

    def test_zero_limit_raises(self):
        """Zero limit should raise ValueError."""
        from backend.services.validators import validate_pagination
        
        with pytest.raises(ValueError, match="Limit must be >= 1"):
            validate_pagination(1, 0)

    def test_limit_clamped_to_max(self):
        """Limit exceeding max_limit should be clamped."""
        from backend.services.validators import validate_pagination
        
        page, limit = validate_pagination(1, 999999, max_limit=100)
        
        assert limit == 100

    def test_limit_at_max_allowed(self):
        """Limit exactly at max should be allowed."""
        from backend.services.validators import validate_pagination
        
        page, limit = validate_pagination(1, 100, max_limit=100)
        
        assert limit == 100

    def test_invalid_string_page_defaults(self):
        """Invalid string for page should default to 1."""
        from backend.services.validators import validate_pagination
        
        page, limit = validate_pagination('abc', 50, max_limit=100)
        
        assert page == 1

    def test_invalid_string_limit_uses_default(self):
        """Invalid string for limit should use default."""
        from backend.services.validators import validate_pagination
        
        page, limit = validate_pagination(1, 'abc', max_limit=100, default_limit=25)
        
        assert limit == 25
