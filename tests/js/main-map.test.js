const fs = require('fs');
const path = require('path');

const SCRIPT_PATH = path.join(__dirname, '../../static/js/pages/main.js');

function createLayerGroup() {
    return {
        addLayer: jest.fn(),
        removeLayer: jest.fn(),
        clearLayers: jest.fn(),
        addTo: jest.fn().mockReturnThis()
    };
}

describe('Index map adapter', () => {
    let map;
    let mapCore;
    let markerRegistry;
    let popupController;
    let viewportController;
    let viewportOptions;
    let mapCoreOptions;
    let currentZoom;
    let activeFilterCount;

    beforeAll(() => {
        document.body.innerHTML = '<div id="map"></div><div id="zoomBannerInfo" class="d-none"></div>';
        delete window.map;

        currentZoom = 17;
        activeFilterCount = 0;
        const bounds = {
            pad: jest.fn(function () { return this; }),
            contains: jest.fn(() => true),
            getSouth: () => 46,
            getNorth: () => 47,
            getWest: () => 7,
            getEast: () => 8
        };
        map = {
            getZoom: jest.fn(() => currentZoom),
            getBounds: jest.fn(() => bounds),
            setView: jest.fn(),
            removeLayer: jest.fn(),
            invalidateSize: jest.fn()
        };
        mapCore = {
            map,
            baseLayers: { OpenStreetMap: {} },
            destroy: jest.fn()
        };
        markerRegistry = {
            reconcile: jest.fn(),
            clear: jest.fn(),
            destroy: jest.fn()
        };
        popupController = {
            attach: jest.fn(),
            detach: jest.fn(),
            invalidate: jest.fn(),
            destroy: jest.fn()
        };
        viewportController = {
            reload: jest.fn(() => Promise.resolve({ status: 'loaded' })),
            invalidate: jest.fn(),
            pause: jest.fn(() => jest.fn()),
            destroy: jest.fn()
        };

        class ClusterManager {
            constructor() {
                this.entries = [];
            }

            addMarker(lat, lon, markerData) {
                this.entries.push({ lat, lon, markerData });
            }

            getClusteredData() {
                return this.entries.slice();
            }
        }

        window.L = global.L = {
            layerGroup: jest.fn(createLayerGroup),
            polyline: jest.fn(() => ({}))
        };
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
                MAX_NATIVE_ZOOM: 19,
                MAX_BOUNDS: [[45.5, 5.5], [48, 11]],
                MAX_BOUNDS_VISCOSITY: 1
            },
            DATA_LOADING: {
                GENERAL_LIMIT: 1800,
                VIEW_DEBOUNCE_MS: 150
            },
            COLORS: {}
        };
        window.activeFilters = global.activeFilters = {
            stopType: [],
            matchMethods: [],
            station: [],
            stationTypes: [],
            routeDirections: [],
            transportTypes: [],
            osmEntityTypes: [],
            atlasOperators: [],
            osmOperators: [],
            osmGroups: [],
            showDuplicatesOnly: false,
            topN: null
        };
        window.getActiveFilterCount = jest.fn(() => activeFilterCount);
        window.MapShared = {
            getAtlasMarkerIdentity: stop => stop.sloid || stop.id || null,
            getViewportZoomPolicy: zoom => ({
                isOverview: zoom < 13,
                isFullDetail: zoom >= 15,
                shouldShowBanner: zoom < 15,
                limit: zoom < 15 ? 1800 : null,
                mode: zoom < 13 ? 'overview' : (zoom < 15 ? 'limited' : 'full')
            }),
            createEntityKey: (type, stop) => {
                const identity = type === 'atlas'
                    ? (stop.sloid || stop.id)
                    : (stop.osm_node_id || stop.id);
                return identity == null ? null : type + ':' + identity;
            }
        };
        window.MapRenderer = {
            MarkerClusterManager: ClusterManager,
            getMarkerRenderSignature: jest.fn((type, color, data, zoom) =>
                [type, color, zoom < 18 ? 'circle' : 'label', data.osmNodeType || 'plain'].join('|')),
            createAtlasMarker: jest.fn(() => ({
                options: {}, setLatLng: jest.fn(), on: jest.fn(), off: jest.fn(),
                bindPopup: jest.fn(), openPopup: jest.fn(), closePopup: jest.fn(), unbindPopup: jest.fn()
            })),
            createOsmMarker: jest.fn(() => ({
                options: {}, setLatLng: jest.fn(), on: jest.fn(), off: jest.fn(),
                bindPopup: jest.fn(), openPopup: jest.fn(), closePopup: jest.fn(), unbindPopup: jest.fn()
            })),
            createPopupWithOptions: jest.fn(content => ({ content })),
            createMarkersWithOverlapHandling: jest.fn(() => [])
        };
        window.PopupRenderer = global.PopupRenderer = {
            generatePopupHtml: jest.fn(() => 'popup'),
            generateSingleAtlasBubbleHtml: jest.fn(() => 'atlas popup'),
            generateSingleOsmBubbleHtml: jest.fn(() => 'osm popup')
        };
        window.LineRenderer = global.LineRenderer = {
            clearLines: jest.fn(),
            drawAll: jest.fn()
        };
        window.MapComponents = {
            MapCore: {
                create: jest.fn(options => {
                    mapCoreOptions = options;
                    return mapCore;
                })
            },
            MapLayerRegistry: { create: jest.fn(() => markerRegistry) },
            MapPopupController: { create: jest.fn(() => popupController) },
            MapViewportLoader: {
                create: jest.fn(options => {
                    viewportOptions = options;
                    return viewportController;
                })
            }
        };
        window.HeaderSummary = { bind: jest.fn() };
        window.MobileFilters = {
            isMobileViewport: jest.fn(() => false),
            bind: jest.fn()
        };

        const jqueryResult = {
            ready: jest.fn(),
            on: jest.fn(),
            each: jest.fn(),
            empty: jest.fn(),
            html: jest.fn(),
            length: 0
        };
        const jquery = jest.fn(() => jqueryResult);
        jquery.getJSON = jest.fn();
        window.$ = global.$ = jquery;

        window.eval(fs.readFileSync(SCRIPT_PATH, 'utf8'));
        window.IndexMapPage.init();
    });

    afterAll(() => {
        window.IndexMapPage.destroy();
    });

    test('initializes MapCore with the Index map contract without publishing window.map', () => {
        expect(mapCoreOptions).toEqual(expect.objectContaining({
            container: 'map',
            view: {
                center: [47.3769, 8.5417],
                zoom: 14
            },
            mapOptions: expect.objectContaining({
                minZoom: 8,
                maxZoom: 20,
                zoomControl: false
            }),
            rendererPadding: expect.any(Function),
            defaultBaseLayer: 'OpenStreetMap',
            popupBehavior: true,
            controls: {
                zoom: { position: 'bottomleft' },
                layers: { position: 'bottomleft' }
            }
        }));
        expect(window.map).toBeUndefined();
    });

    test('builds filter-aware identities without tying uncapped cache entries to an exact zoom', () => {
        currentZoom = 17;
        const first = window.IndexMapPage.getViewportPolicy(17);
        const second = window.IndexMapPage.getViewportPolicy(18);
        expect(first.identity).toBe(second.identity);

        activeFilters.osmOperators = ['TL'];
        activeFilterCount = 1;
        const filtered = window.IndexMapPage.getViewportPolicy(18);
        expect(filtered.identity).not.toBe(second.identity);
        expect(filtered.identity).toContain('osm_operator=TL');
        activeFilters.osmOperators = [];
        activeFilterCount = 0;
    });

    test('reconciles stable marker keys on cache hits and changes representation at the icon threshold', () => {
        const payload = [{
            id: 'atlas-id',
            sloid: 'ch:1:sloid:1',
            stop_type: 'atlas_unmatched',
            lat: 46.5,
            lon: 7.5
        }];

        viewportOptions.onData(payload, { zoom: 17, cacheHit: false, reason: 'load' });
        viewportOptions.onData(payload, { zoom: 18, cacheHit: true, reason: 'zoomend' });

        const firstDescriptors = markerRegistry.reconcile.mock.calls[0][0];
        const secondDescriptors = markerRegistry.reconcile.mock.calls[1][0];
        expect(firstDescriptors[0].key).toBe('atlas:ch:1:sloid:1');
        expect(secondDescriptors[0].key).toBe(firstDescriptors[0].key);
        expect(secondDescriptors[0].renderSignature).not.toBe(firstDescriptors[0].renderSignature);
        expect(LineRenderer.drawAll).toHaveBeenCalledTimes(2);
    });

    test('reuses a contained uncapped result across zoom-in but never a capped one', () => {
        const requestBounds = { contains: jest.fn(() => true) };
        const context = { zoom: 18, bounds: map.getBounds() };
        const uncapped = {
            zoom: 17,
            requestBounds,
            data: { stops: [], meta: { has_more: false } }
        };
        const capped = {
            zoom: 17,
            requestBounds,
            data: { stops: [], meta: { has_more: true } }
        };

        expect(viewportOptions.shouldReuse(uncapped, context)).toBe(true);
        expect(viewportOptions.shouldReuse(capped, context)).toBe(false);
    });

    test('passes the loader AbortSignal to native fetch and serializes the viewport', async () => {
        const signal = { test: 'signal' };
        window.fetch = global.fetch = jest.fn(() => Promise.resolve({
            ok: true,
            json: () => Promise.resolve([])
        }));
        const requestBounds = map.getBounds();

        await viewportOptions.load({ zoom: 18, requestBounds, signal });

        expect(fetch).toHaveBeenCalledWith(
            expect.stringContaining('/api/data?'),
            expect.objectContaining({ signal })
        );
        const url = fetch.mock.calls[0][0];
        expect(url).toContain('min_lat=46');
        expect(url).toContain('max_lon=8');
        expect(url).toContain('zoom=18');
    });

    test('aborts Top N work and rejects a late response after leaving Top N mode', () => {
        let successCallback;
        let failureCallback;
        let alwaysCallback;
        const request = {
            readyState: 1,
            abort: jest.fn(function () { request.readyState = 0; }),
            fail: jest.fn(function (callback) {
                failureCallback = callback;
                return request;
            }),
            always: jest.fn(function (callback) {
                alwaysCallback = callback;
                return request;
            })
        };
        $.getJSON.mockImplementation((_url, _params, callback) => {
            successCallback = callback;
            return request;
        });
        activeFilters.topN = 10;
        activeFilters.stopType = ['matched'];

        window.loadTopNMatches();
        activeFilters.topN = null;
        window.loadDataForViewport();
        successCallback([{
            id: 'late',
            sloid: 'late-sloid',
            osm_node_id: 'late-osm',
            stop_type: 'matched',
            atlas_lat: 46.5,
            atlas_lon: 7.5,
            osm_lat: 46.6,
            osm_lon: 7.6
        }]);

        expect(request.abort).toHaveBeenCalledTimes(1);
        expect(window.MapRenderer.createMarkersWithOverlapHandling).not.toHaveBeenCalled();
        expect(failureCallback).toEqual(expect.any(Function));
        expect(alwaysCallback).toEqual(expect.any(Function));
        activeFilters.stopType = [];
    });
});
