from werkzeug.middleware.proxy_fix import ProxyFix

from backend.app import create_app
from backend.extensions import limiter


def _build_rate_limited_app(monkeypatch, trusted_proxy_count=None):
    monkeypatch.setenv('DATABASE_URI', 'sqlite:///:memory:')
    if trusted_proxy_count is None:
        monkeypatch.delenv('TRUSTED_PROXY_COUNT', raising=False)
    else:
        monkeypatch.setenv('TRUSTED_PROXY_COUNT', str(trusted_proxy_count))

    app = create_app()
    limiter.reset()

    @app.route('/_test_rate_limit')
    @limiter.limit('2 per minute')
    def _test_rate_limit():
        return {'ok': True}

    return app


def test_trusted_proxy_count_zero_ignores_x_forwarded_for(monkeypatch):
    app = _build_rate_limited_app(monkeypatch, trusted_proxy_count=0)
    assert not isinstance(app.wsgi_app, ProxyFix)

    client = app.test_client()
    assert client.get('/_test_rate_limit', headers={'X-Forwarded-For': '203.0.113.10'}).status_code == 200
    assert client.get('/_test_rate_limit', headers={'X-Forwarded-For': '203.0.113.20'}).status_code == 200
    # Spoofing a third X-Forwarded-For value must not bypass the 2/minute limit.
    assert client.get('/_test_rate_limit', headers={'X-Forwarded-For': '203.0.113.30'}).status_code == 429


def test_trusted_proxy_count_one_isolates_clients_and_blocks_spoofing(monkeypatch):
    app = _build_rate_limited_app(monkeypatch, trusted_proxy_count=1)
    assert isinstance(app.wsgi_app, ProxyFix)
    assert app.wsgi_app.x_for == 1
    assert app.wsgi_app.x_proto == 1

    client = app.test_client()
    assert client.get('/_test_rate_limit', headers={'X-Forwarded-For': '203.0.113.10'}).status_code == 200
    assert client.get('/_test_rate_limit', headers={'X-Forwarded-For': '203.0.113.10'}).status_code == 200
    assert client.get('/_test_rate_limit', headers={'X-Forwarded-For': '203.0.113.10'}).status_code == 429

    # A spoofed leftmost IP still resolves to the rightmost proxy-appended IP (203.0.113.10).
    assert client.get('/_test_rate_limit', headers={'X-Forwarded-For': '1.2.3.4, 203.0.113.10'}).status_code == 429

    # A different client IP gets its own counter bucket.
    assert client.get('/_test_rate_limit', headers={'X-Forwarded-For': '203.0.113.20'}).status_code == 200


def test_trusted_proxy_count_is_bounded_between_zero_and_two(monkeypatch):
    app_high = _build_rate_limited_app(monkeypatch, trusted_proxy_count=99)
    assert isinstance(app_high.wsgi_app, ProxyFix)
    assert app_high.wsgi_app.x_for == 2
    assert app_high.wsgi_app.x_proto == 2

    app_invalid = _build_rate_limited_app(monkeypatch, trusted_proxy_count='invalid')
    assert not isinstance(app_invalid.wsgi_app, ProxyFix)

    app_negative = _build_rate_limited_app(monkeypatch, trusted_proxy_count=-3)
    assert not isinstance(app_negative.wsgi_app, ProxyFix)
