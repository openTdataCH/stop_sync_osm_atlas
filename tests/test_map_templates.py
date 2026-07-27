import pytest


COMMON_MAP_SCRIPTS = [
    "vendor/leaflet/leaflet.js",
    "js/shared/constants.js",
    "js/shared/utils.js",
    "js/components/mobile-filters.js",
    "js/components/header-summary.js",
    "js/components/map-shared.js",
    "js/components/filter-chip-utils.js",
    "js/components/popup-utils.js",
    "js/components/popup-renderer.js",
    "js/components/move_popup.js",
    "js/components/map-renderer.js",
    "js/components/map-core.js",
    "js/components/map-popup-controller.js",
    "js/components/line-renderer.js",
    "js/components/operator-dropdown.js",
]


@pytest.mark.parametrize("path", ["/", "/problems"])
def test_primary_maps_load_the_shared_asset_sequence_once(client, path):
    response = client.get(path)
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    positions = []
    for script in COMMON_MAP_SCRIPTS:
        assert html.count(script) == 1
        positions.append(html.index(script))
    assert positions == sorted(positions)


def test_index_map_loads_registry_and_viewport_before_its_controller(client):
    html = client.get("/").get_data(as_text=True)

    assert html.index("js/components/map-layer-registry.js") < html.index(
        "js/components/map-viewport-loader.js"
    )
    assert html.index("js/components/map-viewport-loader.js") < html.index(
        "js/pages/main.js"
    )


def test_problems_map_loads_its_feature_renderer_before_controller(client):
    html = client.get("/problems").get_data(as_text=True)

    assert html.index("js/pages/problems-state.js") < html.index(
        "js/pages/problems-renderer.js"
    )
    assert html.index("js/pages/problems-renderer.js") < html.index(
        "js/pages/problems-map.js"
    )
    assert html.index("js/pages/problems-map.js") < html.index(
        "js/pages/problems.js"
    )
