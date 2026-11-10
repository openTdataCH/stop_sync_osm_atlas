"""Input validation for backend API endpoints: pagination parameters."""


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
