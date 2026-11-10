// Index map state. `let` keeps the Leaflet instance out of window.map; the
// small set of page functions used by filters.js is exported explicitly below.
let map;
let indexMapCore = null;
let viewportLoader = null;
let markerRegistry = null;
let popupController = null;
let focusedStop = null; // the stop centerMapAndOpenPopup opened; see showFocusedStop
let topNPopupMarkers = [];
let topNRequest = null;
let topNRequestSequence = 0;
let headerSummaryController = null;
let mobileFiltersController = null;
var markersLayer = L.layerGroup();
var linesLayer = L.layerGroup();
var topNLayer = L.layerGroup(); // For top N distances overlay
var stopsById = {};   // Global store for stops by id.

// Performance tuning constants (from AppConstants)
var ZOOM_LINE_THRESHOLD = AppConstants.MAP.ZOOM_LINE_THRESHOLD;
var VIEW_DEBOUNCE_MS = AppConstants.DATA_LOADING.VIEW_DEBOUNCE_MS;

// Request management unrelated to viewport loading.
var currentGlobalStatsRequest = null; // AbortController of in-flight /api/global_stats
var currentGlobalStatsSeq = 0;  // sequence id to ignore stale global stats responses
var zoomBannerTimeout = null;   // debounce timer for the zoom warning banner
var zoomBannerTransientHiddenReasons = Object.create(null); // temporary hide reasons (e.g. hover/tooltips)
var headerSummaryFiltersExpanded = false;
var headerSummaryCollapsed = false;
var mobileFiltersOpen = false;

// Permalinks (see the "Permalinks" section below).
var INDEX_STOP_KEYS = ['sloid', 'osm'];
var INDEX_POPUP_OPTIONS = { permalinks: true };
var indexMapHash = null;
var indexPopupLinks = null;

/**
 * Invalidate the viewport cache, forcing the next load to fetch fresh data.
 * Call this when filters change or when you need to force a refresh.
 */
function invalidateViewportCache() {
    if (viewportLoader) viewportLoader.invalidate();
    // Stop details can depend on data refreshed by a filter change. Keep the
    // marker identity, but make the next click fetch current popup data.
    if (popupController) popupController.invalidate();
}

// Expose globally for filter changes
window.invalidateViewportCache = invalidateViewportCache;

function _stableParamsKey(params, mode) {
    // Zoom is represented by the request policy (`mode` and `limit`), not by
    // its exact number. This lets an uncapped buffered result survive a
    // zoom-in while marker render signatures still update.
    var ignored = { min_lat: 1, max_lat: 1, min_lon: 1, max_lon: 1, offset: 1, include_meta: 1 };
    var keys = Object.keys(params || {}).filter(function (k) { return !ignored[k]; }).sort();
    var parts = ['mode=' + String(mode || '')];
    keys.forEach(function (k) {
        parts.push(k + '=' + String(params[k]));
    });
    return parts.join('&');
}

// Shared canonical entity rendering is provided by map-renderer.js

// Create the Index map from one explicit configuration. MapCore owns map,
// controls, base layers, path renderer, popup-line handlers, and cleanup.
function initMap() {
    indexMapCore = window.MapComponents.MapCore.create({
        container: 'map',
        view: Permalinks.initialMapView({
            center: AppConstants.MAP.DEFAULT_CENTER,
            zoom: AppConstants.MAP.DEFAULT_ZOOM
        }),
        mapOptions: {
            closePopupOnClick: false,
            minZoom: AppConstants.MAP.MIN_ZOOM,
            maxZoom: AppConstants.MAP.MAX_ZOOM,
            maxBounds: AppConstants.MAP.MAX_BOUNDS,
            maxBoundsViscosity: AppConstants.MAP.MAX_BOUNDS_VISCOSITY,
            zoomControl: false
        },
        layerGroups: {
            markers: { layer: markersLayer, controlLabel: 'Markers' },
            lines: { layer: linesLayer, controlLabel: 'Connection Lines' },
            topN: { layer: topNLayer }
        },
        controls: {
            zoom: { position: 'bottomleft' },
            layers: { position: 'bottomleft' }
        },
        defaultBaseLayer: 'OpenStreetMap',
        popupBehavior: true,
        invalidateOnResize: true
    });

    map = indexMapCore.map;
    MapLegend.add(map, { sourceLabel: SharedUtils.sourceLabel() });
    popupController = createIndexPopupController();
    markerRegistry = createIndexMarkerRegistry();
    viewportLoader = createIndexViewportLoader();
    bindIndexPermalinks();
}

function showZoomBanner(show, delayMs = 0) {
    var banner = document.getElementById('zoomBannerInfo');
    if (!banner) return;

    if (zoomBannerTimeout) {
        clearTimeout(zoomBannerTimeout);
        zoomBannerTimeout = null;
    }

    if (show) {
        if (!banner.classList.contains('d-none')) return;

        if (delayMs > 0) {
            zoomBannerTimeout = setTimeout(function () {
                banner.classList.remove('d-none');
                zoomBannerTimeout = null;
            }, delayMs);
        } else {
            banner.classList.remove('d-none');
        }
    } else {
        banner.classList.add('d-none');
    }
}

function setZoomBannerText(text) {
    var banner = document.getElementById('zoomBannerInfo');
    if (!banner) return;
    banner.textContent = text;
}

function setZoomBannerTransientHidden(reasonKey, hidden) {
    var banner = document.getElementById('zoomBannerInfo');
    if (!banner) return;

    if (!reasonKey) return;
    zoomBannerTransientHiddenReasons[String(reasonKey)] = !!hidden;

    var shouldHide = Object.keys(zoomBannerTransientHiddenReasons).some(function (k) {
        return zoomBannerTransientHiddenReasons[k];
    });

    banner.classList.toggle('zoom-banner--faded', shouldHide);
}

