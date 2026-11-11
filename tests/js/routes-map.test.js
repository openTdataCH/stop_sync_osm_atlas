const loadBrowserScript = require('./load-browser-script');
const path = require('path');

// Leaflet markers as far as the stop popup controller uses them.
function fakeMarker(fields) {
    const handlers = {};
    return {
        ...fields, handlers, popup: null, open: false,
        on(event, callback) { handlers[event] = callback; },
        off(event) { delete handlers[event]; },
        bindPopup(popup) { this.popup = popup; },
        unbindPopup() { this.popup = null; },
        getPopup() { return this.popup; },
        openPopup() { this.open = true; },
        closePopup() { this.open = false; },
        isPopupOpen() { return this.open; }
    };
}

function loadRouteMapComponents() {
    require('./load-map-components')();
    loadBrowserScript(path.join(__dirname, '../../static/js/components/map-popup-controller.js'));
}

test('route previews preserve grouped order, refresh labels at zoom 18, and toggle subdued context', async () => {
    const direction = {
        gtfs_uic_groups: [{ members: [
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
    window.AppConstants = { MAP: { DEFAULT_CENTER: [0, 0], DEFAULT_ZOOM: 2, MIN_ZOOM: 2, MAX_ZOOM: 20, MAX_BOUNDS: null, LABEL_ICON_MIN_ZOOM: 18 } };
    loadRouteMapComponents();
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
        marker: jest.fn((position, options) => fakeMarker({ kind: 'icon', position, options })),
        circleMarker: jest.fn((position, options) => fakeMarker({ kind: 'circle', position, options })),
        divIcon: jest.fn(options => options),
        latLngBounds: jest.fn(() => ({ pad() { return this; }, getSouth: () => 46.9, getNorth: () => 47.2,
            getWest: () => 7.9, getEast: () => 8.2 }))
    };
    window.fetch = global.fetch = jest.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve([
        { id: 99, sloid: 'context', atlas_lat: 47.2, atlas_lon: 8.2, stop_type: 'atlas_unmatched' },
        { id: 2, sloid: 'source:a', atlas_lat: 47.1, atlas_lon: 8.1, stop_type: 'matched' }
    ]) }));
    loadBrowserScript(path.join(__dirname, '../../static/js/shared/permalinks.js'));
    loadBrowserScript(path.join(__dirname, '../../static/js/components/header-summary.js'));
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
    const direction = { gtfs_uic_groups: [{ members: [
        { stop_id: 'fixed', lat: 47, lon: 8, stop_type: 'atlas_unmatched' }
    ] }], osm_uic_groups: [] };
    document.body.innerHTML = [0, 1].map(index => `
        <details class="route-card__panel--map"><section class="variant-comparison"></section>
          <div class="route-card__map-shell"><div id="routeMap${index}" class="route-card__map" data-map-index="${index}"></div></div>
          <script class="variant-data" data-map-index="${index}" type="application/json">${JSON.stringify(direction)}</script>
        </details>`).join('');
    window.AppConstants = { MAP: { DEFAULT_CENTER: [0, 0], DEFAULT_ZOOM: 2, MIN_ZOOM: 2, MAX_ZOOM: 20, MAX_BOUNDS: null, LABEL_ICON_MIN_ZOOM: 18 } };
    loadRouteMapComponents();
    const layer = () => ({ markers: [], addLayer(value) { this.markers.push(value); }, clearLayers() { this.markers = []; } });
    const maps = [];
    window.MapComponents.MapCore = { create: jest.fn(() => {
        const core = { map: { getZoom: () => 12, on: jest.fn(), off: jest.fn(), fitBounds: jest.fn(), invalidateSize: jest.fn() },
            layers: { markers: layer(), lines: layer() }, destroy: jest.fn() };
        maps.push(core);
        return core;
    }) };
    window.L = global.L = {
        circleMarker: jest.fn((position, options) => fakeMarker({ position, options })),
        polyline: jest.fn((positions, options) => ({ positions, options })),
        latLngBounds: jest.fn(() => ({ pad() { return this; } }))
    };
    loadBrowserScript(path.join(__dirname, '../../static/js/shared/permalinks.js'));
    loadBrowserScript(path.join(__dirname, '../../static/js/components/header-summary.js'));
    loadBrowserScript(path.join(__dirname, '../../static/js/pages/routes.js'));
    document.dispatchEvent(new Event('DOMContentLoaded'));
    const panels = [...document.querySelectorAll('details')];
    panels.forEach(panel => { panel.open = true; panel.dispatchEvent(new Event('toggle')); });
    const comparison = { rows: [
        { gtfs: { id: 1, stop_ids: ['fixed'], source_id: 'fixed', lat: 47, lon: 8,
            partners: [{ stop_id: 'osm:2', lat: 47.0001, lon: 8.0001 }] },
        osm: { id: 2, stop_ids: ['osm:2'], source_id: 'osm:2', lat: 47.0001, lon: 8.0001,
            partners: [{ stop_id: 'fixed', lat: 47, lon: 8 }] }, match_type: 'resolved_sloid_match' },
        { gtfs: null, osm: { id: 3, stop_ids: ['osm:3'], source_id: 'osm:3', lat: 47.1, lon: 8.1, stop_type: 'matched' }, match_type: null },
        { gtfs: { id: 4, stop_ids: ['missing'], lat: null, lon: null },
            osm: { id: 5, stop_ids: ['osm:5'], lat: null, lon: null }, match_type: 'uic_match' },
        // Zürich Selnau: each platform is matched to a stop that only the other variants call at.
        { gtfs: { id: 6, stop_ids: ['platform-2'], source_id: 'platform-2', lat: 47.2, lon: 8.2, stop_type: 'matched',
            partners: [{ stop_id: 'osm:8', lat: 47.3, lon: 8.3 }] },
        osm: { id: 7, stop_ids: ['osm:7'], source_id: 'osm:7', lat: 47.2001, lon: 8.2001,
            partners: [{ stop_id: 'platform-1', lat: 47.4, lon: 8.4 }] }, match_type: null, same_station: true }
    ] };
    const first = panels[0].querySelector('section');
    first.dispatchEvent(new CustomEvent('routecomparisonchange', { bubbles: true, detail: comparison }));
    const markers = maps[0].layers.markers.markers;
    expect(markers.map(marker => marker.position)).toEqual([
        [47, 8], [47.2, 8.2], [47.0001, 8.0001], [47.1, 8.1], [47.2001, 8.2001], [47.3, 8.3], [47.4, 8.4]
    ]);
    // Colours are stop matching, as on the main map, whatever the comparison says.
    expect(markers.map(marker => marker.options.color)).toEqual(['#DC3545', '#174092', '#6C757D', '#4CAF50', '#6C757D', '#4CAF50', '#174092']);
    // The partners neither variant calls at are faded.
    expect(markers.map(marker => marker.options.opacity)).toEqual([1, 1, 1, 1, 1, 0.4, 0.4]);
    // A solid line joins the same stop, a dashed line the same station at
    // another platform, and a dashed ring circles each stop the other lacks.
    // A thin line joins each stop to its own matches, unless the solid line already does.
    const marks = maps[0].layers.lines.markers;
    expect(marks.map(mark => mark.positions || mark.position)).toEqual([
        [[47, 8], [47.0001, 8.0001]], [47.1, 8.1], [[47.2, 8.2], [47.2001, 8.2001]], [47.2, 8.2], [47.2001, 8.2001],
        [[47.2, 8.2], [47.3, 8.3]], [[47.2001, 8.2001], [47.4, 8.4]]
    ]);
    expect(marks.map(mark => mark.options.dashArray || null)).toEqual([null, '3,3', '4,4', '3,3', '3,3', null, null]);
    expect(marks.slice(5).map(mark => mark.options.weight)).toEqual([1.5, 1.5]);
    expect(marks[0].options.color).toBe('#174092');
    // Drawn over the stops: a click on a stop must reach its popup.
    expect(marks.every(mark => mark.options.interactive === false)).toBe(true);
    expect(maps[1].layers.markers.markers.map(marker => marker.position)).toEqual([[47, 8]]);
    expect(maps[1].layers.lines.markers).toHaveLength(0);
    first.dispatchEvent(new CustomEvent('routecomparisonchange', { bubbles: true, detail: null }));
    expect(maps[0].layers.markers.markers.map(marker => marker.position)).toEqual([[47, 8]]);
    expect(maps[0].layers.lines.markers).toHaveLength(0);
    window.dispatchEvent(new Event('pagehide'));
    await new Promise(resolve => setTimeout(resolve, 0));
});

