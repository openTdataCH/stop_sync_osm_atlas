// Global variables
var map;
var osmLayer;
var markersLayer = L.layerGroup();
var linesLayer = L.layerGroup();
var topNLayer = L.layerGroup(); // For top N distances overlay
var stopsById = {};   // Global store for stops by id.
var renderedMarkers = new Map(); // Track currently rendered markers by unique key (type-id)
// manual matching variables are now defined in manual-matching.js

// Performance tuning constants (from AppConstants)
var ZOOM_MARKER_THRESHOLD = AppConstants.MAP.ZOOM_MARKER_THRESHOLD;
var ZOOM_LINE_THRESHOLD = AppConstants.MAP.ZOOM_LINE_THRESHOLD;
var VIEW_DEBOUNCE_MS = AppConstants.DATA_LOADING.VIEW_DEBOUNCE_MS;
var LOW_ZOOM_SMALLSET_LIMIT = AppConstants.DATA_LOADING.LOW_ZOOM_SMALLSET_LIMIT;
var ADDITIONAL_BANNER_ZOOM_LEVELS = AppConstants.MAP.ADDITIONAL_BANNER_ZOOM_LEVELS;

// Request management
var currentDataRequest = null;  // jqXHR of in-flight /api/data
var currentDataRequestSeq = 0;  // sequence id to ignore stale responses
var loadViewportTimer = null;   // debounce timer id
var zoomBannerTimeout = null;   // debounce timer for the zoom warning banner
var suppressViewportReloadCount = 0; // skip this many reloads after programmatic center

// Viewport cache: avoid refetching while panning within a buffered extent.
// This reduces API calls and prevents marker reshuffling caused by capped results.
var viewportDataCache = {
    bounds: null,     // L.LatLngBounds of the cached (buffered) query extent
    key: null,        // stable key representing non-bbox request params + mode
    zoom: null,       // zoom level used for the cached request
    data: null,       // cached response data for smooth transitions
    capped: false,    // whether the cached data was limited/capped
    renderedStopIds: new Set(), // track which stops are currently rendered
    lastRenderZoom: null // track the zoom level of the last render to detect threshold crossings
};

/**
 * Invalidate the viewport cache, forcing the next load to fetch fresh data.
 * Call this when filters change or when you need to force a refresh.
 */
function invalidateViewportCache() {
    viewportDataCache.bounds = null;
    viewportDataCache.key = null;
    viewportDataCache.zoom = null;
    viewportDataCache.data = null;
    viewportDataCache.capped = false;
    viewportDataCache.renderedStopIds = new Set();
    viewportDataCache.lastRenderZoom = null;
}

// Expose globally for filter changes
window.invalidateViewportCache = invalidateViewportCache;

function _expandBounds(bounds, ratio) {
    try {
        var sw = bounds.getSouthWest();
        var ne = bounds.getNorthEast();
        var latSpan = ne.lat - sw.lat;
        var lonSpan = ne.lng - sw.lng;
        return L.latLngBounds(
            [sw.lat - latSpan * ratio, sw.lng - lonSpan * ratio],
            [ne.lat + latSpan * ratio, ne.lng + lonSpan * ratio]
        );
    } catch (e) {
        return bounds;
    }
}

function _stableParamsKey(params, mode) {
    // Build a stable string key from params excluding bbox-only fields.
    // Note: 'limit' IS included since changing it should invalidate cache.
    var ignored = { min_lat: 1, max_lat: 1, min_lon: 1, max_lon: 1, offset: 1 };
    var keys = Object.keys(params || {}).filter(function(k) { return !ignored[k]; }).sort();
    var parts = ['mode=' + String(mode || '')];
    keys.forEach(function(k) {
        parts.push(k + '=' + String(params[k]));
    });
    return parts.join('&');
}

// Note: popup HTML generation functions are provided by popup-renderer.js
// Note: createAtlasMarker and createOsmMarker functions are now provided by map-renderer.js

// Function to initialize the map with event listeners that preserve popups during movement
function initMap() {
    map = L.map('map', {
        closePopupOnClick: false, // Prevent map click from closing popups
        // Use SVG renderer so popup connection lines can be drawn in the map's SVG layer
        preferCanvas: false,
        // Switzerland-focused: prevent zooming too far out and panning far away
        minZoom: AppConstants.MAP.MIN_ZOOM,
        maxZoom: AppConstants.MAP.MAX_ZOOM,
        maxBounds: AppConstants.MAP.MAX_BOUNDS,
        maxBoundsViscosity: AppConstants.MAP.MAX_BOUNDS_VISCOSITY,
        zoomControl: false
    }).setView(AppConstants.MAP.DEFAULT_CENTER, AppConstants.MAP.DEFAULT_ZOOM);
    
    osmLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
         maxZoom: AppConstants.MAP.MAX_ZOOM,
         maxNativeZoom: AppConstants.MAP.MAX_NATIVE_ZOOM,
         attribution: '© OpenStreetMap'
    });

    var transportLayer = L.tileLayer('https://tile.memomaps.de/tilegen/{z}/{x}/{y}.png', {
        maxZoom: AppConstants.MAP.MAX_ZOOM,
        maxNativeZoom: 18,
        attribution: 'Map <a href="https://memomaps.de/">memomaps.de</a> <a href="http://creativecommons.org/licenses/by-sa/2.0/">CC-BY-SA</a>, map data &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    });

    var satelliteLayer = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
        maxZoom: AppConstants.MAP.MAX_ZOOM,
        maxNativeZoom: 19,
        attribution: 'Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EBP, and the GIS User Community'
    });
    
    osmLayer.addTo(map);

    var baseMaps = {
        "OpenStreetMap": osmLayer,
        "Transport Map": transportLayer,
        "Satellite": satelliteLayer
    };

    var overlayMaps = {
        "Markers": markersLayer,
        "Connection Lines": linesLayer
    };

    // Put layer + zoom controls on the right (they will be offset under the stats overlay)
    L.control.zoom({ position: 'topright' }).addTo(map);
    L.control.layers(baseMaps, overlayMaps, { position: 'topright' }).addTo(map);

    // Random stop control (below the layers control)
    try {
        var RandomStopControl = L.Control.extend({
            options: { position: 'topright' },
            onAdd: function() {
                var container = L.DomUtil.create('div', 'leaflet-bar leaflet-control');
                var link = L.DomUtil.create('a', '', container);
                link.href = '#';
                link.title = 'View random stop (uses current filters)';
                link.setAttribute('aria-label', 'View random stop');
                link.innerHTML = '<i class="fas fa-random"></i>';

                L.DomEvent.disableClickPropagation(container);
                L.DomEvent.disableScrollPropagation(container);
                L.DomEvent.on(link, 'click', L.DomEvent.stop);
                L.DomEvent.on(link, 'click', function() {
                    if (typeof focusOnRandomFilteredStop === 'function') {
                        focusOnRandomFilteredStop();
                    }
                });
                return container;
            }
        });
        map.addControl(new RandomStopControl());
    } catch (e) {
        // If Leaflet isn't ready for some reason, fail silently.
        console.error('Failed to add RandomStopControl:', e);
    }

    markersLayer.addTo(map);
    linesLayer.addTo(map);
    topNLayer.addTo(map);

    // Place right-side Leaflet controls under the stats overlay (#headerSummary)
    positionIndexMapRightControls();
    window.addEventListener('resize', positionIndexMapRightControls);
    
    // Attach standard popup-line handlers
    var openPopups = attachPopupLineHandlersToMap(map);
    
    // Add low-zoom banner container
    ensureZoomBannerExists();

    // After pan/zoom ends: reload data (debounced). Skip once if we just centered programmatically.
    map.on('moveend zoomend', function() {
        if (suppressViewportReloadCount > 0) {
            suppressViewportReloadCount--;
            return;
        }
        if (loadViewportTimer) clearTimeout(loadViewportTimer);
        loadViewportTimer = setTimeout(function() {
            loadDataForViewport();
        }, VIEW_DEBOUNCE_MS);
    });
}