function setMobileFiltersOpen(open) {
    var nextOpen = !!open;
    mobileFiltersOpen = nextOpen;

    if (mobileFiltersController) mobileFiltersController.setOpen(nextOpen, 'page-state');

    var overlay = document.querySelector('.top-filters-overlay');
    var toggle = document.getElementById('mobileFiltersToggle');
    var banner = document.getElementById('zoomBannerInfo');
    if (!overlay || !toggle) return;

    if (banner) {
        banner.classList.toggle('zoom-banner--filters-open', mobileFiltersOpen);
    }
}

function setHeaderSummaryCollapsed(collapsed) {
    headerSummaryCollapsed = !!collapsed;
    if (headerSummaryController) headerSummaryController.setCollapsed(headerSummaryCollapsed, 'page-state');
}

function applyMobileLayoutState() {
    if (SharedUtils.isMobileViewport()) {
        setMobileFiltersOpen(false);
        setHeaderSummaryCollapsed(true);
        return;
    }

    setMobileFiltersOpen(false);
    setHeaderSummaryCollapsed(false);
}

function syncHeaderSummaryFilterToggle() {
    if (!headerSummaryController) return;
    headerSummaryController.syncFilters({
        activeFilterCount: window.getActiveFilterCount(),
        expanded: headerSummaryFiltersExpanded
    });
}

function initializeSharedUiBindings() {
    headerSummaryController = window.HeaderSummary.bind({
        collapsed: headerSummaryCollapsed,
        filtersExpanded: headerSummaryFiltersExpanded,
        getActiveFilterCount: window.getActiveFilterCount,
        isMobileViewport: SharedUtils.isMobileViewport,
        onCollapsedChange: function (collapsed) {
            headerSummaryCollapsed = collapsed;
            if (!collapsed && SharedUtils.isMobileViewport() && mobileFiltersController) {
                mobileFiltersController.setOpen(false, 'summary-opened');
            }
        },
        onFiltersExpandedChange: function (expanded) {
            headerSummaryFiltersExpanded = expanded;
        },
        onClearAll: function () {
            window.clearAllFilters();
        }
    });

    mobileFiltersController = window.MobileFilters.bind({
        overlaySelector: '.top-filters-overlay',
        toggleId: 'mobileFiltersToggle',
        isOpen: mobileFiltersOpen,
        closeOnOutsideClick: true,
        closeOnEscape: true,
        onOpenChange: function (open) {
            mobileFiltersOpen = open;
            var banner = document.getElementById('zoomBannerInfo');
            if (banner) banner.classList.toggle('zoom-banner--filters-open', open);
            if (open && SharedUtils.isMobileViewport() && headerSummaryController) {
                headerSummaryController.setCollapsed(true, 'filters-opened');
            }
        }
    });
}

function appendOsmGroupParams(params) {
    if (!activeFilters.osmGroups || activeFilters.osmGroups.length === 0) {
        return params;
    }

    const selectedGroupTypes = activeFilters.osmGroups.filter(function (groupType) {
        return groupType !== 'all';
    });

    if (activeFilters.osmGroups.includes('all')) {
        params.osm_group_types = 'all';
    } else if (selectedGroupTypes.length > 0) {
        params.osm_group_types = selectedGroupTypes.join(',');
    }

    return params;
}

function restoreOperatorFiltersFromUrl() {
    var params = new URLSearchParams(window.location.search);
    [
        ['atlas_operator', 'atlasOperators', 'operatorDropdown'],
        ['osm_operator', 'osmOperators', 'osmOperatorDropdown'],
        ['osm_operator_wikidata', 'osmOperatorWikidata', 'osmOperatorWikidataDropdown']
    ].forEach(function (entry) {
        if (!params.has(entry[0])) return;
        var values = params.getAll(entry[0]).flatMap(function (value) {
            return value.split(',').map(function (item) { return item.trim(); }).filter(Boolean);
        });
        activeFilters[entry[1]] = [...new Set(values)];
        if (window[entry[2]]) window[entry[2]].setSelection(activeFilters[entry[1]]);
    });
    activeFilters.missingOsmOperatorWikidata = params.get('missing_osm_operator_wikidata') === 'true';
    var missingWikidataCheckbox = document.getElementById('filterMissingOsmOperatorWikidata');
    if (missingWikidataCheckbox) missingWikidataCheckbox.checked = activeFilters.missingOsmOperatorWikidata;
    if (activeFilters.missingOsmOperatorWikidata) {
        activeFilters.osmOperatorWikidata = [];
        if (window.osmOperatorWikidataDropdown) window.osmOperatorWikidataDropdown.setSelection([]);
    }
}

// problem_type (all, or a list) and priority: the stops with such a problem.
function appendProblemFilterParams(params) {
    var types = activeFilters.problemTypes || [];
    var priorities = activeFilters.problemPriorities || [];
    if (types.length > 0) params.problem_type = types.join(',');
    if (priorities.length > 0) params.priority = priorities.join(',');
    return params;
}

function appendCurrentFilterParams(params, options) {
    options = options || {};
    var includeTopN = options.includeTopN === true;
    var includeShowDuplicates = options.includeShowDuplicates === true;

    if (activeFilters.stopType.length > 0) {
        params.stop_filter = activeFilters.stopType.join(',');
    }
    if (activeFilters.matchMethods.length > 0) {
        params.match_method = activeFilters.matchMethods.join(',');
    }
    if (activeFilters.station.length > 0) {
        params.station_filter = activeFilters.station.join(',');
        params.filter_types = activeFilters.stationTypes.join(',');
        params.route_directions = activeFilters.routeDirections.join(',');
        if (routeVariantsParam()) params.route_variants = routeVariantsParam();
    }
    if (activeFilters.transportTypes.length > 0) {
        params.transport_types = activeFilters.transportTypes.join(',');
    }
    if (activeFilters.osmEntityTypes.length > 0) {
        params.osm_entity_types = activeFilters.osmEntityTypes.join(',');
    }
    if (activeFilters.atlasOperators.length > 0) {
        params.atlas_operator = activeFilters.atlasOperators.join(',');
    }
    if (activeFilters.osmOperators.length > 0) {
        params.osm_operator = activeFilters.osmOperators.join(',');
    }
    if (activeFilters.osmOperatorWikidata && activeFilters.osmOperatorWikidata.length > 0) {
        params.osm_operator_wikidata = activeFilters.osmOperatorWikidata.join(',');
    }
    if (activeFilters.missingOsmOperatorWikidata) params.missing_osm_operator_wikidata = 'true';
    appendProblemFilterParams(params);
    if (includeTopN && activeFilters.topN) {
        params.top_n = activeFilters.topN;
    }
    if (includeShowDuplicates) {
        params.show_duplicates_only = activeFilters.showDuplicatesOnly ? 'true' : 'false';
    }

    appendOsmGroupParams(params);
    return params;
}

