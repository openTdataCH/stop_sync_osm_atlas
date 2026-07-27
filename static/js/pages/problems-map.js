// problems-map.js - Map functionality for the Problem Identification Page

/**
 * ProblemsMap - Map initialization and rendering functionality
 * Depends on: ProblemsState, MapComponents.MapCore,
 * MapComponents.MapPopupController, MapRenderer, LineRenderer, MapShared,
 * PopupRenderer
 */
window.ProblemsMap = (function() {
    'use strict';

    // Performance tuning constants for the problems page
    const PROBLEM_LINE_ZOOM_THRESHOLD = AppConstants.MAP.ZOOM_LINE_THRESHOLD;   // draw context lines only at high zoom
    const CONTEXT_COORDINATE_OFFSET = 0.02; // Roughly 2 km around the selected problem
    const CONTEXT_MARKER_OPACITY = 0.6;
    const ZOOM_RENDER_DEBOUNCE_MS = 80;
    const MAP_COLORS = AppConstants.COLORS || {};
    const COLOR_ATLAS_MATCHED = MAP_COLORS.ATLAS_MATCHED || '#174092';
    const COLOR_OSM_MATCHED = MAP_COLORS.OSM_MATCHED || '#4CAF50';
    const COLOR_ATLAS_UNMATCHED = MAP_COLORS.ATLAS_UNMATCHED || '#DC3545';
    const COLOR_OSM_UNMATCHED = MAP_COLORS.OSM_UNMATCHED || '#6C757D';

    let problemMapCore = null;
    let contextPopupController = null;
    let contextPopupMarkers = new Set();
    let contextPopupKeyByMarker = new Map();
    let renderedContext = null;
    let zoomEndHandler = null;
    let zoomRenderTimer = null;
    let contextBatchCancel = null;
    let contextRenderSequence = 0;
    let isRenderingProblem = false;
    let renderedProblem = null;
    let removeResizeHandlers = null;

    // Request management for context loading
    let currentContextRequest = null; // jqXHR of in-flight /api/data
    let contextRequestSequence = 0;

    function createAbortError() {
        const error = new Error('Popup request aborted');
        error.name = 'AbortError';
        return error;
    }

    /**
     * Adapt the page's jQuery endpoint to the promise/AbortSignal contract used
     * by MapPopupController. The shared popup component remains transport-free.
     */
    function requestStopPopup(stopData, viewType, signal) {
        return new Promise(function(resolve, reject) {
            if (signal && signal.aborted) {
                reject(createAbortError());
                return;
            }
            if (typeof $ === 'undefined' || typeof $.getJSON !== 'function') {
                reject(new Error('The popup transport is unavailable.'));
                return;
            }

            const request = $.getJSON('/api/stop_popup', {
                stop_id: stopData.id,
                view_type: viewType
            });
            let settled = false;

            function removeAbortListener() {
                if (signal && typeof signal.removeEventListener === 'function') {
                    signal.removeEventListener('abort', onAbort);
                }
            }

            function settle(callback, value) {
                if (settled) return;
                settled = true;
                removeAbortListener();
                callback(value);
            }

            function onAbort() {
                if (request && typeof request.abort === 'function') {
                    request.abort();
                }
                settle(reject, createAbortError());
            }

            if (signal && typeof signal.addEventListener === 'function') {
                signal.addEventListener('abort', onAbort, { once: true });
            }

            request.done(function(payload) {
                settle(resolve, payload);
            }).fail(function(_jqXHR, textStatus, errorThrown) {
                if (textStatus === 'abort' || (signal && signal.aborted)) {
                    settle(reject, createAbortError());
                    return;
                }
                settle(reject, new Error(errorThrown || textStatus || 'Failed to load stop details.'));
            });
        });
    }

    function renderStopPopup(payload, viewType) {
        const enriched = payload && (payload.stop || payload);
        if (!enriched) {
            throw new Error('The popup endpoint returned no stop data.');
        }

        if (enriched.stop_type === 'atlas_unmatched') {
            return viewType === 'atlas'
                ? PopupRenderer.generateSingleAtlasBubbleHtml(enriched, true)
                : PopupRenderer.generateSingleOsmBubbleHtml(enriched, true);
        }
        return PopupRenderer.generatePopupHtml(enriched, viewType);
    }

    function getContextPopupKey(markerData) {
        if (!markerData || !markerData.stopData || !markerData.type) {
            return null;
        }
        if (window.MapShared && typeof window.MapShared.createEntityKey === 'function') {
            return window.MapShared.createEntityKey(markerData.type, markerData.stopData);
        }
        return markerData.stopData.id == null
            ? null
            : `${markerData.type}:${markerData.stopData.id}`;
    }

    function bindContextMarkerPopup(marker, markerData) {
        if (!contextPopupController) return;
        const key = getContextPopupKey(markerData);
        if (!key || markerData.stopData.id == null) return;

        contextPopupKeyByMarker.set(marker, key);
        contextPopupController.attach(marker, {
            key: key,
            // A zoom redraw only changes projected marker positions. Preserve
            // loaded details for the replacement marker.
            retainCacheOnDetach: true,
            load: function(context) {
                return requestStopPopup(markerData.stopData, markerData.type, context.signal);
            },
            render: function(payload) {
                return renderStopPopup(payload, markerData.type);
            }
        });
    }

    function getOpenContextPopupKeys() {
        const openKeys = new Set();
        contextPopupMarkers.forEach(function(marker) {
            if (typeof marker.isPopupOpen === 'function' && marker.isPopupOpen()) {
                const key = contextPopupKeyByMarker.get(marker);
                if (key) openKeys.add(key);
            }
        });
        return openKeys;
    }

    function detachContextPopups(options) {
        options = options || {};
        const keysToRemove = new Set();
        if (contextPopupController) {
            contextPopupMarkers.forEach(function(marker) {
                const key = contextPopupKeyByMarker.get(marker);
                contextPopupController.detach(marker);
                if (!options.preserveCache && key) keysToRemove.add(key);
                contextPopupKeyByMarker.delete(marker);
            });
            keysToRemove.forEach(function(key) {
                contextPopupController.remove(key);
            });
        }
        contextPopupMarkers = new Set();
    }

    function normalizeProblemMembers(problem) {
        if (!problem) {
            return [];
        }
        return Array.isArray(problem.members) && problem.members.length ? problem.members : [problem];
    }

    function getProblemKey(problem) {
        if (!problem) return null;
        const memberIds = normalizeProblemMembers(problem).map(function(member) {
            if (!member) return '';
            if (member.id != null) return String(member.id);
            return String(member.sloid || member.osm_node_id || '');
        }).sort();
        return [problem.problem || '', problem.group_type || '', memberIds.join(',')].join('|');
    }

    function buildProblemIdentitySets(problem) {
        const members = normalizeProblemMembers(problem);
        const identities = {
            stopIds: new Set(),
            sloids: new Set(),
            osmNodeIds: new Set()
        };

        members.forEach(member => {
            if (!member) {
                return;
            }
            if (member.id != null) {
                identities.stopIds.add(String(member.id));
            }
            if (member.sloid) {
                identities.sloids.add(String(member.sloid));
            }
            if (member.osm_node_id != null) {
                identities.osmNodeIds.add(String(member.osm_node_id));
            }
        });

        return identities;
    }

    function stopMatchesProblemIdentities(stop, identities) {
        if (!stop) {
            return false;
        }

        if (stop.id != null && identities.stopIds.has(String(stop.id))) {
            return true;
        }
        if (stop.sloid && identities.sloids.has(String(stop.sloid))) {
            return true;
        }
        if (stop.osm_node_id != null && identities.osmNodeIds.has(String(stop.osm_node_id))) {
            return true;
        }

        if (Array.isArray(stop.osm_matches)) {
            return stop.osm_matches.some(match => {
                if (!match) {
                    return false;
                }
                return (
                    (match.id != null && identities.stopIds.has(String(match.id))) ||
                    (match.osm_node_id != null && identities.osmNodeIds.has(String(match.osm_node_id)))
                );
            });
        }

        return false;
    }

    function getProblemCenter(problem) {
        const members = Array.isArray(problem && problem.members) ? problem.members : [];
        const candidates = [problem].concat(members);

        for (const candidate of candidates) {
            if (!candidate) {
                continue;
            }

            const coordinatePairs = [
                [candidate.atlas_lat, candidate.atlas_lon],
                [candidate.osm_lat, candidate.osm_lon]
            ];

            for (const [rawLat, rawLon] of coordinatePairs) {
                if (rawLat == null || rawLon == null) {
                    continue;
                }

                const lat = Number(rawLat);
                const lon = Number(rawLon);
                if (Number.isFinite(lat) && Number.isFinite(lon)) {
                    return { lat, lon };
                }
            }
        }

        return null;
    }

    function abortCurrentContextRequest() {
        const request = currentContextRequest;
        currentContextRequest = null;

        if (request && request.readyState !== 4 && typeof request.abort === 'function') {
            try {
                request.abort();
            } catch (error) {
                // Sequence checks still prevent this request from committing.
            }
        }
    }

    function clearContextLayer() {
        contextRenderSequence += 1;
        if (contextBatchCancel) {
            contextBatchCancel();
            contextBatchCancel = null;
        }
        detachContextPopups();
        const contextMarkersLayer = ProblemsState.getContextMarkersLayer();
        if (contextMarkersLayer) {
            contextMarkersLayer.clearLayers();
        }
    }

    /**
     * Cancel any pending context work and remove the currently displayed context.
     */
    function clearContextData() {
        contextRequestSequence += 1;
        abortCurrentContextRequest();
        renderedContext = null;
        clearContextLayer();
    }

    function normalizeContextResponse(payload) {
        if (Array.isArray(payload)) {
            return payload;
        }
        if (payload && Array.isArray(payload.stops)) {
            return payload.stops;
        }
        return null;
    }

    function buildContextMarkerData(stops) {
        const markerData = [];
        const createdAtlasMarkers = new Set();

        stops.forEach(function(stop) {
            const atlasMarkerKey = window.MapShared && typeof window.MapShared.getAtlasMarkerIdentity === 'function'
                ? window.MapShared.getAtlasMarkerIdentity(stop)
                : null;
            if (stop.sloid && stop.atlas_lat != null && stop.atlas_lon != null && (!atlasMarkerKey || !createdAtlasMarkers.has(atlasMarkerKey))) {
                let atlasColor = COLOR_OSM_UNMATCHED;
                if (stop.stop_type === 'matched') atlasColor = COLOR_ATLAS_MATCHED;
                else if (stop.stop_type === 'atlas_unmatched') atlasColor = COLOR_ATLAS_UNMATCHED;

                markerData.push({
                    key: window.MapShared.createEntityKey('atlas', stop),
                    lat: parseFloat(stop.atlas_lat),
                    lon: parseFloat(stop.atlas_lon),
                    type: 'atlas',
                    color: atlasColor,
                    hasAtlasDuplicate: stop.has_atlas_duplicate,
                    originalLat: parseFloat(stop.atlas_lat),
                    originalLon: parseFloat(stop.atlas_lon),
                    stopData: stop,
                    opacity: CONTEXT_MARKER_OPACITY
                });
                if (atlasMarkerKey) {
                    createdAtlasMarkers.add(atlasMarkerKey);
                }
            }

            const osmNodesToProcess = [];

            if (stop.osm_node_id && stop.osm_lat != null && stop.osm_lon != null) {
                osmNodesToProcess.push(stop);
            }

            if (Array.isArray(stop.osm_matches)) {
                stop.osm_matches.forEach(osmMatch => {
                    if (osmMatch.osm_node_id && osmMatch.osm_lat != null && osmMatch.osm_lon != null) {
                        osmNodesToProcess.push({
                            ...stop,
                            ...osmMatch,
                            id: osmMatch.osm_id || stop.id,
                            osm_node_id: osmMatch.osm_node_id,
                            osm_lat: osmMatch.osm_lat,
                            osm_lon: osmMatch.osm_lon
                        });
                    }
                });
            }

            osmNodesToProcess.forEach(osmData => {
                let osmColor = COLOR_OSM_UNMATCHED;
                if (osmData.stop_type === 'matched') osmColor = COLOR_OSM_MATCHED;

                markerData.push({
                    key: window.MapShared.createEntityKey('osm', osmData),
                    lat: parseFloat(osmData.osm_lat),
                    lon: parseFloat(osmData.osm_lon),
                    type: 'osm',
                    color: osmColor,
                    osmNodeType: osmData.osm_node_type,
                    originalLat: parseFloat(osmData.osm_lat),
                    originalLon: parseFloat(osmData.osm_lon),
                    stopData: osmData,
                    opacity: CONTEXT_MARKER_OPACITY
                });
            });
        });

        return markerData;
    }

    function renderContextData(problem, stops, problemMap, zoom, options) {
        options = options || {};
        const contextMarkersLayer = ProblemsState.getContextMarkersLayer();
        if (!contextMarkersLayer) {
            return;
        }

        if (stops.length === 0) {
            clearContextLayer();
            return;
        }

        const problemIdentities = buildProblemIdentitySets(problem);
        const filteredStops = stops.filter(stop => !stopMatchesProblemIdentities(stop, problemIdentities));
        const previousOpenPopupKeys = options.preservePopupState
            ? getOpenContextPopupKeys()
            : new Set();
        if (!options.preservePopupState) {
            clearContextLayer();
        } else {
            contextRenderSequence += 1;
            if (contextBatchCancel) {
                contextBatchCancel();
                contextBatchCancel = null;
            }
        }
        const renderSequence = contextRenderSequence;

        // Render into a disposable child layer. If a newer problem supersedes this
        // render, clearing the parent detaches all of its remaining marker chunks.
        const renderedContextLayer = L.layerGroup();
        LineRenderer.drawAll(filteredStops, renderedContextLayer, {
            showAtlas: true,
            showOsm: true,
            minZoom: PROBLEM_LINE_ZOOM_THRESHOLD,
            currentZoom: zoom,
            isContext: true
        });

        const contextMarkerData = buildContextMarkerData(filteredStops);
        const contextMarkers = window.MapRenderer.createMarkersWithOverlapHandling(contextMarkerData, renderedContextLayer, {
            batchAdd: true,
            map: problemMap,
            zoom: zoom,
            bindPopup: bindContextMarkerPopup
        });

        contextMarkers.forEach(marker => {
            window.MapRenderer.setMarkerOpacity(marker, CONTEXT_MARKER_OPACITY);
        });

        if (options.preservePopupState) {
            // Attach replacements first so a same-key in-flight popup request is
            // still owned while the old marker is detached.
            detachContextPopups({ preserveCache: true });
            contextMarkersLayer.clearLayers();
        }
        contextPopupMarkers = new Set(contextMarkers);
        contextMarkersLayer.addLayer(renderedContextLayer);

        contextBatchCancel = typeof contextMarkers.cancelBatch === 'function'
            ? contextMarkers.cancelBatch
            : null;
        const batchComplete = contextMarkers.batchComplete || Promise.resolve({ status: 'complete' });
        batchComplete.then(function(result) {
            if (renderSequence !== contextRenderSequence || !result || result.status !== 'complete') return;
            contextBatchCancel = null;
            if (!options.preservePopupState || !contextPopupController) return;
            contextMarkers.forEach(function(marker) {
                const key = contextPopupKeyByMarker.get(marker);
                if (key && previousOpenPopupKeys.has(key)) {
                    contextPopupController.open(marker);
                }
            });
        });
    }

    function renderProblem(problem, options) {
        const problemMap = ProblemsState.getProblemMap();
        if (!problemMap || !window.ProblemsRenderer || typeof window.ProblemsRenderer.drawProblemOnMap !== 'function') {
            return false;
        }

        isRenderingProblem = true;
        try {
            window.ProblemsRenderer.drawProblemOnMap(problemMap, problem, {
                markersLayer: ProblemsState.getProblemMarkersLayer(),
                linesLayer: ProblemsState.getProblemLinesLayer()
            }, options || {});
            const labelZoom = AppConstants.MAP.LABEL_ICON_MIN_ZOOM || 18;
            renderedProblem = {
                problemKey: getProblemKey(problem),
                zoomBand: problemMap.getZoom() < labelZoom ? 'circle' : 'label'
            };
        } finally {
            isRenderingProblem = false;
        }
        return true;
    }

    function rerenderAtCurrentZoom() {
        if (isRenderingProblem) return;
        const problemMap = ProblemsState.getProblemMap();
        const problem = ProblemsState.getCurrentProblem();
        if (!problemMap || !problem) return;

        const labelZoom = AppConstants.MAP.LABEL_ICON_MIN_ZOOM || 18;
        const currentZoomBand = problemMap.getZoom() < labelZoom ? 'circle' : 'label';
        const problemKey = getProblemKey(problem);
        if (
            problem.problem === 'duplicates' ||
            !renderedProblem ||
            renderedProblem.problemKey !== problemKey ||
            renderedProblem.zoomBand !== currentZoomBand
        ) {
            renderProblem(problem, { fitView: false });
        }
        if (
            ProblemsState.getShowContext() &&
            renderedContext &&
            renderedContext.problemKey === getProblemKey(problem)
        ) {
            renderContextData(
                problem,
                renderedContext.stops,
                problemMap,
                problemMap.getZoom(),
                { preservePopupState: true }
            );
        }
    }

    function scheduleZoomRerender() {
        if (isRenderingProblem) return;
        if (zoomRenderTimer != null) clearTimeout(zoomRenderTimer);
        zoomRenderTimer = setTimeout(function() {
            zoomRenderTimer = null;
            rerenderAtCurrentZoom();
        }, ZOOM_RENDER_DEBOUNCE_MS);
    }

    /**
     * Initialize the map on the problems page with same style as main page
     */
    function initProblemMap() {
        destroyProblemMap();

        if (!window.MapComponents || !window.MapComponents.MapCore || !window.MapComponents.MapPopupController) {
            throw new Error('ProblemsMap requires MapCore and MapPopupController.');
        }

        problemMapCore = window.MapComponents.MapCore.create({
            container: 'problemMap',
            view: {
                center: [47.3769, 8.5417],
                zoom: 12
            },
            mapOptions: {
                closePopupOnClick: false,
                preferCanvas: false,
                maxZoom: AppConstants.MAP.MAX_ZOOM,
                zoomControl: false
            },
            rendererPadding: function(zoom) {
                return zoom >= 16 ? 2.0 : 0.1;
            },
            popupBehavior: true,
            baseLayers: function() {
                return window.MapShared.createBaseTileLayers();
            },
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
        });

        const problemMap = problemMapCore.map;
        const problemMarkersLayer = problemMapCore.layers.problemMarkers;
        const problemLinesLayer = problemMapCore.layers.problemLines;
        const contextMarkersLayer = problemMapCore.layers.contextMarkers;
        const osmLayerProblems = problemMapCore.baseLayers.OpenStreetMap;

        contextPopupController = window.MapComponents.MapPopupController.create({
            cache: 'payload',
            createPopup: function(content) {
                return window.MapRenderer.createPopupWithOptions(content);
            },
            errorContent: '<div class="popup-error">Unable to load stop details. Click the marker to retry.</div>',
            onError: function(error) {
                console.error('Failed to load stop popup:', error);
            }
        });

        // Store in state
        ProblemsState.setProblemMap(problemMap);
        ProblemsState.setOsmLayerProblems(osmLayerProblems);
        ProblemsState.setProblemMarkersLayer(problemMarkersLayer);
        ProblemsState.setProblemLinesLayer(problemLinesLayer);
        ProblemsState.setContextMarkersLayer(contextMarkersLayer);

        zoomEndHandler = scheduleZoomRerender;
        problemMap.on('zoomend', zoomEndHandler);

        return problemMap;
    }

    function invalidateMapSize() {
        return problemMapCore ? problemMapCore.invalidateSize() : undefined;
    }

    function destroyProblemMap() {
        contextRequestSequence += 1;
        abortCurrentContextRequest();
        renderedContext = null;
        renderedProblem = null;
        detachContextPopups();
        if (zoomRenderTimer != null) {
            clearTimeout(zoomRenderTimer);
            zoomRenderTimer = null;
        }
        if (contextBatchCancel) {
            contextBatchCancel();
            contextBatchCancel = null;
        }
        contextRenderSequence += 1;

        const problemMap = problemMapCore && problemMapCore.map;
        if (problemMap && zoomEndHandler && typeof problemMap.off === 'function') {
            problemMap.off('zoomend', zoomEndHandler);
        }
        zoomEndHandler = null;

        if (contextPopupController) {
            contextPopupController.destroy();
            contextPopupController = null;
        }
        if (problemMapCore) {
            problemMapCore.destroy();
            problemMapCore = null;
        }
        if (removeResizeHandlers) {
            removeResizeHandlers();
            removeResizeHandlers = null;
        }

        ProblemsState.setProblemMap(null);
        ProblemsState.setOsmLayerProblems(null);
        ProblemsState.setProblemMarkersLayer(null);
        ProblemsState.setProblemLinesLayer(null);
        ProblemsState.setContextMarkersLayer(null);
    }

    /**
     * Load context data (nearby entries) for the current problem
     */
    function loadContextData(problem) {
        if (!ProblemsState.getShowContext() || !problem) {
            clearContextData();
            return null;
        }

        const center = getProblemCenter(problem);
        if (!center) {
            clearContextData();
            return null;
        }

        const problemMap = ProblemsState.getProblemMap();
        const zoom = problemMap ? problemMap.getZoom() : 14;
        const problemKey = getProblemKey(problem);
        if (renderedContext && renderedContext.problemKey !== problemKey) {
            renderedContext = null;
            clearContextLayer();
        }
        const params = {
            min_lat: center.lat - CONTEXT_COORDINATE_OFFSET,
            max_lat: center.lat + CONTEXT_COORDINATE_OFFSET,
            min_lon: center.lon - CONTEXT_COORDINATE_OFFSET,
            max_lon: center.lon + CONTEXT_COORDINATE_OFFSET,
            zoom: zoom
        };

        const requestSequence = ++contextRequestSequence;
        abortCurrentContextRequest();

        const request = $.getJSON('/api/data', params);
        currentContextRequest = request;

        request.done(function(payload) {
            if (
                requestSequence !== contextRequestSequence ||
                request !== currentContextRequest ||
                !ProblemsState.getShowContext()
            ) {
                return;
            }

            const stops = normalizeContextResponse(payload);
            if (stops === null) {
                console.error('Failed to load context data: unexpected API response');
                return;
            }

            renderedContext = {
                problemKey: problemKey,
                stops: stops
            };
            const renderZoom = problemMap ? problemMap.getZoom() : zoom;
            renderContextData(problem, stops, problemMap, renderZoom);
        }).fail(function(jqXHR, textStatus, errorThrown) {
            if (requestSequence === contextRequestSequence && textStatus !== 'abort') {
                console.error('Failed to load context data:', textStatus, errorThrown);
            }
        }).always(function() {
            if (currentContextRequest === request) {
                currentContextRequest = null;
            }
        });

        return request;
    }

    /**
     * Toggle context view
     */
    function toggleContext() {
        const showContext = !ProblemsState.getShowContext();
        ProblemsState.setShowContext(showContext);
        const button = $('#toggleContextBtn');
        
        if (showContext) {
            button.removeClass('bg-white text-dark').addClass('btn-secondary');
            button.html('<i class="fas fa-eye-slash"></i> Hide other markers');
            const currentProblem = ProblemsState.getCurrentProblem();
            if (currentProblem) {
                loadContextData(currentProblem);
            }
        } else {
            button.removeClass('btn-secondary').addClass('bg-white text-dark');
            button.html('<i class="fas fa-eye"></i> See other markers');
            clearContextData();
        }
    }

    /**
     * Initialize modern resize functionality
     */
    function initializeResize() {
        if (removeResizeHandlers) removeResizeHandlers();
        const mapSection = $('#mapSection');
        const problemSection = $('#problemSection');
        const resizeDivider = $('#resizeDivider');

        let isResizing = false;
        let startX = 0;
        let startMapWidth = 0;
        let startProblemWidth = 0;

        resizeDivider.on('mousedown.problemsMapResize', function(e) {
            isResizing = true;
            startX = e.clientX;
            startMapWidth = mapSection.width();
            startProblemWidth = problemSection.width();
            
            $('body').addClass('user-select-none');
            resizeDivider.addClass('resizing');
            e.preventDefault();
        });

        $(document).on('mousemove.problemsMapResize', function(e) {
            if (!isResizing) return;
            
            const deltaX = e.clientX - startX;
            let newMapWidth = startMapWidth + deltaX;
            let newProblemWidth = startProblemWidth - deltaX;
            
            // Enforce min-width constraints from CSS
            const minMapWidth = parseInt(mapSection.css('min-width'), 10) || 300;
            const minProblemWidth = parseInt(problemSection.css('min-width'), 10) || 450;

            if (newMapWidth < minMapWidth) {
                newMapWidth = minMapWidth;
                newProblemWidth = startMapWidth + startProblemWidth - newMapWidth;
            }
            
            if (newProblemWidth < minProblemWidth) {
                newProblemWidth = minProblemWidth;
                newMapWidth = startMapWidth + startProblemWidth - newProblemWidth;
            }

            mapSection.css('flex', `1 1 ${newMapWidth}px`);
            problemSection.css('flex', `0 0 ${newProblemWidth}px`);
        });

        $(document).on('mouseup.problemsMapResize', function() {
            if (isResizing) {
                isResizing = false;
                $('body').removeClass('user-select-none');
                resizeDivider.removeClass('resizing');
                
                // Invalidate map size to fix any rendering issues
                const problemMap = ProblemsState.getProblemMap();
                if (problemMap) {
                    problemMap.invalidateSize();
                }
            }
        });

        removeResizeHandlers = function() {
            resizeDivider.off('.problemsMapResize');
            $(document).off('.problemsMapResize');
            $('body').removeClass('user-select-none');
            resizeDivider.removeClass('resizing');
        };
    }

    // Public API
    return {
        initProblemMap,
        invalidateMapSize,
        destroyProblemMap,
        renderProblem,
        loadContextData,
        clearContextData,
        toggleContext,
        initializeResize
    };
})();