function positionIndexMapRightControls() {
    const mapEl = document.getElementById('map');
    if (!mapEl) return;

    const corner = mapEl.querySelector('.leaflet-top.leaflet-right');
    if (!corner) return;

    const header = document.getElementById('headerSummary');
    if (!header) {
        corner.style.marginTop = '';
        return;
    }

    const offset = header.offsetTop + header.offsetHeight + 8;
    corner.style.marginTop = offset > 0 ? offset + 'px' : '';
}












// Create and control a low-zoom banner prompting users to zoom in
function ensureZoomBannerExists() {
    if (document.getElementById('zoomBanner')) return;
    var banner = document.createElement('div');
    banner.id = 'zoomBanner';
    banner.style.position = 'absolute';
    banner.style.top = AppConstants.ZOOM_BANNER.TOP_POSITION;
    banner.style.left = '50%';
    banner.style.transform = 'translateX(-50%)';
    banner.style.zIndex = AppConstants.ZOOM_BANNER.Z_INDEX;
    banner.style.background = AppConstants.ZOOM_BANNER.BACKGROUND;
    banner.style.color = AppConstants.ZOOM_BANNER.COLOR;
    banner.style.padding = AppConstants.ZOOM_BANNER.PADDING;
    banner.style.borderRadius = AppConstants.ZOOM_BANNER.BORDER_RADIUS;
    banner.style.fontSize = AppConstants.ZOOM_BANNER.FONT_SIZE;
    banner.style.display = 'none';
    banner.style.transition = 'opacity 0.2s ease-in-out';
    banner.style.pointerEvents = 'none'; // Don't block map interactions
    banner.textContent = 'Zoom in to see individual stop markers';
    var mapContainer = document.getElementById('map');
    if (mapContainer && mapContainer.parentElement) {
        mapContainer.parentElement.style.position = 'relative';
        mapContainer.parentElement.appendChild(banner);
    } else {
        document.body.appendChild(banner);
    }
}

function showZoomBanner(show, delayMs = 0) {
    var banner = document.getElementById('zoomBanner');
    if (!banner) return;
    
    if (zoomBannerTimeout) {
        clearTimeout(zoomBannerTimeout);
        zoomBannerTimeout = null;
    }

    if (show) {
        // If already visible, just ensure it stays visible
        if (banner.style.display === 'block') return;
        
        if (delayMs > 0) {
            zoomBannerTimeout = setTimeout(function() {
                banner.style.display = 'block';
                zoomBannerTimeout = null;
            }, delayMs);
        } else {
            banner.style.display = 'block';
        }
    } else {
        banner.style.display = 'none';
    }
}

function setZoomBannerText(text) {
    var banner = document.getElementById('zoomBanner');
    if (!banner) return;
    banner.textContent = text;
}