function getEffectiveMapSideVisibility() {
    if (activeFilters.showDuplicatesOnly) {
        return { showAtlas: true, showOsm: false };
    }

    return { showAtlas: true, showOsm: true };
}

function clearTopNMarkers() {
    topNRequestSequence += 1;
    if (topNRequest) topNRequest.abort();
    topNRequest = null;
    topNPopupMarkers.forEach(function (marker) {
        if (popupController) popupController.detach(marker);
    });
    topNPopupMarkers = [];
    topNLayer.clearLayers();
}

function setTopNMessage(html) {
    var message = document.getElementById('topNDistancesMessage');
    if (message) message.innerHTML = html;
}

function loadTopNMatches() {
    clearTopNMarkers();
    setTopNMessage('');

    if (activeFilters.topN && activeFilters.stopType.includes("matched")) {
        var params = { limit: activeFilters.topN };
        // Send specific, active match methods
        if (activeFilters.matchMethods.length > 0) {
            params.match_method = activeFilters.matchMethods.join(',');
        }

        // Add station filter values and type if available
        if (activeFilters.station.length > 0) {
            params.station_filter = activeFilters.station.join(',');
            params.filter_types = activeFilters.stationTypes.join(',');
            params.route_directions = activeFilters.routeDirections.join(',');
            if (routeVariantsParam()) params.route_variants = routeVariantsParam();
        }

        // Add transport type filters to params (New)
        if (activeFilters.transportTypes.length > 0) {
            params.transport_types = activeFilters.transportTypes.join(',');
        }

        // Add atlas operator filters to params
        if (activeFilters.atlasOperators.length > 0) {
            params.atlas_operator = activeFilters.atlasOperators.join(',');
        }

        // Add OSM operator filters to params
        if (activeFilters.osmOperators.length > 0) {
            params.osm_operator = activeFilters.osmOperators.join(',');
        }
        if (activeFilters.osmOperatorWikidata && activeFilters.osmOperatorWikidata.length > 0) {
            params.osm_operator_wikidata = activeFilters.osmOperatorWikidata.join(',');
        }
        if (activeFilters.missingOsmOperatorWikidata) params.missing_osm_operator_wikidata = 'true';
        if (activeFilters.showDuplicatesOnly) {
            params.show_duplicates_only = 'true';
        }
        appendProblemFilterParams(params);

        appendOsmGroupParams(params);

        var requestSequence = ++topNRequestSequence;
        var request = new AbortController();
        topNRequest = request;
        SharedUtils.fetchJson("/api/top_matches", params, { signal: request.signal }).then(function (data) {
            if (requestSequence !== topNRequestSequence || !activeFilters.topN) return;
            let filteredData = data;

            if (filteredData.length === 0) {
                setTopNMessage("<div class='alert alert-warning mt-2'>No matched nodes satisfy these conditions.</div>");
            } else {
                var mapSideVisibility = getEffectiveMapSideVisibility();
                var showAtlasNodes = mapSideVisibility.showAtlas;
                var showOSMNodes = mapSideVisibility.showOsm;

                var snapshot = window.MapEntityAdapters.topMatches(filteredData, {
                    showAtlas: showAtlasNodes, showOsm: showOSMNodes
                });
                var layout = window.MapRenderer.layoutEntities(snapshot.entities, {
                    map: map, zoom: map.getZoom(), sourcePositionsByKey: snapshot.sourcePositionsByKey
                });
                LineRenderer.drawRelationships(snapshot.relationships, topNLayer, layout.displayPositionsByKey, {
                    showAtlas: showAtlasNodes, showOsm: showOSMNodes, currentZoom: map.getZoom()
                });
                topNPopupMarkers = window.MapRenderer.renderEntities(snapshot.entities, topNLayer, {
                    layout: layout,
                    bindPopup: function (marker, entity) { attachIndexPopup(marker, { key: entity.key, entity: entity }); }
                });
                showFocusedStop();
            }
        }, function (error) {
            if (requestSequence !== topNRequestSequence || SharedUtils.isAbortError(error)) return;
            setTopNMessage("<div class='alert alert-warning mt-2'>Could not load Top N matches.</div>");
        }).finally(function () {
            if (topNRequest === request) topNRequest = null;
        });
    }
}

function getViewportPolicy(zoom) {
    var zoomPolicy = window.MapShared.getViewportZoomPolicy(zoom);
    var isLowZoom = zoomPolicy.isOverview;
    var hasAnyActiveFilter = window.getActiveFilterCount() > 0;
    var fullUncappedZoom = zoomPolicy.isFullDetail;
    var params = {
        offset: 0,
        include_meta: 1
    };

    if (zoomPolicy.limit != null) {
        params.limit = zoomPolicy.limit;
    }

    if (isLowZoom && !hasAnyActiveFilter) {
        params.stop_filter = 'atlas_unmatched';
        params.node_type = 'atlas';
        if (activeFilters.atlasOperators.length > 0) {
            params.atlas_operator = activeFilters.atlasOperators.join(',');
        }
    } else {
        appendCurrentFilterParams(params, { includeShowDuplicates: true });
    }

    var mode = isLowZoom
        ? (hasAnyActiveFilter ? 'lowzoom_filtered' : 'lowzoom_unmatched_atlas')
        : 'normal';

    return {
        zoom: zoom,
        isLowZoom: isLowZoom,
        hasAnyActiveFilter: hasAnyActiveFilter,
        fullUncappedZoom: fullUncappedZoom,
        shouldShowBanner: !fullUncappedZoom,
        mode: mode,
        params: params,
        identity: _stableParamsKey(params, mode)
    };
}

