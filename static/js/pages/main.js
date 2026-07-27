// Index map state. `let` keeps the Leaflet instance out of window.map; the
// small set of page functions used by filters.js is exported explicitly below.
let map;
let indexMapCore = null;
let viewportLoader = null;
let markerRegistry = null;
let popupController = null;
let currentFocusedLayer = null;
let topNPopupMarkers = [];
let topNRequest = null;
let topNRequestSequence = 0;
const popupModeByKey = new Map();
let headerSummaryController = null;
let mobileFiltersController = null;
var markersLayer = L.layerGroup();
var linesLayer = L.layerGroup();
var topNLayer = L.layerGroup(); // For top N distances overlay
var stopsById = {};   // Global store for stops by id.

// Performance tuning constants (from AppConstants)
var ZOOM_LINE_THRESHOLD = AppConstants.MAP.ZOOM_LINE_THRESHOLD;
var VIEW_DEBOUNCE_MS = AppConstants.DATA_LOADING.VIEW_DEBOUNCE_MS;
var MAIN_PAGE_COLORS = AppConstants.COLORS || {};
var MAIN_COLOR_ATLAS_MATCHED = MAIN_PAGE_COLORS.ATLAS_MATCHED || '#174092';
var MAIN_COLOR_OSM_MATCHED = MAIN_PAGE_COLORS.OSM_MATCHED || '#4CAF50';
var MAIN_COLOR_ATLAS_UNMATCHED = MAIN_PAGE_COLORS.ATLAS_UNMATCHED || '#DC3545';
var MAIN_COLOR_OSM_UNMATCHED = MAIN_PAGE_COLORS.OSM_UNMATCHED || '#6C757D';
var MAIN_COLOR_LINE_ATLAS_OSM = MAIN_PAGE_COLORS.LINE_ATLAS_OSM || MAIN_COLOR_ATLAS_MATCHED;
var MAIN_COLOR_TEMP_MARKER = MAIN_PAGE_COLORS.TEMP_MARKER || MAIN_COLOR_ATLAS_MATCHED;

// Request management unrelated to viewport loading.
var currentGlobalStatsRequest = null; // jqXHR of in-flight /api/global_stats
var currentGlobalStatsSeq = 0;  // sequence id to ignore stale global stats responses
var zoomBannerTimeout = null;   // debounce timer for the zoom warning banner
var zoomBannerTransientHiddenReasons = Object.create(null); // temporary hide reasons (e.g. hover/tooltips)
var headerSummaryFiltersExpanded = false;
var headerSummaryCollapsed = false;
var mobileFiltersOpen = false;

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
    // Zoom is intentionally represented by the request policy (`mode` and
    // `limit`), not by its exact number. This lets an uncapped buffered result
    // survive a zoom-in while marker render signatures still update.
    var ignored = { min_lat: 1, max_lat: 1, min_lon: 1, max_lon: 1, offset: 1, zoom: 1, include_meta: 1 };
    var keys = Object.keys(params || {}).filter(function (k) { return !ignored[k]; }).sort();
    var parts = ['mode=' + String(mode || '')];
    keys.forEach(function (k) {
        parts.push(k + '=' + String(params[k]));
    });
    return parts.join('&');
}

function fetchJson(url, params, signal) {
    var query = new URLSearchParams();
    Object.keys(params || {}).sort().forEach(function (key) {
        var value = params[key];
        if (value !== null && value !== undefined && value !== '') {
            query.set(key, String(value));
        }
    });
    var requestUrl = query.toString() ? url + '?' + query.toString() : url;
    return fetch(requestUrl, { signal: signal, headers: { Accept: 'application/json' } }).then(function (response) {
        if (!response.ok) {
            var error = new Error('Request failed with HTTP ' + response.status);
            error.status = response.status;
            throw error;
        }
        return response.json();
    });
}

function getAtlasMarkerIdentity(stopData) {
    if (window.MapShared && typeof window.MapShared.getAtlasMarkerIdentity === 'function') {
        return window.MapShared.getAtlasMarkerIdentity(stopData);
    }
    if (!stopData) return null;
    if (stopData.id != null && stopData.id !== '') return String(stopData.id);
    return null;
}

function isStandaloneOsmStopType(stopType) {
    return stopType === 'osm_unmatched' || stopType === 'effectively_matched';
}

function getStandaloneOsmMarkerColor(stopData) {
    return stopData && stopData.stop_type === 'effectively_matched'
        ? MAIN_COLOR_OSM_MATCHED
        : MAIN_COLOR_OSM_UNMATCHED;
}

// Note: popup HTML generation functions are provided by popup-renderer.js
// Note: createAtlasMarker and createOsmMarker functions are now provided by map-renderer.js

