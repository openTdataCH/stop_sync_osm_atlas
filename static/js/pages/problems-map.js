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
    // The problem's box: its stops plus this many degrees on every side, about
    // 2.2 km north-south and 1.5 km east-west in Switzerland. Nearby stops are
    // loaded for this box, and the map cannot pan or zoom out beyond it.
    const CONTEXT_COORDINATE_OFFSET = 0.02;
    const ZOOM_RENDER_DEBOUNCE_MS = 80;

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
    let baseMinZoom = 0;     // the map's own minimum zoom, without a problem

    // Request management for context loading
    let currentContextRequest = null; // AbortController of in-flight /api/data
    let contextRequestSequence = 0;

    // A stop's popup content, from /api/stop_popup; MapPopupController aborts it through signal.
    function requestStopPopup(stopData, viewType, signal) {
        return SharedUtils.fetchJson('/api/stop_popup', {
            stop_id: stopData.id,
            view_type: viewType
        }, { signal: signal });
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

    function bindContextMarkerPopup(marker, markerData) {
        if (!contextPopupController) return;
        const key = markerData.key;
        if (!key || markerData.popupRef.id == null) return;

        contextPopupKeyByMarker.set(marker, key);
        contextPopupController.attach(marker, {
            key: key,
            // A zoom redraw only changes projected marker positions. Preserve
            // loaded details for the replacement marker.
            retainCacheOnDetach: true,
            load: function(context) {
                return requestStopPopup(markerData.popupRef, markerData.entityType, context.signal);
            },
            render: function(payload) {
                return renderStopPopup(payload, markerData.entityType);
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

    // Every ATLAS and OSM position of the problem and its members, padded by
    // CONTEXT_COORDINATE_OFFSET; null when the problem has no position.
    function getProblemBox(problem) {
        const members = Array.isArray(problem && problem.members) ? problem.members : [];
        let box = null;

        [problem].concat(members).forEach(function(candidate) {
            if (!candidate) return;
            [
                [candidate.atlas_lat, candidate.atlas_lon],
                [candidate.osm_lat, candidate.osm_lon]
            ].forEach(function([rawLat, rawLon]) {
                if (rawLat == null || rawLon == null) return;
                const lat = Number(rawLat);
                const lon = Number(rawLon);
                if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;
                box = box
                    ? {
                        minLat: Math.min(box.minLat, lat), maxLat: Math.max(box.maxLat, lat),
                        minLon: Math.min(box.minLon, lon), maxLon: Math.max(box.maxLon, lon)
                    }
                    : { minLat: lat, maxLat: lat, minLon: lon, maxLon: lon };
            });
        });

        if (!box) return null;
        return {
            minLat: box.minLat - CONTEXT_COORDINATE_OFFSET,
            maxLat: box.maxLat + CONTEXT_COORDINATE_OFFSET,
            minLon: box.minLon - CONTEXT_COORDINATE_OFFSET,
            maxLon: box.maxLon + CONTEXT_COORDINATE_OFFSET
        };
    }

    // Lets the map pan and zoom anywhere again: no problem is shown.
    function releaseView() {
        const problemMap = ProblemsState.getProblemMap();
        if (!problemMap || typeof problemMap.setMaxBounds !== 'function') return;
        problemMap.setMaxBounds(null);
        problemMap.setMinZoom(baseMinZoom);
    }

    // Keeps the view inside the problem's box: no panning out of it and no
    // zooming out further than the zoom at which it fills the map. If the
    // problem's own view is wider (stops far apart on a short screen), that
    // view stays reachable.
    function lockViewToProblem(problemMap, problem) {
        if (typeof problemMap.setMaxBounds !== 'function') return;
        const box = getProblemBox(problem);
        if (!box) {
            releaseView();
            return;
        }
        const bounds = L.latLngBounds([box.minLat, box.minLon], [box.maxLat, box.maxLon]);
        problemMap.setMinZoom(Math.min(problemMap.getBoundsZoom(bounds, true), problemMap.getZoom()));
        problemMap.setMaxBounds(bounds.extend(problemMap.getBounds()));
    }

    function abortCurrentContextRequest() {
        const request = currentContextRequest;
        currentContextRequest = null;
        // Sequence checks also keep a late answer from committing.
        if (request) request.abort();
    }

    // A failed load of nearby stops leaves the map looking as if there were
    // none, so the page says so on the map and offers to try again.
    function contextErrorMessage(error) {
        if (error && error.status === 429) {
            return 'Nearby stops not shown: too many requests. Wait a moment, then retry.';
        }
        return 'Nearby stops could not be loaded.';
    }

    function showContextError(message) {
        const banner = document.getElementById('problemContextBanner');
        if (!banner) return;
        const text = document.getElementById('problemContextBannerText');
        const retry = document.getElementById('problemContextRetry');
        if (text) text.textContent = message;
        if (retry) {
            retry.hidden = false;
            retry.onclick = function() {
                loadContextData(ProblemsState.getCurrentProblem());
            };
        }
        banner.classList.remove('d-none');
    }

    function hideContextError() {
        const banner = document.getElementById('problemContextBanner');
        if (banner) banner.classList.add('d-none');
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
        hideContextError();
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
        const snapshot = window.MapEntityAdapters.stops(filteredStops, { emphasis: 'context' });
        const layout = window.MapRenderer.layoutEntities(snapshot.entities, {
            map: problemMap, zoom: zoom, sourcePositionsByKey: snapshot.sourcePositionsByKey
        });
        LineRenderer.drawRelationships(snapshot.relationships, renderedContextLayer, layout.displayPositionsByKey, {
            minZoom: PROBLEM_LINE_ZOOM_THRESHOLD, currentZoom: zoom, isContext: true
        });
        const contextMarkers = window.MapRenderer.renderEntities(snapshot.entities, renderedContextLayer, {
            batchAdd: true, layout: layout, bindPopup: bindContextMarkerPopup
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

    // Pixels of the map hidden by the filter toolbar (top) and the problem panel (bottom).
    function problemViewInsets(map) {
        const container = map.getContainer && map.getContainer();
        if (!container) return null;
        const mapRect = container.getBoundingClientRect();
        const toolbar = document.querySelector('.top-filters-overlay');
        const panel = document.getElementById('problemSection');
        const toolbarBottom = toolbar ? toolbar.getBoundingClientRect().bottom : mapRect.top;
        const panelTop = panel ? panel.getBoundingClientRect().top : mapRect.bottom;
        return {
            top: Math.max(0, toolbarBottom - mapRect.top),
            bottom: Math.max(0, mapRect.bottom - panelTop)
        };
    }

    function renderProblem(problem, options) {
        const problemMap = ProblemsState.getProblemMap();
        if (!problemMap) return false;

        const fitsView = !options || options.fitView !== false;
        isRenderingProblem = true;
        try {
            // Fitting a new problem may need to leave the previous one's box.
            if (fitsView) releaseView();
            ProblemsRenderer.drawProblemOnMap(problemMap, problem, {
                markersLayer: ProblemsState.getProblemMarkersLayer(),
                linesLayer: ProblemsState.getProblemLinesLayer()
            }, { viewInsets: () => problemViewInsets(problemMap), ...(options || {}) });
            const labelZoom = AppConstants.MAP.LABEL_ICON_MIN_ZOOM || 18;
            if (fitsView) lockViewToProblem(problemMap, problem);
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
                center: AppConstants.MAP.DEFAULT_CENTER,
                zoom: AppConstants.MAP.DEFAULT_ZOOM
            },
            mapOptions: {
                closePopupOnClick: false,
                maxZoom: AppConstants.MAP.MAX_ZOOM,
                // The problem's box is a hard edge, not an elastic one.
                maxBoundsViscosity: 1.0,
                zoomControl: false
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
        baseMinZoom = typeof problemMap.getMinZoom === 'function' ? problemMap.getMinZoom() : 0;
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
        hideContextError();
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

        const box = getProblemBox(problem);
        if (!box) {
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
            min_lat: box.minLat,
            max_lat: box.maxLat,
            min_lon: box.minLon,
            max_lon: box.maxLon,
            zoom: zoom
        };

        const requestSequence = ++contextRequestSequence;
        abortCurrentContextRequest();
        hideContextError();

        const request = new AbortController();
        currentContextRequest = request;

        SharedUtils.fetchJson('/api/data', params, { signal: request.signal }).then(function(payload) {
            if (
                requestSequence !== contextRequestSequence ||
                request !== currentContextRequest ||
                !ProblemsState.getShowContext()
            ) {
                return;
            }

            const stops = normalizeContextResponse(payload);
            if (stops === null) {
                showContextError(contextErrorMessage(null));
                return;
            }

            renderedContext = {
                problemKey: problemKey,
                stops: stops
            };
            const renderZoom = problemMap ? problemMap.getZoom() : zoom;
            renderContextData(problem, stops, problemMap, renderZoom);
        }, function(error) {
            if (
                requestSequence === contextRequestSequence &&
                !SharedUtils.isAbortError(error) &&
                ProblemsState.getShowContext()
            ) {
                showContextError(contextErrorMessage(error));
            }
        }).finally(function() {
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
        const button = document.getElementById('toggleContextBtn');

        if (showContext) {
            button.classList.remove('bg-body', 'text-body');
            button.classList.add('btn-secondary');
            button.innerHTML = '<i class="fas fa-eye-slash"></i> Hide other markers';
            const currentProblem = ProblemsState.getCurrentProblem();
            if (currentProblem) {
                loadContextData(currentProblem);
            }
        } else {
            button.classList.remove('btn-secondary');
            button.classList.add('bg-body', 'text-body');
            button.innerHTML = '<i class="fas fa-eye"></i> See other markers';
            clearContextData();
        }
    }

    /**
     * Initialize modern resize functionality
     */
    function initializeResize() {
        if (removeResizeHandlers) removeResizeHandlers();
        const mapSection = document.getElementById('mapSection');
        const problemSection = document.getElementById('problemSection');
        const resizeDivider = document.getElementById('resizeDivider');
        if (!mapSection || !problemSection || !resizeDivider) return;
        const listeners = new AbortController();
        const listen = { signal: listeners.signal };

        let isResizing = false;
        let startX = 0;
        let startMapWidth = 0;
        let startProblemWidth = 0;

        resizeDivider.addEventListener('mousedown', function(e) {
            isResizing = true;
            startX = e.clientX;
            startMapWidth = mapSection.getBoundingClientRect().width;
            startProblemWidth = problemSection.getBoundingClientRect().width;

            document.body.classList.add('user-select-none');
            resizeDivider.classList.add('resizing');
            e.preventDefault();
        }, listen);

        document.addEventListener('mousemove', function(e) {
            if (!isResizing) return;

            const deltaX = e.clientX - startX;
            let newMapWidth = startMapWidth + deltaX;
            let newProblemWidth = startProblemWidth - deltaX;

            // Enforce min-width constraints from CSS
            const minMapWidth = parseInt(getComputedStyle(mapSection).minWidth, 10) || 300;
            const minProblemWidth = parseInt(getComputedStyle(problemSection).minWidth, 10) || 450;

            if (newMapWidth < minMapWidth) {
                newMapWidth = minMapWidth;
                newProblemWidth = startMapWidth + startProblemWidth - newMapWidth;
            }

            if (newProblemWidth < minProblemWidth) {
                newProblemWidth = minProblemWidth;
                newMapWidth = startMapWidth + startProblemWidth - newProblemWidth;
            }

            mapSection.style.flex = `1 1 ${newMapWidth}px`;
            problemSection.style.flex = `0 0 ${newProblemWidth}px`;
        }, listen);

        document.addEventListener('mouseup', function() {
            if (isResizing) {
                isResizing = false;
                document.body.classList.remove('user-select-none');
                resizeDivider.classList.remove('resizing');

                // Invalidate map size to fix any rendering issues
                const problemMap = ProblemsState.getProblemMap();
                if (problemMap) {
                    problemMap.invalidateSize();
                }
            }
        }, listen);

        removeResizeHandlers = function() {
            listeners.abort();
            document.body.classList.remove('user-select-none');
            resizeDivider.classList.remove('resizing');
        };
    }

    // Public API
    return {
        initProblemMap,
        invalidateMapSize,
        destroyProblemMap,
        renderProblem,
        releaseView,
        loadContextData,
        clearContextData,
        toggleContext,
        initializeResize
    };
})();