function normalizeViewportPayload(rawData) {
    if (rawData && typeof rawData === 'object' && Array.isArray(rawData.stops)) {
        return {
            stops: rawData.stops,
            meta: rawData.meta || null
        };
    }
    return {
        stops: Array.isArray(rawData) ? rawData : [],
        meta: null
    };
}

function isViewportPayloadCapped(rawData, policy) {
    var payload = normalizeViewportPayload(rawData);
    if (payload.meta && payload.meta.has_more) return true;
    return !!(
        policy.params.limit &&
        payload.stops.length >= Number(policy.params.limit)
    );
}

function prepareZoomBanner(policy) {
    if (!policy.shouldShowBanner) {
        showZoomBanner(false);
        return;
    }
    if (!policy.hasAnyActiveFilter) {
        setZoomBannerText(policy.isLowZoom
            ? `Showing only unmatched ${SharedUtils.sourceLabel()} stops. Zoom in to see all.`
            : 'Showing some stops here. Zoom in to see all.');
    }
    showZoomBanner(true, 150);
}

function updateZoomBannerFromPayload(policy, stops, capped) {
    if (!policy.shouldShowBanner) {
        showZoomBanner(false);
        return;
    }

    if (policy.hasAnyActiveFilter) {
        var resultCount = stops.length;
        var count = SharedUtils.formatCount(resultCount);
        var one = resultCount === 1;

        setZoomBannerText(capped
            ? 'Showing ' + count + ' filtered stop' + (one ? '' : 's') + '. Zoom in to see all.'
            : count + (one ? ' stop matches' : ' stops match') + ' the filters.');
        showZoomBanner(true);
        return;
    }

    if (!policy.isLowZoom && !capped) {
        showZoomBanner(false);
    }
}

function getViewportVisibility(policy) {
    if (policy.isLowZoom && !policy.hasAnyActiveFilter) {
        return { showAtlas: true, showOsm: false };
    }
    return getEffectiveMapSideVisibility();
}

function popupContentForMarker(payload, markerData) {
    var enriched = payload && (payload.stop || payload);
    if (enriched && enriched.stop_type === 'atlas_unmatched') {
        return markerData.entityType === 'atlas'
            ? PopupRenderer.generateSingleAtlasBubbleHtml(enriched, true, INDEX_POPUP_OPTIONS)
            : PopupRenderer.generateSingleOsmBubbleHtml(enriched, true, INDEX_POPUP_OPTIONS);
    }
    return PopupRenderer.generatePopupHtml(enriched, markerData.entityType, INDEX_POPUP_OPTIONS);
}

function attachIndexPopup(marker, descriptor) {
    var markerData = descriptor.entity;
    marker.options = marker.options || {};
    marker.options.markerData = markerData;

    if (!markerData || !markerData.popupRef) return;
    popupController.attach(marker, {
        key: descriptor.key,
        errorContent: '<div class="p-2 text-danger">Unable to load stop details. Click to retry.</div>',
        // The server builds the whole popup, an OSM element's every ATLAS match
        // included, so its content never depends on the zoom or the loaded data.
        load: function (request) {
            var latest = marker.options.markerData;
            return SharedUtils.fetchJson('/api/stop_popup', {
                stop_id: latest.popupRef.id,
                view_type: latest.entityType
            }, { signal: request.signal });
        },
        render: function (payload) {
            return popupContentForMarker(payload, marker.options.markerData);
        },
        createPopup: function (content) {
            return window.MapRenderer.createPopupWithOptions(content);
        },
        onError: function (error) {
            console.error('Failed to load stop popup:', error);
        }
    });
}

function createIndexPopupController() {
    return window.MapComponents.MapPopupController.create({
        cache: 'payload'
    });
}

function createIndexMarkerRegistry() {
    return window.MapComponents.MapLayerRegistry.create({
        layerGroup: markersLayer,
        create: function (descriptor) {
            var marker = window.MapRenderer.createEntityMarker(descriptor);
            attachIndexPopup(marker, descriptor);
            return marker;
        },
        update: function (marker, descriptor) {
            marker.setLatLng(descriptor.displayPosition);
            attachIndexPopup(marker, descriptor);
        },
        onRemove: function (marker, descriptor, removal) {
            if (removal && removal.reason === 'replace' && removal.replacementLayer) {
                popupController.transfer(marker, removal.replacementLayer);
            } else {
                popupController.detach(marker);
            }
        }
    });
}

function renderIndexViewport(rawData, context) {
    if (activeFilters.topN) return;

    var policy = getViewportPolicy(context.zoom);
    var payload = normalizeViewportPayload(rawData);
    var capped = isViewportPayloadCapped(rawData, policy);
    var visibility = getViewportVisibility(policy);

    updateZoomBannerFromPayload(policy, payload.stops, capped);

    Object.keys(stopsById).forEach(function (stopId) {
        delete stopsById[stopId];
    });
    payload.stops.forEach(function (stop) {
        if (stop && stop.id != null) stopsById[stop.id] = stop;
    });

    var snapshot = window.MapEntityAdapters.stops(payload.stops, {
        showAtlas: visibility.showAtlas, showOsm: visibility.showOsm
    });
    var layout = window.MapRenderer.layoutEntities(snapshot.entities, {
        map: map, zoom: context.zoom, sourcePositionsByKey: snapshot.sourcePositionsByKey
    });
    markerRegistry.reconcile(layout.descriptors, {
        zoom: context.zoom,
        cacheHit: context.cacheHit,
        reason: context.reason
    });

    LineRenderer.clearLines(linesLayer);
    LineRenderer.drawRelationships(snapshot.relationships, linesLayer, layout.displayPositionsByKey, {
        showAtlas: visibility.showAtlas,
        showOsm: visibility.showOsm,
        minZoom: ZOOM_LINE_THRESHOLD,
        currentZoom: context.zoom,
        isContext: false
    });
    showFocusedStop();
}

