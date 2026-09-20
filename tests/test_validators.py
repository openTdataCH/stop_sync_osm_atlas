"""
Unit tests for backend input validation utilities.

Tests cover:
- Pagination validation (validate_pagination)
- Text content validation (validate_text_content)
- HTML/XSS sanitization (sanitize_html)
"""

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


class TestValidateTextContent:
    """Tests for the validate_text_content function."""

    def test_valid_text(self):
        """Valid text should be returned stripped."""
        from backend.services.validators import validate_text_content
        
        result = validate_text_content('  hello world  ', max_length=100)
        
        assert result == 'hello world'

    def test_none_raises(self):
        """None text should raise ValueError."""
        from backend.services.validators import validate_text_content
        
        with pytest.raises(ValueError, match="Content cannot be empty"):
            validate_text_content(None, max_length=100)

    def test_empty_string_raises(self):
        """Empty string should raise ValueError."""
        from backend.services.validators import validate_text_content
        
        with pytest.raises(ValueError, match="Content cannot be empty"):
            validate_text_content('', max_length=100)

    def test_whitespace_only_raises(self):
        """Whitespace-only string should raise ValueError."""
        from backend.services.validators import validate_text_content
        
        with pytest.raises(ValueError, match="Content cannot be empty"):
            validate_text_content('   \t\n  ', max_length=100)

    def test_exceeds_max_length_raises(self):
        """Text exceeding max_length should raise ValueError."""
        from backend.services.validators import validate_text_content
        
        long_text = 'a' * 101
        with pytest.raises(ValueError, match="exceeds maximum length"):
            validate_text_content(long_text, max_length=100)

    def test_exactly_max_length_allowed(self):
        """Text exactly at max_length should be allowed."""
        from backend.services.validators import validate_text_content
        
        exact_text = 'a' * 100
        result = validate_text_content(exact_text, max_length=100)
        
        assert result == exact_text

    def test_custom_field_name_in_error(self):
        """Custom field_name should appear in error message."""
        from backend.services.validators import validate_text_content
        
        with pytest.raises(ValueError, match="Note cannot be empty"):
            validate_text_content('', max_length=100, field_name='note')


class TestSanitizeHtml:
    """Tests for the sanitize_html function."""

    def test_plain_text_unchanged(self):
        """Plain text without HTML should be unchanged."""
        from backend.services.validators import sanitize_html
        
        result = sanitize_html('Hello, World!')
        
        assert result == 'Hello, World!'

    def test_allowed_tags_preserved(self):
        """Allowed tags should be preserved."""
        from backend.services.validators import sanitize_html
        
        result = sanitize_html('<b>bold</b> and <i>italic</i>')
        
        assert '<b>bold</b>' in result
        assert '<i>italic</i>' in result

    def test_script_tag_removed(self):
        """Script tags should be removed."""
        from backend.services.validators import sanitize_html
        
        result = sanitize_html('<script>alert("xss")</script>Hello')
        
        assert '<script>' not in result
        assert 'alert' not in result
        assert 'Hello' in result

    def test_event_handlers_removed(self):
        """Event handlers should be removed."""
        from backend.services.validators import sanitize_html
        
        result = sanitize_html('<div onclick="alert(1)">Click me</div>')
        
        assert 'onclick' not in result
        assert 'Click me' in result

    def test_javascript_url_removed(self):
        """JavaScript URLs should be removed."""
        from backend.services.validators import sanitize_html
        
        result = sanitize_html('<a href="javascript:alert(1)">Link</a>')
        
        assert 'javascript:' not in result

    def test_none_returns_empty_string(self):
        """None input should return empty string."""
        from backend.services.validators import sanitize_html
        
        result = sanitize_html(None)
        
        assert result == ''

    def test_link_href_preserved(self):
        """Valid href on links should be preserved."""
        from backend.services.validators import sanitize_html
        
        result = sanitize_html('<a href="https://example.com">Link</a>')
        
        assert 'href="https://example.com"' in result
        assert 'Link' in result

    def test_img_tag_removed(self):
        """Img tags should be removed (not in allowed list)."""
        from backend.services.validators import sanitize_html
        
        result = sanitize_html('<img src="x" onerror="alert(1)">')
        
        assert '<img' not in result
        assert 'onerror' not in result

    def test_nested_dangerous_content(self):
        """Nested dangerous content should be sanitized."""
        from backend.services.validators import sanitize_html
        
        result = sanitize_html('<b onclick="alert(1)"><script>evil</script>safe</b>')
        
        assert '<script>' not in result
        assert 'alert' not in result
        assert 'safe' in result
