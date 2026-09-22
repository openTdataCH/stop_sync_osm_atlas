const loadBrowserScript = require('./load-browser-script');
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
    loadBrowserScript(path.join(__dirname, '../../static/js/pages/routes.js'));
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
    // The native <details> toggle remains queued after changing `open` above.
    // Page teardown must remove its listener before that event is delivered.
    await new Promise(resolve => setTimeout(resolve, 0));
    panel.dispatchEvent(new Event('toggle'));
    expect(window.MapComponents.MapCore.create).toHaveBeenCalledTimes(1);
});

test('inline comparisons update only their own map and restore the fixed variant when cleared', async () => {
    const direction = { atlas_uic_groups: [{ members: [
        { stop_id: 'fixed', lat: 47, lon: 8, stop_type: 'atlas_unmatched' }
    ] }], osm_uic_groups: [] };
    document.body.innerHTML = [0, 1].map(index => `
        <details class="route-card__panel--map"><section class="variant-comparison"></section>
          <div class="route-card__map-shell"><div id="routeMap${index}" class="route-card__map" data-map-index="${index}"></div></div>
          <script class="variant-data" data-map-index="${index}" type="application/json">${JSON.stringify(direction)}</script>
        </details>`).join('');
    window.AppConstants = { MAP: { DEFAULT_CENTER: [0, 0], DEFAULT_ZOOM: 2, MIN_ZOOM: 2, MAX_ZOOM: 20, MAX_BOUNDS: null } };
    require('./load-map-components')();
    const layer = () => ({ markers: [], addLayer(value) { this.markers.push(value); }, clearLayers() { this.markers = []; } });
    const maps = [];
    window.MapComponents.MapCore = { create: jest.fn(() => {
        const core = { map: { getZoom: () => 12, on: jest.fn(), off: jest.fn(), fitBounds: jest.fn(), invalidateSize: jest.fn() },
            layers: { markers: layer(), lines: layer() }, destroy: jest.fn() };
        maps.push(core);
        return core;
    }) };
    window.L = global.L = {
        circleMarker: jest.fn((position, options) => ({ position, options })),
        polyline: jest.fn((positions, options) => ({ positions, options })),
        latLngBounds: jest.fn(() => ({ pad() { return this; } }))
    };
    loadBrowserScript(path.join(__dirname, '../../static/js/pages/routes.js'));
    document.dispatchEvent(new Event('DOMContentLoaded'));
    const panels = [...document.querySelectorAll('details')];
    panels.forEach(panel => { panel.open = true; panel.dispatchEvent(new Event('toggle')); });
    const comparison = { rows: [
        { atlas: { id: 1, stop_ids: ['fixed'], lat: 47, lon: 8 },
            osm: { id: 2, stop_ids: ['osm:2'], lat: 47.0001, lon: 8.0001 }, match_type: 'resolved_sloid_match' },
        { atlas: null, osm: { id: 3, stop_ids: ['osm:3'], lat: 47.1, lon: 8.1 }, match_type: null },
        { atlas: { id: 4, stop_ids: ['missing'], lat: null, lon: null },
            osm: { id: 5, stop_ids: ['osm:5'], lat: null, lon: null }, match_type: 'uic_match' }
    ] };
    const first = panels[0].querySelector('section');
    first.dispatchEvent(new CustomEvent('routecomparisonchange', { bubbles: true, detail: comparison }));
    expect(maps[0].layers.markers.markers.map(marker => marker.position)).toEqual([[47, 8], [47.0001, 8.0001], [47.1, 8.1]]);
    expect(maps[0].layers.lines.markers).toHaveLength(1);
    expect(maps[0].layers.lines.markers[0].options.color).toBe('#174092');
    expect(maps[1].layers.markers.markers.map(marker => marker.position)).toEqual([[47, 8]]);
    expect(maps[1].layers.lines.markers).toHaveLength(0);
    first.dispatchEvent(new CustomEvent('routecomparisonchange', { bubbles: true, detail: null }));
    expect(maps[0].layers.markers.markers.map(marker => marker.position)).toEqual([[47, 8]]);
    expect(maps[0].layers.lines.markers).toHaveLength(0);
    window.dispatchEvent(new Event('pagehide'));
    await new Promise(resolve => setTimeout(resolve, 0));
});