function createIndexViewportLoader() {
    return window.MapComponents.MapViewportLoader.create({
        map: map,
        events: ['moveend', 'zoomend'],
        debounceMs: VIEW_DEBOUNCE_MS,
        buildRequestBounds: function (context) {
            var policy = getViewportPolicy(context.zoom);
            return context.bounds.pad(policy.isLowZoom ? 0.5 : 0.35);
        },
        getRequestIdentity: function (context) {
            return getViewportPolicy(context.zoom).identity;
        },
        shouldReuse: function (cacheEntry, context) {
            var cachedPolicy = getViewportPolicy(cacheEntry.zoom);
            var sameZoom = cacheEntry.zoom === context.zoom;
            var safeZoomIn = context.zoom > cacheEntry.zoom &&
                !isViewportPayloadCapped(cacheEntry.data, cachedPolicy);
            if (!sameZoom && !safeZoomIn) return false;

            try {
                return cacheEntry.requestBounds.contains(context.bounds.pad(-0.05));
            } catch (error) {
                return false;
            }
        },
        shouldLoad: function () {
            return !activeFilters.topN;
        },
        load: function (context) {
            var policy = getViewportPolicy(context.zoom);
            var params = Object.assign({}, policy.params, {
                min_lat: context.requestBounds.getSouth(),
                max_lat: context.requestBounds.getNorth(),
                min_lon: context.requestBounds.getWest(),
                max_lon: context.requestBounds.getEast()
            });
            prepareZoomBanner(policy);
            return SharedUtils.fetchJson('/api/data', params, { signal: context.signal });
        },
        onData: renderIndexViewport,
        onError: function (error) {
            console.error('Failed to refresh /api/data:', error);
            setZoomBannerText('⚠️ Could not load stops. Showing the previous view.');
            showZoomBanner(true);
        }
    });
}

function loadDataForViewport(options) {
    if (!viewportLoader || !markerRegistry) return Promise.resolve({ status: 'not-ready' });

    if (activeFilters.topN) {
        viewportLoader.invalidate();
        markerRegistry.clear('top-n-mode');
        LineRenderer.clearLines(linesLayer);
        showZoomBanner(false);
        return Promise.resolve({ status: 'top-n' });
    }

    clearTopNMarkers();
    prepareZoomBanner(getViewportPolicy(map.getZoom()));
    return viewportLoader.reload(options || { reason: 'page-request' });
}

// The marker the map draws for an entity key, in the viewport or the Top N overlay.
function findMapMarker(key) {
    var marker = markerRegistry && markerRegistry.has(key) ? markerRegistry.get(key) : null;
    if (marker) return marker;
    return topNPopupMarkers.find(function (candidate) {
        var markerData = candidate.options && candidate.options.markerData;
        return markerData && markerData.key === key;
    }) || null;
}

function removeFocusedStop() {
    if (focusedStop && focusedStop.layer && map) map.removeLayer(focusedStop.layer);
    focusedStop = null;
}

// Shows the stop opened by search, a link or Random stop on the marker the map
// draws for it, so the stop has one marker and its match line starts there.
// Only while the map draws none (filters can leave the stop out) does the stop
// get a marker of its own, which goes as soon as the map draws one.
function showFocusedStop() {
    var focus = focusedStop;
    if (!focus || !map) return;
    var marker = findMapMarker(focus.entity.key);
    if (marker) {
        var popupOpen = focus.layer
            ? focus.layer.getLayers().some(function (layer) { return layer.isPopupOpen(); })
            : focus.openPopup;
        removeFocusedStop();
        if (popupOpen && popupController && popupController.has(marker)) popupController.open(marker);
        return;
    }
    if (focus.layer) return;
    focus.layer = L.layerGroup().addTo(map);
    var created = window.MapRenderer.renderEntities([focus.entity], focus.layer, {
        bindPopup: function (layer) { layer.bindPopup(focus.popup); },
        map: map,
        zoom: map.getZoom()
    });
    if (focus.openPopup && created.length > 0) created[0].openPopup();
}

// Reusable function to center map and open popup for a stop
function centerMapAndOpenPopup(stopData, centerLat, centerLon, popupViewType, zoomLevel = 17, shouldOpenPopup = true) {
    if (stopData && centerLat !== undefined && centerLon !== undefined) {
        // Pause loader-owned map events while changing the view, then perform
        // one explicit reload for the final viewport.
        var resumeViewport = viewportLoader ? viewportLoader.pause() : function () {};
        map.setView([centerLat, centerLon], zoomLevel, { animate: false });
        // The popup opens above its stop, so show the stop two thirds down the map
        // instead of in the middle, where the popup would reach the top.
        if (shouldOpenPopup) {
            map.panBy([0, -Math.round(map.getSize().y / 6)], { animate: false });
        }
        resumeViewport();

        // Ensure the stopData is stored in stopsById if it wasn't already
        stopsById[stopData.id] = stopData;

        // Generate the appropriate popup HTML
        const popupHtml = PopupRenderer.generatePopupHtml(stopData, popupViewType, INDEX_POPUP_OPTIONS);
        const popup = window.MapRenderer.createPopupWithOptions(popupHtml).setLatLng([centerLat, centerLon]);

        const entity = window.MapEntityAdapters.stopEntity(popupViewType, stopData, {
            position: [centerLat, centerLon], emphasis: 'focused'
        });

        removeFocusedStop();
        const focus = entity ? { entity: entity, popup: popup, openPopup: shouldOpenPopup, layer: null } : null;
        focusedStop = focus;

        // The stop is shown once the new view has loaded: renderIndexViewport
        // calls showFocusedStop, and this call covers loads that draw nothing.
        const showAfterLoad = function () {
            if (focus && focusedStop === focus) showFocusedStop();
        };
        loadDataForViewport().then(showAfterLoad, showAfterLoad);

    } else {
        SharedUtils.notify('This stop has no coordinates to show on the map.');
    }
}

