const fs = require('fs');
const path = require('path');

function createRequest() {
    const callbacks = {
        done: [],
        fail: [],
        always: []
    };

    const request = {
        readyState: 1,
        abort: jest.fn(function() {
            request.readyState = 0;
        }),
        done(callback) {
            callbacks.done.push(callback);
            return request;
        },
        fail(callback) {
            callbacks.fail.push(callback);
            return request;
        },
        always(callback) {
            callbacks.always.push(callback);
            return request;
        },
        resolve(payload) {
            request.readyState = 4;
            callbacks.done.forEach(callback => callback(payload));
            callbacks.always.forEach(callback => callback());
        },
        reject(textStatus = 'error', errorThrown = 'request failed') {
            request.readyState = 4;
            callbacks.fail.forEach(callback => callback(request, textStatus, errorThrown));
            callbacks.always.forEach(callback => callback());
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

        window.MapShared = {
            getAtlasMarkerIdentity: stop => stop.sloid || null,
            createEntityKey: (type, stop) => {
                const id = type === 'atlas' ? (stop.sloid || stop.id) : (stop.osm_node_id || stop.id);
                return id == null ? null : `${type}:${id}`;
            },
            createBaseTileLayers: jest.fn()
        };

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
            drawAll: jest.fn()
        };
        window.LineRenderer = global.LineRenderer;

        window.MapRenderer = global.MapRenderer = {
            createMarkersWithOverlapHandling: jest.fn(markerData => markerData.map(() => ({
                setOpacity: jest.fn()
            }))),
            setMarkerOpacity: jest.fn(),
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

        const getJSON = jest.fn(() => {
            const request = createRequest();
            requests.push(request);
            return request;
        });
        global.$ = window.$ = { getJSON };

        delete window.ProblemsMap;
        delete window.map;
        const scriptPath = path.join(__dirname, '../../static/js/pages/problems-map.js');
        window.eval(fs.readFileSync(scriptPath, 'utf8'));
        global.ProblemsMap = window.ProblemsMap;
    });

    afterEach(() => {
        jest.useRealTimers();
    });

    test('requests the complete fixed context without a row limit and renders all returned stops', () => {
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

        expect($.getJSON).toHaveBeenCalledTimes(1);
        expect($.getJSON.mock.calls[0][0]).toBe('/api/data');
        const params = $.getJSON.mock.calls[0][1];
        expect(params.min_lat).toBeCloseTo(46.51);
        expect(params.max_lat).toBeCloseTo(46.55);
        expect(params.min_lon).toBeCloseTo(6.63);
        expect(params.max_lon).toBeCloseTo(6.67);
        expect(params.zoom).toBe(17);
        expect(params).not.toHaveProperty('limit');

        requests[0].resolve(stops);

        const markerData = MapRenderer.createMarkersWithOverlapHandling.mock.calls[0][0];
        const markerOptions = MapRenderer.createMarkersWithOverlapHandling.mock.calls[0][2];
        expect(markerData).toHaveLength(250);
        expect(markerOptions).toEqual(expect.objectContaining({
            map: problemMap,
            zoom: 17,
            bindPopup: expect.any(Function)
        }));
        expect(MapRenderer.setMarkerOpacity).toHaveBeenCalledTimes(250);
        expect(LineRenderer.drawAll).toHaveBeenCalledWith(stops, renderedChildLayers[0], expect.objectContaining({
            currentZoom: 17,
            isContext: true
        }));
        expect(contextLayer.clearLayers).toHaveBeenCalledTimes(1);
        expect(contextLayer.addLayer).toHaveBeenCalledWith(renderedChildLayers[0]);
    });

    test('an empty successful response clears context left by the previous problem', () => {
        ProblemsMap.loadContextData({ id: 'problem', atlas_lat: 46.53, atlas_lon: 6.65 });
        requests[0].resolve([]);

        expect(contextLayer.clearLayers).toHaveBeenCalledTimes(1);
        expect(contextLayer.addLayer).not.toHaveBeenCalled();
        expect(MapRenderer.createMarkersWithOverlapHandling).not.toHaveBeenCalled();
    });

    test('only the newest request may replace the displayed context', () => {
        const firstProblem = { id: 'first', atlas_lat: 46.53, atlas_lon: 6.65 };
        const secondProblem = { id: 'second', atlas_lat: 47.37, atlas_lon: 8.54 };
        const firstStops = [{ id: 'first-context', sloid: 'first-context', stop_type: 'atlas_unmatched', atlas_lat: 46.54, atlas_lon: 6.66 }];
        const secondStops = [{ id: 'second-context', sloid: 'second-context', stop_type: 'atlas_unmatched', atlas_lat: 47.38, atlas_lon: 8.55 }];

        ProblemsMap.loadContextData(firstProblem);
        ProblemsMap.loadContextData(secondProblem);

        expect(requests[0].abort).toHaveBeenCalledTimes(1);

        requests[1].resolve(secondStops);
        requests[0].resolve(firstStops); // Simulate a transport that still invokes its callback after abort.

        expect(LineRenderer.drawAll).toHaveBeenCalledTimes(1);
        expect(LineRenderer.drawAll.mock.calls[0][0]).toEqual(secondStops);
        expect(contextLayer.clearLayers).toHaveBeenCalledTimes(1);
        expect(contextLayer.addLayer).toHaveBeenCalledTimes(1);
    });

    test('clearing context aborts pending work and prevents it from committing later', () => {
        ProblemsMap.loadContextData({ id: 'problem', atlas_lat: 46.53, atlas_lon: 6.65 });
        ProblemsMap.clearContextData();

        expect(requests[0].abort).toHaveBeenCalledTimes(1);
        expect(contextLayer.clearLayers).toHaveBeenCalledTimes(1);

        requests[0].resolve([{ id: 'late', sloid: 'late', stop_type: 'atlas_unmatched', atlas_lat: 46.54, atlas_lon: 6.66 }]);

        expect(LineRenderer.drawAll).not.toHaveBeenCalled();
        expect(contextLayer.addLayer).not.toHaveBeenCalled();
    });

    test('initializes the shared map core with the problems page layers and controls', () => {
        const initializedMap = ProblemsMap.initProblemMap();

        expect(initializedMap).toBe(problemMap);
        expect(window.MapComponents.MapCore.create).toHaveBeenCalledWith(expect.objectContaining({
            container: 'problemMap',
            view: { center: [47.3769, 8.5417], zoom: 12 },
            mapOptions: expect.objectContaining({
                closePopupOnClick: false,
                preferCanvas: false,
                zoomControl: false
            }),
            rendererPadding: expect.any(Function),
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
        const coreOptions = window.MapComponents.MapCore.create.mock.calls[0][0];
        expect(coreOptions.rendererPadding(15)).toBe(0.1);
        expect(coreOptions.rendererPadding(16)).toBe(2.0);
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
        requests[0].resolve([{
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
            { fitView: false }
        );
        expect(MapRenderer.createMarkersWithOverlapHandling).toHaveBeenCalledTimes(2);
        expect(MapRenderer.createMarkersWithOverlapHandling.mock.calls[1][2]).toEqual(expect.objectContaining({
            map: problemMap,
            zoom: 18
        }));
        expect(LineRenderer.drawAll.mock.calls[1][2]).toEqual(expect.objectContaining({
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
        MapRenderer.createMarkersWithOverlapHandling.mockImplementation((markerData, _layer, options) => {
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
        requests[0].resolve([{
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
        MapRenderer.createMarkersWithOverlapHandling.mockImplementation((markerData, _layer, options) => {
            options.bindPopup(marker, markerData[0]);
            return [marker];
        });

        ProblemsMap.loadContextData({ id: 'focused', atlas_lat: 46.53, atlas_lon: 6.65 });
        requests[0].resolve([{
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
        expect($.getJSON).toHaveBeenLastCalledWith('/api/stop_popup', {
            stop_id: 'context-id',
            view_type: 'atlas'
        });
        requests[1].resolve({ stop: { id: 'context-id', stop_type: 'matched' } });
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