// Create the Index map from one explicit configuration. MapCore owns map,
// controls, base layers, renderer padding, popup-line handlers, and cleanup.
function initMap() {
    indexMapCore = window.MapComponents.MapCore.create({
        container: 'map',
        view: {
            center: AppConstants.MAP.DEFAULT_CENTER,
            zoom: AppConstants.MAP.DEFAULT_ZOOM
        },
        mapOptions: {
            closePopupOnClick: false,
            preferCanvas: false,
            minZoom: AppConstants.MAP.MIN_ZOOM,
            maxZoom: AppConstants.MAP.MAX_ZOOM,
            maxBounds: AppConstants.MAP.MAX_BOUNDS,
            maxBoundsViscosity: AppConstants.MAP.MAX_BOUNDS_VISCOSITY,
            zoomControl: false
        },
        rendererPadding: function (zoom) {
            return zoom >= 16 ? 0.5 : 0.1;
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
    popupController = createIndexPopupController();
    markerRegistry = createIndexMarkerRegistry();
    viewportLoader = createIndexViewportLoader();
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

function isMobileViewport() {
    if (window.MobileFilters && typeof window.MobileFilters.isMobileViewport === 'function') {
        return window.MobileFilters.isMobileViewport();
    }
    return window.matchMedia('(max-width: 768px)').matches;
}

function setMobileFiltersOpen(open) {
    var nextOpen = !!open;
    mobileFiltersOpen = nextOpen;

    if (mobileFiltersController) {
        mobileFiltersController.setOpen(nextOpen, 'page-state');
    } else if (window.MobileFilters && typeof window.MobileFilters.setMobileFiltersOpen === 'function') {
        window.MobileFilters.setMobileFiltersOpen({
            overlaySelector: '.top-filters-overlay',
            toggleId: 'mobileFiltersToggle',
            isOpen: nextOpen
        });
    }

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
    if (headerSummaryController) {
        headerSummaryController.setCollapsed(headerSummaryCollapsed, 'page-state');
    } else if (window.HeaderSummary && typeof window.HeaderSummary.setCollapsed === 'function') {
        window.HeaderSummary.setCollapsed(headerSummaryCollapsed);
    }
}

function applyMobileLayoutState() {
    if (isMobileViewport()) {
        setMobileFiltersOpen(false);
        setHeaderSummaryCollapsed(true);
        return;
    }

    setMobileFiltersOpen(false);
    setHeaderSummaryCollapsed(false);
}

function getSharedActiveFilterCount() {
    if (typeof window.getActiveFilterCount === 'function') {
        return window.getActiveFilterCount();
    }
    return 0;
}

function getSharedActiveFilterCountText() {
    if (window.HeaderSummary && typeof window.HeaderSummary.getCountText === 'function') {
        return window.HeaderSummary.getCountText(getSharedActiveFilterCount());
    }
    var count = getSharedActiveFilterCount();
    return count + ' filter' + (count !== 1 ? 's' : '') + ' active';
}

function syncHeaderSummaryFilterToggle() {
    if (headerSummaryController) {
        headerSummaryController.syncFilters({
            activeFilterCount: getSharedActiveFilterCount(),
            expanded: headerSummaryFiltersExpanded
        });
        return;
    }
    if (!window.HeaderSummary || typeof window.HeaderSummary.syncFilters !== 'function') return;
    window.HeaderSummary.syncFilters({
        activeFilterCount: getSharedActiveFilterCount(),
        expanded: headerSummaryFiltersExpanded
    });
}

function initializeSharedUiBindings() {
    headerSummaryController = window.HeaderSummary.bind({
        collapsed: headerSummaryCollapsed,
        filtersExpanded: headerSummaryFiltersExpanded,
        getActiveFilterCount: getSharedActiveFilterCount,
        isMobileViewport: isMobileViewport,
        onCollapsedChange: function (collapsed) {
            headerSummaryCollapsed = collapsed;
            if (!collapsed && isMobileViewport() && mobileFiltersController) {
                mobileFiltersController.setOpen(false, 'summary-opened');
            }
        },
        onFiltersExpandedChange: function (expanded) {
            headerSummaryFiltersExpanded = expanded;
        },
        onClearAll: function () {
            if (typeof window.clearAllFilters === 'function') window.clearAllFilters();
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
            if (open && isMobileViewport() && headerSummaryController) {
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
    if (topNRequest && topNRequest.readyState !== 4) {
        try { topNRequest.abort(); } catch (error) { }
    }
    topNRequest = null;
    topNPopupMarkers.forEach(function (marker) {
        if (popupController) popupController.detach(marker);
    });
    topNPopupMarkers = [];
    topNLayer.clearLayers();
}

function loadTopNMatches() {
    clearTopNMarkers();
    $('#topNDistancesMessage').empty();

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
        if (activeFilters.showDuplicatesOnly) {
            params.show_duplicates_only = 'true';
        }

        appendOsmGroupParams(params);

        var requestSequence = ++topNRequestSequence;
        topNRequest = $.getJSON("/api/top_matches", params, function (data) {
            if (requestSequence !== topNRequestSequence || !activeFilters.topN) return;
            let filteredData = data;

            if (filteredData.length === 0) {
                $('#topNDistancesMessage').html("<div class='alert alert-warning mt-2'>No matched nodes satisfy these conditions.</div>");
            } else {
                var mapSideVisibility = getEffectiveMapSideVisibility();
                var showAtlasNodes = mapSideVisibility.showAtlas;
                var showOSMNodes = mapSideVisibility.showOsm;

                // Collect marker data for cluster handling
                var topNMarkerData = [];
                var createdAtlasMarkers = new Set();
                var createdOsmMarkers = new Set();

                filteredData.forEach(function (stop) {
                    if (stop.stop_type === 'matched' && stop.atlas_lat && stop.atlas_lon && stop.osm_lat && stop.osm_lon) {
                        var atlasMarkerKey = getAtlasMarkerIdentity(stop);

                        if (showAtlasNodes && (!atlasMarkerKey || !createdAtlasMarkers.has(atlasMarkerKey))) {
                            var atlasMarkerData = {
                                lat: parseFloat(stop.atlas_lat),
                                lon: parseFloat(stop.atlas_lon),
                                type: 'atlas',
                                color: MAIN_COLOR_ATLAS_MATCHED,
                                hasAtlasDuplicate: stop.has_atlas_duplicate,
                                originalLat: parseFloat(stop.atlas_lat),
                                originalLon: parseFloat(stop.atlas_lon),
                                stopData: stop
                            };
                            atlasMarkerData.key = getMarkerEntityKey('atlas', stop);
                            topNMarkerData.push(atlasMarkerData);
                            if (atlasMarkerKey) {
                                createdAtlasMarkers.add(atlasMarkerKey);
                            }
                        }
                        if (showOSMNodes) {
                            var osmMarkerKey = getMarkerEntityKey('osm', stop);
                            if (osmMarkerKey && !createdOsmMarkers.has(osmMarkerKey)) {
                                var osmMarkerData = {
                                    lat: parseFloat(stop.osm_lat),
                                    lon: parseFloat(stop.osm_lon),
                                    type: 'osm',
                                    color: MAIN_COLOR_OSM_MATCHED,
                                    osmNodeType: stop.osm_node_type,
                                    originalLat: parseFloat(stop.osm_lat),
                                    originalLon: parseFloat(stop.osm_lon),
                                    stopData: stop
                                };
                                osmMarkerData.key = osmMarkerKey;
                                topNMarkerData.push(osmMarkerData);
                                createdOsmMarkers.add(osmMarkerKey);
                            }
                        }

                        // Add connecting line when both node types are visible (Top N view is lightweight)
                        if (showAtlasNodes && showOSMNodes) {
                            var line = L.polyline([
                                [parseFloat(stop.atlas_lat), parseFloat(stop.atlas_lon)],
                                [parseFloat(stop.osm_lat), parseFloat(stop.osm_lon)]
                            ], { color: MAIN_COLOR_LINE_ATLAS_OSM });
                            topNLayer.addLayer(line);
                        }
                    }
                });

                // Create markers with overlap handling
                topNPopupMarkers = window.MapRenderer.createMarkersWithOverlapHandling(topNMarkerData, topNLayer, {
                    map: map,
                    zoom: map.getZoom(),
                    bindPopup: function (marker, markerData) {
                        if (!markerData.key) return;
                        attachIndexPopup(marker, {
                            key: markerData.key,
                            markerData: markerData,
                            zoom: map.getZoom()
                        });
                    }
                });
            }
        }).fail(function (_jqXHR, textStatus) {
            if (requestSequence !== topNRequestSequence || textStatus === 'abort') return;
            $('#topNDistancesMessage').html("<div class='alert alert-warning mt-2'>Could not load Top N matches.</div>");
        }).always(function () {
            if (requestSequence === topNRequestSequence) topNRequest = null;
        });
    }
}

function getViewportPolicy(zoom) {
    var zoomPolicy = window.MapShared.getViewportZoomPolicy(zoom);
    var isLowZoom = zoomPolicy.isOverview;
    var hasAnyActiveFilter = getSharedActiveFilterCount() > 0;
    var fullUncappedZoom = zoomPolicy.isFullDetail;
    var params = {
        offset: 0,
        zoom: zoom,
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
            ? '📍 Overview mode: showing unmatched ATLAS stops only. Zoom in for all markers.'
            : '📍 Zoom in a bit more to see all markers in this area');
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
        var currentFilterCount = getSharedActiveFilterCount();
        var filterText = currentFilterCount > 0
            ? ' (' + getSharedActiveFilterCountText() + ')'
            : '';
        var prefix = policy.isLowZoom ? '🔍 Low zoom: showing ' : '🔍 Showing ';

        if (capped) {
            setZoomBannerText(
                '🔍 Showing first ' + resultCount + ' filtered result' +
                (resultCount !== 1 ? 's' : '') + filterText +
                '. Zoom in to see all.'
            );
        } else {
            setZoomBannerText(
                prefix + resultCount + ' filtered result' +
                (resultCount !== 1 ? 's' : '') + filterText
            );
        }
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

function getMarkerEntityKey(type, stopData) {
    if (window.MapShared && typeof window.MapShared.createEntityKey === 'function') {
        return window.MapShared.createEntityKey(type, stopData);
    }
    var identity = type === 'atlas'
        ? getAtlasMarkerIdentity(stopData)
        : (stopData && (stopData.osm_node_id || stopData.id));
    return identity == null ? null : type + ':' + String(identity);
}

function addUniqueMarker(markerData, markerList, markerKeys) {
    var key = getMarkerEntityKey(markerData.type, markerData.stopData);
    if (!key || markerKeys.has(key)) return false;
    markerData.key = key;
    markerList.push(markerData);
    markerKeys.add(key);
    return true;
}

function buildOsmMultiMatchData(stops, showOsm, zoom) {
    if (!showOsm || zoom < ZOOM_LINE_THRESHOLD) return {};

    var counts = Object.create(null);
    stops.forEach(function (stop) {
        if (stop.stop_type !== 'matched' || !Array.isArray(stop.osm_matches)) return;
        stop.osm_matches.forEach(function (osmMatch) {
            if (!osmMatch || osmMatch.osm_node_id == null) return;
            var nodeId = String(osmMatch.osm_node_id);
            counts[nodeId] = (counts[nodeId] || 0) + 1;
        });
    });

    var multiNodeIds = new Set(
        Object.keys(counts).filter(function (nodeId) { return counts[nodeId] > 1; })
    );
    var result = Object.create(null);
    if (multiNodeIds.size === 0) return result;

    stops.forEach(function (stop) {
        if (stop.stop_type !== 'matched' || !stop.sloid || !Array.isArray(stop.osm_matches)) return;
        stop.osm_matches.forEach(function (osmMatch) {
            if (!osmMatch || osmMatch.osm_node_id == null) return;
            var nodeId = String(osmMatch.osm_node_id);
            if (!multiNodeIds.has(nodeId)) return;

            if (!result[nodeId]) {
                result[nodeId] = {
                    osmData: {
                        osm_id: osmMatch.osm_id,
                        osm_node_id: osmMatch.osm_node_id,
                        osm_name: osmMatch.osm_name,
                        osm_uic_name: osmMatch.osm_uic_name,
                        osm_uic_ref: osmMatch.osm_uic_ref,
                        osm_local_ref: osmMatch.osm_local_ref,
                        osm_network: osmMatch.osm_network,
                        osm_operator: osmMatch.osm_operator,
                        osm_public_transport: osmMatch.osm_public_transport,
                        osm_amenity: osmMatch.osm_amenity,
                        osm_aerialway: osmMatch.osm_aerialway,
                        osm_railway: osmMatch.osm_railway,
                        osm_lat: osmMatch.osm_lat,
                        osm_lon: osmMatch.osm_lon,
                        osm_node_type: osmMatch.osm_node_type,
                        routes_osm: osmMatch.routes_osm,
                        uic_ref: stop.uic_ref
                    },
                    atlasMatches: []
                };
            }

            result[nodeId].atlasMatches.push({
                id: stop.id,
                sloid: stop.sloid,
                uic_ref: stop.uic_ref,
                atlas_designation: stop.atlas_designation,
                atlas_designation_official: stop.atlas_designation_official,
                atlas_business_org_abbr: stop.atlas_business_org_abbr,
                atlas_lat: stop.atlas_lat,
                atlas_lon: stop.atlas_lon,
                distance_m: osmMatch.distance_m,
                match_type: osmMatch.match_type || stop.match_type,
                routes_atlas: stop.routes_atlas
            });
        });
    });

    return result;
}

function buildIndexMarkerData(stops, visibility, zoom) {
    var markerData = [];
    var markerKeys = new Set();
    var multiMatches = buildOsmMultiMatchData(stops, visibility.showOsm, zoom);
    var multiNodeIds = new Set(Object.keys(multiMatches));

    function addAtlas(stop, lat, lon, color) {
        if (!visibility.showAtlas || lat == null || lon == null) return;
        var parsedLat = Number(lat);
        var parsedLon = Number(lon);
        if (!Number.isFinite(parsedLat) || !Number.isFinite(parsedLon)) return;
        addUniqueMarker({
            lat: parsedLat,
            lon: parsedLon,
            type: 'atlas',
            color: color,
            hasAtlasDuplicate: stop.has_atlas_duplicate,
            originalLat: parsedLat,
            originalLon: parsedLon,
            stopData: stop
        }, markerData, markerKeys);
    }

    function addOsm(stopData, lat, lon, color, osmNodeType, extra) {
        if (!visibility.showOsm || lat == null || lon == null) return;
        var parsedLat = Number(lat);
        var parsedLon = Number(lon);
        if (!Number.isFinite(parsedLat) || !Number.isFinite(parsedLon)) return;
        var item = {
            lat: parsedLat,
            lon: parsedLon,
            type: 'osm',
            color: color,
            osmNodeType: osmNodeType,
            originalLat: parsedLat,
            originalLon: parsedLon,
            stopData: stopData
        };
        Object.keys(extra || {}).forEach(function (key) { item[key] = extra[key]; });
        addUniqueMarker(item, markerData, markerKeys);
    }

    stops.forEach(function (stop) {
        if (stop.stop_type === 'matched') {
            if (stop.sloid && Array.isArray(stop.osm_matches)) {
                addAtlas(stop, stop.atlas_lat, stop.atlas_lon, MAIN_COLOR_ATLAS_MATCHED);
                stop.osm_matches.forEach(function (osmMatch) {
                    if (!osmMatch || osmMatch.osm_node_id == null) return;
                    var nodeId = String(osmMatch.osm_node_id);
                    if (multiNodeIds.has(nodeId)) return;
                    addOsm({
                        id: osmMatch.osm_id || stop.id,
                        stop_type: 'matched',
                        match_type: stop.match_type,
                        osm_node_id: osmMatch.osm_node_id
                    }, osmMatch.osm_lat, osmMatch.osm_lon, MAIN_COLOR_OSM_MATCHED, osmMatch.osm_node_type);
                });
                return;
            }

            if (stop.sloid && stop.osm_node_id != null) {
                addAtlas(stop, stop.atlas_lat, stop.atlas_lon, MAIN_COLOR_ATLAS_MATCHED);
                addOsm(
                    stop,
                    stop.osm_lat,
                    stop.osm_lon,
                    MAIN_COLOR_OSM_MATCHED,
                    stop.osm_node_type
                );
            }
            return;
        }

        if (stop.stop_type === 'atlas_unmatched') {
            addAtlas(stop, stop.lat, stop.lon, MAIN_COLOR_ATLAS_UNMATCHED);
            return;
        }

        if (isStandaloneOsmStopType(stop.stop_type)) {
            addOsm(
                stop,
                stop.osm_lat,
                stop.osm_lon,
                getStandaloneOsmMarkerColor(stop),
                stop.osm_node_type
            );
        }
    });

    Object.keys(multiMatches).sort().forEach(function (nodeId) {
        var multiMatch = multiMatches[nodeId];
        if (!multiMatch || multiMatch.atlasMatches.length <= 1) return;
        var osmData = multiMatch.osmData;
        var popupPayload = {
            id: osmData.osm_id,
            stop_type: 'matched',
            is_osm_node: true,
            osm_node_id: nodeId,
            osm_name: osmData.osm_name,
            osm_uic_name: osmData.osm_uic_name,
            osm_uic_ref: osmData.osm_uic_ref,
            osm_local_ref: osmData.osm_local_ref,
            osm_network: osmData.osm_network,
            osm_operator: osmData.osm_operator,
            osm_public_transport: osmData.osm_public_transport,
            osm_amenity: osmData.osm_amenity,
            osm_aerialway: osmData.osm_aerialway,
            osm_railway: osmData.osm_railway,
            osm_lat: osmData.osm_lat,
            osm_lon: osmData.osm_lon,
            osm_node_type: osmData.osm_node_type,
            uic_ref: osmData.uic_ref,
            routes_osm: osmData.routes_osm,
            atlas_matches: multiMatch.atlasMatches
        };
        addOsm(
            popupPayload,
            osmData.osm_lat,
            osmData.osm_lon,
            MAIN_COLOR_OSM_MATCHED,
            osmData.osm_node_type,
            { popupPayload: popupPayload, isMultiMatch: true }
        );
    });

    return markerData;
}

function buildMarkerDescriptors(markerData, zoom) {
    var clusterManager = new window.MapRenderer.MarkerClusterManager({ map: map, zoom: zoom });
    markerData.forEach(function (item) {
        clusterManager.addMarker(item.lat, item.lon, item);
    });

    return clusterManager.getClusteredData().map(function (clustered) {
        var data = clustered.markerData;
        return {
            key: data.key,
            position: [clustered.lat, clustered.lon],
            renderSignature: window.MapRenderer.getMarkerRenderSignature(
                data.type,
                data.color,
                data,
                zoom
            ),
            markerData: data,
            zoom: zoom
        };
    });
}

function popupContentForMarker(payload, markerData) {
    var enriched = payload && (payload.stop || payload);
    if (enriched && enriched.stop_type === 'atlas_unmatched') {
        return markerData.type === 'atlas'
            ? PopupRenderer.generateSingleAtlasBubbleHtml(enriched, true)
            : PopupRenderer.generateSingleOsmBubbleHtml(enriched, true);
    }
    return PopupRenderer.generatePopupHtml(enriched, markerData.type);
}

function attachIndexPopup(marker, descriptor) {
    var markerData = descriptor.markerData;
    marker.options = marker.options || {};
    marker.options.markerData = markerData;

    if (!markerData || !markerData.stopData) return;
    popupController.attach(marker, {
        key: descriptor.key,
        loadingContent: '<div class="p-2 text-muted">Loading stop details…</div>',
        errorContent: '<div class="p-2 text-danger">Unable to load stop details. Click to retry.</div>',
        load: function (request) {
            var latest = marker.options.markerData;
            if (latest.popupPayload) return latest.popupPayload;
            return fetchJson('/api/stop_popup', {
                stop_id: latest.stopData.id,
                view_type: latest.type
            }, request.signal);
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
            var data = descriptor.markerData;
            var marker = data.type === 'atlas'
                ? window.MapRenderer.createAtlasMarker(
                    descriptor.position[0],
                    descriptor.position[1],
                    data.color,
                    data.hasAtlasDuplicate,
                    descriptor.zoom
                )
                : window.MapRenderer.createOsmMarker(
                    descriptor.position[0],
                    descriptor.position[1],
                    data.color,
                    data.osmNodeType,
                    descriptor.zoom
                );
            attachIndexPopup(marker, descriptor);
            return marker;
        },
        update: function (marker, descriptor) {
            marker.setLatLng(descriptor.position);
            attachIndexPopup(marker, descriptor);
        },
        onRemove: function (marker, descriptor, removal) {
            if (removal && removal.reason === 'replace' && removal.replacementLayer) {
                popupController.transfer(marker, removal.replacementLayer);
            } else {
                popupController.detach(marker);
            }
            if (!removal || removal.reason !== 'replace') {
                popupModeByKey.delete(removal && removal.key ? removal.key : descriptor.key);
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

    var markerData = buildIndexMarkerData(payload.stops, visibility, context.zoom);
    var descriptors = buildMarkerDescriptors(markerData, context.zoom);
    descriptors.forEach(function (descriptor) {
        var nextMode = descriptor.markerData.isMultiMatch ? 'multi-match' : 'single-entity';
        var previousMode = popupModeByKey.get(descriptor.key);
        if (previousMode && previousMode !== nextMode) {
            // The same OSM entity has a richer local payload at multi-match
            // zooms. Clear only that popup cache before updating its binding.
            popupController.remove(descriptor.key);
        }
        popupModeByKey.set(descriptor.key, nextMode);
    });
    markerRegistry.reconcile(descriptors, {
        zoom: context.zoom,
        cacheHit: context.cacheHit,
        reason: context.reason
    });

    LineRenderer.clearLines(linesLayer);
    LineRenderer.drawAll(payload.stops, linesLayer, {
        showAtlas: visibility.showAtlas,
        showOsm: visibility.showOsm,
        minZoom: ZOOM_LINE_THRESHOLD,
        currentZoom: context.zoom,
        isContext: false
    });
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
            return fetchJson('/api/data', params, context.signal);
        },
        onData: renderIndexViewport,
        onError: function (error) {
            console.error('Failed to refresh /api/data:', error);
            setZoomBannerText('⚠️ Could not refresh map data. Showing the last successful view.');
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

// Reusable function to center map and open popup for a stop
function centerMapAndOpenPopup(stopData, centerLat, centerLon, popupViewType, zoomLevel = 17, shouldOpenPopup = true) {
    if (stopData && centerLat !== undefined && centerLon !== undefined) {
        // Pause loader-owned map events while changing the view, then perform
        // one explicit reload for the final viewport.
        var resumeViewport = viewportLoader ? viewportLoader.pause() : function () {};
        map.setView([centerLat, centerLon], zoomLevel, { animate: false });
        resumeViewport();

        // Ensure the stopData is stored in stopsById if it wasn't already
        stopsById[stopData.id] = stopData;

        // Generate the appropriate popup HTML
        const popupHtml = PopupRenderer.generatePopupHtml(stopData, popupViewType);
        const popup = window.MapRenderer.createPopupWithOptions(popupHtml).setLatLng([centerLat, centerLon]);

        // Add a temporary marker
        let tempMarkerColor = MAIN_COLOR_TEMP_MARKER;
        if (stopData.stop_type === 'matched') {
            tempMarkerColor = (popupViewType === 'atlas') ? MAIN_COLOR_ATLAS_MATCHED : MAIN_COLOR_OSM_MATCHED;
        } else if (stopData.stop_type === 'atlas_unmatched') {
            tempMarkerColor = (popupViewType === 'atlas') ? MAIN_COLOR_ATLAS_UNMATCHED : MAIN_COLOR_OSM_UNMATCHED;
        } else if (isStandaloneOsmStopType(stopData.stop_type)) {
            tempMarkerColor = getStandaloneOsmMarkerColor(stopData);
        }


        // Create temporary marker with cluster handling
        const tempMarkerData = [{
            lat: centerLat,
            lon: centerLon,
            type: popupViewType,
            color: tempMarkerColor,
            hasAtlasDuplicate: popupViewType === 'atlas' ? stopData.has_atlas_duplicate : false,
            osmNodeType: popupViewType === 'osm' ? stopData.osm_node_type : null,
            popup: popup,
            originalLat: centerLat,
            originalLon: centerLon,
            stopData: stopData
        }];

        // Clear previous temporary markers if any (optional, depends on desired behavior)
        // For now, let's assume new interaction clears old temporary focus
        if (currentFocusedLayer) {
            map.removeLayer(currentFocusedLayer);
            currentFocusedLayer = null;
        }

        // Create a temporary layer for this marker
        const tempLayer = L.layerGroup().addTo(map);
        const createdMarkers = window.MapRenderer.createMarkersWithOverlapHandling(tempMarkerData, tempLayer, {
            map: map,
            zoom: map.getZoom()
        });

        if (createdMarkers.length > 0) {
            if (shouldOpenPopup) {
                createdMarkers[0].openPopup();
            }
            currentFocusedLayer = tempLayer;
        }

        // Reload markers for the new viewport so other entries in view appear alongside the focused stop
        loadDataForViewport();

    } else {
        alert("Stop data is incomplete or coordinates are missing for centering.");
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

    $.getJSON("/api/random_stop", params, function (data) {
        if (data.error) {
            alert("Error focusing on random stop: " + data.error);
            return;
        }
        centerMapAndOpenPopup(data.stop, data.center_lat, data.center_lon, data.popup_view_type);
    }).fail(function (jqXHR, textStatus, errorThrown) {
        alert("Failed to fetch random stop. Status: " + textStatus + ", Error: " + errorThrown);
        try {
            console.error("Server response for random stop failure:", jqXHR.responseJSON || jqXHR.responseText);
        } catch (e) {
            console.error("Could not parse server error response.");
        }
    });
}

function fetchAndCenterSpecificStop(identifier, identifierType) {
    return new Promise((resolve, reject) => {
        let backendIdentifierType = '';
        let typeName = '';
        if (identifierType === 'atlas') {
            backendIdentifierType = 'sloid';
            typeName = 'ATLAS SLOID';
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

        $.getJSON("/api/stop_by_id", { identifier: identifier, identifier_type: backendIdentifierType }, function (data) {
            if (data.error) {
                reject(`No ${typeName} found matching: ${identifier}`);
                return;
            }
            // Use a slightly less zoomed-in level for specific searches compared to random.
            const openPopup = !(identifierType === 'station' || identifierType === 'route');
            const zoomLevel = identifierType === 'route' ? 14 : 16;
            centerMapAndOpenPopup(data.stop, data.center_lat, data.center_lon, data.popup_view_type, zoomLevel, openPopup);
            resolve();
        }).fail(function () {
            reject(`No ${typeName} found matching: ${identifier}`);
        });
    });
}

function handleIndexResize() {
    applyMobileLayoutState();
}

function destroyIndexPage() {
    window.removeEventListener('resize', handleIndexResize);
    if (currentGlobalStatsRequest && currentGlobalStatsRequest.readyState !== 4) {
        try { currentGlobalStatsRequest.abort(); } catch (error) { }
    }
    if (viewportLoader) viewportLoader.destroy();
    clearTopNMarkers();
    if (markerRegistry) markerRegistry.destroy();
    if (popupController) popupController.destroy();
    popupModeByKey.clear();
    if (headerSummaryController) headerSummaryController.destroy();
    if (mobileFiltersController) mobileFiltersController.destroy();
    if (currentFocusedLayer && map) map.removeLayer(currentFocusedLayer);
    if (indexMapCore) indexMapCore.destroy();
}


$(document).ready(function () {
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
        $(topFiltersOverlay).on('shown.bs.dropdown', '.dropdown', function () {
            var toggle = this.querySelector('.dropdown-toggle');
            var id = toggle ? toggle.id : Math.random().toString();
            this.dataset.dropdownInstanceId = id; // Save it to ensure consistent removal
            setZoomBannerTransientHidden('filters-dropdown-' + id, true);
        });
        $(topFiltersOverlay).on('hidden.bs.dropdown', '.dropdown', function () {
            var id = this.dataset.dropdownInstanceId || 'unknown';
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
            updateFiltersUI();
            if (typeof window.invalidateViewportCache === 'function') window.invalidateViewportCache();
            loadDataForViewport();
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
            updateFiltersUI();
            if (typeof window.invalidateViewportCache === 'function') window.invalidateViewportCache();
            loadDataForViewport();
            updateHeaderSummary();
        }
    });

    // Report functionality is only needed on /reports.
    // Index uses the navbar for navigation.
    if (window.initReportGeneration) {
        window.initReportGeneration();
    }



    // Log layout when accordion sections are shown or hidden
    $('#filterAccordion .collapse, .nested-accordion-content.collapse').on('shown.bs.collapse hidden.bs.collapse', function (e) {
        updateAccordionIcons();
        // logFilterPanelLayout(`Accordion Toggled: #${e.target.id}`); // Function removed in refactor
    });

    // Initial setup calls
    updateAccordionIcons();
    updateActiveFilters(); // This will call loadDataForViewport and updateFiltersUI
    updateHeaderSummary(); // Initial summary update

    // Remove the old, duplicated event listener for new search type dropdown options
    // The initSearchTypeModal handles the new modal-based selector.
});

// Additional safety: invalidate map size when window fully loads (images, fonts, etc.)
// This catches edge cases where flex layout changes after DOMContentLoaded
$(window).on('load', function () {
    if (map) {
        map.invalidateSize();
    }
});


// Function to update accordion toggle icons
function updateAccordionIcons() {
    $('.nested-accordion-header').each(function () {
        const targetCollapseId = $(this).data('target');
        const icon = $(this).find('.accordion-toggle-icon');
        if ($(targetCollapseId).hasClass('show')) {
            icon.removeClass('fa-chevron-right').addClass('fa-chevron-down'); // Expanded
            $(this).attr('aria-expanded', 'true');
        } else {
            icon.removeClass('fa-chevron-down').addClass('fa-chevron-right'); // Collapsed
            $(this).attr('aria-expanded', 'false');
        }
    });
}

// Function to update the header summary
function updateHeaderSummary() {
    const summaryContainer = $('#headerSummaryInfo');
    const statsContainer = $('#headerSummaryStats');
    if (!summaryContainer.length || !statsContainer.length) return;

    syncHeaderSummaryFilterToggle();

    var params = appendCurrentFilterParams({}, { includeTopN: true, includeShowDuplicates: true });

    Object.keys(params).forEach(key => {
        if (params[key] === null || params[key] === '') {
            delete params[key];
        }
    });

    var mySeq = ++currentGlobalStatsSeq;

    if (currentGlobalStatsRequest && currentGlobalStatsRequest.readyState !== 4) {
        try { currentGlobalStatsRequest.abort(); } catch (e) { }
    }

    currentGlobalStatsRequest = $.getJSON("/api/global_stats", params, function (data) {
        if (mySeq !== currentGlobalStatsSeq) return;

        if (data.error) {
            statsContainer.html(`<div><small>Error loading summary.</small></div>`);
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
            summaryHtml += `<div class="header-summary__stat"><img class="header-summary__stat-icon" src="/static/osm.svg" alt="OSM icon">${totalOSM} OSM stops, <span style="color: ${MAIN_COLOR_OSM_MATCHED}; font-weight: bold;">${osmPercentage}% matched</span></div>`;
        }
        if (totalATLAS > 0) {
            summaryHtml += `<div class="header-summary__stat"><img class="header-summary__stat-icon" src="/static/atlas.svg" alt="ATLAS icon">${totalATLAS} ATLAS stops, <span style="color: ${MAIN_COLOR_ATLAS_MATCHED}; font-weight: bold;">${atlasPercentage}% matched</span></div>`;
        }

        if (!summaryHtml) { // Fallback if both counts are zero for some reason based on filters
            summaryHtml = '<div><small>No data matching current filters.</small></div>';
        }

        statsContainer.html(summaryHtml);
        syncHeaderSummaryFilterToggle();
    }).fail(function () {
        if (mySeq !== currentGlobalStatsSeq) return;

        statsContainer.html(`<div><small>Failed to load summary.</small></div>`);
        console.error("Failed to fetch global stats from server.");
        syncHeaderSummaryFilterToggle();
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
    buildIndexMarkerData: buildIndexMarkerData,
    buildMarkerDescriptors: buildMarkerDescriptors,
    renderIndexViewport: renderIndexViewport,
    destroy: destroyIndexPage
});
