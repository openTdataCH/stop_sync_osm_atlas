import xml.etree.ElementTree as ET

from flask import Blueprint, Response, current_app, request, url_for


seo_bp = Blueprint('seo', __name__)

PUBLIC_HTML_ENDPOINTS = {
    'index',
    'problems',
    'data_analytics',
    'data_reports',
    'operators.operators_page',
    'routes.routes_page',
    'routes.non_gtfs_routes_page',
    'routes.routes_gtfs_stop_id_sloid_page',
    'docs.docs_page',
}

SITEMAP_ENDPOINTS = (
    'index',
    'problems',
    'routes.routes_page',
    'routes.non_gtfs_routes_page',
    'routes.routes_gtfs_stop_id_sloid_page',
    'operators.operators_page',
    'data_analytics',
    'data_reports',
)


def site_url(path: str) -> str:
    configured_base = current_app.config.get('SITE_URL', '').rstrip('/')
    base = configured_base or request.url_root.rstrip('/')
    normalized_path = '/' + path.lstrip('/')
    return f'{base}{normalized_path}'


def seo_template_context() -> dict[str, str]:
    has_query_filters = bool(request.query_string)
    indexable = (
        request.endpoint in PUBLIC_HTML_ENDPOINTS
        and not has_query_filters
    )
    return {
        'seo_canonical_url': site_url(request.path),
        'seo_robots': 'index,follow' if indexable else 'noindex,follow',
    }


def _sitemap_paths() -> list[str]:
    paths = [url_for(endpoint) for endpoint in SITEMAP_ENDPOINTS]

    # Documentation is file-backed, so include every canonical documentation
    # slug rather than the duplicate /docs entry point.
    from backend.blueprints.docs import _build_doc_slug_maps, _list_markdown_files

    files = _list_markdown_files()
    file_to_slug, _ = _build_doc_slug_maps(files)
    paths.extend(
        url_for('docs.docs_page', page=file_to_slug[filename])
        for filename in files
        if file_to_slug.get(filename)
    )
    return list(dict.fromkeys(paths))


@seo_bp.route('/robots.txt')
def robots_txt():
    body = '\n'.join((
        'User-agent: *',
        'Allow: /',
        'Disallow: /api/',
        f'Sitemap: {site_url("/sitemap.xml")}',
        '',
    ))
    response = Response(body, content_type='text/plain; charset=utf-8')
    response.headers['Cache-Control'] = 'public, max-age=3600'
    return response


@seo_bp.route('/sitemap.xml')
def sitemap_xml():
    namespace = 'http://www.sitemaps.org/schemas/sitemap/0.9'
    ET.register_namespace('', namespace)
    urlset = ET.Element(f'{{{namespace}}}urlset')
    for path in _sitemap_paths():
        url_element = ET.SubElement(urlset, f'{{{namespace}}}url')
        ET.SubElement(url_element, f'{{{namespace}}}loc').text = site_url(path)

    body = ET.tostring(urlset, encoding='utf-8', xml_declaration=True)
    response = Response(body, content_type='application/xml; charset=utf-8')
    response.headers['Cache-Control'] = 'public, max-age=3600'
    return response
