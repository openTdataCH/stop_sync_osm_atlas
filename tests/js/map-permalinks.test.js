const loadBrowserScript = require('./load-browser-script');
const path = require('path');

const SCRIPT_PATH = path.join(__dirname, '../../static/js/pages/main.js');
const POPUP_OPTIONS = { permalinks: true };

function createLayerGroup() {
    return {
        addLayer: jest.fn(),
        removeLayer: jest.fn(),
        clearLayers: jest.fn(),
        addTo: jest.fn().mockReturnThis()
    };
}

// Enough of a Leaflet map to dispatch moveend/popupopen/popupclose.
function createMap() {
    const handlers = {};
    const map = {
        zoom: 14,
        center: { lat: 47.3769, lng: 8.5417 },
        on: jest.fn((name, handler) => { (handlers[name] = handlers[name] || []).push(handler); }),
        off: jest.fn((name, handler) => { handlers[name] = (handlers[name] || []).filter(h => h !== handler); }),
        fire: (name, event) => (handlers[name] || []).slice().forEach(handler => handler(event || {})),
        getContainer: () => document.getElementById('map'),
        getZoom: jest.fn(() => map.zoom),
        getCenter: jest.fn(() => ({ lat: map.center.lat, lng: map.center.lng })),
        setView: jest.fn((center, zoom) => {
            map.center = { lat: center[0], lng: center[1] };
            map.zoom = zoom;
            map.fire('moveend');
        }),
        getSize: () => ({ x: 1200, y: 600 }),
        panBy: jest.fn(),
        removeLayer: jest.fn(),
        invalidateSize: jest.fn()
    };
    return map;
}

function createPopup(content) {
    const element = document.createElement('div');
    element.innerHTML = content;
    return { setLatLng() { return this; }, getElement: () => element };
}

async function flushPromises() {
    for (let i = 0; i < 5; i += 1) await Promise.resolve();
}

// A matched pair: opened as ATLAS it links by SLOID, opened as OSM by way id.
const matchedStop = {
    id: 1,
    stop_type: 'matched',
    sloid: 'ch:1:sloid:7000',
    osm_node_id: 'way_456',
    atlas_lat: 46.9,
    atlas_lon: 7.4,
    osm_lat: 46.9001,
    osm_lon: 7.4001
};

