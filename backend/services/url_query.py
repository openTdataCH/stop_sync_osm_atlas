from collections.abc import Iterable
from urllib.parse import urlencode

from flask import redirect, request, url_for


def canonical_query_redirect(
    endpoint: str,
    pairs: Iterable[tuple[str, object]],
    safe: str = ',',
):
    """Redirect equivalent GET query variants to one stable representation.

    ``safe`` lists characters left unencoded in values; static/js/shared/
    permalinks.js writes the same encoding so a reload does not redirect.
    """
    normalized_pairs = [
        (key, str(value))
        for key, value in pairs
        if value is not None and str(value) != ''
    ]
    # Comma is the single, readable separator for multi-value filters.
    query_string = urlencode(normalized_pairs, safe=safe)
    current_query_string = request.query_string.decode('utf-8', errors='replace')
    if current_query_string == query_string:
        return None

    location = url_for(endpoint)
    if query_string:
        location = f'{location}?{query_string}'
    return redirect(location, code=308)
