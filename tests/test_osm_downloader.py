from pathlib import Path


class DummyResponse:
    def __init__(self, status_code=200, text="<osm></osm>", url="https://overpass-api.de/api/interpreter"):
        self.status_code = status_code
        self.text = text
        self.url = url
        self.encoding = None


def test_query_overpass_posts_raw_query(monkeypatch, tmp_path):
    from matching_and_import_db.downloader import get_osm_data

    monkeypatch.chdir(tmp_path)
    captured = {}

    class DummySession:
        def post(self, url, data=None, headers=None, timeout=None):
            captured["url"] = url
            captured["data"] = data
            captured["headers"] = headers
            captured["timeout"] = timeout
            return DummyResponse(text="<osm version='0.6'></osm>", url=url)

    result = get_osm_data.query_overpass(session=DummySession())

    assert result == "<osm version='0.6'></osm>"
    assert captured["url"] == get_osm_data.OVERPASS_URL
    assert isinstance(captured["data"], bytes)
    assert captured["data"].decode("utf-8").startswith("[out:xml]")
    assert captured["headers"]["Content-Type"].startswith("text/plain")
    assert captured["timeout"] == (30, 600)
    assert Path("data/raw/osm_data.xml").read_text(encoding="utf-8") == result


def test_query_overpass_raises_on_http_error(monkeypatch, tmp_path):
    from matching_and_import_db.downloader import get_osm_data

    monkeypatch.chdir(tmp_path)

    class DummySession:
        def post(self, url, data=None, headers=None, timeout=None):
            return DummyResponse(status_code=406, text="Not Acceptable", url=url)

    try:
        get_osm_data.query_overpass(session=DummySession())
    except RuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError("Expected RuntimeError for Overpass HTTP failure")

    assert "Overpass request failed (406)" in message
    assert "Not Acceptable" in message


def test_query_overpass_retries_504_then_succeeds(monkeypatch, tmp_path):
    from matching_and_import_db.downloader import get_osm_data

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(get_osm_data, "OVERPASS_MAX_RETRIES", 2)
    monkeypatch.setattr(get_osm_data, "OVERPASS_RETRY_BACKOFF_SECONDS", 0.25)
    sleeps = []
    monkeypatch.setattr(get_osm_data.time, "sleep", sleeps.append)

    class DummySession:
        def __init__(self):
            self.calls = 0

        def post(self, url, data=None, headers=None, timeout=None):
            self.calls += 1
            if self.calls == 1:
                return DummyResponse(status_code=504, text="Gateway Timeout", url=url)
            return DummyResponse(text="<osm version='0.6'></osm>", url=url)

    session = DummySession()

    result = get_osm_data.query_overpass(session=session)

    assert result == "<osm version='0.6'></osm>"
    assert session.calls == 2
    assert sleeps == [0.25]


def test_query_overpass_exhausts_retries_for_502(monkeypatch, tmp_path):
    from matching_and_import_db.downloader import get_osm_data

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(get_osm_data, "OVERPASS_MAX_RETRIES", 2)
    monkeypatch.setattr(get_osm_data, "OVERPASS_RETRY_BACKOFF_SECONDS", 0.5)
    sleeps = []
    monkeypatch.setattr(get_osm_data.time, "sleep", sleeps.append)

    class DummySession:
        def __init__(self):
            self.calls = 0

        def post(self, url, data=None, headers=None, timeout=None):
            self.calls += 1
            return DummyResponse(status_code=502, text="Bad Gateway", url=url)

    session = DummySession()

    try:
        get_osm_data.query_overpass(session=session)
    except RuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError("Expected RuntimeError after retry exhaustion")

    assert session.calls == 3
    assert sleeps == [0.5, 1.0]
    assert "Overpass request failed (502)" in message
    assert "Bad Gateway" in message