describe('Index map permalinks', () => {
    let map;
    let mapCoreOptions;
    let viewportLoader;

    function openPage(url) {
        history.replaceState(null, '', url);
        window.IndexMapPage.init();
    }

    beforeAll(() => {
        document.body.innerHTML = '<div id="map"></div>';
        window.L = global.L = { layerGroup: jest.fn(createLayerGroup) };
        window.AppConstants = global.AppConstants = {
            MAP: {
                ZOOM_MARKER_THRESHOLD: 13,
                ZOOM_LINE_THRESHOLD: 13,
                LABEL_ICON_MIN_ZOOM: 18,
                ADDITIONAL_BANNER_ZOOM_LEVELS: 2,
                DEFAULT_CENTER: [47.3769, 8.5417],
                DEFAULT_ZOOM: 14,
                MIN_ZOOM: 8,
                MAX_ZOOM: 20,
                MAX_BOUNDS: [[45.5, 5.5], [48, 11]],
                MAX_BOUNDS_VISCOSITY: 1
            },
            DATA_LOADING: { GENERAL_LIMIT: 1800, VIEW_DEBOUNCE_MS: 150 },
            COLORS: {}
        };
        window.activeFilters = global.activeFilters = {
            stopType: [], matchMethods: [], station: [], stationTypes: [], routeDirections: [],
            transportTypes: [], osmEntityTypes: [], atlasOperators: [], osmOperators: [],
            osmGroups: [], showDuplicatesOnly: false, topN: null
        };
        window.getActiveFilterCount = jest.fn(() => 0);
        require('./load-map-components')();
        loadBrowserScript(path.join(__dirname, '../../static/js/components/popup-utils.js'));
        loadBrowserScript(path.join(__dirname, '../../static/js/components/popup-renderer.js'));
        window.MapRenderer = {
            ...window.MapRenderer,
            createPopupWithOptions: jest.fn(createPopup),
            renderEntities: jest.fn((entities, layer, options) => entities.map(() => {
                const marker = {
                    bindPopup(popup) { marker.popup = popup; return marker; },
                    openPopup() { map.fire('popupopen', { popup: marker.popup }); }
                };
                options.bindPopup(marker);
                return marker;
            }))
        };
        window.LineRenderer = global.LineRenderer = { clearLines: jest.fn(), drawRelationships: jest.fn() };
        viewportLoader = {
            reload: jest.fn(() => Promise.resolve({ status: 'loaded' })),
            invalidate: jest.fn(),
            pause: jest.fn(() => jest.fn()),
            destroy: jest.fn()
        };
        window.MapComponents = {
            MapCore: {
                create: jest.fn(options => {
                    mapCoreOptions = options;
                    map = createMap();
                    return { map, destroy: jest.fn() };
                })
            },
            MapLayerRegistry: { create: () => ({ reconcile: jest.fn(), clear: jest.fn(), destroy: jest.fn() }) },
            MapPopupController: { create: () => ({ attach: jest.fn(), detach: jest.fn(), invalidate: jest.fn(), destroy: jest.fn() }) },
            MapViewportLoader: { create: () => viewportLoader }
        };
        const jqueryResult = { ready: jest.fn(), on: jest.fn() };
        const jquery = jest.fn(() => jqueryResult);
        jquery.getJSON = jest.fn();
        window.$ = global.$ = jquery;

        loadBrowserScript(path.join(__dirname, '../../static/js/shared/permalinks.js'));
        loadBrowserScript(SCRIPT_PATH);
    });

    beforeEach(() => {
        jest.useFakeTimers();
    });

    afterEach(() => {
        window.IndexMapPage.destroy();
        jest.runOnlyPendingTimers();
        jest.useRealTimers();
        document.getElementById('map').innerHTML = '';
        history.replaceState(null, '', '/');
    });

    test('starts at a valid hash view and silently ignores an invalid one', () => {
        openPage('/#map=16/46.94809/7.44744');
        expect(mapCoreOptions.view).toEqual({ center: [46.94809, 7.44744], zoom: 16 });
        window.IndexMapPage.destroy();

        openPage('/#map=16/52.5/13.4');
        expect(mapCoreOptions.view).toEqual({ center: [47.3769, 8.5417], zoom: 14 });
    });

    test('parses stop parameters into /api/stop_by_id identifiers and back', () => {
        expect(window.parseStopPermalink('?sloid=ch:1:sloid:7000')).toEqual({ type: 'atlas', identifier: 'ch:1:sloid:7000' });
        expect(window.parseStopPermalink('?osm=node/123')).toEqual({ type: 'osm', identifier: '123' });
        expect(window.parseStopPermalink('?osm=way%2F456')).toEqual({ type: 'osm', identifier: 'way_456' });
        ['?osm=relation/1', '?osm=node/abc', '?osm=123', '?osm=way/', '?sloid=', ''].forEach(search => {
            expect(window.parseStopPermalink(search)).toBeNull();
        });

        expect(window.Permalinks.stopParams('atlas', 'ch:1:sloid:7000')).toEqual({ sloid: 'ch:1:sloid:7000' });
        expect(window.Permalinks.stopParams('osm', '123')).toEqual({ osm: 'node/123' });
        expect(window.Permalinks.stopParams('osm', 'way_456')).toEqual({ osm: 'way/456' });
        expect(window.Permalinks.stopParams('gtfs', '8507000:0:1')).toBeNull();
    });

    test('writes the view to the hash once per burst of moves without loading data', () => {
        openPage('/?atlas_operator=EX');
        const historyLength = history.length;
        map.center = { lat: 46.948091234, lng: 7.4474449 };
        map.zoom = 15;

        map.fire('moveend');
        map.fire('moveend');
        expect(window.location.hash).toBe('');
        jest.advanceTimersByTime(300);

        expect(window.location.href).toBe('http://localhost/?atlas_operator=EX#map=15/46.94809/7.44744');
        expect(history.length).toBe(historyLength);
        expect(viewportLoader.reload).not.toHaveBeenCalled();
        expect(map.setView).not.toHaveBeenCalled();
    });

    test('follows a hash pasted into an open page and repairs an unusable one', () => {
        openPage('/#map=14/47.3769/8.5417');

        history.replaceState(null, '', '/#map=12/46.9/7.4');
        window.dispatchEvent(new Event('hashchange'));
        expect(map.setView).toHaveBeenCalledWith([46.9, 7.4], 12);

        history.replaceState(null, '', '/#');
        window.dispatchEvent(new Event('hashchange'));
        expect(window.location.hash).toBe('#map=12/46.9/7.4');
    });

    test('names the most recent open stop popup in the query, by the side it was opened as', () => {
        openPage('/?osm_operator=Example+%26+Co&atlas_operator=EX#map=14/47.3769/8.5417');
        const historyLength = history.length;
        const operators = '?osm_operator=Example+%26+Co&atlas_operator=EX';
        const atlasPopup = createPopup(PopupRenderer.generatePopupHtml(matchedStop, 'atlas', POPUP_OPTIONS));
        const osmPopup = createPopup(PopupRenderer.generatePopupHtml(matchedStop, 'osm', POPUP_OPTIONS));

        map.fire('popupopen', { popup: atlasPopup });
        expect(window.location.search).toBe(operators + '&sloid=ch:1:sloid:7000');
        map.fire('popupopen', { popup: osmPopup });
        expect(window.location.search).toBe(operators + '&osm=way/456');

        // Error or loading content has no stop identity and leaves the URL alone.
        map.fire('popupopen', { popup: createPopup('<div>Unable to load stop details.</div>') });
        expect(window.location.search).toBe(operators + '&osm=way/456');

        map.fire('popupclose', { popup: osmPopup });
        expect(window.location.search).toBe(operators + '&sloid=ch:1:sloid:7000');
        map.fire('popupclose', { popup: atlasPopup });
        expect(window.location.search).toBe(operators);

        expect(window.location.hash).toBe('#map=14/47.3769/8.5417');
        expect(history.length).toBe(historyLength);
        expect(viewportLoader.reload).not.toHaveBeenCalled();
    });

    test('keeps the stop parameter when the page is torn down on unload', () => {
        openPage('/');
        const popup = createPopup(PopupRenderer.generatePopupHtml(matchedStop, 'atlas', POPUP_OPTIONS));
        map.fire('popupopen', { popup });

        window.IndexMapPage.destroy();
        map.fire('popupclose', { popup });

        expect(window.location.search).toBe('?sloid=ch:1:sloid:7000');
    });

    test('renders Copy link next to the iD editor link only when the page asks for it', () => {
        const container = document.createElement('div');
        container.innerHTML = PopupRenderer.generatePopupHtml(matchedStop, 'osm', POPUP_OPTIONS);
        const links = container.querySelector('.popup-initial-view .osm-editor-link-container');

        expect(links.querySelector('.osm-editor-link').getAttribute('href')).toBe('https://www.openstreetmap.org/edit?way=456');
        expect(links.querySelector('.popup-copy-link').dataset).toMatchObject({ permalinkType: 'osm', permalinkRef: 'way_456' });
        expect(PopupRenderer.generatePopupHtml(matchedStop, 'atlas', POPUP_OPTIONS)).toContain('data-permalink-ref="ch:1:sloid:7000"');
        expect(PopupRenderer.generatePopupHtml(matchedStop, 'osm')).not.toContain('popup-copy-link');
    });

    test('Copy link copies the stop link with the current view and confirms briefly', async () => {
        const writeText = jest.fn(() => Promise.resolve());
        Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
        try {
            openPage('/?atlas_operator=EX&sloid=ch:1:sloid:1');
            map.center = { lat: 46.94809, lng: 7.44744 };
            map.zoom = 17;
            document.getElementById('map').innerHTML = PopupRenderer.generatePopupHtml(matchedStop, 'osm', POPUP_OPTIONS);
            const button = document.querySelector('#map .popup-copy-link');

            button.querySelector('i').click();
            await flushPromises();

            expect(writeText).toHaveBeenCalledWith('http://localhost/?atlas_operator=EX&osm=way/456#map=17/46.94809/7.44744');
            expect(button.textContent.trim()).toBe('Copied');
            jest.advanceTimersByTime(1500);
            expect(button.textContent.trim()).toBe('Copy link');
            expect(window.location.search).toBe('?atlas_operator=EX&sloid=ch:1:sloid:1');
        } finally {
            delete navigator.clipboard;
        }
    });

    test('a ?osm= link opens the stop with exactly one /api/stop_by_id call', async () => {
        openPage('/?atlas_operator=EX&osm=way/456#map=10/46.5/7.5');
        expect(mapCoreOptions.view).toEqual({ center: [46.5, 7.5], zoom: 10 });
        $.getJSON.mockImplementation((url, params, success) => {
            success({ stop: matchedStop, center_lat: 46.9001, center_lon: 7.4001, popup_view_type: 'osm' });
            return { fail: jest.fn() };
        });

        await expect(window.openStopFromUrl()).resolves.toBe(true);
        jest.advanceTimersByTime(300);

        expect($.getJSON).toHaveBeenCalledTimes(1);
        expect($.getJSON).toHaveBeenCalledWith(
            '/api/stop_by_id',
            { identifier: 'way_456', identifier_type: 'osm_node_id' },
            expect.any(Function)
        );
        expect(map.setView).toHaveBeenCalledWith([46.9001, 7.4001], 16, { animate: false });
        expect(map.panBy).toHaveBeenCalledWith([0, -100], { animate: false });
        expect(window.location.search).toBe('?atlas_operator=EX&osm=way/456');
        expect(window.location.hash).toBe('#map=16/46.9001/7.4001');
    });

    test('a missing stop keeps the hash view, drops the parameter and says so without blocking', async () => {
        const message = jest.spyOn(SharedUtils, 'showTemporaryMessage').mockImplementation(() => {});
        try {
            openPage('/?atlas_operator=EX&sloid=ch:1:sloid:%3Cb%3E404#map=10/46.5/7.5');
            $.getJSON.mockImplementation(() => ({ fail: callback => callback() }));

            await expect(window.openStopFromUrl()).resolves.toBe(false);

            expect($.getJSON).toHaveBeenCalledTimes(1);
            expect(map.setView).not.toHaveBeenCalled();
            expect(window.location.search).toBe('?atlas_operator=EX');
            expect(window.location.hash).toBe('#map=10/46.5/7.5');
            expect(message).toHaveBeenCalledWith(expect.stringContaining('sloid=ch:1:sloid:&lt;b&gt;404'), 'warning', 6000);

            $.getJSON.mockClear();
            history.replaceState(null, '', '/?osm=relation/1');
            await expect(window.openStopFromUrl()).resolves.toBe(false);
            expect($.getJSON).not.toHaveBeenCalled();
            expect(window.location.search).toBe('');
        } finally {
            message.mockRestore();
        }
    });
});