// Function to fetch and center on a random stop based on current filters
function focusOnRandomFilteredStop() {
    // Random pick honoring current filters
    var params = appendCurrentFilterParams({}, { includeTopN: true, includeShowDuplicates: true });
    Object.keys(params).forEach(function (k) {
        if (params[k] === null || params[k] === undefined || params[k] === '') {
            delete params[k];
        }
    });

    SharedUtils.fetchJson("/api/random_stop", params).then(function (data) {
        if (data.error) {
            SharedUtils.notify(data.error);
            return;
        }
        centerMapAndOpenPopup(data.stop, data.center_lat, data.center_lon, data.popup_view_type);
    }, function (error) {
        // The server explains a 404 ("No stop found for the current filters.") and a 429.
        SharedUtils.notify(SharedUtils.buildErrorMessage(error, 'Could not pick a random stop. Try again.'));
    });
}

function fetchAndCenterSpecificStop(identifier, identifierType) {
    return new Promise((resolve, reject) => {
        let backendIdentifierType = '';
        let typeName = '';
        if (identifierType === 'atlas') {
            backendIdentifierType = 'sloid';
            typeName = SharedUtils.sourceLabel() + ' ' + SharedUtils.sourceIdLabel();
        } else if (identifierType === 'osm') {
            backendIdentifierType = 'osm_node_id';
            typeName = 'OSM node';
        } else if (identifierType === 'station') {
            backendIdentifierType = 'station';
            typeName = 'UIC station';
        } else if (identifierType === 'route') {
            backendIdentifierType = 'route';
            typeName = 'route';
        } else {
            console.log("Centering not implemented for identifier type:", identifierType);
            reject("Invalid identifier type.");
            return;
        }

        SharedUtils.fetchJson("/api/stop_by_id", { identifier: identifier, identifier_type: backendIdentifierType }).then(function (data) {
            if (data.error) {
                reject(`No ${typeName} found matching: ${identifier}`);
                return;
            }
            // Use a slightly less zoomed-in level for specific searches compared to random.
            const openPopup = !(identifierType === 'station' || identifierType === 'route');
            const zoomLevel = identifierType === 'route' ? 14 : 16;
            centerMapAndOpenPopup(data.stop, data.center_lat, data.center_lon, data.popup_view_type, zoomLevel, openPopup);
            resolve(data);
        }, function () {
            reject(`No ${typeName} found matching: ${identifier}`);
        });
    });
}

// ==========================================
// Permalinks
// ==========================================
// The view is kept in #map=<zoom>/<lat>/<lon> and the stop whose popup is open
// in ?sloid=<sloid> or ?osm=node|way/<id> (static/js/shared/permalinks.js).

// Reads ?sloid= / ?osm= into the identifier /api/stop_by_id expects. OSM ways
// are stored as "way_<id>" and nodes as the bare number.
function parseStopPermalink(search) {
    var params = new URLSearchParams(search);
    var sloid = (params.get('sloid') || '').trim();
    if (sloid) return { type: 'atlas', identifier: sloid };

    var osm = /^(node|way)\/(\d+)$/.exec((params.get('osm') || '').trim());
    if (!osm) return null;
    return { type: 'osm', identifier: osm[1] === 'way' ? 'way_' + osm[2] : osm[2] };
}

// The inverse is Permalinks.stopParams, shared with the route maps' links.
function stopParamsFromButton(button) {
    if (!button) return null;
    return Permalinks.stopParams(button.getAttribute('data-permalink-type'), button.getAttribute('data-permalink-ref'));
}

// Sets (or, with null, removes) the stop parameter, keeping the others.
function replaceIndexStop(params) {
    Permalinks.replaceUrl({
        search: Permalinks.buildSearch(window.location.search, INDEX_STOP_KEYS, Permalinks.encodeParams(params))
    });
}

// The summary panel's Copy link: the view, the filters and the open stop.
function bindCopyMapLink() {
    var button = document.getElementById('copyMapLink');
    if (!button) return;
    button.addEventListener('click', function () {
        Permalinks.copyLink(button, Permalinks.pageUrl(window.location.search, Permalinks.currentMapHash(map)));
    });
}

function handleIndexMapClick(event) {
    var button = event.target && event.target.closest ? event.target.closest('.popup-copy-link') : null;
    var params = stopParamsFromButton(button);
    if (!params) return;
    var search = Permalinks.buildSearch(window.location.search, INDEX_STOP_KEYS, Permalinks.encodeParams(params));
    Permalinks.copyLink(button, Permalinks.pageUrl(search, Permalinks.currentMapHash(map)));
}

// Opens the stop named in the query string. Called once per page load; the
// stop's own view wins over a #map= hash. When the stop cannot be opened the
// map keeps the hash or default view and the stop parameter is dropped.
function openStopFromUrl() {
    var params = new URLSearchParams(window.location.search);
    var linkedKey = params.has('sloid') ? 'sloid' : (params.has('osm') ? 'osm' : null);
    if (!linkedKey) return Promise.resolve(false);

    var stop = parseStopPermalink(window.location.search);
    var request = stop
        ? fetchAndCenterSpecificStop(stop.identifier, stop.type)
        : Promise.reject(new Error('Invalid stop link.'));
    return request.then(function () {
        return true;
    }, function () {
        replaceIndexStop(null);
        SharedUtils.showTemporaryMessage(
            'Could not open the linked stop (' + SharedUtils.escapeHtml(linkedKey + '=' + params.get(linkedKey)) + ').',
            'warning',
            6000
        );
        return false;
    });
}