function loadTopNMatches() {
    topNLayer.clearLayers();
    $('#topNDistancesMessage').empty();
    
    if(activeFilters.topN && activeFilters.stopType.includes("matched")) {
        var params = { limit: activeFilters.topN };
        // Send specific, active match methods
        if(activeFilters.matchMethods.length > 0) {
            params.match_method = activeFilters.matchMethods.join(',');
        }
        
        // Add station filter values and type if available
        if(activeFilters.station.length > 0) {
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
    
    $.getJSON("/api/top_matches", params, function(data) {
            let filteredData = data;
            
            // --- Client-side filtering for Show Duplicates Only --- 
            if (activeFilters.showDuplicatesOnly) {
                // Note: This filters *after* the operator mismatch filter if active
                filteredData = filteredData.filter(stop => typeof isDuplicateFlagSet === 'function' ? isDuplicateFlagSet(stop.atlas_duplicate_sloid) : (stop.atlas_duplicate_sloid && stop.atlas_duplicate_sloid !== ''));
            }

            if(filteredData.length === 0) {
                 $('#topNDistancesMessage').html("<div class='alert alert-warning mt-2'>No matched nodes satisfy these conditions.</div>");
            } else {
                // Check if node type filtering is active
                var showAtlasNodes = activeFilters.nodeType.length === 0 || activeFilters.nodeType.indexOf("atlas") !== -1;
                var showOSMNodes = activeFilters.nodeType.length === 0 || activeFilters.nodeType.indexOf("osm") !== -1;
                
                // Collect marker data for cluster handling
                var topNMarkerData = [];
                
                filteredData.forEach(function(stop) {
                    if(stop.stop_type === 'matched' && stop.atlas_lat && stop.atlas_lon && stop.osm_lat && stop.osm_lon) {
                        
                        if(showAtlasNodes) {
                            topNMarkerData.push({
                                lat: parseFloat(stop.atlas_lat),
                                lon: parseFloat(stop.atlas_lon),
                                type: 'atlas',
                                color: 'green',
                                duplicateSloid: stop.atlas_duplicate_sloid,
                                originalLat: parseFloat(stop.atlas_lat),
                                originalLon: parseFloat(stop.atlas_lon),
                                stopData: stop
                            });
                        }
                        if(showOSMNodes) {
                            topNMarkerData.push({
                                lat: parseFloat(stop.osm_lat),
                                lon: parseFloat(stop.osm_lon),
                                type: 'osm',
                                color: 'blue',
                                osmNodeType: stop.osm_node_type,
                                originalLat: parseFloat(stop.osm_lat),
                                originalLon: parseFloat(stop.osm_lon),
                                stopData: stop
                            });
                        }
                        
                        // Add connecting line when both node types are visible (Top N view is lightweight)
                        if(showAtlasNodes && showOSMNodes) {
                            const isManual = stop.match_type === 'manual';
                            const isPersistent = !!stop.manual_is_persistent;
                            const style = isManual ? { color: 'purple', dashArray: isPersistent ? null : '5,5' } : { color: 'green' };
                            var line = L.polyline([
                                [parseFloat(stop.atlas_lat), parseFloat(stop.atlas_lon)],
                                [parseFloat(stop.osm_lat), parseFloat(stop.osm_lon)]
                            ], style);
                            topNLayer.addLayer(line);
                        }
                    }
                });
                
                // Create markers with overlap handling
                createMarkersWithOverlapHandling(topNMarkerData, topNLayer);
            }
        });
    }
}

// Note: createPopupWithOptions function is now provided by map-renderer.js

function loadDataForViewport() {
    // When Top N filter is active, skip loading full viewport data.
    if(activeFilters.topN) {
        markersLayer.clearLayers();
        linesLayer.clearLayers();
        // Top-N mode is explicit and doesn't need the "zoom in" guidance banner.
        showZoomBanner(false);
        return;
    }
    // Zoom gating: do not load or render markers if zoom is too low
    var zoom = map.getZoom();
    var isLowZoom = zoom < ZOOM_MARKER_THRESHOLD;

    // Determine whether the user has any active filters that should take precedence at low zoom.
    // If true, we still cap results for performance, but show entries matching the filters.
    var hasAnyActiveFilter = (
        (activeFilters.station && activeFilters.station.length > 0) ||
        (activeFilters.stopType && activeFilters.stopType.length > 0) ||
        (activeFilters.nodeType && activeFilters.nodeType.length > 0) ||
        (activeFilters.matchMethods && activeFilters.matchMethods.length > 0) ||
        (activeFilters.transportTypes && activeFilters.transportTypes.length > 0) ||
        (activeFilters.atlasOperators && activeFilters.atlasOperators.length > 0) ||
        !!activeFilters.showDuplicatesOnly
    );
    // Banner policy:
    // - Show it at ALL zoom levels where we might not be rendering "all markers" (i.e., while results are capped),
    //   and hide it only once we reach the fully-uncapped zoom level.
    // This fixes the previous behavior where the banner only appeared at a single zoom level.
    var fullUncappedZoom = zoom >= (ZOOM_MARKER_THRESHOLD + ADDITIONAL_BANNER_ZOOM_LEVELS);
    var shouldShowBanner = !fullUncappedZoom;
    
    // Helper to count active filters
    var filterCount = (activeFilters.station?.length || 0) + 
                      (activeFilters.atlasOperators?.length || 0);
    
    // Add 1 for each non-empty array filter that isn't just "all"
    if (activeFilters.stopType?.length > 0) filterCount++;
    if (activeFilters.nodeType?.length > 0) filterCount++;
    if (activeFilters.matchMethods?.length > 0) filterCount++;
    if (activeFilters.transportTypes?.length > 0) filterCount++;
    if (activeFilters.showDuplicatesOnly) filterCount++;

    if (shouldShowBanner) {
        if (isLowZoom) {
            if (hasAnyActiveFilter) {
                // More informative message showing filter context
                var filterText = filterCount > 0 ? ` (${filterCount} filter${filterCount !== 1 ? 's' : ''} active)` : '';
                setZoomBannerText('🔍 Low zoom: showing filtered results' + filterText);
            } else {
                setZoomBannerText('📍 Overview mode: showing unmatched ATLAS stops only. Zoom in for all markers.');
            }
        } else {
            // Mid-zoom: still capped but closer
            // If filters are active, show filter info instead of generic zoom message
            if (hasAnyActiveFilter) {
                 var filterText = filterCount > 0 ? ` (${filterCount} filter${filterCount !== 1 ? 's' : ''} active)` : '';
                 setZoomBannerText('🔍 Showing filtered results' + filterText);
            } else {
                setZoomBannerText('📍 Zoom in a bit more to see all markers in this area');
            }
        }
    }
    showZoomBanner(shouldShowBanner, 150);
    var viewportBounds = map.getBounds();
    var params = {
        min_lat: viewportBounds.getSouth(),
        max_lat: viewportBounds.getNorth(),
        min_lon: viewportBounds.getWest(),
        max_lon: viewportBounds.getEast(),
        offset: 0,
        zoom: zoom,
        include_meta: 1
    };

    // Decide result limiting based on zoom level
    if (!fullUncappedZoom) {
        params.limit = AppConstants.DATA_LOADING.GENERAL_LIMIT;
    }

    if (isLowZoom && !hasAnyActiveFilter) {
        // Low-zoom policy: show only unmatched ATLAS markers (overview)
        params.stop_filter = 'unmatched';
        params.node_type = 'atlas';

        // Keep operator filter if active
        if (activeFilters.atlasOperators.length > 0) {
            params.atlas_operator = activeFilters.atlasOperators.join(',');
        }
    } else {
        // Normal or filtered mode: build standard filters
        
        // Determine if pure OSM nodes should be included in stop_filter when 'unmatched' is active
        var includeOsmInStopFilterForUnmatched = activeFilters.stopType.includes('unmatched') &&
                                            (activeFilters.nodeType.includes('osm') || activeFilters.nodeType.length === 0) &&
                                            !activeFilters.stopType.includes('osm');

        if(activeFilters.stopType.length > 0 || includeOsmInStopFilterForUnmatched) {
            var stopFilterTypes = [...activeFilters.stopType];
            if (includeOsmInStopFilterForUnmatched) {
                if (!stopFilterTypes.includes('osm')) {
                    stopFilterTypes.push('osm');
                }
            }
            if (stopFilterTypes.length > 0) {
                params.stop_filter = stopFilterTypes.join(',');
            }
        }

        if(activeFilters.nodeType.length > 0) {
            params.node_type = activeFilters.nodeType.join(',');
        }
        if(activeFilters.matchMethods.length > 0) {
            params.match_method = activeFilters.matchMethods.join(',');
        }
        if(activeFilters.station.length > 0) {
            params.station_filter = activeFilters.station.join(',');
            params.filter_types = activeFilters.stationTypes.join(',');
            params.route_directions = activeFilters.routeDirections.join(',');
        }
        if (activeFilters.transportTypes.length > 0) {
            params.transport_types = activeFilters.transportTypes.join(',');
        }
        if (activeFilters.atlasOperators.length > 0) {
            params.atlas_operator = activeFilters.atlasOperators.join(',');
        }
    }

    // Viewport cache: if we already fetched a buffered area covering the current view
    // with the same non-bbox params AND zoom level, skip the request and keep markers.
    // This avoids reshuffling caused by capped/limited responses on small pans.
    var mode = isLowZoom ? (hasAnyActiveFilter ? 'lowzoom_filtered' : 'lowzoom_unmatched_atlas') : 'normal';
    var requestKey = _stableParamsKey(params, mode);
    
    // Cache hit conditions:
    // 1. Same request parameters (filters, limits, etc.)
    // 2. Same zoom level OR (Zoom In AND Cached data was uncapped)
    // 3. Current viewport is contained within cached bounds
    var canReuseCache = false;
    if (viewportDataCache.bounds && viewportDataCache.key === requestKey) {
        if (viewportDataCache.zoom === zoom) {
             canReuseCache = true;
        } else if (zoom > viewportDataCache.zoom && !viewportDataCache.capped) {
             canReuseCache = true;
        }
    }

    if (canReuseCache) {
        try {
            // Use a slightly smaller bounds for the check to be safe (avoid edge cases)
            var checkBounds = viewportBounds.pad(-0.05);
            if (viewportDataCache.bounds.contains(checkBounds)) {
                // Cache hit - no need to refetch, markers stay stable

                // Check if we need to update the banner for mid-zoom/no-filter case
                if (shouldShowBanner && !isLowZoom && !hasAnyActiveFilter) {
                     var cachedStops = viewportDataCache.data || [];
                     var limit = params.limit;
                     var capped = (limit && cachedStops.length >= limit);
                     
                     if (!capped) {
                         showZoomBanner(false);
                     } else {
                         showZoomBanner(true);
                     }
                } else if (!shouldShowBanner) {
                    showZoomBanner(false);
                }

                return;
            }
        } catch (e) {
            // Bounds check failed, proceed with fetch
        }
    }

    // Expand requested bbox so small pans stay within the cached extent.
    // Use larger buffer at lower zooms where panning covers more ground.
    var bufferRatio = isLowZoom ? 0.5 : 0.35;
    var bufferedBounds = _expandBounds(viewportBounds, bufferRatio);
    params.min_lat = bufferedBounds.getSouth();
    params.max_lat = bufferedBounds.getNorth();
    params.min_lon = bufferedBounds.getWest();
    params.max_lon = bufferedBounds.getEast();
    
    // Cancel previous data request if still in flight
    if (currentDataRequest && currentDataRequest.readyState !== 4) {
        try { currentDataRequest.abort(); } catch(e) {}
    }
    var mySeq = ++currentDataRequestSeq;
    currentDataRequest = $.getJSON("/api/data", params, function(rawData) {
         // Ignore stale responses
         if (mySeq !== currentDataRequestSeq) return;

         // Update cache with new data
         viewportDataCache.bounds = bufferedBounds;
         viewportDataCache.key = requestKey;
         viewportDataCache.zoom = zoom;
         
         var meta = null;
         var rawStops = rawData;
         if (rawData && typeof rawData === 'object' && Array.isArray(rawData.stops)) {
             rawStops = rawData.stops;
             meta = rawData.meta || null;
         }

         // Determine if the result set was capped by the backend limit
         var capped = false;
         if (meta && meta.has_more) {
             capped = true;
         } else if (params && params.limit && Array.isArray(rawStops) && rawStops.length >= params.limit) {
             capped = true;
         }
         
         viewportDataCache.capped = capped;

         // Update banner visibility and text based on actual data returned
         if (shouldShowBanner) {
             if (hasAnyActiveFilter) {
                 var resultCount = Array.isArray(rawStops) ? rawStops.length : 0;
                 
                 // Recalculate filter count to be safe
                 var currentFilterCount = (activeFilters.station?.length || 0) + 
                                          (activeFilters.atlasOperators?.length || 0);
                 if (activeFilters.stopType?.length > 0) currentFilterCount++;
                 if (activeFilters.nodeType?.length > 0) currentFilterCount++;
                 if (activeFilters.matchMethods?.length > 0) currentFilterCount++;
                 if (activeFilters.transportTypes?.length > 0) currentFilterCount++;
                 if (activeFilters.showDuplicatesOnly) currentFilterCount++;
                 
                 var filterText = currentFilterCount > 0 ? ` (${currentFilterCount} filter${currentFilterCount !== 1 ? 's' : ''} active)` : '';

                 if (capped) {
                     setZoomBannerText('🔍 Showing first ' + resultCount + ' filtered results. Zoom in to see all.');
                 } else {
                     // If not capped, we are showing ALL results for this filter in this view
                     // So we can just say "Showing X results"
                     if (isLowZoom) {
                         setZoomBannerText('🔍 Low zoom: showing ' + resultCount + ' filtered result' + (resultCount !== 1 ? 's' : '') + filterText);
                     } else {
                         setZoomBannerText('🔍 Showing ' + resultCount + ' filtered result' + (resultCount !== 1 ? 's' : '') + filterText);
                     }
                 }
                 showZoomBanner(true);
             } else if (!isLowZoom) {
                 // Mid-zoom, no filters.
                 // If we are not capped, we are showing all markers, so we can hide the "Zoom in" warning.
                 if (!capped) {
                     showZoomBanner(false);
                 }
                 // If capped, the default text "Zoom in a bit more..." set before the request is still valid.
             }
         }

         // If low zoom with no active filters: we are showing unmatched atlas markers.
         if (isLowZoom && !hasAnyActiveFilter) {
             // Apply client-side duplicates filter before counting
             let probeData = rawStops;
             if (activeFilters.showDuplicatesOnly) {
                 probeData = probeData.filter(stop => stop.atlas_duplicate_sloid && stop.atlas_duplicate_sloid !== '');
             }
             rawStops = probeData;
         }
         
         // Store cached data for potential future use
         viewportDataCache.data = rawStops;

         // Reset global store for data lookup
         stopsById = {}; 
         
         // Clear existing connection lines (preserves manual match overlay lines)
         LineRenderer.clearLines(linesLayer);

         // --- Client-side Filtering for Show Duplicates Only --- 
         let data = rawStops;
            if (activeFilters.showDuplicatesOnly) {
                // Apply this filter after the operator mismatch filter
                data = data.filter(stop => typeof isDuplicateFlagSet === 'function' ? isDuplicateFlagSet(stop.atlas_duplicate_sloid) : (stop.atlas_duplicate_sloid && stop.atlas_duplicate_sloid !== ''));
            }
         
         // Node type visibility flags
         var showAtlasNodes, showOSMNodes;
         if (isLowZoom) {
             if (!hasAnyActiveFilter) {
                 showAtlasNodes = true;
                 showOSMNodes = false;
             } else {
                 showAtlasNodes = activeFilters.nodeType.length === 0 || activeFilters.nodeType.indexOf("atlas") !== -1;
                 showOSMNodes = activeFilters.nodeType.length === 0 || activeFilters.nodeType.indexOf("osm") !== -1;
             }
         } else {
             showAtlasNodes = activeFilters.nodeType.length === 0 || activeFilters.nodeType.indexOf("atlas") !== -1;
             showOSMNodes = activeFilters.nodeType.length === 0 || activeFilters.nodeType.indexOf("osm") !== -1;
         }

         // Cache stop lookup for later interactions
         data.forEach(function(rawStop) {
             stopsById[rawStop.id] = rawStop;
         });

         // 1) Detect OSM nodes that have multiple ATLAS matches (cheap pass).
         // We use this to avoid building heavy per-node structures unless needed.
         var osmMultiMatchNodeIds = null;
         if (showOSMNodes) {
             var osmMatchCount = Object.create(null);
             data.forEach(function(s) {
                 if (s.stop_type !== 'matched' || !Array.isArray(s.osm_matches)) return;
                 s.osm_matches.forEach(function(m) {
                     if (!m || !m.osm_node_id) return;
                     var k = String(m.osm_node_id);
                     osmMatchCount[k] = (osmMatchCount[k] || 0) + 1;
                 });
             });
             osmMultiMatchNodeIds = new Set();
             Object.keys(osmMatchCount).forEach(function(k) {
                 if (osmMatchCount[k] > 1) osmMultiMatchNodeIds.add(k);
             });
         }

         // 2) Build detailed multi-match payload only when it can actually be used (high zoom).
         var osmNodeToAtlasMatches = {};
         var shouldBuildMultiMatchDetails = !!(showOSMNodes && osmMultiMatchNodeIds && osmMultiMatchNodeIds.size > 0 && map.getZoom() >= ZOOM_LINE_THRESHOLD);
         if (shouldBuildMultiMatchDetails) {
             data.forEach(function(rawStop) {
                 if (rawStop.stop_type !== 'matched' || !rawStop.sloid || !Array.isArray(rawStop.osm_matches)) return;
                 rawStop.osm_matches.forEach(function(osmMatch) {
                     if (!osmMatch || !osmMatch.osm_node_id) return;
                     const nodeId = String(osmMatch.osm_node_id);
                     if (!osmMultiMatchNodeIds.has(nodeId)) return;

                     if (!osmNodeToAtlasMatches[nodeId]) {
                         osmNodeToAtlasMatches[nodeId] = {
                             osm_data: {
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
                                 lat: osmMatch.osm_lat,
                                 lon: osmMatch.osm_lon,
                                 routes_osm: osmMatch.routes_osm,
                                 uic_ref: rawStop.uic_ref
                             },
                             atlas_matches: []
                         };
                     }
                     osmNodeToAtlasMatches[nodeId].atlas_matches.push({
                         id: rawStop.id,
                         sloid: rawStop.sloid,
                         uic_ref: rawStop.uic_ref,
                         atlas_designation: rawStop.atlas_designation,
                         atlas_designation_official: rawStop.atlas_designation_official,
                         atlas_business_org_abbr: rawStop.atlas_business_org_abbr,
                         atlas_lat: rawStop.atlas_lat,
                         atlas_lon: rawStop.atlas_lon,
                         distance_m: osmMatch.distance_m,
                         match_type: osmMatch.match_type || rawStop.match_type,
                         routes_unified: rawStop.routes_unified
                     });
                 });
             });
         }

         // 3) Collect Marker Data for Cluster Management
         var createdOsmMarkers = new Set();
         var allMarkerData = [];

         data.forEach(function(stop) {
            if (stop.stop_type === 'matched') {
                if (stop.sloid && Array.isArray(stop.osm_matches)) {
                    if (showAtlasNodes && stop.atlas_lat != null && stop.atlas_lon != null) {
                        // Use the new helper function to create the ATLAS marker
                        var isStation = stop.osm_matches && stop.osm_matches.length > 0 && stop.osm_matches.some(om => om.osm_public_transport === 'station' && om.osm_aerialway !== 'station');
                        if (!isStation && stop.osm_public_transport === 'station' && stop.osm_aerialway !== 'station') isStation = true;
                        
                        const atlasLat = +stop.atlas_lat;
                        const atlasLon = +stop.atlas_lon;
                        allMarkerData.push({
                            lat: atlasLat,
                            lon: atlasLon,
                            type: 'atlas',
                            color: 'green',
                            duplicateSloid: stop.atlas_duplicate_sloid,
                            originalLat: atlasLat,
                            originalLon: atlasLon,
                            stopData: stop
                        });
                    }

                    if (showOSMNodes) {
                        stop.osm_matches.forEach(function(osm_match) {
                            if (!osm_match || !osm_match.osm_node_id || !osm_match.osm_lat || !osm_match.osm_lon) return;
                            const nodeId = String(osm_match.osm_node_id);
                            const osmNodeIdKey = `osm-${nodeId}`; 
                            const hasMultipleAtlasMatches = osmMultiMatchNodeIds && osmMultiMatchNodeIds.has(nodeId);

                            if (!hasMultipleAtlasMatches && !createdOsmMarkers.has(osmNodeIdKey)) {
                                // Keep stopData minimal: used mainly for /api/stop_popup (stop_id + view_type).
                                // Also keep match flags for line styling.
                                const stopDataForOsmPopup = {
                                    id: osm_match.osm_id || stop.id,
                                    stop_type: 'matched',
                                    match_type: stop.match_type,
                                    manual_is_persistent: stop.manual_is_persistent,
                                    osm_node_id: osm_match.osm_node_id
                                };
                                const osmLat = +osm_match.osm_lat;
                                const osmLon = +osm_match.osm_lon;
                                allMarkerData.push({
                                    lat: osmLat,
                                    lon: osmLon,
                                    type: 'osm',
                                    color: 'blue',
                                    osmNodeType: osm_match.osm_node_type,
                                    originalLat: osmLat,
                                    originalLon: osmLon,
                                    stopData: stopDataForOsmPopup
                                });
                                
                                createdOsmMarkers.add(osmNodeIdKey);
                            }
                        });
                    }
                } else if (stop.sloid && stop.osm_node_id && (!Array.isArray(stop.osm_matches) || stop.osm_matches.length <= 1)) {
                     const osmNodeIdKey = `osm-${stop.osm_node_id}`;

                     if (showAtlasNodes && stop.atlas_lat != null && stop.atlas_lon != null) {
                         const atlasLat = +stop.atlas_lat;
                         const atlasLon = +stop.atlas_lon;
                         allMarkerData.push({
                             lat: atlasLat,
                             lon: atlasLon,
                             type: 'atlas',
                             color: 'green',
                             duplicateSloid: stop.atlas_duplicate_sloid,
                             originalLat: atlasLat,
                             originalLon: atlasLon,
                             stopData: stop
                         });
                     }
                     
                     if (showOSMNodes && stop.osm_lat != null && stop.osm_lon != null && !createdOsmMarkers.has(osmNodeIdKey)) {
                         const osmLat = +stop.osm_lat;
                         const osmLon = +stop.osm_lon;
                         allMarkerData.push({
                             lat: osmLat,
                             lon: osmLon,
                             type: 'osm',
                             color: 'blue',
                             osmNodeType: stop.osm_node_type,
                             originalLat: osmLat,
                             originalLon: osmLon,
                             stopData: stop
                         });
                         createdOsmMarkers.add(osmNodeIdKey);
                     }
                }
            }
            // --- Handle Station-Matched ATLAS Stops ---
            else if (stop.stop_type === 'station') {
                if (showAtlasNodes) {
                    const atlasLat = +(stop.atlas_lat || stop.lat);
                    const atlasLon = +(stop.atlas_lon || stop.lon);
                    allMarkerData.push({
                        lat: atlasLat,
                        lon: atlasLon,
                        type: 'atlas',
                        color: 'orange',
                        duplicateSloid: stop.atlas_duplicate_sloid,
                        originalLat: atlasLat,
                        originalLon: atlasLon,
                        stopData: stop
                    });
                }
            }
            // --- Handle Unmatched ATLAS Stops ---
            else if (stop.stop_type === 'unmatched') {
                 if (showAtlasNodes) {
                    const atlasLat = +stop.lat;
                    const atlasLon = +stop.lon;
                    allMarkerData.push({
                        lat: atlasLat,
                        lon: atlasLon,
                        type: 'atlas',
                        color: 'red',
                        duplicateSloid: stop.atlas_duplicate_sloid,
                        originalLat: atlasLat,
                        originalLon: atlasLon,
                        stopData: stop
                    });
                }
            }
            // --- Handle Unmatched OSM Nodes (standalone) ---
            else if (stop.stop_type === 'osm') {
                 const osmNodeIdKey = `osm-${stop.osm_node_id}`;
                 if (showOSMNodes && !createdOsmMarkers.has(osmNodeIdKey)) { // Check if not already created as part of a match
                     const osmLat = +stop.osm_lat;
                     const osmLon = +stop.osm_lon;
                     allMarkerData.push({
                         lat: osmLat,
                         lon: osmLon,
                         type: 'osm',
                         color: 'gray',
                         osmNodeType: stop.osm_node_type,
                         originalLat: osmLat,
                         originalLon: osmLon,
                         stopData: stop
                     });
                     createdOsmMarkers.add(osmNodeIdKey);
                 }
            }
         });

         // 3. Sync markers with overlap handling (Diffing)
         var clusterManager = new MarkerClusterManager();
         allMarkerData.forEach(function(m) { clusterManager.addMarker(m.lat, m.lon, m); });
         var clusteredData = clusterManager.getClusteredData();
         
         var newRenderedKeys = new Set();
         
         // Helper to generate unique key
         function getMarkerKey(m) {
             if (m.type === 'atlas') return 'atlas-' + m.stopData.id;
             if (m.type === 'osm') return 'osm-' + (m.stopData.osm_node_id || m.stopData.id);
             return null;
         }

         // Detect if we crossed the zoom threshold where marker representation changes (Circle <-> Icon)
         var currentZoom = map.getZoom();
         var lastZoom = viewportDataCache.lastRenderZoom;
         var crossedThreshold = (lastZoom !== null) && (
             (lastZoom < 23 && currentZoom >= 23) || 
             (lastZoom >= 23 && currentZoom < 23)
         );
         viewportDataCache.lastRenderZoom = currentZoom;

         clusteredData.forEach(function(item) {
             var mData = item.markerData;
             var key = getMarkerKey(mData);
             if (!key) return;
             
             newRenderedKeys.add(key);
             
             var shouldRecreate = false;
             if (renderedMarkers.has(key)) {
                 if (crossedThreshold) {
                     // If we crossed the threshold, we might need to switch between CircleMarker and Marker
                     // For simplicity and robustness, we recreate all markers when crossing the threshold.
                     shouldRecreate = true;
                 }
             }

             if (renderedMarkers.has(key) && !shouldRecreate) {
                 // Update existing marker position
                 var marker = renderedMarkers.get(key);
                 var oldLatLng = marker.getLatLng();
                 if (oldLatLng.lat !== item.lat || oldLatLng.lng !== item.lon) {
                     marker.setLatLng([item.lat, item.lon]);
                 }
                 // Update data for popup
                 marker.options.markerData = mData;
             } else {
                 // Remove existing if we need to recreate
                 if (renderedMarkers.has(key)) {
                     markersLayer.removeLayer(renderedMarkers.get(key));
                     renderedMarkers.delete(key);
                 }

                 // Create new marker
                 var marker;
                 if (mData.type === 'atlas') {
                     marker = createAtlasMarker(item.lat, item.lon, mData.color, mData.duplicateSloid);
                 } else {
                     marker = createOsmMarker(item.lat, item.lon, mData.color, mData.osmNodeType);
                 }
                 
                 // Attach data for popup
                 marker.options.markerData = mData;
                 
                 // Bind popup logic
                 if (mData.popup) {
                    marker.bindPopup(mData.popup);
                 } else if (mData.stopData && mData.type) {
                    marker.on('click', function() {
                        var currentData = this.options.markerData; // Use latest data
                        if (this._popupLoaded || this._popupLoading) {
                            if (this._popupLoaded && this.getPopup()) this.openPopup();
                            return;
                        }
                        this._popupLoading = true;
                        var self = this;
                        if (typeof $ !== 'undefined' && $.getJSON) {
                            $.getJSON('/api/stop_popup', { stop_id: currentData.stopData.id, view_type: currentData.type })
                              .done(function(resp) {
                                  try {
                                      const enriched = resp && (resp.stop || resp);
                                      let content = '';
                                      if (enriched && enriched.stop_type === 'unmatched') {
                                          content = currentData.type === 'atlas'
                                            ? PopupRenderer.generateSingleAtlasBubbleHtml(enriched, true)
                                            : PopupRenderer.generateSingleOsmBubbleHtml(enriched, true);
                                      } else {
                                          content = PopupRenderer.generatePopupHtml(enriched, currentData.type);
                                      }
                                      const popup = createPopupWithOptions(content);
                                      self.bindPopup(popup);
                                      self._popupLoaded = true;
                                      self.openPopup();
                                  } catch (e) {
                                      console.error('Failed to render popup:', e);
                                  } finally {
                                      self._popupLoading = false;
                                  }
                              })
                              .fail(function() {
                                  self._popupLoading = false;
                              });
                        }
                    });
                 }
                 
                 markersLayer.addLayer(marker);
                 renderedMarkers.set(key, marker);
             }
         });
         
         // Remove markers that are no longer in the view
         renderedMarkers.forEach(function(marker, key) {
             if (!newRenderedKeys.has(key)) {
                 markersLayer.removeLayer(marker);
                 renderedMarkers.delete(key);
             }
         });

         // 4. Draw connection lines between matched ATLAS-OSM pairs
         // Uses LineRenderer for consistent handling of all match types (1:1, 1:N, N:1)
         LineRenderer.drawAll(data, linesLayer, {
             showAtlas: showAtlasNodes,
             showOsm: showOSMNodes,
             minZoom: ZOOM_LINE_THRESHOLD,
             currentZoom: map.getZoom(),
             isContext: false
         });

         // 5. Handle OSM nodes with multiple ATLAS matches (marker creation only)
         // Note: Line drawing is handled by LineRenderer.drawAll() above
         if (showOSMNodes && map.getZoom() >= ZOOM_LINE_THRESHOLD) {
             Object.keys(osmNodeToAtlasMatches).forEach(function(osmNodeId) {
                 const multiMatchData = osmNodeToAtlasMatches[osmNodeId];
                 
                 if (multiMatchData.atlas_matches.length > 1) {
                     const osmNodeIdKey = `osm-${osmNodeId}`;
                     if (!createdOsmMarkers.has(osmNodeIdKey)) {
                         const osmBaseData = multiMatchData.osm_data;
                         if (!osmBaseData || !osmBaseData.osm_lat || !osmBaseData.osm_lon) {
                              console.warn("Missing base OSM data for multi-match node:", osmNodeId);
                              return; 
                         }

                         const osmWithMatches = {
                             id: osmBaseData.osm_id,
                             stop_type: 'matched',
                             is_osm_node: true, 
                             osm_node_id: osmNodeId,
                             osm_name: osmBaseData.osm_name,
                             osm_uic_name: osmBaseData.osm_uic_name,
                             osm_uic_ref: osmBaseData.osm_uic_ref,
                             osm_local_ref: osmBaseData.osm_local_ref,
                             osm_network: osmBaseData.osm_network,
                             osm_operator: osmBaseData.osm_operator,
                             osm_public_transport: osmBaseData.osm_public_transport,
                             osm_amenity: osmBaseData.osm_amenity,
                             osm_aerialway: osmBaseData.osm_aerialway,
                             osm_railway: osmBaseData.osm_railway,
                             osm_lat: osmBaseData.osm_lat,
                             osm_lon: osmBaseData.osm_lon,
                             osm_node_type: osmBaseData.osm_node_type,
                             uic_ref: osmBaseData.uic_ref, 
                             routes_osm: osmBaseData.routes_osm,
                             atlas_matches: multiMatchData.atlas_matches,
                         };

                         // Add the multi-match OSM marker data for cluster handling
                         const additionalOsmMarkerData = {
                             lat: parseFloat(osmWithMatches.osm_lat),
                             lon: parseFloat(osmWithMatches.osm_lon),
                             type: 'osm',
                             color: 'blue',
                             osmNodeType: osmWithMatches.osm_node_type,
                             originalLat: parseFloat(osmWithMatches.osm_lat),
                             originalLon: parseFloat(osmWithMatches.osm_lon),
                             stopData: osmWithMatches,
                             isMultiMatch: true
                         };
                         
                         // Use cluster handling for this marker too
                         createMarkersWithOverlapHandling([additionalOsmMarkerData], markersLayer);
                         createdOsmMarkers.add(osmNodeIdKey); 
                     }
                 }
             });
         }

         // Legacy manual match overlay removed
    }).fail(function(jqXHR, textStatus, errorThrown) {
         // Avoid noisy alerts on aborts (expected during fast pan/zoom)
         if (textStatus === 'abort') return;
         console.error("Failed to fetch /api/data:", textStatus, errorThrown);
         try {
             console.error("Server response:", jqXHR.responseJSON || jqXHR.responseText);
         } catch (e) {}
         // Keep existing markers rather than clearing; show banner to hint something is wrong
         showZoomBanner(true);
    });
}

// Reusable function to center map and open popup for a stop
function centerMapAndOpenPopup(stopData, centerLat, centerLon, popupViewType, zoomLevel = 17) {
    if (stopData && centerLat !== undefined && centerLon !== undefined) {
        // After programmatic center, skip the next 1 auto-reload cycle to avoid clearing existing markers
        suppressViewportReloadCount = 1;
        map.setView([centerLat, centerLon], zoomLevel); // Center map and zoom

        // Ensure the stopData is stored in stopsById if it wasn't already
        stopsById[stopData.id] = stopData;

        // Generate the appropriate popup HTML
        const popupHtml = PopupRenderer.generatePopupHtml(stopData, popupViewType);
        const popup = createPopupWithOptions(popupHtml).setLatLng([centerLat, centerLon]);

        // Add a temporary marker
        let tempMarkerColor = 'purple'; // Default color
        if (stopData.stop_type === 'matched') {
            tempMarkerColor = (popupViewType === 'atlas') ? 'green' : 'blue';
        } else if (stopData.stop_type === 'unmatched') {
            tempMarkerColor = (popupViewType === 'atlas') ? 'red' : 'gray'; // Red for ATLAS unmatched, Gray for OSM unmatched if popupViewType is 'osm'
        } else if (stopData.stop_type === 'osm') { // Pure OSM nodes
            tempMarkerColor = 'gray';
        }


        // Create temporary marker with cluster handling
        const tempMarkerData = [{
            lat: centerLat,
            lon: centerLon,
            type: popupViewType,
            color: tempMarkerColor,
            duplicateSloid: popupViewType === 'atlas' ? stopData.atlas_duplicate_sloid : null,
            osmNodeType: popupViewType === 'osm' ? stopData.osm_node_type : null,
            popup: popup,
            originalLat: centerLat,
            originalLon: centerLon,
            stopData: stopData
        }];

        // Clear previous temporary markers if any (optional, depends on desired behavior)
        // For now, let's assume new interaction clears old temporary focus
        if (window.currentFocusedMarker) {
            map.removeLayer(window.currentFocusedMarker);
        }
        
        // Create a temporary layer for this marker
        const tempLayer = L.layerGroup().addTo(map);
        const createdMarkers = createMarkersWithOverlapHandling(tempMarkerData, tempLayer);
        
        if (createdMarkers.length > 0) {
            createdMarkers[0].openPopup();
            window.currentFocusedMarker = tempLayer; // Store reference to layer instead of marker
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
    var params = {
        stop_filter: (activeFilters.stopType && activeFilters.stopType.length > 0) ? activeFilters.stopType.join(',') : null,
        match_method: (activeFilters.matchMethods && activeFilters.matchMethods.length > 0) ? activeFilters.matchMethods.join(',') : null,
        station_filter: (activeFilters.station && activeFilters.station.length > 0) ? activeFilters.station.join(',') : null,
        filter_types: (activeFilters.stationTypes && activeFilters.stationTypes.length > 0) ? activeFilters.stationTypes.join(',') : null,
        route_directions: (activeFilters.routeDirections && activeFilters.routeDirections.length > 0) ? activeFilters.routeDirections.join(',') : null,
        transport_types: (activeFilters.transportTypes && activeFilters.transportTypes.length > 0) ? activeFilters.transportTypes.join(',') : null,
        node_type: (activeFilters.nodeType && activeFilters.nodeType.length > 0) ? activeFilters.nodeType.join(',') : null,
        atlas_operator: (activeFilters.atlasOperators && activeFilters.atlasOperators.length > 0) ? activeFilters.atlasOperators.join(',') : null,
        top_n: activeFilters.topN || null,
        show_duplicates_only: (activeFilters.showDuplicatesOnly ? 'true' : 'false')
    };
    Object.keys(params).forEach(function(k) {
        if (params[k] === null || params[k] === undefined || params[k] === '') {
            delete params[k];
        }
    });

    $.getJSON("/api/random_stop", params, function(data) {
        if (data.error) {
            alert("Error focusing on random stop: " + data.error);
            return;
        }
        centerMapAndOpenPopup(data.stop, data.center_lat, data.center_lon, data.popup_view_type);
    }).fail(function(jqXHR, textStatus, errorThrown) {
        alert("Failed to fetch random stop. Status: " + textStatus + ", Error: " + errorThrown);
        try {
            console.error("Server response for random stop failure:", jqXHR.responseJSON || jqXHR.responseText);
        } catch (e) {
            console.error("Could not parse server error response.");
        }
    });
}

// Function to fetch and center on a specific stop by ID
function fetchAndCenterSpecificStop(identifier, identifierType) {
    // Determine the backend identifier_type based on the frontend filterType
    let backendIdentifierType = '';
    if (identifierType === 'atlas') {
        backendIdentifierType = 'sloid';
    } else if (identifierType === 'osm') {
        backendIdentifierType = 'osm_node_id';
    } else {
        // For UIC or other types, we don't auto-center for now, or could implement later
        console.log("Centering not implemented for identifier type:", identifierType);
        return;
    }

    $.getJSON("/api/stop_by_id", { identifier: identifier, identifier_type: backendIdentifierType }, function(data) {
        if (data.error) {
            alert("Error fetching stop " + identifier + ": " + data.error);
            return;
        }
        // Use a slightly less zoomed-in level for specific searches compared to random.
        centerMapAndOpenPopup(data.stop, data.center_lat, data.center_lon, data.popup_view_type, 16);
    }).fail(function() {
        alert("Failed to fetch stop " + identifier + " from the server.");
    });
}


// Function to initialize the new dropdown-based search type selector
function initSearchTypeSelector() {
    const selectEl = $('#searchTypeSelect');
    const filterTypeInput = $('#filterTypeActual');
    const searchInput = $('#stationFilter'); // Standard search input

    const placeholders = {
        station: 'Enter UIC Number',
        atlas: 'Enter ATLAS SloidID',
        osm: 'Enter OSM Node ID',
        route: 'Enter Route ID'
    };

    // Initialize select to current hidden value
    const initialType = filterTypeInput.val() || 'station';
    if (selectEl.length) {
        selectEl.val(initialType);
    }
    if (searchInput.length) {
        searchInput.attr('placeholder', placeholders[initialType] || 'Enter value');
    }
    toggleFilterInputs();

    // Handle selection changes
    selectEl.on('change', function() {
        const selectedValue = $(this).val();
        filterTypeInput.val(selectedValue);
        if (searchInput.length) {
            searchInput.val('');
            searchInput.attr('placeholder', placeholders[selectedValue] || 'Enter value');
        }
        toggleFilterInputs();
    });
}

// Apply saved filter panel state from localStorage
function applySavedFilterPanelState() {
    var filterPanel = document.getElementById('filterPanelContainer');
    if (!filterPanel) return false;
    
    var savedState = localStorage.getItem('indexFilterPanelCollapsed');
    if (savedState === 'true') {
        // Disable transitions temporarily for instant state application
        filterPanel.style.transition = 'none';
        filterPanel.classList.add('collapsed');
        
        // Force reflow to apply the collapsed state immediately
        filterPanel.offsetHeight;
        
        // Re-enable transitions after a frame
        requestAnimationFrame(function() {
            filterPanel.style.transition = '';
        });
        
        return true; // Panel was collapsed
    }
    return false; // Panel was not collapsed
}

// Filter panel toggle functionality
function initFilterPanelToggle() {
    var filterPanel = document.getElementById('filterPanelContainer');
    var toggleBtn = document.getElementById('filterToggleBtn');
    
    if (!filterPanel || !toggleBtn) return;
    
    toggleBtn.addEventListener('click', function() {
        filterPanel.classList.toggle('collapsed');
        var isCollapsed = filterPanel.classList.contains('collapsed');
        localStorage.setItem('indexFilterPanelCollapsed', isCollapsed);
        // No need to invalidate map size - panel now overlays the map
    });
}

$(document).ready(function(){
    // Apply saved panel state BEFORE initializing map
    var panelWasCollapsed = applySavedFilterPanelState();
    
    initMap();
    
    // loadDataForViewport(); // updateActiveFilters will call this after initial filter setup
    initSearchTypeSelector();
    initFilterPanelToggle();

    // logFilterPanelLayout("Document Ready"); // Function removed in refactor

    // Initialize filter event handlers (moved to filters.js)
    initFilterEventHandlers();
    
    // Initialize operator dropdown
    window.operatorDropdown = new OperatorDropdown('#atlasOperatorFilter', {
        placeholder: 'Select operators...',
        multiple: true,
        onSelectionChange: function(selectedOperators) {
            activeFilters.atlasOperators = selectedOperators;
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
$(window).on('load', function() {
    if (map) {
        map.invalidateSize();
    }
});


// Function to update accordion toggle icons
function updateAccordionIcons() {
    $('.nested-accordion-header').each(function() {
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
    const summaryContainer = $('#headerSummary');
    if (!summaryContainer.length) return;

    var params = {
        stop_filter: activeFilters.stopType.join(',') || null,
        match_method: activeFilters.matchMethods.join(',') || null,
        station_filter: activeFilters.station.join(',') || null,
        filter_types: activeFilters.stationTypes.join(',') || null,
        route_directions: activeFilters.routeDirections.join(',') || null,
        transport_types: activeFilters.transportTypes.join(',') || null,
        node_type: activeFilters.nodeType.join(',') || null,
        atlas_operator: activeFilters.atlasOperators.join(',') || null,
        top_n: activeFilters.topN || null,
        show_duplicates_only: activeFilters.showDuplicatesOnly.toString()
    };

    Object.keys(params).forEach(key => {
        if (params[key] === null || params[key] === '') {
            delete params[key];
        }
    });

    $.getJSON("/api/global_stats", params, function(data) {
        if (data.error) {
            summaryContainer.html(`<div><small>Error loading summary.</small></div>`);
            console.error("Error loading global stats:", data.error);
            positionIndexMapRightControls();
            return;
        }

        let summaryHtml = '';
        const activeNodeTypes = activeFilters.nodeType;

        const totalOSM = data.total_osm_nodes || 0;
        const matchedOSM = data.matched_osm_nodes || 0;
        const totalATLAS = data.total_atlas_stops || 0;
        const matchedATLAS = data.matched_atlas_stops || 0;
        // const matchedPairs = data.matched_pairs_count || 0;
        // const unmatchedEntities = data.unmatched_entities_count || 0;

        const osmPercentage = totalOSM > 0 ? ((matchedOSM / totalOSM) * 100).toFixed(1) : 0;
        const atlasPercentage = totalATLAS > 0 ? ((matchedATLAS / totalATLAS) * 100).toFixed(1) : 0;

        // Always show both lines if data is available, colorize percentages
        if (totalOSM > 0 || (activeNodeTypes.length === 0 || activeNodeTypes.includes('osm'))) {
             summaryHtml += `<div><i class="fas fa-map-marker-alt"></i> ${totalOSM} OSM nodes, <span style="color: #007bff; font-weight: bold;">${osmPercentage}% matched</span></div>`;
        }
        if (totalATLAS > 0 || (activeNodeTypes.length === 0 || activeNodeTypes.includes('atlas'))) {
            summaryHtml += `<div><i class="fas fa-atlas"></i> ${totalATLAS} ATLAS stops, <span style="color: #28a745; font-weight: bold;">${atlasPercentage}% matched</span></div>`;
        }
        
        if (!summaryHtml) { // Fallback if both counts are zero for some reason based on filters
            summaryHtml = '<div><small>No data matching current filters.</small></div>';
        }
        
        const activeFilterBadges = $('#activeFilters .badge');
        if (activeFilterBadges.length > 0 && activeFilterBadges.first().text() !== 'All entries') {
            summaryHtml += `<div class="mt-1"><small>Filters: ${activeFilterBadges.length} active</small></div>`;
        } else {
            summaryHtml += `<div class="mt-1"><small>Filters: None (All entries)</small></div>`;
        }

        summaryContainer.html(summaryHtml);
        positionIndexMapRightControls();
    }).fail(function() {
        summaryContainer.html(`<div><small>Failed to load summary.</small></div>`);
        console.error("Failed to fetch global stats from server.");
        positionIndexMapRightControls();
    });
}