test('preview maps leave the wheel to the page until clicked and ring the stops of hovered rows', async () => {
    const direction = { gtfs_uic_groups: [{ members: [{ stop_id: 'fixed', lat: 47, lon: 8, stop_type: 'matched' }] }], osm_uic_groups: [] };
    document.body.innerHTML = `
        <details class="route-card__panel--map"><section class="variant-comparison"></section>
          <aside class="route-card__map-shell"><div id="routeMap0" class="route-card__map" data-map-index="0"></div></aside>
          <script class="variant-data" data-map-index="0" type="application/json">${JSON.stringify(direction)}</script>
        </details>`;
    window.AppConstants = { MAP: { DEFAULT_CENTER: [0, 0], DEFAULT_ZOOM: 2, MIN_ZOOM: 2, MAX_ZOOM: 20, MAX_BOUNDS: null, LABEL_ICON_MIN_ZOOM: 18 } };
    loadRouteMapComponents();
    const layer = () => ({ markers: [], addLayer(value) { this.markers.push(value); }, clearLayers() { this.markers = []; } });
    let wheelZoom = false;
    const map = {
        getZoom: () => 12, on: jest.fn(), off: jest.fn(), fitBounds: jest.fn(), invalidateSize: jest.fn(), setView: jest.fn(),
        scrollWheelZoom: { enabled: () => wheelZoom, enable: jest.fn(() => { wheelZoom = true; }), disable: jest.fn(() => { wheelZoom = false; }) }
    };
    const layers = { markers: layer(), lines: layer(), highlight: layer() };
    window.MapComponents.MapCore = { create: jest.fn(() => ({ map, layers, destroy: jest.fn() })) };
    window.L = global.L = {
        circleMarker: jest.fn((position, options) => fakeMarker({ position, options })),
        latLngBounds: jest.fn(points => ({ points, getCenter: () => points[0] }))
    };
    loadBrowserScript(path.join(__dirname, '../../static/js/shared/permalinks.js'));
    loadBrowserScript(path.join(__dirname, '../../static/js/components/header-summary.js'));
    loadBrowserScript(path.join(__dirname, '../../static/js/pages/routes.js'));
    document.dispatchEvent(new Event('DOMContentLoaded'));
    const panel = document.querySelector('details');
    panel.open = true;
    panel.dispatchEvent(new Event('toggle'));

    const options = window.MapComponents.MapCore.create.mock.calls[0][0];
    expect(options.mapOptions.scrollWheelZoom).toBe(false);
    expect(options.layerGroups.highlight).toBe(true);
    expect(map.fitBounds).toHaveBeenCalledWith(expect.anything(), { padding: [28, 28], maxZoom: 17 });

    const shell = document.querySelector('aside');
    const mapElement = document.getElementById('routeMap0');
    mapElement.dispatchEvent(new Event('wheel'));
    expect(shell.classList).toContain('is-wheel-hint');
    mapElement.click();
    expect(map.scrollWheelZoom.enable).toHaveBeenCalled();
    expect(shell.classList).not.toContain('is-wheel-hint');
    mapElement.dispatchEvent(new Event('wheel'));
    expect(shell.classList).not.toContain('is-wheel-hint');
    mapElement.dispatchEvent(new Event('mouseleave'));
    expect(wheelZoom).toBe(false);

    const section = document.querySelector('section');
    section.dispatchEvent(new CustomEvent('routecomparisonhover', { bubbles: true, detail: [[47.1, 8.1], [47.2, 8.2]] }));
    expect(layers.highlight.markers.map(marker => [marker.position, marker.options.radius])).toEqual([[[47.1, 8.1], 14], [[47.2, 8.2], 14]]);
    expect(map.setView).not.toHaveBeenCalled();
    section.dispatchEvent(new CustomEvent('routecomparisonhover', { bubbles: true, detail: null }));
    expect(layers.highlight.markers).toHaveLength(0);
    section.dispatchEvent(new CustomEvent('routecomparisonfocus', { bubbles: true, detail: [[47.1, 8.1]] }));
    expect(map.setView).toHaveBeenCalledWith([47.1, 8.1], 16);

    window.dispatchEvent(new Event('pagehide'));
    await new Promise(resolve => setTimeout(resolve, 0));
    mapElement.dispatchEvent(new Event('wheel'));
    expect(shell.classList).not.toContain('is-wheel-hint');
});