// Opens the route variants named by ?atlas_variant= / ?osm_variant=, the
// routes page's keys: a route filter narrowed to them. Without a #map= hash or
// a stop link, the map fits their stops.
function openRouteVariantsFromUrl() {
    var params = new URLSearchParams(window.location.search);
    var atlas = (params.get('atlas_variant') || '').trim();
    var osm = (params.get('osm_variant') || '').trim();
    if (!atlas && !osm) return Promise.resolve(false);
    if (!SharedUtils.hasCapability('routes')) return Promise.resolve(false);
    var fitView = !Permalinks.parseMapHash(window.location.hash) && !parseStopPermalink(window.location.search);
    return fetchRouteVariants({ atlas_variant: atlas, osm_variant: osm }).then(function (data) {
        addRouteVariantFilter(data);
        if (fitView && data.bounds) map.fitBounds(data.bounds, { padding: [40, 40], maxZoom: 17 });
        return true;
    }, function () {
        syncRouteVariantUrl();  // no narrowed route filter: drops the parameters
        SharedUtils.showTemporaryMessage(
            'Could not open the linked route variant (' + SharedUtils.escapeHtml(atlas || osm) +
            '): a newer import may have changed it.',
            'warning',
            6000
        );
        return false;
    });
}

function bindIndexPermalinks() {
    indexMapHash = Permalinks.bindMapHash(map);
    indexPopupLinks = Permalinks.trackPopups(map, INDEX_STOP_KEYS, function (popup) {
        return Permalinks.encodeParams(stopParamsFromButton(Permalinks.popupCopyButton(popup)));
    });
    map.getContainer().addEventListener('click', handleIndexMapClick);
}

function unbindIndexPermalinks() {
    if (indexMapHash) indexMapHash.destroy();
    if (indexPopupLinks) indexPopupLinks.destroy();
    indexMapHash = null;
    indexPopupLinks = null;
    if (map) map.getContainer().removeEventListener('click', handleIndexMapClick);
    Permalinks.cancelCopyFeedback();
}

function handleIndexResize() {
    applyMobileLayoutState();
}

function destroyIndexPage() {
    // First, so popups closed below do not strip ?sloid=/?osm= from the
    // history entry that Back returns to.
    unbindIndexPermalinks();
    window.removeEventListener('resize', handleIndexResize);
    if (currentGlobalStatsRequest && currentGlobalStatsRequest.readyState !== 4) {
        try { currentGlobalStatsRequest.abort(); } catch (error) { }
    }
    if (viewportLoader) viewportLoader.destroy();
    clearTopNMarkers();
    if (markerRegistry) markerRegistry.destroy();
    if (popupController) popupController.destroy();
    if (headerSummaryController) headerSummaryController.destroy();
    if (mobileFiltersController) mobileFiltersController.destroy();
    removeFocusedStop();
    if (indexMapCore) indexMapCore.destroy();
}


document.addEventListener('DOMContentLoaded', function () {
    initMap();
    initializeSharedUiBindings();
    applyMobileLayoutState();

    window.addEventListener('resize', handleIndexResize);
    window.addEventListener('beforeunload', destroyIndexPage, { once: true });

    var randomStopBtn = document.getElementById('randomStopBtn');
    var randomStopHint = document.getElementById('randomStopHint');
    if (randomStopBtn && randomStopHint) {
        var randomHintShowTimer = null;
        var randomHintHideTimer = null;

        var cancelRandomHintTimers = function () {
            if (randomHintShowTimer) {
                clearTimeout(randomHintShowTimer);
                randomHintShowTimer = null;
            }
            if (randomHintHideTimer) {
                clearTimeout(randomHintHideTimer);
                randomHintHideTimer = null;
            }
        };

        var showRandomStopHint = function () {
            if (randomHintHideTimer) {
                clearTimeout(randomHintHideTimer);
                randomHintHideTimer = null;
            }
            if (!randomStopHint.classList.contains('d-none')) {
                return;
            }
            randomHintShowTimer = setTimeout(function () {
                randomStopHint.classList.remove('d-none');
                setZoomBannerTransientHidden('random-hint', true);
                randomHintShowTimer = null;
            }, 70);
        };

        var hideRandomStopHint = function () {
            if (randomHintShowTimer) {
                clearTimeout(randomHintShowTimer);
                randomHintShowTimer = null;
            }
            randomHintHideTimer = setTimeout(function () {
                randomStopHint.classList.add('d-none');
                setZoomBannerTransientHidden('random-hint', false);
                randomHintHideTimer = null;
            }, 120);
        };

        randomStopBtn.addEventListener('mouseenter', showRandomStopHint);
        randomStopBtn.addEventListener('mouseleave', hideRandomStopHint);
        randomStopBtn.addEventListener('focus', showRandomStopHint);
        randomStopBtn.addEventListener('blur', hideRandomStopHint);
        randomStopBtn.addEventListener('click', hideRandomStopHint);
        window.addEventListener('beforeunload', function () {
            cancelRandomHintTimers();
            setZoomBannerTransientHidden('random-hint', false);
        });
    }

    // Hide zoom banner while desktop filter popups are open to avoid overlap.
    var topFiltersOverlay = document.querySelector('.top-filters-overlay');
    if (topFiltersOverlay) {
        topFiltersOverlay.addEventListener('shown.bs.dropdown', function (event) {
            var dropdown = event.target.closest('.dropdown');
            if (!dropdown) return;
            var toggle = dropdown.querySelector('.dropdown-toggle');
            var id = toggle ? toggle.id : Math.random().toString();
            dropdown.dataset.dropdownInstanceId = id; // Save it to ensure consistent removal
            setZoomBannerTransientHidden('filters-dropdown-' + id, true);
        });
        topFiltersOverlay.addEventListener('hidden.bs.dropdown', function (event) {
            var dropdown = event.target.closest('.dropdown');
            if (!dropdown) return;
            var id = dropdown.dataset.dropdownInstanceId || 'unknown';
            setZoomBannerTransientHidden('filters-dropdown-' + id, false);
        });
    }

    // Fix race condition: flexbox layout may not be fully computed when Leaflet initializes
    // on first page visit (cold cache). Double rAF ensures we wait for layout + paint phases.
    requestAnimationFrame(function () {
        requestAnimationFrame(function () {
            if (map) {
                map.invalidateSize();
            }
        });
    });

    // loadDataForViewport(); // updateActiveFilters will call this after initial filter setup
    // logFilterPanelLayout("Document Ready"); // Function removed in refactor

    // Initialize filter event handlers (moved to filters.js)
    initFilterEventHandlers();

    // Initialize operator dropdown
    window.operatorDropdown = new OperatorDropdown('#atlasOperatorFilter', {
        placeholder: 'Select operators...',
        multiple: true,
        onSelectionChange: function (selectedOperators) {
            activeFilters.atlasOperators = selectedOperators;
            updateActiveFilters();
            updateHeaderSummary();
        }
    });

    // Initialize OSM operator dropdown
    window.osmOperatorDropdown = new OperatorDropdown('#osmOperatorFilter', {
        apiUrl: '/api/osm_operators',
        placeholder: 'Select OSM stop operators...',
        multiple: true,
        onSelectionChange: function (selectedOperators) {
            activeFilters.osmOperators = selectedOperators;
            updateActiveFilters();
            updateHeaderSummary();
        }
    });

    // Initialize OSM operator Wikidata dropdown
    window.osmOperatorWikidataDropdown = new OperatorDropdown('#osmOperatorWikidataFilter', {
        apiUrl: '/api/osm_operator_wikidata',
        placeholder: 'Select Wikidata values...',
        multiple: true,
        onSelectionChange: function (selectedOperators) {
            activeFilters.osmOperatorWikidata = selectedOperators;
            if (selectedOperators.length) document.getElementById('filterMissingOsmOperatorWikidata').checked = false;
            updateActiveFilters();
            updateHeaderSummary();
        }
    });

    restoreOperatorFiltersFromUrl();
    restoreFiltersFromUrl();

    // Initial setup calls
    updateActiveFilters(); // This will call loadDataForViewport and updateFiltersUI
    enableFilterUrlSync(); // from now on the address bar follows the filters
    updateHeaderSummary(); // Initial summary update
    bindCopyMapLink();
    openStopFromUrl();
    openRouteVariantsFromUrl();
});

