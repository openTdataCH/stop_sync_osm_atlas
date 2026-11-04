"""Absolute public URLs, for canonical links, robots.txt and the sitemap."""
from flask import current_app, request


def site_url(path: str) -> str:
    """``path`` under the configured ``SITE_URL``, or under the request's own root when none is set."""
    configured_base = current_app.config.get('SITE_URL', '').rstrip('/')
    base = configured_base or request.url_root.rstrip('/')
    normalized_path = '/' + path.lstrip('/')
    return f'{base}{normalized_path}'
