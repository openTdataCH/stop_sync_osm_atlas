from pathlib import Path
import csv


class DummyResponse:
    def __init__(self, status_code=200, text="<osm></osm>", url="https://overpass-api.de/api/interpreter"):
        self.status_code = status_code
        self.text = text
        self.url = url
        self.encoding = None


def test_query_overpass_posts_raw_query(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    from matching_and_import_db.downloader import get_osm_data
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
    monkeypatch.chdir(tmp_path)
    from matching_and_import_db.downloader import get_osm_data

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
    monkeypatch.chdir(tmp_path)
    from matching_and_import_db.downloader import get_osm_data
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
    monkeypatch.chdir(tmp_path)
    from matching_and_import_db.downloader import get_osm_data
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


def test_process_osm_routes_data_writes_route_master_and_relation_csvs(monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        from matching_and_import_db.downloader import get_osm_data

        xml_data = """
        <osm version="0.6">
            <node id="100" lat="47.1" lon="8.1">
                <tag k="uic_ref" v="8500" />
                <tag k="name" v="Station A" />
                <tag k="public_transport" v="platform" />
            </node>
            <way id="200">
                <center lat="47.2" lon="8.2" />
                <tag k="uic_ref" v="8600" />
                <tag k="name" v="Station B" />
                <tag k="aerialway" v="station" />
                <tag k="public_transport" v="station" />
            </way>
            <relation id="300" version="1">
                <tag k="type" v="route" />
                <tag k="route" v="bus" />
                <tag k="name" v="Line 10 Outbound" />
                <tag k="ref" v="10" />
                <tag k="operator" v="Transit Co" />
                <tag k="gtfs:route_id" v="10" />
                <tag k="ref_trips" v="trip1.H" />
                <member type="node" ref="100" role="platform" />
                <member type="way" ref="200" role="platform" />
            </relation>
            <relation id="400" version="1">
                <tag k="type" v="route_master" />
                <tag k="route_master" v="bus" />
                <tag k="name" v="Line 10" />
                <tag k="ref" v="10" />
                <tag k="operator" v="Transit Co" />
                <tag k="gtfs:route_id" v="10" />
                <member type="relation" ref="300" role="" />
            </relation>
        </osm>
        """

        get_osm_data.process_osm_routes_data(xml_data, out_dir="data/processed")

        with open("data/processed/osm_route_masters.csv", encoding="utf-8", newline="") as handle:
                route_master_rows = list(csv.DictReader(handle))
        with open("data/processed/osm_route_master_members.csv", encoding="utf-8", newline="") as handle:
                route_master_member_rows = list(csv.DictReader(handle))
        with open("data/processed/osm_route_relations.csv", encoding="utf-8", newline="") as handle:
                route_relation_rows = list(csv.DictReader(handle))
        with open("data/processed/osm_route_relation_stops.csv", encoding="utf-8", newline="") as handle:
                route_stop_rows = list(csv.DictReader(handle))
        assert route_master_rows[0]["route_master_id"] == "400"
        assert route_master_rows[0]["gtfs_route_id"] == "10"
        assert route_master_member_rows[0]["relation_id"] == "300"
        assert route_relation_rows[0]["relation_id"] == "300"
        assert route_relation_rows[0]["route_master_id"] == "400"
        assert route_relation_rows[0]["family_origin"] == "route_master"
        assert route_relation_rows[0]["synthetic_family_key"] == "route_master:400"
        assert route_stop_rows[0]["osm_node_id"] == "100"
        assert route_stop_rows[0]["uic_ref"] == "8500"
        assert route_stop_rows[1]["osm_node_id"] == "way_200"
        assert route_stop_rows[1]["stop_label"] == "Station B"
        assert route_stop_rows[1]["direction_id"] == "0"


def test_process_osm_routes_data_deduplicates_duplicate_route_master_relation_members(monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        from matching_and_import_db.downloader import get_osm_data

        xml_data = """
        <osm version="0.6">
            <relation id="300" version="1">
                <tag k="type" v="route" />
                <tag k="route" v="bus" />
                <tag k="ref" v="10" />
            </relation>
            <relation id="400" version="1">
                <tag k="type" v="route_master" />
                <tag k="route_master" v="bus" />
                <tag k="ref" v="10" />
                <member type="relation" ref="300" role="forward" />
                <member type="relation" ref="300" role="backward" />
            </relation>
        </osm>
        """

        get_osm_data.process_osm_routes_data(xml_data, out_dir="data/processed")

        with open("data/processed/osm_route_master_members.csv", encoding="utf-8", newline="") as handle:
                route_master_member_rows = list(csv.DictReader(handle))

        assert route_master_member_rows == [{
                "run_id": route_master_member_rows[0]["run_id"],
                "route_master_id": "400",
                "relation_id": "300",
                "member_sequence": "0",
                "member_role": "forward",
        }]