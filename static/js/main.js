// Global variables
var map;
var osmLayer;
var markersLayer = L.layerGroup();
var linesLayer = L.layerGroup();
var topNLayer = L.layerGroup(); // For top N distances overlay
var stopsById = {};   // Global store for stops by id.
// manual matching variables are now defined in manual-matching.js

// Performance tuning constants
var ZOOM_MARKER_THRESHOLD = 13; // below this zoom, do not render markers
var ZOOM_LINE_THRESHOLD = 14;   // below this zoom, do not render polylines between matches
var VIEW_DEBOUNCE_MS = 320;     // debounce pan/zoom events (slightly higher to reduce redundant loads)
var LOW_ZOOM_SMALLSET_LIMIT = 250; // if <= this many entries match, render even below threshold
var ADDITIONAL_BANNER_ZOOM_LEVELS = 2; // keep banner for a couple of levels after markers appear

// Request management
var currentDataRequest = null;  // jqXHR of in-flight /api/data
var currentDataRequestSeq = 0;  // sequence id to ignore stale responses
var loadViewportTimer = null;   // debounce timer id

// Note: popup HTML generation functions are provided by popup-renderer.js



// (Removed unused wrappers and helpers: formatRouteInfo, formatRoutesDisplay, createCollapsible,
//  toggleCollapsible, createFilterLink, and getStationIdentifier)

// Note: createAtlasMarker and createOsmMarker functions are now provided by map-renderer.js

// Function to initialize the map with event listeners that preserve popups during movement
function initMap() {
    map = L.map('map', {
        closePopupOnClick: false, // Prevent map click from closing popups
        // Use SVG renderer so popup connection lines can be drawn in the map's SVG layer
        preferCanvas: false
    }).setView([47.3769, 8.5417], 13);
    
    osmLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
         maxZoom: 19,
         attribution: '© OpenStreetMap'
    });
    osmLayer.addTo(map);
    markersLayer.addTo(map);
    linesLayer.addTo(map);
    topNLayer.addTo(map);
    
    // Attach standard popup-line handlers
    var openPopups = attachPopupLineHandlersToMap(map);
    
    // Add low-zoom banner container
    ensureZoomBannerExists();

    // After pan/zoom ends: reload data (debounced) only if no popups are open
    map.on('moveend zoomend', function() {
        if (openPopups.length !== 0) return;
        if (loadViewportTimer) clearTimeout(loadViewportTimer);
        loadViewportTimer = setTimeout(function() {
            loadDataForViewport();
            updateHeaderSummary();
        }, VIEW_DEBOUNCE_MS);
    });
}















// Create and control a low-zoom banner prompting users to zoom in
function ensureZoomBannerExists() {
    if (document.getElementById('zoomBanner')) return;
    var banner = document.createElement('div');
    banner.id = 'zoomBanner';
    banner.style.position = 'absolute';
    banner.style.top = '10px';
    banner.style.left = '50%';
    banner.style.transform = 'translateX(-50%)';
    banner.style.zIndex = '1000';
    banner.style.background = 'rgba(0,0,0,0.75)';
    banner.style.color = '#fff';
    banner.style.padding = '8px 12px';
    banner.style.borderRadius = '6px';
    banner.style.fontSize = '14px';
    banner.style.display = 'none';
    banner.textContent = 'Zoom in to see all stop markers';
    var mapContainer = document.getElementById('map');
    if (mapContainer && mapContainer.parentElement) {
        mapContainer.parentElement.style.position = 'relative';
        mapContainer.parentElement.appendChild(banner);
    } else {
        document.body.appendChild(banner);
    }
}