// Additional safety: invalidate map size when window fully loads (images, fonts, etc.)
// This catches edge cases where flex layout changes after DOMContentLoaded
window.addEventListener('load', function () {
    if (map) {
        map.invalidateSize();
    }
});

// Function to update the header summary
function updateHeaderSummary() {
    const summaryContainer = document.getElementById('headerSummaryInfo');
    const statsContainer = document.getElementById('headerSummaryStats');
    if (!summaryContainer || !statsContainer) return;

    syncHeaderSummaryFilterToggle();

    var params = appendCurrentFilterParams({}, { includeTopN: true, includeShowDuplicates: true });

    Object.keys(params).forEach(key => {
        if (params[key] === null || params[key] === '') {
            delete params[key];
        }
    });

    var mySeq = ++currentGlobalStatsSeq;

    if (currentGlobalStatsRequest) currentGlobalStatsRequest.abort();
    var request = new AbortController();
    currentGlobalStatsRequest = request;

    SharedUtils.fetchJson("/api/global_stats", params, { signal: request.signal }).then(function (data) {
        if (mySeq !== currentGlobalStatsSeq) return;

        if (data.error) {
            statsContainer.innerHTML = `<div><small>Error loading summary.</small></div>`;
            console.error("Error loading global stats:", data.error);
            return;
        }

        let summaryHtml = '';

        const totalOSM = data.total_osm_stops || data.total_osm_nodes || 0;
        const matchedOSM = data.matched_osm_stops || data.matched_osm_nodes || 0;
        const totalATLAS = data.total_atlas_stops || 0;
        const matchedATLAS = data.matched_atlas_stops || 0;
        // const matchedPairs = data.matched_pairs_count || 0;
        // const unmatchedEntities = data.unmatched_entities_count || 0;

        const osmPercentage = totalOSM > 0 ? ((matchedOSM / totalOSM) * 100).toFixed(1) : 0;
        const atlasPercentage = totalATLAS > 0 ? ((matchedATLAS / totalATLAS) * 100).toFixed(1) : 0;

        // Always show both lines if data is available, colorize percentages
        if (totalOSM > 0) {
            summaryHtml += `<div class="header-summary__stat"><img class="header-summary__stat-icon" src="/static/osm.svg" alt="OSM icon">${SharedUtils.formatCount(totalOSM)} OSM stops, <span class="header-summary__rate header-summary__rate--success">${osmPercentage}% matched</span></div>`;
        }
        if (totalATLAS > 0) {
            summaryHtml += `<div class="header-summary__stat">${SharedUtils.formatCount(totalATLAS)} ${SharedUtils.sourceLabelHtml()} stops, <span class="header-summary__rate header-summary__rate--primary">${atlasPercentage}% matched</span></div>`;
        }

        if (!summaryHtml) { // Fallback if both counts are zero for some reason based on filters
            summaryHtml = '<div><small>No data matching current filters.</small></div>';
        }

        statsContainer.innerHTML = summaryHtml;
        syncHeaderSummaryFilterToggle();
    }, function (error) {
        if (mySeq !== currentGlobalStatsSeq || SharedUtils.isAbortError(error)) return;

        statsContainer.innerHTML = `<div><small>Failed to load summary.</small></div>`;
        console.error("Failed to fetch global stats from server.");
        syncHeaderSummaryFilterToggle();
    }).finally(function () {
        if (currentGlobalStatsRequest === request) currentGlobalStatsRequest = null;
    });
}

// Explicit cross-script surface used by filters.js and the Index template.
// Map internals remain private to this page controller.
window.loadDataForViewport = loadDataForViewport;
window.loadTopNMatches = loadTopNMatches;
window.centerMapAndOpenPopup = centerMapAndOpenPopup;
window.focusOnRandomFilteredStop = focusOnRandomFilteredStop;
window.fetchAndCenterSpecificStop = fetchAndCenterSpecificStop;
window.updateHeaderSummary = updateHeaderSummary;
window.IndexMapPage = Object.freeze({
    init: initMap,
    getViewportPolicy: getViewportPolicy,
    normalizeViewportPayload: normalizeViewportPayload,
    isViewportPayloadCapped: isViewportPayloadCapped,
    renderIndexViewport: renderIndexViewport,
    destroy: destroyIndexPage
});
