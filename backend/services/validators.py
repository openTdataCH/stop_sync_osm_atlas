"""
Input validation utilities for backend API endpoints.

Provides centralized validation for:
- Pagination parameters (page, limit)
- Text content (length, format)
- HTML sanitization (XSS protection)
"""

import bleach

# Allowed HTML tags for notes (basic formatting only)
ALLOWED_TAGS = ['b', 'i', 'em', 'strong', 'br', 'p', 'ul', 'ol', 'li', 'a']
ALLOWED_ATTRIBUTES = {'a': ['href', 'title']}


def validate_pagination(page, limit, max_limit=1000, default_limit=100):
    """
    Validate and normalize pagination parameters.
    
    Args:
        page: Page number (1-indexed). Accepts int or string.
        limit: Number of items per page. Accepts int or string.
        max_limit: Maximum allowed limit value (default 1000).
        default_limit: Default limit if not provided or invalid (default 100).
    
    Returns:
        tuple: (validated_page, validated_limit)
    
    Raises:
        ValueError: If page is less than 1 or limit is negative.
    """
    # Parse page
    try:
        page = int(page) if page is not None else 1
    except (ValueError, TypeError):
        page = 1
    
    if page < 1:
        raise ValueError("Page must be >= 1")
    
    # Parse limit
    try:
        limit = int(limit) if limit is not None else default_limit
    except (ValueError, TypeError):
        limit = default_limit
    
    if limit < 1:
        raise ValueError("Limit must be >= 1")
    
    # Clamp limit to max
    if limit > max_limit:
        limit = max_limit
    
    return page, limit


def validate_text_content(text, max_length, field_name='content'):
    """
    Validate text content for length and emptiness.
    
    Args:
        text: The text content to validate.
        max_length: Maximum allowed character length.
        field_name: Name of the field (for error messages).
    
    Returns:
        str: Stripped text content.
    
    Raises:
        ValueError: If text is empty or exceeds max_length.
    """
    if text is None:
        raise ValueError(f"{field_name.capitalize()} cannot be empty")
    
    text = str(text).strip()
    
    if not text:
        raise ValueError(f"{field_name.capitalize()} cannot be empty")
    
    if len(text) > max_length:
        raise ValueError(
            f"{field_name.capitalize()} exceeds maximum length of {max_length} characters"
        )
    
    return text


def sanitize_html(text):
    """
    Sanitize HTML content to prevent XSS attacks.
    
    Allows basic formatting tags while stripping scripts and event handlers.
    
    Args:
        text: HTML text to sanitize.
    
    Returns:
        str: Sanitized text with dangerous content removed.
    """
    if text is None:
        return ''
    
    return bleach.clean(
        str(text),
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        strip=True
    )