test('route stops open their popup by source id, keep it open across a redraw and link to the main map', async () => {
    const direction = {
        gtfs_uic_groups: [{ members: [{ stop_id: 'ch:1:sloid:7', lat: 47, lon: 8, stop_type: 'matched' }] }],
        osm_uic_groups: [{ members: [{ stop_id: 'way_5', lat: 47.0001, lon: 8.0001, stop_type: 'matched' }] }]
    };
    document.body.innerHTML = `
        <details class="route-card__panel--map" data-gtfs-variant="91-10-A-j26-1:0:Zürich Selnau" data-osm-variant="1561015">
          <section class="variant-comparison"></section>
          <aside class="route-card__map-shell">
            <a class="variant-map__main-map" href="/"></a>
            <div id="routeMap0" class="route-card__map" data-map-index="0"></div>
          </aside>
          <script class="variant-data" data-map-index="0" type="application/json">${JSON.stringify(direction)}</script>
        </details>`;
    window.AppConstants = { MAP: { DEFAULT_CENTER: [0, 0], DEFAULT_ZOOM: 2, MIN_ZOOM: 2, MAX_ZOOM: 20, MAX_BOUNDS: null, LABEL_ICON_MIN_ZOOM: 18 } };
    loadRouteMapComponents();
    ['shared/utils', 'shared/permalinks', 'components/popup-utils', 'components/popup-renderer'].forEach(name => {
        loadBrowserScript(path.join(__dirname, '../../static/js/' + name + '.js'));
    });
    const layer = () => ({ markers: [], addLayer(value) { this.markers.push(value); }, clearLayers() { this.markers = []; } });
    const layers = { markers: layer(), lines: layer() };
    let zoom = 17;
    const handlers = {};
    const map = {
        getZoom: () => zoom, getCenter: () => ({ lat: 47.00005, lng: 8.00005 }), getSize: () => ({ x: 400, y: 500 }),
        on: (event, callback) => { handlers[event] = callback; }, off: jest.fn(), fitBounds: jest.fn(), invalidateSize: jest.fn()
    };
    window.MapComponents.MapCore = { create: jest.fn(() => ({ map, layers, destroy: jest.fn() })) };
    window.L = global.L = {
        circleMarker: jest.fn((position, options) => fakeMarker({ position, options })),
        marker: jest.fn((position, options) => fakeMarker({ position, options })),
        divIcon: jest.fn(options => options),
        latLngBounds: jest.fn(() => ({})),
        popup: jest.fn(options => ({ options, setContent(content) { this.content = content; return this; } }))
    };
    window.fetch = global.fetch = jest.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve({ stop: {
        id: 11, sloid: 'ch:1:sloid:7', stop_type: 'atlas_unmatched', atlas_designation_official: 'Uetliberg'
    } }) }));
    loadBrowserScript(path.join(__dirname, '../../static/js/components/header-summary.js'));
    loadBrowserScript(path.join(__dirname, '../../static/js/pages/routes.js'));
    document.dispatchEvent(new Event('DOMContentLoaded'));
    const panel = document.querySelector('details');
    panel.open = true;
    panel.dispatchEvent(new Event('toggle'));

    const [atlasMarker, osmMarker] = layers.markers.markers;
    atlasMarker.handlers.click();
    await new Promise(resolve => setTimeout(resolve, 0));
    expect(fetch).toHaveBeenCalledWith('/api/stop_popup?sloid=ch%3A1%3Asloid%3A7&view_type=atlas', expect.anything());
    expect(atlasMarker.isPopupOpen()).toBe(true);
    expect(atlasMarker.popup.options).toEqual(expect.objectContaining({ autoClose: true, autoPan: true, maxHeight: 408 }));
    expect(atlasMarker.popup.content).toContain('href="/?sloid=ch:1:sloid:7"');
    expect(atlasMarker.popup.content).toContain('Open in main map');
    expect(osmMarker.handlers.click).toEqual(expect.any(Function));

    zoom = 18;
    handlers.zoomend();
    const redrawn = layers.markers.markers[0];
    expect(redrawn).not.toBe(atlasMarker);
    expect(atlasMarker.isPopupOpen()).toBe(false);
    await new Promise(resolve => setTimeout(resolve, 0));
    expect(redrawn.isPopupOpen()).toBe(true);
    expect(fetch).toHaveBeenCalledTimes(1);

    layers.markers.markers[1].handlers.click();
    expect(fetch).toHaveBeenLastCalledWith('/api/stop_popup?osm_node_id=way_5&view_type=osm', expect.anything());

    // The main map opens on the variants this map shows, where this map is.
    const mainMap = document.querySelector('.variant-map__main-map');
    handlers.moveend();
    expect(mainMap.getAttribute('href')).toBe('/?gtfs_variant=91-10-A-j26-1:0:Z%C3%BCrich+Selnau&osm_variant=1561015#map=18/47.00005/8.00005');
    // A comparison with another variant names that one; clearing it brings back the panel's own.
    document.querySelector('section').dispatchEvent(new CustomEvent('routecomparisonchange', { bubbles: true, detail: {
        gtfs: { source_itinerary_id: '91-10-A-j26-1:0:Zürich HB' }, osm: null, rows: []
    } }));
    expect(mainMap.getAttribute('href')).toBe('/?gtfs_variant=91-10-A-j26-1:0:Z%C3%BCrich+HB#map=18/47.00005/8.00005');
    document.querySelector('section').dispatchEvent(new CustomEvent('routecomparisonchange', { bubbles: true, detail: null }));
    expect(mainMap.getAttribute('href')).toContain('?gtfs_variant=91-10-A-j26-1:0:Z%C3%BCrich+Selnau&osm_variant=1561015#map=');

    window.dispatchEvent(new Event('pagehide'));
    await new Promise(resolve => setTimeout(resolve, 0));
});
