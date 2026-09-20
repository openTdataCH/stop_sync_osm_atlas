const fs = require('fs');
const path = require('path');

test('route previews preserve grouped order, refresh labels at zoom 18, and toggle subdued context', async () => {
    const direction = {
        atlas_uic_groups: [{ members: [
            { stop_id: 'source:b', lat: 47, lon: 8, stop_type: 'atlas_unmatched', has_atlas_duplicate: true },
            { stop_id: 'source:a', lat: 47.1, lon: 8.1, stop_type: 'matched' }
        ] }],
        osm_uic_groups: [{ members: [{ stop_id: '2', lat: 47, lon: 8, stop_type: 'matched', osm_node_type: 'platform' }] }]
    };
    document.body.innerHTML = `
        <details class="route-card__panel--map"><div class="route-card__map-shell">
            <div id="routeMap0" class="route-card__map" data-map-index="0"></div>
        </div></details>
        <button class="toggle-context-btn" data-map-index="0"></button>
        <script class="variant-data" data-map-index="0" type="application/json">${JSON.stringify(direction)}</script>`;
    window.AppConstants = { MAP: { DEFAULT_CENTER: [0, 0], DEFAULT_ZOOM: 2, MIN_ZOOM: 2, MAX_ZOOM: 20, MAX_BOUNDS: null } };
    require('./load-map-components')();
    function layer() {
        return { markers: [], addLayer(value) { this.markers.push(value); }, clearLayers() { this.markers = []; } };
    }
    const layers = { markers: layer(), lines: layer() };
    let zoom = 17;
    const handlers = {};
    const map = { getZoom: () => zoom, on: (event, callback) => { handlers[event] = callback; },
        off: jest.fn(), fitBounds: jest.fn(), invalidateSize: jest.fn() };
    window.MapComponents.MapCore = { create: jest.fn(() => ({ map, layers, destroy: jest.fn() })) };
    window.L = global.L = {
        marker: jest.fn((position, options) => ({ kind: 'icon', position, options })),
        circleMarker: jest.fn((position, options) => ({ kind: 'circle', position, options })),
        divIcon: jest.fn(options => options),
        latLngBounds: jest.fn(() => ({ pad() { return this; }, getSouth: () => 46.9, getNorth: () => 47.2,
            getWest: () => 7.9, getEast: () => 8.2 }))
    };
    window.fetch = global.fetch = jest.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve([
        { id: 99, sloid: 'context', atlas_lat: 47.2, atlas_lon: 8.2, stop_type: 'atlas_unmatched' },
        { id: 2, sloid: 'source:a', atlas_lat: 47.1, atlas_lon: 8.1, stop_type: 'matched' }
    ]) }));
    window.eval(fs.readFileSync(path.join(__dirname, '../../static/js/pages/routes.js'), 'utf8'));
    document.dispatchEvent(new Event('DOMContentLoaded'));
    const panel = document.querySelector('details');
    panel.open = true;
    panel.dispatchEvent(new Event('toggle'));
    expect(window.MapComponents.MapCore.create.mock.calls[0][0].mapOptions.maxBounds).toBeNull();
    expect(layers.markers.markers.map(marker => marker.position)).toEqual([[47, 8], [47.1, 8.1], [47, 8]]);
    expect(layers.markers.markers.every(marker => marker.kind === 'circle')).toBe(true);
    expect(layers.markers.markers.map(marker => marker.options.color)).toEqual(['#DC3545', '#174092', '#4CAF50']);
    zoom = 18;
    handlers.zoomend();
    expect(layers.markers.markers.map(marker => marker.kind)).toEqual(['icon', 'circle', 'icon']);
    expect(layers.markers.markers[0].options.icon.html).toContain('>D</text>');
    expect(layers.markers.markers[2].options.icon.html).toContain('>P</text>');
    document.querySelector('button').click();
    for (let i = 0; i < 6; i++) await Promise.resolve();
    expect(layers.markers.markers).toHaveLength(4);
    expect(layers.markers.markers[3].options).toEqual(expect.objectContaining({ opacity: 0.4, fillOpacity: 0.2 }));
    document.querySelector('button').click();
    expect(layers.markers.markers).toHaveLength(3);
    window.dispatchEvent(new Event('pagehide'));
});
