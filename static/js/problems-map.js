// problems-map.js - Map functionality for the Problem Identification Page

/**
 * ProblemsMap - Map initialization and rendering functionality
 * Depends on: ProblemsState, PopupRenderer (from popup-renderer.js), map utilities (from map-renderer.js)
 */
window.ProblemsMap = (function() {
    'use strict';

    // Performance tuning constants for the problems page
    // (Removed unused PROBLEM_MARKER_ZOOM_THRESHOLD)
    const PROBLEM_LINE_ZOOM_THRESHOLD = 14;   // draw context lines only at high zoom
    const CONTEXT_LIMIT_LOW_ZOOM = 150;
    const CONTEXT_LIMIT_HIGH_ZOOM = 200;

    // Request management for context loading
    let currentContextRequest = null; // jqXHR of in-flight /api/data

    /**
     * Initialize the map on the problems page with same style as main page
     */
    function initProblemMap() {
        const problemMap = L.map('problemMap', {
            closePopupOnClick: false,
            // Use SVG renderer so popup connection lines can be drawn (same as main map)
            preferCanvas: false
        }).setView([47.3769, 8.5417], 13);
        
        // Use same tile layer as main page
        const osmLayerProblems = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
             maxZoom: 19,
             attribution: '© OpenStreetMap'
        }).addTo(problemMap);
        
        const problemMarkersLayer = L.layerGroup().addTo(problemMap);
        const problemLinesLayer = L.layerGroup().addTo(problemMap);
        const contextMarkersLayer = L.layerGroup().addTo(problemMap);
        
        // Attach standard popup-line handlers (shared)
        attachPopupLineHandlersToMap(problemMap);

        // Store in state
        ProblemsState.setProblemMap(problemMap);
        ProblemsState.setOsmLayerProblems(osmLayerProblems);
        ProblemsState.setProblemMarkersLayer(problemMarkersLayer);
        ProblemsState.setProblemLinesLayer(problemLinesLayer);
        ProblemsState.setContextMarkersLayer(contextMarkersLayer);

        // Expose the map as window.map so shared marker utilities can switch to Canvas at low zoom
        // This is safe on problems.html where the main map is not present
        window.map = problemMap;

        // Manual match popup interactions are handled globally in map-renderer.js via attachPopupLineHandlersToMap
        
        console.log("Problem map initialized with layers:", {
            problemMarkersLayer: problemMarkersLayer,
            problemLinesLayer: problemLinesLayer,
            contextMarkersLayer: contextMarkersLayer
        });
    }

    /**
     * Load context data (nearby entries) for the current problem
     */
    function loadContextData(problem) {
        if (!ProblemsState.getShowContext() || !problem) {
            console.log("Context loading skipped:", !ProblemsState.getShowContext() ? "showContext false" : "no problem");
            console.log("showContext:", ProblemsState.getShowContext(), "problem:", problem);
            return;
        }
        
        // Calculate bounds around the problem location
        const lat = problem.atlas_lat || problem.osm_lat;
        const lon = problem.atlas_lon || problem.osm_lon;
        
        console.log("Problem coordinates:", lat, lon);
        
        if (!lat || !lon) {
            console.log("No coordinates found for problem");
            return;
        }
        
        // Create a bounds around the problem (roughly 2km radius for better context)
        const offset = 0.02; // Approximately 2km
        const bounds = {
            min_lat: lat - offset,
            max_lat: lat + offset,
            min_lon: lon - offset,
            max_lon: lon + offset
        };
        
        // Fetch data for the viewport
        const problemMap = ProblemsState.getProblemMap();
        const zoom = problemMap ? problemMap.getZoom() : 14;
        const params = {
            min_lat: bounds.min_lat,
            max_lat: bounds.max_lat,
            min_lon: bounds.min_lon,
            max_lon: bounds.max_lon,
            limit: zoom < PROBLEM_LINE_ZOOM_THRESHOLD ? CONTEXT_LIMIT_LOW_ZOOM : CONTEXT_LIMIT_HIGH_ZOOM,
            zoom: zoom
        };
        
        console.log("Fetching context data with params:", params);
        
        // Cancel previous context request if still in flight
        if (currentContextRequest && currentContextRequest.readyState !== 4) {
            try { currentContextRequest.abort(); } catch(e) {}
        }
        currentContextRequest = $.getJSON("/api/data", params, function(data) {
            console.log("Received context data:", data.length, "entries");
            
            if (data.length === 0) {
                console.warn("No context data received from API");
                return;
            }
            
            const contextMarkersLayer = ProblemsState.getContextMarkersLayer();
            contextMarkersLayer.clearLayers();
            
            // Log a sample of the received data to understand structure
            console.log("Sample context data entry:", data[0]);
            
            // Filter out the current problem from context data
            let filteredData = data.filter(stop => {
                // More robust filtering - handle different data structures
                const isCurrentProblem = (
                    (problem.id && stop.id === problem.id) ||
                    (problem.sloid && stop.sloid === problem.sloid) ||
                    (problem.osm_node_id && stop.osm_node_id === problem.osm_node_id) ||
                    // Handle case where stop has osm_matches array
                    (problem.sloid && Array.isArray(stop.osm_matches) && 
                     stop.osm_matches.some(match => match.osm_node_id === problem.osm_node_id)) ||
                    // Handle case where problem is in osm_matches
                    (problem.osm_node_id && Array.isArray(stop.osm_matches) && 
                     stop.osm_matches.some(match => match.osm_node_id === problem.osm_node_id))
                );
                return !isCurrentProblem;
            });
            
            console.log("Filtered context data:", filteredData.length, "entries after removing current problem");
            console.log("Current problem details:", {
                id: problem.id,
                sloid: problem.sloid, 
                osm_node_id: problem.osm_node_id,
                problem_type: problem.problem
            });
            
            if (filteredData.length === 0) {
                console.warn("All context data was filtered out - trying with less strict filtering");
                // Try with simpler filtering as fallback
                const simplefilteredData = data.filter(stop => {
                    // Only filter out exact matches by coordinates
                    const problemLat = parseFloat(problem.atlas_lat || problem.osm_lat);
                    const problemLon = parseFloat(problem.atlas_lon || problem.osm_lon);
                    const stopAtlasLat = parseFloat(stop.atlas_lat);
                    const stopAtlasLon = parseFloat(stop.atlas_lon);
                    const stopOsmLat = parseFloat(stop.osm_lat);
                    const stopOsmLon = parseFloat(stop.osm_lon);
                    
                    // Check if coordinates are too close (within 10 meters)
                    const isAtSameLocation = (
                        (stopAtlasLat && stopAtlasLon && 
                         Math.abs(stopAtlasLat - problemLat) < 0.0001 && 
                         Math.abs(stopAtlasLon - problemLon) < 0.0001) ||
                        (stopOsmLat && stopOsmLon && 
                         Math.abs(stopOsmLat - problemLat) < 0.0001 && 
                         Math.abs(stopOsmLon - problemLon) < 0.0001)
                    );
                    
                    return !isAtSameLocation;
                });
                
                if (simplefilteredData.length === 0) {
                    console.warn("Even simple filtering removed all entries - showing all nearby data");
                    filteredData = data; // Show everything as last resort
                } else {
                    filteredData = simplefilteredData;
                }
            }
            
            console.log("Final context data to display:", filteredData.length, "entries");
            
            // Collect marker data for cluster handling
            var contextMarkerData = [];
            
            // Process both ATLAS and OSM markers for each stop
            filteredData.forEach(function(stop) {
                // Handle ATLAS markers
                if (stop.sloid && stop.atlas_lat != null && stop.atlas_lon != null) {
                    let atlasColor = 'gray';
                    if (stop.stop_type === 'matched') atlasColor = 'green';
                    else if (stop.stop_type === 'unmatched') atlasColor = 'red';
                    else if (stop.stop_type === 'station') atlasColor = 'orange';
                    
                    contextMarkerData.push({
                        lat: parseFloat(stop.atlas_lat),
                        lon: parseFloat(stop.atlas_lon),
                        type: 'atlas',
                        color: atlasColor,
                        duplicateSloid: stop.atlas_duplicate_sloid,
                        originalLat: parseFloat(stop.atlas_lat),
                        originalLon: parseFloat(stop.atlas_lon),
                        stopData: stop,
                        opacity: 0.6
                    });
                }
                
                // Handle OSM markers - both direct and from osm_matches array
                const osmNodesToProcess = [];
                
                // Direct OSM data
                if (stop.osm_node_id && stop.osm_lat != null && stop.osm_lon != null) {
                    osmNodesToProcess.push(stop);
                }
                
                // OSM data from osm_matches array
                if (Array.isArray(stop.osm_matches)) {
                    stop.osm_matches.forEach(osmMatch => {
                        if (osmMatch.osm_node_id && osmMatch.osm_lat != null && osmMatch.osm_lon != null) {
                            // Create a combined data object for the OSM marker
                            const combinedOsmData = {
                                ...stop, // Base stop data
                                ...osmMatch, // Override with OSM-specific data
                                id: osmMatch.osm_id || stop.id,
                                osm_node_id: osmMatch.osm_node_id,
                                osm_lat: osmMatch.osm_lat,
                                osm_lon: osmMatch.osm_lon
                            };
                            osmNodesToProcess.push(combinedOsmData);
                        }
                    });
                }
                
                // Create markers for all OSM nodes
                osmNodesToProcess.forEach(osmData => {
                    let osmColor = 'gray';
                    if (osmData.stop_type === 'matched') osmColor = 'blue';
                    else if (osmData.stop_type === 'osm') osmColor = 'gray';
                    
                    contextMarkerData.push({
                        lat: parseFloat(osmData.osm_lat),
                        lon: parseFloat(osmData.osm_lon),
                        type: 'osm',
                        color: osmColor,
                        osmNodeType: osmData.osm_node_type,
                        originalLat: parseFloat(osmData.osm_lat),
                        originalLon: parseFloat(osmData.osm_lon),
                        stopData: osmData,
                        opacity: 0.6
                    });
                    
                    // Add connection lines for matched pairs (only at high zoom)
                    if (problemMap.getZoom() >= PROBLEM_LINE_ZOOM_THRESHOLD && stop.stop_type === 'matched' && stop.atlas_lat && osmData.osm_lat) {
                        const isManual = (stop.match_type === 'manual');
                        const isPersistent = !!stop.manual_is_persistent;
                        const style = isManual ? { color: 'purple', opacity: 0.6, weight: 2, dashArray: isPersistent ? null : '5,5' } : { color: 'green', opacity: 0.4, weight: 2 };
                        const line = L.polyline([
                            [parseFloat(stop.atlas_lat), parseFloat(stop.atlas_lon)],
                            [parseFloat(osmData.osm_lat), parseFloat(osmData.osm_lon)]
                        ], style);
                        contextMarkersLayer.addLayer(line);
                    }
                });
            });
            
            // Create markers with overlap handling (batch add to keep UI responsive)
            const contextMarkers = createMarkersWithOverlapHandling(contextMarkerData, contextMarkersLayer, { batchAdd: true, batchSize: 150 });
            
            // Apply opacity to markers after creation
            contextMarkers.forEach(marker => {
                if (marker.setOpacity) {
                    marker.setOpacity(0.6); // For L.marker (duplicates)
                } else if (marker.setStyle) {
                    marker.setStyle({opacity: 0.6}); // For L.circleMarker (non-duplicates)
                }
            });
            
            console.log("Added", contextMarkersLayer.getLayers().length, "context elements to map");
        }).fail(function(jqXHR, textStatus, errorThrown) {
            console.error("Failed to load context data:", textStatus, errorThrown);
        });
    }

    /**
     * Toggle context view
     */
    function toggleContext() {
        const showContext = !ProblemsState.getShowContext();
        ProblemsState.setShowContext(showContext);
        const button = $('#toggleContextBtn');
        
        console.log("Toggle context called, showContext is now:", showContext);
        
        if (showContext) {
            button.removeClass('btn-outline-secondary').addClass('btn-secondary');
            button.html('<i class="fas fa-eye-slash"></i> Hide other markers');
            const currentProblem = ProblemsState.getCurrentProblem();
            if (currentProblem) {
                loadContextData(currentProblem);
            } else {
                console.warn("No current problem to load context for.");
            }
        } else {
            button.removeClass('btn-secondary').addClass('btn-outline-secondary');
            button.html('<i class="fas fa-eye"></i> See other markers');
            const contextMarkersLayer = ProblemsState.getContextMarkersLayer();
            if (contextMarkersLayer) {
                contextMarkersLayer.clearLayers();
            }
            console.log("Context markers cleared");
        }
    }

    /**
     * Initialize modern resize functionality
     */
    function initializeResize() {
        const mapSection = $('#mapSection');
        const problemSection = $('#problemSection');
        const resizeDivider = $('#resizeDivider');
        const contentArea = $('#contentArea'); // The flex container

        let isResizing = false;
        let startX = 0;
        let startMapWidth = 0;
        let startProblemWidth = 0;

        resizeDivider.on('mousedown', function(e) {
            isResizing = true;
            startX = e.clientX;
            startMapWidth = mapSection.width();
            startProblemWidth = problemSection.width();
            
            $('body').addClass('user-select-none');
            resizeDivider.addClass('resizing');
            e.preventDefault();
        });

        $(document).on('mousemove', function(e) {
            if (!isResizing) return;
            
            const deltaX = e.clientX - startX;
            let newMapWidth = startMapWidth + deltaX;
            let newProblemWidth = startProblemWidth - deltaX;
            
            // Enforce min-width constraints from CSS
            const minMapWidth = parseInt(mapSection.css('min-width'), 10) || 300;
            const minProblemWidth = parseInt(problemSection.css('min-width'), 10) || 350;

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

        $(document).on('mouseup', function() {
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
    }

    /**
     * Initialize filter panel toggle functionality
     */
    function initializeFilterToggle() {
        const filterPanel = $('#filterPanel');
        const filterToggleBtn = $('#filterToggleBtn');
        const contentArea = $('#contentArea');
        
        filterToggleBtn.on('click', function() {
            filterPanel.toggleClass('collapsed');
            
            // Update button text and icon
            const isCollapsed = filterPanel.hasClass('collapsed');
            const toggleText = filterToggleBtn.find('.toggle-text');
            const toggleIcon = filterToggleBtn.find('.toggle-icon');
            
            if (isCollapsed) {
                toggleText.text('Show');
            } else {
                toggleText.text('Filters');
            }
            
            // Force map to resize after transition
            setTimeout(() => {
                const problemMap = ProblemsState.getProblemMap();
                if (problemMap) {
                    problemMap.invalidateSize();
                }
            }, 350); // Slightly longer than CSS transition
        });
    }

    // Public API
    return {
        initProblemMap,
        loadContextData,
        toggleContext,
        initializeResize,
        initializeFilterToggle
    };
})();