function showZoomBanner(show) {
    var banner = document.getElementById('zoomBanner');
    if (!banner) return;
    banner.style.display = show ? 'block' : 'none';
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
                filteredData = filteredData.filter(stop => stop.atlas_duplicate_sloid && stop.atlas_duplicate_sloid !== '');
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
        return;
    }
    // Zoom gating: do not load or render markers if zoom is too low
    var zoom = map.getZoom();
    var isLowZoom = zoom < ZOOM_MARKER_THRESHOLD;
    var showPartialBanner = !isLowZoom && zoom < (ZOOM_MARKER_THRESHOLD + ADDITIONAL_BANNER_ZOOM_LEVELS);
    if (!isLowZoom) {
        // At early post-threshold zooms, we still hint that not all markers may be visible
        showZoomBanner(showPartialBanner);
    }
    var bounds = map.getBounds();
    var params = {
        min_lat: bounds.getSouth(),
        max_lat: bounds.getNorth(),
        min_lon: bounds.getWest(),
        max_lon: bounds.getEast(),
        offset: 0,
        // Increased limit with minimal payload (normal), reduced for low-zoom probe
        limit: isLowZoom ? LOW_ZOOM_SMALLSET_LIMIT : 500,
        zoom: zoom
    };
    
    // Determine if pure OSM nodes should be included in stop_filter when 'unmatched' is active
    var includeOsmInStopFilterForUnmatched = activeFilters.stopType.includes('unmatched') &&
                                           (activeFilters.nodeType.includes('osm') || activeFilters.nodeType.length === 0) && // OSM node type selected OR no node types selected (all)
                                           !activeFilters.stopType.includes('osm'); // Avoid duplicate 'osm' if already there for other reasons
    
    // Prepare stop type filter parameter
    if(activeFilters.stopType.length > 0 || includeOsmInStopFilterForUnmatched) { // check includeOsmInStopFilterForUnmatched as it might be the only reason to send stop_filter
        var stopFilterTypes = [...activeFilters.stopType];
        if (includeOsmInStopFilterForUnmatched) {
            if (!stopFilterTypes.includes('osm')) { // Ensure 'osm' is not added if already present
                stopFilterTypes.push('osm');
            }
        }
        if (stopFilterTypes.length > 0) {
            params.stop_filter = stopFilterTypes.join(',');
        }
    }
    
    // Add node type filter parameter
    if(activeFilters.nodeType.length > 0) {
        params.node_type = activeFilters.nodeType.join(',');
    }
    
    // Prepare match method filter parameter - use the already prepared activeFilters.matchMethods
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
    
    // Cancel previous data request if still in flight
    if (currentDataRequest && currentDataRequest.readyState !== 4) {
        try { currentDataRequest.abort(); } catch(e) {}
    }
    var mySeq = ++currentDataRequestSeq;
    currentDataRequest = $.getJSON("/api/data", params, function(rawData) {
         // Ignore stale responses
         if (mySeq !== currentDataRequestSeq) return;
         // Check first few items for atlas_is_duplicate
         rawData.slice(0, 5).forEach((item, index) => {
         });

         // If low zoom: only render when the filtered result count <= LOW_ZOOM_SMALLSET_LIMIT
         if (isLowZoom) {
             // Apply client-side duplicates filter before counting
             let probeData = rawData;
             if (activeFilters.showDuplicatesOnly) {
                 probeData = probeData.filter(stop => stop.atlas_duplicate_sloid && stop.atlas_duplicate_sloid !== '');
             }
             if (probeData.length === 0) {
                 showZoomBanner(true);
                 markersLayer.clearLayers();
                 linesLayer.clearLayers();
                 return;
             }
             if (probeData.length >= LOW_ZOOM_SMALLSET_LIMIT) {
                 // Too many to render at low zoom – show banner and skip rendering
                 showZoomBanner(true);
                 markersLayer.clearLayers();
                 linesLayer.clearLayers();
                 return;
             }
             // Else: small enough – proceed to render using probeData, hide banner
             showZoomBanner(false);
             // Continue with normal pipeline using probeData instead of rawData
             rawData = probeData;
         }

         markersLayer.clearLayers();
         // Only clear non-manual match lines
         linesLayer.eachLayer(function(layer) {
             if (!layer.options || !layer.options.isManualMatch) {
                 linesLayer.removeLayer(layer);
             }
         });
         stopsById = {}; // Reset global store

         // --- Client-side Filtering for Show Duplicates Only --- 
         let data = rawData;
         if (activeFilters.showDuplicatesOnly) {
             // Apply this filter after the operator mismatch filter
             data = data.filter(stop => stop.atlas_duplicate_sloid && stop.atlas_duplicate_sloid !== '');
         }
         
         // Node type visibility flags
         var showAtlasNodes = activeFilters.nodeType.length === 0 || activeFilters.nodeType.indexOf("atlas") !== -1;
         var showOSMNodes = activeFilters.nodeType.length === 0 || activeFilters.nodeType.indexOf("osm") !== -1;
         var showUnmatchedOSM = activeFilters.stopType.includes('unmatched') && showOSMNodes;

         // --- Refactored Data Processing ---
         var osmNodeToAtlasMatches = {};
         var allStopsData = []; 

         data.forEach(function(rawStop) {
             stopsById[rawStop.id] = rawStop;
             allStopsData.push(rawStop); 

             if (rawStop.stop_type === 'matched' && rawStop.sloid && Array.isArray(rawStop.osm_matches)) {
                 rawStop.osm_matches.forEach(function(osmMatch) {
                     if (!osmMatch || !osmMatch.osm_node_id) return;
                     const nodeId = osmMatch.osm_node_id;

                     if (!osmNodeToAtlasMatches[nodeId]) {
                         osmNodeToAtlasMatches[nodeId] = {
                             osm_data: { 
                                 osm_id: osmMatch.osm_id,
                                 osm_node_id: osmMatch.osm_node_id,
                                 osm_name: osmMatch.osm_name,
                                 osm_uic_name: osmMatch.osm_uic_name,
                                 osm_local_ref: osmMatch.osm_local_ref,
                                 osm_network: osmMatch.osm_network,
                                 osm_operator: osmMatch.osm_operator,
                                 osm_public_transport: osmMatch.osm_public_transport,
                                 osm_amenity: osmMatch.osm_amenity,
                                 osm_aerialway: osmMatch.osm_aerialway,
                                 osm_railway: osmMatch.osm_railway,
                                 osm_lat: osmMatch.osm_lat,
                                 osm_lon: osmMatch.osm_lon,
                                 osm_node_type: osmMatch.osm_node_type, // Include the node type
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
                         routes_atlas: rawStop.routes_atlas
                     });
                 });
             }
         });

                  // 2. Collect Marker Data for Cluster Management
         var createdOsmMarkers = new Set(); 
         var allMarkerData = [];

         allStopsData.forEach(function(stop) {
            if (stop.stop_type === 'matched') {
                if (stop.sloid && Array.isArray(stop.osm_matches)) {
                    let atlasMarkerData = null;

                    if (showAtlasNodes && stop.atlas_lat != null && stop.atlas_lon != null) {
                        // Use the new helper function to create the ATLAS marker
                        var isStation = stop.osm_matches && stop.osm_matches.length > 0 && stop.osm_matches.some(om => om.osm_public_transport === 'station' && om.osm_aerialway !== 'station');
                        if (!isStation && stop.osm_public_transport === 'station' && stop.osm_aerialway !== 'station') isStation = true;
                        
                        atlasMarkerData = {
                            lat: parseFloat(stop.atlas_lat),
                            lon: parseFloat(stop.atlas_lon),
                            type: 'atlas',
                            color: 'green',
                            duplicateSloid: stop.atlas_duplicate_sloid,
                            originalLat: parseFloat(stop.atlas_lat),
                            originalLon: parseFloat(stop.atlas_lon),
                            stopData: stop
                        };
                        allMarkerData.push(atlasMarkerData);
                    }

                    if (showOSMNodes) {
                        stop.osm_matches.forEach(function(osm_match) {
                            if (!osm_match || !osm_match.osm_node_id || !osm_match.osm_lat || !osm_match.osm_lon) return;
                            const nodeId = osm_match.osm_node_id;
                            const osmNodeIdKey = `osm-${nodeId}`; 
                            const multiMatchData = osmNodeToAtlasMatches[nodeId];
                            const hasMultipleAtlasMatches = multiMatchData && multiMatchData.atlas_matches.length > 1;

                            if (!hasMultipleAtlasMatches && !createdOsmMarkers.has(osmNodeIdKey)) {
                                const stopDataForOsmPopup = {
                                    ...stop, 
                                    id: osm_match.osm_id || stop.id, 
                                    osm_node_id: osm_match.osm_node_id,
                                    osm_name: osm_match.osm_name,
                                    osm_uic_name: osm_match.osm_uic_name,
                                    osm_local_ref: osm_match.osm_local_ref,
                                    osm_network: osm_match.osm_network,
                                    osm_operator: osm_match.osm_operator,
                                    osm_public_transport: osm_match.osm_public_transport,
                                    osm_amenity: osm_match.osm_amenity,
                                    osm_aerialway: osm_match.osm_aerialway,
                                    osm_railway: osm_match.osm_railway,
                                    osm_lat: osm_match.osm_lat,
                                    osm_lon: osm_match.osm_lon,
                                    distance_m: osm_match.distance_m,
                                    routes_osm: osm_match.routes_osm,
                                    lat: osm_match.osm_lat,
                                    lon: osm_match.osm_lon,
                                    stop_type: 'matched',
                                };
                                allMarkerData.push({
                                    lat: parseFloat(osm_match.osm_lat),
                                    lon: parseFloat(osm_match.osm_lon),
                                    type: 'osm',
                                    color: 'blue',
                                    osmNodeType: osm_match.osm_node_type,
                                    originalLat: parseFloat(osm_match.osm_lat),
                                    originalLon: parseFloat(osm_match.osm_lon),
                                    stopData: stopDataForOsmPopup,
                                    atlasMarkerData: atlasMarkerData
                                });
                                
                                createdOsmMarkers.add(osmNodeIdKey);
                            }
                        });
                    }
                } else if (stop.sloid && stop.osm_node_id && (!Array.isArray(stop.osm_matches) || stop.osm_matches.length <= 1)) {
                     const osmNodeIdKey = `osm-${stop.osm_node_id}`;
                     let atlasMarkerData = null;

                     if (showAtlasNodes && stop.atlas_lat != null && stop.atlas_lon != null) {
                         atlasMarkerData = {
                             lat: parseFloat(stop.atlas_lat),
                             lon: parseFloat(stop.atlas_lon),
                             type: 'atlas',
                             color: 'green',
                             duplicateSloid: stop.atlas_duplicate_sloid,
                             originalLat: parseFloat(stop.atlas_lat),
                             originalLon: parseFloat(stop.atlas_lon),
                             stopData: stop
                         };
                         allMarkerData.push(atlasMarkerData);
                     }
                     
                     if (showOSMNodes && stop.osm_lat != null && stop.osm_lon != null && !createdOsmMarkers.has(osmNodeIdKey)) {
                         allMarkerData.push({
                             lat: parseFloat(stop.osm_lat),
                             lon: parseFloat(stop.osm_lon),
                             type: 'osm',
                             color: 'blue',
                             osmNodeType: stop.osm_node_type,
                             originalLat: parseFloat(stop.osm_lat),
                             originalLon: parseFloat(stop.osm_lon),
                             stopData: stop,
                             atlasMarkerData: atlasMarkerData
                         });
                         createdOsmMarkers.add(osmNodeIdKey);
                     }
                }
            }
            // --- Handle Station-Matched ATLAS Stops ---
            else if (stop.stop_type === 'station') {
                if (showAtlasNodes) {
                    allMarkerData.push({
                        lat: parseFloat(stop.atlas_lat || stop.lat),
                        lon: parseFloat(stop.atlas_lon || stop.lon),
                        type: 'atlas',
                        color: 'orange',
                        duplicateSloid: stop.atlas_duplicate_sloid,
                        originalLat: parseFloat(stop.atlas_lat || stop.lat),
                        originalLon: parseFloat(stop.atlas_lon || stop.lon),
                        stopData: stop
                    });
                }
            }
            // --- Handle Unmatched ATLAS Stops ---
            else if (stop.stop_type === 'unmatched') {
                 if (showAtlasNodes) {
                    allMarkerData.push({
                        lat: parseFloat(stop.lat),
                        lon: parseFloat(stop.lon),
                        type: 'atlas',
                        color: 'red',
                        duplicateSloid: stop.atlas_duplicate_sloid,
                        originalLat: parseFloat(stop.lat),
                        originalLon: parseFloat(stop.lon),
                        stopData: stop
                    });
                }
            }
            // --- Handle Unmatched OSM Nodes (standalone) ---
            else if (stop.stop_type === 'osm') {
                 const osmNodeIdKey = `osm-${stop.osm_node_id}`;
                 if (showOSMNodes && !createdOsmMarkers.has(osmNodeIdKey)) { // Check if not already created as part of a match
                     allMarkerData.push({
                         lat: parseFloat(stop.osm_lat),
                         lon: parseFloat(stop.osm_lon),
                         type: 'osm',
                         color: 'gray',
                         osmNodeType: stop.osm_node_type,
                         originalLat: parseFloat(stop.osm_lat),
                         originalLon: parseFloat(stop.osm_lon),
                         stopData: stop
                     });
                     createdOsmMarkers.add(osmNodeIdKey);
                 }
            }
         });

         // 3. Create markers with overlap handling (batch add to avoid long main thread blocks)
         createMarkersWithOverlapHandling(allMarkerData, markersLayer, { batchAdd: true, batchSize: 150 });

         // 4. Add connection lines after markers are created (only at high zoom)
         if (map.getZoom() >= ZOOM_LINE_THRESHOLD) {
             allMarkerData.forEach(function(markerData) {
                 if (markerData.atlasMarkerData && markerData.type === 'osm') {
                     const isManual = (markerData.stopData && markerData.stopData.match_type === 'manual') || (markerData.atlasMarkerData && markerData.atlasMarkerData.stopData && markerData.atlasMarkerData.stopData.match_type === 'manual');
                     const isPersistent = (markerData.stopData && markerData.stopData.manual_is_persistent === true) || (markerData.atlasMarkerData && markerData.atlasMarkerData.stopData && markerData.atlasMarkerData.stopData.manual_is_persistent === true);
                     const style = isManual ? { color: 'purple', dashArray: isPersistent ? null : '5,5', weight: 2 } : { color: 'green' };
                     var line = L.polyline([
                         [markerData.atlasMarkerData.originalLat, markerData.atlasMarkerData.originalLon],
                         [markerData.originalLat, markerData.originalLon]
                     ], style);
                     linesLayer.addLayer(line);
                 }
             });
         }

         // 5. Handle OSM nodes with multiple ATLAS matches
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
                             osm_local_ref: osmBaseData.osm_local_ref,
                             osm_network: osmBaseData.osm_network,
                             osm_operator: osmBaseData.osm_operator,
                             osm_public_transport: osmBaseData.osm_public_transport,
                             osm_amenity: osmBaseData.osm_amenity,
                             osm_aerialway: osmBaseData.osm_aerialway,
                             osm_railway: osmBaseData.osm_railway,
                             osm_lat: osmBaseData.osm_lat,
                             osm_lon: osmBaseData.osm_lon,
                             osm_node_type: osmBaseData.osm_node_type, // Include the node type
                             uic_ref: osmBaseData.uic_ref, 
                             routes_osm: osmBaseData.routes_osm,
                             atlas_matches: multiMatchData.atlas_matches, // Includes isOperatorMismatch flag per match
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

                     if (showAtlasNodes) {
                         multiMatchData.atlas_matches.forEach(function(atlasMatch) {
                             if (atlasMatch.atlas_lat != null && atlasMatch.atlas_lon != null && multiMatchData.osm_data && multiMatchData.osm_data.osm_lat != null && multiMatchData.osm_data.osm_lon != null) {
                                 var line = L.polyline([
                                     [parseFloat(atlasMatch.atlas_lat), parseFloat(atlasMatch.atlas_lon)],
                                     [parseFloat(multiMatchData.osm_data.osm_lat), parseFloat(multiMatchData.osm_data.osm_lon)]
                                 ], { color: "purple" }); 
                                 linesLayer.addLayer(line);
                             }
                         });
                     }
                 }
             });
         }

         // Legacy manual match overlay removed
    });
}

