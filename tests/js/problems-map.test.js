const loadBrowserScript = require('./load-browser-script');
const path = require('path');

// Microtasks only, so it also works under fake timers.
const flush = async () => { for (let i = 0; i < 10; i++) await Promise.resolve(); };

// A SharedUtils.fetchJson call the test answers; settling waits for the page's callbacks.
function createRequest(options) {
    let settle;
    const promise = new Promise((resolve, reject) => { settle = { resolve, reject }; });
    const request = {
        promise,
        get aborted() { return !!(options && options.signal && options.signal.aborted); },
        resolve(payload) {
            settle.resolve(payload);
            return flush();
        },
        reject(status) {
            const error = new Error('Request failed with status ' + status);
            error.status = status;
            settle.reject(error);
            return flush();
        },
        abortWith() {
            const error = new Error('The operation was aborted.');
            error.name = 'AbortError';
            settle.reject(error);
            return flush();
        }
    };
    return request;
}

describe('ProblemsMap context loading', () => {
    let contextLayer;
    let requests;
    let renderedChildLayers;
    let problemMap;
    let currentZoom;
    let currentProblem;
    let mapHandlers;
    let popupController;
    let mapCoreResult;
    let fetchJson;

    beforeEach(() => {
        requests = [];
        renderedChildLayers = [];
        contextLayer = {
            clearLayers: jest.fn(),
            addLayer: jest.fn()
        };
        currentZoom = 17;
        currentProblem = null;
        mapHandlers = new Map();
        problemMap = {
            getZoom: jest.fn(() => currentZoom),
            on: jest.fn((eventName, handler) => {
                mapHandlers.set(eventName, handler);
                return problemMap;
            }),
            off: jest.fn((eventName, handler) => {
                if (mapHandlers.get(eventName) === handler) mapHandlers.delete(eventName);
                return problemMap;
            }),
            emit(eventName) {
                const handler = mapHandlers.get(eventName);
                if (handler) handler();
            }
        };

        window.AppConstants = global.AppConstants = {
            MAP: {
                DEFAULT_CENTER: [47.3769, 8.5417],
                DEFAULT_ZOOM: 12,
                ZOOM_LINE_THRESHOLD: 16,
                MAX_ZOOM: 20,
                MAX_NATIVE_ZOOM: 19
            },
            COLORS: {
                ATLAS_MATCHED: '#174092',
                OSM_MATCHED: '#4CAF50',
                ATLAS_UNMATCHED: '#DC3545',
                OSM_UNMATCHED: '#6C757D'
            }
        };

        window.ProblemsState = global.ProblemsState = {
            getShowContext: jest.fn(() => true),
            getCurrentProblem: jest.fn(() => currentProblem),
            getProblemMap: jest.fn(() => problemMap),
            getProblemMarkersLayer: jest.fn(() => mapCoreResult && mapCoreResult.layers.problemMarkers),
            getProblemLinesLayer: jest.fn(() => mapCoreResult && mapCoreResult.layers.problemLines),
            getContextMarkersLayer: jest.fn(() => contextLayer),
            setProblemMap: jest.fn(),
            setOsmLayerProblems: jest.fn(),
            setProblemMarkersLayer: jest.fn(),
            setProblemLinesLayer: jest.fn(),
            setContextMarkersLayer: jest.fn()
        };

        require('./load-map-components')();
        popupController = {
            attach: jest.fn(),
            open: jest.fn(() => Promise.resolve({ status: 'opened' })),
            detach: jest.fn(),
            destroy: jest.fn()
        };
        mapCoreResult = {
            map: problemMap,
            layers: {
                problemMarkers: { name: 'problemMarkers' },
                problemLines: { name: 'problemLines' },
                contextMarkers: contextLayer
            },
            baseLayers: {
                OpenStreetMap: { name: 'osm' }
            },
            invalidateSize: jest.fn(),
            destroy: jest.fn()
        };
        window.MapComponents = {
            MapCore: {
                create: jest.fn(() => mapCoreResult)
            },
            MapPopupController: {
                create: jest.fn(() => popupController)
            }
        };

        global.LineRenderer = {
            drawRelationships: jest.fn()
        };
        window.LineRenderer = global.LineRenderer;

        window.MapRenderer = global.MapRenderer = {
            ...window.MapRenderer,
            renderEntities: jest.fn(markerData => markerData.map(() => ({
                setOpacity: jest.fn()
            }))),
            createPopupWithOptions: jest.fn(content => ({ content }))
        };

        window.PopupRenderer = global.PopupRenderer = {
            generateSingleAtlasBubbleHtml: jest.fn(() => 'single atlas'),
            generateSingleOsmBubbleHtml: jest.fn(() => 'single osm'),
            generatePopupHtml: jest.fn(() => 'popup html')
        };
        window.ProblemsRenderer = global.ProblemsRenderer = {
            drawProblemOnMap: jest.fn()
        };

        global.L = window.L = {
            layerGroup: jest.fn(() => {
                const layer = { addLayer: jest.fn() };
                renderedChildLayers.push(layer);
                return layer;
            })
        };

        fetchJson = jest.spyOn(SharedUtils, 'fetchJson').mockImplementation((_url, _params, options) => {
            const request = createRequest(options);
            requests.push(request);
            return request.promise;
        });

        delete window.ProblemsMap;
        delete window.map;
        const scriptPath = path.join(__dirname, '../../static/js/pages/problems-map.js');
        loadBrowserScript(scriptPath);
        global.ProblemsMap = window.ProblemsMap;
    });

    afterEach(() => {
        jest.useRealTimers();
        fetchJson.mockRestore();
    });

    test('requests the complete fixed context without a row limit and renders all returned stops', async () => {
        const problem = {
            id: 'focused',
            sloid: 'focused-sloid',
            atlas_lat: 46.53,
            atlas_lon: 6.65
        };
        const stops = Array.from({ length: 250 }, (_, index) => ({
            id: `context-${index}`,
            sloid: `context-sloid-${index}`,
            stop_type: 'atlas_unmatched',
            atlas_lat: 46.52 + index * 0.000001,
            atlas_lon: 6.64 + index * 0.000001
        }));

        ProblemsMap.loadContextData(problem);

        expect(fetchJson).toHaveBeenCalledTimes(1);
        expect(fetchJson.mock.calls[0][0]).toBe('/api/data');
        const params = fetchJson.mock.calls[0][1];
        expect(params.min_lat).toBeCloseTo(46.51);
        expect(params.max_lat).toBeCloseTo(46.55);
        expect(params.min_lon).toBeCloseTo(6.63);
        expect(params.max_lon).toBeCloseTo(6.67);
        expect(params).not.toHaveProperty('zoom');
        expect(params).not.toHaveProperty('limit');

        await requests[0].resolve(stops);

        const markerData = MapRenderer.renderEntities.mock.calls[0][0];
        const markerOptions = MapRenderer.renderEntities.mock.calls[0][2];
        expect(markerData).toHaveLength(250);
        expect(markerOptions).toEqual(expect.objectContaining({
            layout: expect.objectContaining({ descriptors: expect.any(Array) }),
            bindPopup: expect.any(Function)
        }));
        expect(markerData.every(entity => entity.emphasis === 'context')).toBe(true);
        expect(LineRenderer.drawRelationships).toHaveBeenCalledWith([], renderedChildLayers[0], expect.any(Map), expect.objectContaining({
            currentZoom: 17,
            isContext: true
        }));
        expect(contextLayer.clearLayers).toHaveBeenCalledTimes(1);
        expect(contextLayer.addLayer).toHaveBeenCalledWith(renderedChildLayers[0]);
    });

    test('an empty successful response clears context left by the previous problem', async () => {
        ProblemsMap.loadContextData({ id: 'problem', atlas_lat: 46.53, atlas_lon: 6.65 });
        await requests[0].resolve([]);

        expect(contextLayer.clearLayers).toHaveBeenCalledTimes(1);
        expect(contextLayer.addLayer).not.toHaveBeenCalled();
        expect(MapRenderer.renderEntities).not.toHaveBeenCalled();
    });

    test('only the newest request may replace the displayed context', async () => {
        const firstProblem = { id: 'first', atlas_lat: 46.53, atlas_lon: 6.65 };
        const secondProblem = { id: 'second', atlas_lat: 47.37, atlas_lon: 8.54 };
        const firstStops = [{ id: 'first-context', sloid: 'first-context', stop_type: 'atlas_unmatched', atlas_lat: 46.54, atlas_lon: 6.66 }];
        const secondStops = [{ id: 'second-context', sloid: 'second-context', stop_type: 'atlas_unmatched', atlas_lat: 47.38, atlas_lon: 8.55 }];

        ProblemsMap.loadContextData(firstProblem);
        ProblemsMap.loadContextData(secondProblem);

        expect(requests[0].aborted).toBe(true);

        await requests[1].resolve(secondStops);
        await requests[0].resolve(firstStops); // Simulate a transport that still invokes its callback after abort.

        expect(LineRenderer.drawRelationships).toHaveBeenCalledTimes(1);
        expect(MapRenderer.renderEntities.mock.calls[0][0].map(entity => entity.popupRef.id)).toEqual(secondStops.map(stop => stop.id));
        expect(contextLayer.clearLayers).toHaveBeenCalledTimes(1);
        expect(contextLayer.addLayer).toHaveBeenCalledTimes(1);
    });

    test('clearing context aborts pending work and prevents it from committing later', async () => {
        ProblemsMap.loadContextData({ id: 'problem', atlas_lat: 46.53, atlas_lon: 6.65 });
        ProblemsMap.clearContextData();

        expect(requests[0].aborted).toBe(true);
        expect(contextLayer.clearLayers).toHaveBeenCalledTimes(1);

        await requests[0].resolve([{ id: 'late', sloid: 'late', stop_type: 'atlas_unmatched', atlas_lat: 46.54, atlas_lon: 6.66 }]);

        expect(LineRenderer.drawRelationships).not.toHaveBeenCalled();
        expect(contextLayer.addLayer).not.toHaveBeenCalled();
    });

    test('initializes the shared map core with the problems page layers and controls', async () => {
        const initializedMap = ProblemsMap.initProblemMap();

        expect(initializedMap).toBe(problemMap);
        expect(window.MapComponents.MapCore.create).toHaveBeenCalledWith(expect.objectContaining({
            container: 'problemMap',
            view: { center: [47.3769, 8.5417], zoom: 12 },
            mapOptions: expect.objectContaining({
                closePopupOnClick: false,
                zoomControl: false
            }),
            popupBehavior: true,
            defaultBaseLayer: 'OpenStreetMap',
            layerGroups: {
                problemMarkers: { controlLabel: 'Problem Markers' },
                problemLines: { controlLabel: 'Connection Lines' },
                contextMarkers: true
            },
            controls: {
                zoom: { position: 'bottomleft' },
                layers: { position: 'bottomleft' }
            }
        }));
        expect(window.MapComponents.MapPopupController.create).toHaveBeenCalledWith(expect.objectContaining({
            cache: 'payload',
            createPopup: expect.any(Function)
        }));
        expect(ProblemsState.setProblemMap).toHaveBeenLastCalledWith(problemMap);
        expect(problemMap.on).toHaveBeenCalledWith('zoomend', expect.any(Function));
        expect(window.map).toBeUndefined();
    });

    test('rerenders focused and context markers for the final zoom after manual zooming', async () => {
        jest.useFakeTimers();
        currentProblem = {
            id: 'focused',
            problem: 'distance',
            atlas_lat: 46.53,
            atlas_lon: 6.65
        };
        ProblemsMap.initProblemMap();
        ProblemsMap.loadContextData(currentProblem);
        await requests[0].resolve([{
            id: 'context',
            sloid: 'context-sloid',
            stop_type: 'atlas_unmatched',
            atlas_lat: 46.54,
            atlas_lon: 6.66
        }]);

        currentZoom = 18;
        problemMap.emit('zoomend');
        jest.advanceTimersByTime(80);
        await Promise.resolve();

        expect(ProblemsRenderer.drawProblemOnMap).toHaveBeenCalledWith(
            problemMap,
            currentProblem,
            expect.objectContaining({ markersLayer: expect.anything(), linesLayer: expect.anything() }),
            expect.objectContaining({ fitView: false, viewInsets: expect.any(Function) })
        );
        expect(MapRenderer.renderEntities).toHaveBeenCalledTimes(2);
        expect(MapRenderer.renderEntities.mock.calls[1][2]).toEqual(expect.objectContaining({
            layout: expect.objectContaining({ descriptors: expect.any(Array) })
        }));
        expect(LineRenderer.drawRelationships.mock.calls[1][3]).toEqual(expect.objectContaining({
            currentZoom: 18
        }));
    });

    test('reopens a retained context popup only after its replacement batch is on the map', async () => {
        jest.useFakeTimers();
        currentProblem = {
            id: 'focused',
            problem: 'distance',
            atlas_lat: 46.53,
            atlas_lon: 6.65
        };
        let resolveReplacementBatch;
        const oldMarker = { isPopupOpen: jest.fn(() => true) };
        const replacementMarker = { isPopupOpen: jest.fn(() => false) };
        let renderCount = 0;
        MapRenderer.renderEntities.mockImplementation((markerData, _layer, options) => {
            renderCount += 1;
            const marker = renderCount === 1 ? oldMarker : replacementMarker;
            options.bindPopup(marker, markerData[0]);
            const markers = [marker];
            Object.defineProperties(markers, {
                cancelBatch: { value: jest.fn() },
                batchComplete: {
                    value: renderCount === 1
                        ? Promise.resolve({ status: 'complete', added: 1 })
                        : new Promise(resolve => { resolveReplacementBatch = resolve; })
                }
            });
            return markers;
        });

        ProblemsMap.initProblemMap();
        ProblemsMap.loadContextData(currentProblem);
        await requests[0].resolve([{
            id: 'context',
            sloid: 'context-sloid',
            stop_type: 'atlas_unmatched',
            atlas_lat: 46.54,
            atlas_lon: 6.66
        }]);
        await Promise.resolve();

        currentZoom = 18;
        problemMap.emit('zoomend');
        jest.advanceTimersByTime(80);
        expect(popupController.open).not.toHaveBeenCalled();

        resolveReplacementBatch({ status: 'complete', added: 1 });
        await Promise.resolve();

        expect(popupController.open).toHaveBeenCalledWith(replacementMarker);
    });

    test('injects the page popup transport and renderer into the shared popup controller', async () => {
        ProblemsMap.initProblemMap();
        const marker = { name: 'marker' };
        MapRenderer.renderEntities.mockImplementation((markerData, _layer, options) => {
            options.bindPopup(marker, markerData[0]);
            return [marker];
        });

        ProblemsMap.loadContextData({ id: 'focused', atlas_lat: 46.53, atlas_lon: 6.65 });
        await requests[0].resolve([{
            id: 'context-id',
            sloid: 'context-sloid',
            stop_type: 'matched',
            atlas_lat: 46.54,
            atlas_lon: 6.66
        }]);

        expect(popupController.attach).toHaveBeenCalledWith(marker, expect.objectContaining({
            key: 'atlas:context-sloid',
            load: expect.any(Function),
            render: expect.any(Function)
        }));
        const binding = popupController.attach.mock.calls[0][1];
        const popupRequest = binding.load({ signal: undefined });
        expect(fetchJson).toHaveBeenLastCalledWith('/api/stop_popup', {
            stop_id: 'context-id',
            view_type: 'atlas'
        }, { signal: undefined });
        await requests[1].resolve({ stop: { id: 'context-id', stop_type: 'matched' } });
        await expect(popupRequest).resolves.toEqual({ stop: { id: 'context-id', stop_type: 'matched' } });
        expect(binding.render({ stop: { id: 'context-id', stop_type: 'matched' } })).toBe('popup html');
        expect(PopupRenderer.generatePopupHtml).toHaveBeenCalledWith(
            { id: 'context-id', stop_type: 'matched' },
            'atlas'
        );

        const controllerOptions = window.MapComponents.MapPopupController.create.mock.calls[0][0];
        expect(controllerOptions.createPopup('details')).toEqual({ content: 'details' });
        expect(MapRenderer.createPopupWithOptions).toHaveBeenCalledWith('details');
    });

    test('nearby stops are loaded for a box around every stop of the problem', () => {
        ProblemsMap.loadContextData({ id: 'pair', atlas_lat: 46.53, atlas_lon: 6.65, osm_lat: 46.54, osm_lon: 6.62 });

        const params = fetchJson.mock.calls[0][1];
        expect(params.min_lat).toBeCloseTo(46.51);
        expect(params.max_lat).toBeCloseTo(46.56);
        expect(params.min_lon).toBeCloseTo(6.60);
        expect(params.max_lon).toBeCloseTo(6.67);
    });

    test('a shown problem keeps the view inside its box until no problem is shown', () => {
        const box = { extend: jest.fn(other => ({ box: 'extended', with: other })) };
        global.L.latLngBounds = window.L.latLngBounds = jest.fn(() => box);
        let minZoom = 3;
        Object.assign(problemMap, {
            getMinZoom: jest.fn(() => minZoom),
            setMinZoom: jest.fn(zoom => { minZoom = zoom; }),
            setMaxBounds: jest.fn(),
            getBoundsZoom: jest.fn(() => 14),
            getBounds: jest.fn(() => 'fitted view')
        });
        ProblemsMap.initProblemMap();
        const problem = { id: 'p', problem: 'distance', atlas_lat: 46.53, atlas_lon: 6.65, osm_lat: 46.54, osm_lon: 6.62 };

        ProblemsMap.renderProblem(problem, { fitView: true });

        // Released before fitting, so the new problem's view can be reached.
        expect(problemMap.setMaxBounds.mock.calls[0]).toEqual([null]);
        expect(problemMap.setMinZoom.mock.calls[0]).toEqual([3]);
        const [southWest, northEast] = L.latLngBounds.mock.calls[0];
        [46.51, 6.6, 46.56, 6.67].forEach((value, i) => expect(southWest.concat(northEast)[i]).toBeCloseTo(value));
        expect(problemMap.getBoundsZoom).toHaveBeenCalledWith(box, true);
        expect(problemMap.setMinZoom).toHaveBeenLastCalledWith(14);
        expect(problemMap.setMaxBounds).toHaveBeenLastCalledWith({ box: 'extended', with: 'fitted view' });

        // A fitted view wider than the box stays reachable.
        currentZoom = 12;
        ProblemsMap.renderProblem(problem, { fitView: true });
        expect(problemMap.setMinZoom).toHaveBeenLastCalledWith(12);

        // Redrawing at a new zoom keeps the lock as it is.
        problemMap.setMaxBounds.mockClear();
        ProblemsMap.renderProblem(problem, { fitView: false });
        expect(problemMap.setMaxBounds).not.toHaveBeenCalled();

        ProblemsMap.releaseView();
        expect(problemMap.setMaxBounds).toHaveBeenLastCalledWith(null);
        expect(problemMap.setMinZoom).toHaveBeenLastCalledWith(3);
    });

    describe('when nearby stops fail to load', () => {
        const problem = { id: 'problem', atlas_lat: 46.53, atlas_lon: 6.65 };
        let banner;
        let bannerText;
        let retry;

        beforeEach(() => {
            document.body.innerHTML = `
                <div id="problemContextBanner" class="d-none">
                    <span id="problemContextBannerText"></span>
                    <button id="problemContextRetry" type="button" hidden>Retry</button>
                </div>`;
            banner = document.getElementById('problemContextBanner');
            bannerText = document.getElementById('problemContextBannerText');
            retry = document.getElementById('problemContextRetry');
            currentProblem = problem;
        });

        function failWith(request, status) {
            return request.reject(status);
        }

        test('a rate-limited request says so on the map, and Retry loads the current problem again', async () => {
            ProblemsMap.loadContextData(problem);
            await failWith(requests[0], 429);

            expect(banner.classList.contains('d-none')).toBe(false);
            expect(bannerText.textContent).toMatch(/too many requests/);
            expect(retry.hidden).toBe(false);

            retry.click();

            expect(requests).toHaveLength(2);
            expect(fetchJson.mock.calls[1][1].min_lat).toBeCloseTo(46.51);
            expect(banner.classList.contains('d-none')).toBe(true);

            await requests[1].resolve([]);
            expect(banner.classList.contains('d-none')).toBe(true);
        });

        test('any other failure, or an unexpected answer, says nearby stops could not be loaded', async () => {
            ProblemsMap.loadContextData(problem);
            await failWith(requests[0], 500);
            expect(bannerText.textContent).toBe('Nearby stops could not be loaded.');

            ProblemsMap.loadContextData(problem);
            await requests[1].resolve({ unexpected: true });
            expect(banner.classList.contains('d-none')).toBe(false);
            expect(bannerText.textContent).toBe('Nearby stops could not be loaded.');
        });

        test('aborted or superseded requests show nothing, and hiding nearby stops removes the message', async () => {
            ProblemsMap.loadContextData(problem);
            ProblemsMap.loadContextData(problem);
            await requests[0].abortWith();
            await failWith(requests[0], 429); // A late failure of the replaced request.
            expect(banner.classList.contains('d-none')).toBe(true);

            await failWith(requests[1], 429);
            expect(banner.classList.contains('d-none')).toBe(false);

            ProblemsMap.clearContextData();
            expect(banner.classList.contains('d-none')).toBe(true);
        });
    });

    test('destroys page-owned popup and map resources cleanly', () => {
        ProblemsMap.initProblemMap();

        ProblemsMap.destroyProblemMap();

        expect(popupController.destroy).toHaveBeenCalledTimes(1);
        expect(mapCoreResult.destroy).toHaveBeenCalledTimes(1);
        expect(problemMap.off).toHaveBeenCalledWith('zoomend', expect.any(Function));
        expect(ProblemsState.setProblemMap).toHaveBeenLastCalledWith(null);
        expect(ProblemsState.setContextMarkersLayer).toHaveBeenLastCalledWith(null);
        expect(ProblemsMap.invalidateMapSize()).toBeUndefined();
    });
});