// Reusable function to center map and open popup for a stop
function centerMapAndOpenPopup(stopData, centerLat, centerLon, popupViewType, zoomLevel = 17) {
    if (stopData && centerLat !== undefined && centerLon !== undefined) {
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

    } else {
        alert("Stop data is incomplete or coordinates are missing for centering.");
    }
}

// Function to fetch and center on a random stop based on current filters
function focusOnRandomFilteredStop() {
    var params = {}; // Initialize empty params object

    // Add active filters to params
    if (activeFilters.stopType.length > 0) {
        // Special handling for 'unmatched' + 'osm' node type
        var stopFilterTypes = [...activeFilters.stopType];
        if (activeFilters.stopType.includes('unmatched') && activeFilters.nodeType.includes('osm') && !stopFilterTypes.includes('osm')) {
            stopFilterTypes.push('osm');
        }
        params.stop_filter = stopFilterTypes.join(',');
    }

    var combinedMatchMethods = [...activeFilters.matchMethods];
    if (activeFilters.stopType.includes('unmatched') && activeFilters.noNearbyOSM) {
        combinedMatchMethods.push('no_nearby_counterpart');
    }
    if (combinedMatchMethods.length > 0) {
        params.match_method = combinedMatchMethods.join(',');
    }

    if (activeFilters.station.length > 0) {
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

    // Determine preferred_view based on nodeType filter
    let preferredView = 'atlas'; // Default
    const atlasSelected = activeFilters.nodeType.includes('atlas');
    const osmSelected = activeFilters.nodeType.includes('osm');

    if (osmSelected && !atlasSelected) {
        preferredView = 'osm';
    } else if (atlasSelected && !osmSelected) {
        preferredView = 'atlas';
    } // If both or neither, default to atlas is fine, or could be made smarter
    params.preferred_view = preferredView;

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


// Function to initialize the new modal-based search type selector
function initSearchTypeModal() {
    const modalButton = $('#searchTypeModalButton');
    const filterTypeInput = $('#filterTypeActual');
    const searchInput = $('#stationFilter'); // Standard search input
    const searchOptionsModal = $('#searchOptionsModal');

    $('.search-type-option-modal').on('click', function(e) {
        e.preventDefault();
        const selectedValue = $(this).data('value');
        const selectedPlaceholder = $(this).data('placeholder');
        const selectedHtmlContent = $(this).html(); // Get the HTML content (icon + text)

        // Update hidden input
        filterTypeInput.val(selectedValue);

        // Update button text/content
        modalButton.html(selectedHtmlContent);

        // Update main search input placeholder
        searchInput.attr('placeholder', selectedPlaceholder);
        searchInput.val(''); // Clear the input field
        
        // Hide the modal
        searchOptionsModal.modal('hide');

        // Toggle inputs and set focus (toggleFilterInputs now handles focus)
        toggleFilterInputs();
    });

    // Set initial button text based on default filterTypeActual value
    const initialFilterType = filterTypeInput.val();
    const initialOption = $(`.search-type-option-modal[data-value="${initialFilterType}"]`);
    if (initialOption.length) {
        modalButton.html(initialOption.html());
        searchInput.attr('placeholder', initialOption.data('placeholder'));
    }
    toggleFilterInputs(); // Call to set initial focus correctly
}

 

$(document).ready(function(){
    initMap();
    // loadDataForViewport(); // updateActiveFilters will call this after initial filter setup
    initSearchTypeModal();

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
            loadDataForViewport();
            updateHeaderSummary();
        }
    });

    initReportGeneration();

    $('#focusRandomVisibleEntryBtn').on('click', focusOnRandomFilteredStop);

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
    }).fail(function() {
        summaryContainer.html(`<div><small>Failed to load summary.</small></div>`);
        console.error("Failed to fetch global stats from server.");
    });
}
