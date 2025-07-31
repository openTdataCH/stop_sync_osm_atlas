// problems.js - JavaScript for the Problem Identification Page

var problemMap;
var osmLayerProblems;
var problemMarkersLayer;
var problemLinesLayer;
var contextMarkersLayer; // Layer for context (all nearby entries)

let allProblems = [];
let filteredProblems = []; // This will now hold only the currently loaded problems
let currentProblemIndex = -1;
let showContext = false; // Toggle state for showing context
let selectedProblemType = 'all'; // Current problem type filter
let selectedAtlasOperators = []; // Current operator filter
let currentProblem = null; // Store current problem for note saving

// New variables for handling multiple problems per entry
let problemsByEntry = {}; // Group problems by entry ID
let currentEntryProblems = []; // Current entry's problems
let currentEntryProblemIndex = 0; // Index within current entry's problems

// New state for pagination and sorting
let currentPage = 1;
let totalProblems = 0;
let isLoadingMore = false;
let currentSolutionFilter = 'all';
let currentSortBy = 'default';
let currentSortOrder = 'asc';

// Show keyboard shortcuts hint
let keyboardHintShown = false;
let keyboardHintTimeout = null;

// New variables for auto-persistence
let autoPersistEnabled = false;
let autoPersistNotesEnabled = false;
let batchPersistInProgress = false;

function showKeyboardHint() {
    if (!keyboardHintShown) {
        const hint = $('#keyboardHint');
        hint.addClass('show');
        keyboardHintShown = true;
        
        // Auto-hide after 5 seconds
        keyboardHintTimeout = setTimeout(() => {
            hideKeyboardHint();
        }, 5000);
    }
}

function hideKeyboardHint() {
    const hint = $('#keyboardHint');
    hint.removeClass('show');
    if (keyboardHintTimeout) {
        clearTimeout(keyboardHintTimeout);
        keyboardHintTimeout = null;
    }
}

// Function to initialize the map on the problems page with same style as main page
function initProblemMap() {
    problemMap = L.map('problemMap', {
        closePopupOnClick: false // Same setting as main map
    }).setView([47.3769, 8.5417], 13);
    
    // Use same tile layer as main page
    osmLayerProblems = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
         maxZoom: 19,
         attribution: '© OpenStreetMap'
    }).addTo(problemMap);
    
    problemMarkersLayer = L.layerGroup().addTo(problemMap);
    problemLinesLayer = L.layerGroup().addTo(problemMap);
    contextMarkersLayer = L.layerGroup().addTo(problemMap);
    
    console.log("Problem map initialized with layers:", {
        problemMarkersLayer: problemMarkersLayer,
        problemLinesLayer: problemLinesLayer,
        contextMarkersLayer: contextMarkersLayer
    });
}

// Group problems by entry (same location/stop)
function groupProblemsByEntry(problems) {
    const grouped = {};
    problems.forEach(problem => {
        const entryKey = `${problem.id}_${problem.atlas_lat || problem.osm_lat}_${problem.atlas_lon || problem.osm_lon}`;
        if (!grouped[entryKey]) {
            grouped[entryKey] = [];
        }
        grouped[entryKey].push(problem);
    });
    // Return an array of problem groups for consistent ordering
    return Object.values(grouped);
}

// Filter problems by type with support for solved/unsolved -
// This will now mainly be used for client-side display counts, as filtering is done on the backend
function filterProblemsOnClient(problems, problemType, solutionFilter = 'all') {
    let filtered = [];
    
    if (problemType === 'all') {
        filtered = allProblems;
    } else {
        filtered = allProblems.filter(problem => problem.problem === problemType);
    }
    
    // Apply solution filter
    if (solutionFilter === 'solved') {
        filtered = filtered.filter(problem => problem.solution && problem.solution.trim() !== '');
    } else if (solutionFilter === 'unsolved') {
        filtered = filtered.filter(problem => !problem.solution || problem.solution.trim() === '');
    }
    
    return filtered;
}

// Update the problem type filter
function updateProblemTypeFilter(newType, solutionFilter = 'all') {
    selectedProblemType = newType;
    currentSolutionFilter = solutionFilter;

    // Reset problems and pagination
    allProblems = [];
    currentPage = 1;
    totalProblems = 0;
    currentProblemIndex = -1;
    
    // Update filter dropdown display
    const filterButton = $('#problemTypeFilter');
    let typeText = newType === 'all' ? 'All Problems' : 
                     newType.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
    
    if (solutionFilter !== 'all') {
        typeText += ` (${solutionFilter})`;
    }
    
    filterButton.html(`<i class="fas fa-filter"></i> ${typeText} <span class="caret"></span>`);
    
    // Update sorting options visibility
    updateSortingOptionsVisibility(newType);
    
    // Fetch the first page of the new filtered data
    fetchProblems();
}

// Update sorting options visibility based on problem type
function updateSortingOptionsVisibility(problemType) {
    const sortingControls = $('#sortingControls');
    if (problemType === 'distance') {
        sortingControls.show();
    } else {
        sortingControls.hide();
        // Reset to default sorting when hiding
        currentSortBy = 'default';
        currentSortOrder = 'asc';
        updateSortingButtonDisplay();
    }
}

// Update sorting button display
function updateSortingButtonDisplay() {
    const sortButton = $('#sortButton');
    if (currentSortBy === 'distance') {
        const orderText = currentSortOrder === 'asc' ? 'Nearest First' : 'Farthest First';
        const orderIcon = currentSortOrder === 'asc' ? 'fas fa-sort-numeric-down' : 'fas fa-sort-numeric-up';
        sortButton.html(`<i class="${orderIcon}"></i> ${orderText}`);
    } else {
        sortButton.html('<i class="fas fa-sort"></i> Default Order');
    }
}

// Update sorting
function updateSorting(sortBy, sortOrder) {
    currentSortBy = sortBy;
    currentSortOrder = sortOrder;
    
    // Reset problems and pagination
    allProblems = [];
    currentPage = 1;
    totalProblems = 0;
    currentProblemIndex = -1;
    
    // Update button display
    updateSortingButtonDisplay();
    
    // Fetch the first page with new sorting
    fetchProblems();
}

// Fetch problems from the backend on page load or when filters change
function fetchProblems(page = 1) {
    if (isLoadingMore) return;
    isLoadingMore = true;
    $('#problemTypeDisplay').text('Loading...');

    const params = {
        page: page,
        limit: 100,
        problem_type: selectedProblemType,
        solution_status: currentSolutionFilter,
        sort_by: currentSortBy,
        sort_order: currentSortOrder
    };
    
    // Add operator filter if operators are selected
    if (selectedAtlasOperators.length > 0) {
        params.atlas_operator = selectedAtlasOperators.join(',');
    }

    $.getJSON("/api/problems", params, function(data) {
        if (data.error) {
            console.error("Error fetching problems:", data.error);
            $('#problemTypeDisplay').text("Error loading problems.");
            isLoadingMore = false;
            return;
        }

        if (page === 1) {
            allProblems = data.problems;
            totalProblems = data.total;
        } else {
            allProblems = allProblems.concat(data.problems);
        }
        
        currentPage = data.page;

        // Group problems by entry
        problemsByEntry = groupProblemsByEntry(allProblems);
        
        if (allProblems.length === 0) {
            const problemTypeDisplayText = selectedProblemType === 'all' ? 'problems' : 
                                         `${selectedProblemType.replace(/_/g, ' ')} problems`;
            $('#problemTypeDisplay').text(`No more ${problemTypeDisplayText}, good job!`);
            $('#actionButtonsContent').empty();
            problemMarkersLayer.clearLayers();
            problemLinesLayer.clearLayers();
            contextMarkersLayer.clearLayers();
        } else {
            if (currentProblemIndex === -1) {
                currentProblemIndex = 0;
            }
            displayProblem(currentProblemIndex);
        }
        updateNavButtons();
        isLoadingMore = false;
    }).fail(function() {
        $('#problemTypeDisplay').text('Error loading problems.');
        isLoadingMore = false;
    });
}

// Pre-fetch next page of problems if user is nearing the end of the current list
function prefetchNextPageIfNeeded() {
    const buffer = 20; // Load next page when user is 20 problems away from the end
    const hasMorePages = allProblems.length < totalProblems;

    if (!isLoadingMore && hasMorePages && (currentProblemIndex >= allProblems.length - buffer)) {
        fetchProblems(currentPage + 1);
    }
}

// Generate attribute comparison HTML for attributes problems
function generateAttributeComparisonHtml(problem) {
    let html = '<div class="problem-section-item">';
    html += '<h6><i class="fas fa-exchange-alt"></i> Attribute Comparison</h6>';
    html += '<div class="row">';
    
    // ATLAS column
    html += '<div class="col-md-6">';
    html += '<h6 class="text-info mb-3"><i class="fas fa-map-marker-alt"></i> ATLAS Entry</h6>';
    if (typeof PopupRenderer !== 'undefined') {
        // Create a temporary ATLAS data object
        const atlasData = {
            sloid: problem.sloid,
            atlas_lat: problem.atlas_lat,
            atlas_lon: problem.atlas_lon,
            atlas_business_org_abbr: problem.atlas_business_org_abbr,
            atlas_designation_official: problem.atlas_designation_official,
            atlas_designation: problem.atlas_designation,
            stop_type: problem.stop_type,
            uic_ref: problem.uic_ref,
            match_type: problem.match_type
        };
        // Add any other atlas_ prefixed properties from problem that might be needed
        Object.keys(problem).forEach(key => {
            if (key.startsWith('atlas_')) {
                if (!atlasData.hasOwnProperty(key)) {
                    atlasData[key] = problem[key];
                }
            }
        });
        html += PopupRenderer.generatePopupHtml(atlasData, 'atlas');
    } else {
        html += '<div class="alert alert-warning">ATLAS info not available</div>';
    }
    html += '</div>';
    
    // OSM column
    html += '<div class="col-md-6">';
    html += '<h6 class="text-primary mb-3"><i class="fas fa-map"></i> OSM Entry</h6>';
    
    if (typeof PopupRenderer !== 'undefined') {
        // Create a temporary OSM data object
        const osmData = {
            osm_node_id: problem.osm_node_id,
            osm_lat: problem.osm_lat,
            osm_lon: problem.osm_lon,
            osm_operator: problem.osm_operator,
            osm_name: problem.osm_name,
            osm_local_ref: problem.osm_local_ref,
            osm_public_transport: problem.osm_public_transport,
            stop_type: problem.stop_type,
            uic_ref: problem.uic_ref,
            match_type: problem.match_type
        };
        // Add all osm_ prefixed properties from problem
        Object.keys(problem).forEach(key => {
            if (key.startsWith('osm_')) {
                osmData[key] = problem[key];
            }
        });
        html += PopupRenderer.generatePopupHtml(osmData, 'osm');
    } else {
        html += '<div class="alert alert-warning">OSM info not available</div>';
    }

    // Add OSM iD Editor link below the popup
    if (problem.osm_node_id) {
        const osmEditorUrl = `https://www.openstreetmap.org/edit?node=${problem.osm_node_id}`;
        html += `<div class="mt-2">
            <a href="${osmEditorUrl}" class="osm-editor-link" target="_blank" rel="noopener noreferrer">
                <i class="fas fa-external-link-alt"></i>
                Edit in OSM iD Editor
            </a>
        </div>`;
    }
    html += '</div>';
    
    html += '</div>'; // End row
    html += '</div>'; // End problem-section-item
    
    return html;
}

// Helper to identify mismatched attributes for display
function getMismatchedAttributes(problem) {
    const attributesToCheck = [
        { atlas: 'atlas_operator', osm: 'osm_operator', label: 'Operator' },
        { atlas: 'atlas_designation_official', osm: 'osm_name', label: 'Name' },
        { atlas: 'atlas_designation', osm: 'osm_local_ref', label: 'Local Reference' },
        { atlas: 'atlas_transport_type', osm: 'osm_public_transport', label: 'Transport Type' }
    ];
    
    const mismatches = [];
    attributesToCheck.forEach(attr => {
        const atlasValue = problem[attr.atlas] || '';
        const osmValue = problem[attr.osm] || '';
        
        // Consider it a mismatch if values are different
        if (atlasValue !== osmValue) {
            mismatches.push(attr);
        }
    });
    return mismatches;
}

// Load context data (nearby entries) for the current problem
function loadContextData(problem) {
    if (!showContext || !problem) {
        console.log("Context loading skipped:", !showContext ? "showContext false" : "no problem");
        console.log("showContext:", showContext, "problem:", problem);
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
    const params = {
        min_lat: bounds.min_lat,
        max_lat: bounds.max_lat,
        min_lon: bounds.min_lon,
        max_lon: bounds.max_lon,
        limit: 200 // Increased limit to get more context
    };
    
    console.log("Fetching context data with params:", params);
    
    $.getJSON("/api/data", params, function(data) {
        console.log("Received context data:", data.length, "entries");
        
        if (data.length === 0) {
            console.warn("No context data received from API");
            return;
        }
        
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
                
                const atlasPopup = createPopupWithOptions(PopupRenderer.generatePopupHtml(stop, 'atlas'));
                contextMarkerData.push({
                    lat: parseFloat(stop.atlas_lat),
                    lon: parseFloat(stop.atlas_lon),
                    type: 'atlas',
                    color: atlasColor,
                    duplicateSloid: stop.atlas_duplicate_sloid,
                    popup: atlasPopup,
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
                
                const osmPopup = createPopupWithOptions(PopupRenderer.generatePopupHtml(osmData, 'osm'));
                contextMarkerData.push({
                    lat: parseFloat(osmData.osm_lat),
                    lon: parseFloat(osmData.osm_lon),
                    type: 'osm',
                    color: osmColor,
                    osmNodeType: osmData.osm_node_type,
                    popup: osmPopup,
                    originalLat: parseFloat(osmData.osm_lat),
                    originalLon: parseFloat(osmData.osm_lon),
                    stopData: osmData,
                    opacity: 0.6
                });
                
                // Add connection lines for matched pairs
                if (stop.stop_type === 'matched' && stop.atlas_lat && osmData.osm_lat) {
                    const line = L.polyline([
                        [parseFloat(stop.atlas_lat), parseFloat(stop.atlas_lon)],
                        [parseFloat(osmData.osm_lat), parseFloat(osmData.osm_lon)]
                    ], { 
                        color: 'green', 
                        opacity: 0.4, // Slightly more visible for context
                        weight: 2 
                    });
                    contextMarkersLayer.addLayer(line);
                }
            });
        });
        
        // Create markers with overlap handling
        const contextMarkers = createMarkersWithOverlapHandling(contextMarkerData, contextMarkersLayer);
        
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

// Render the UI for a single problem. Returns HTML string.
function renderSingleProblemUI(problem, entryIndex, issueIndex, totalIssues) {
    const problemType = problem.problem ? problem.problem.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase()) : "Unknown";
    let html = `<div class="issue-container" id="issue-${problem.id}" data-problem-id="${problem.id}" data-stop-id="${problem.stop_id}">`;

    // Header for the issue
    let displayText = `${problemType}`;
    if (totalIssues > 1) {
        displayText += ` (Issue ${issueIndex + 1}/${totalIssues})`;
    }
    
    // Add distance indicator for distance problems
    if (problem.problem === 'distance' && problem.distance_m) {
        const distance = Math.round(problem.distance_m);
        const distanceClass = distance > 100 ? 'high-distance' : '';
        displayText += `<span class="distance-indicator ${distanceClass}">(${distance}m apart)</span>`;
    }
    
    // Add persistence indicator to header if solution is persistent
    let persistenceIcon = '';
    if (problem.is_persistent) {
        persistenceIcon = ` <i class="fas fa-database text-success" title="This solution is persistent"></i>`;
    }
    
    html += `<h5 class="text-center mb-3">${displayText}${persistenceIcon}</h5>`;

    // Generate action buttons and content based on problem type
    let actionButtonsHtml = '';
    // Show existing solution if available
    if (problem.solution && problem.solution.trim() !== '') {
        let persistenceHtml = '';
        if (problem.is_persistent) {
            persistenceHtml = `
                <div class="mt-2">
                    <span class="badge badge-success"><i class="fas fa-database"></i> Persistent Solution</span>
                    <small class="text-muted ml-2">This solution will be automatically applied after data imports</small>
                </div>
            `;
        } else {
            persistenceHtml = `
                <div class="mt-2">
                    <button class="btn btn-sm btn-outline-success make-persistent-btn" data-problem-id="${problem.id}" data-problem-type="${problem.problem}" data-stop-id="${problem.stop_id}">
                        <i class="fas fa-thumbtack"></i> Make Persistent
                    </button>
                    <small class="text-muted ml-2">Save this solution for future data imports</small>
                </div>
            `;
        }

        actionButtonsHtml += `
            <div class="problem-section-item solution-status-section">
                <h6><i class="fas fa-check-circle text-success"></i> Current Solution</h6>
                <div class="alert alert-success solution-display">
                    <div class="d-flex justify-content-between align-items-center">
                        <div>
                            <strong>Proposed Solution:</strong> ${problem.solution}
                            <br><small class="text-muted">You can modify this solution by selecting a new action below.</small>
                        </div>
                        <button class="btn btn-sm btn-outline-secondary clear-solution-btn" data-problem-id="${problem.id}" data-problem-type="${problem.problem}" data-stop-id="${problem.stop_id}">
                            <i class="fas fa-undo"></i> Clear
                        </button>
                    </div>
                    ${persistenceHtml}
                </div>
            </div>
        `;
    }

    // Add problem-specific action buttons
    switch (problem.problem) {
        case 'distance':
            actionButtonsHtml += generateDistanceActionButtons(problem);
            break;
        case 'isolated':
            actionButtonsHtml += generateIsolatedActionButtons(problem);
            break;
        case 'attributes':
            actionButtonsHtml += generateAttributeComparisonHtml(problem);
            actionButtonsHtml += generateAttributesActionButtons(problem);
            break;
    }
    html += actionButtonsHtml;
    html += '</div>'; // close issue-container
    return html;
}

let observer;
function setupIntersectionObserver() {
    const options = {
      root: document.getElementById('problemContent'),
      rootMargin: '0px',
      threshold: 0.6, // Use a slightly lower threshold
    };

    observer = new IntersectionObserver((entries, observer) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                const problemId = $(entry.target).data('problem-id');

                // Find the problem in the current entry's problems
                const newProblemIndex = currentEntryProblems.findIndex(p => p.id === problemId);
                if (newProblemIndex !== -1 && newProblemIndex !== currentEntryProblemIndex) {
                    currentEntryProblemIndex = newProblemIndex;
                    const problem = currentEntryProblems[currentEntryProblemIndex];
                    currentProblem = problem;
                    
                    // Update map
                    drawProblemOnMap(problemMap, problem, {
                        markersLayer: problemMarkersLayer,
                        linesLayer: problemLinesLayer
                    });

                    // Update active highlight
                    $('.issue-container').removeClass('active');
                    $(entry.target).addClass('active');

                    // Update notes
                    loadNotesForProblem(problem);
                }
            }
        });
    }, options);
}

// Display a problem by its index in the filteredProblems array
function displayProblem(index) {
    if (index < 0 || index >= problemsByEntry.length) {
        return;
    }
    
    currentProblemIndex = index;
    currentEntryProblems = problemsByEntry[index];
    currentEntryProblemIndex = 0; // Reset to the first issue
    currentProblem = currentEntryProblems[0];

    // Update main header
    const problemCount = currentEntryProblems.length;
    const problemText = problemCount > 1 ? 'Problems' : 'Problem';
    $('#problemTypeDisplay').text(`Entry ${index + 1} of ${totalProblems} (${problemCount} ${problemText})`);

    // Clear previous content
    const container = $('#actionButtonsContent');
    container.empty();
    if (observer) {
        observer.disconnect();
    }

    // Render all issues for this entry
    currentEntryProblems.forEach((p, i) => {
        const problemHtml = renderSingleProblemUI(p, index, i, currentEntryProblems.length);
        container.append(problemHtml);
    });

    // Setup intersection observer for the new items
    $('.issue-container').each(function() {
        observer.observe(this);
    });

    // Set first problem as active
    const firstProblem = currentEntryProblems[0];
    if (firstProblem) {
        // Make first issue active
        $(`#issue-${firstProblem.id}`).addClass('active');
        
        // Draw the problem markers and lines on the map
        drawProblemOnMap(problemMap, firstProblem, {
            markersLayer: problemMarkersLayer,
            linesLayer: problemLinesLayer
        });

        // Load context if enabled
        if (showContext) {
            loadContextData(firstProblem);
        } else {
            contextMarkersLayer.clearLayers();
        }

        // Load notes for the first problem
        loadNotesForProblem(firstProblem);
    }
    
    // Add scroll indicator if needed
    const problemContent = $('#problemContent');
    let scrollIndicator = problemContent.find('.scroll-indicator');
    if (currentEntryProblems.length > 1) {
        if (scrollIndicator.length === 0) {
            scrollIndicator = $('<div class="scroll-indicator"><i class="fas fa-chevron-down"></i></div>');
            problemContent.append(scrollIndicator);
        }
        setTimeout(() => scrollIndicator.addClass('visible'), 100);

        // Hide indicator on scroll
        problemContent.off('scroll.indicator').on('scroll.indicator', () => {
            scrollIndicator.removeClass('visible');
        });

    } else {
        scrollIndicator.remove();
    }

    // After displaying problems, check their persistence status
    // No longer needed, as the status is part of the problem object
}

// Update navigation buttons for entry problems
function updateEntryNavButtons() {
    // This function is no longer needed with the scroll-based navigation
}

// Navigate to next/previous problem within the same entry
function navigateEntryProblem(direction) {
    // This function is no longer needed with the scroll-based navigation
}

// Save solution to database
function saveSolution(button, problemType, solution) {
    const problemId = $(button).closest('.issue-container').data('problem-id');
    const problem = currentEntryProblems.find(p => p.id === problemId);

    if (!problem) {
        showTemporaryMessage('Could not find problem data to save.', 'error');
        return;
    }

    // Provide visual feedback
    const originalButtonHtml = $(button).html();
    $(button).prop('disabled', true).html('<span class="spinner-border spinner-border-sm"></span> Saving...');
    
    const data = {
        problem_id: problem.stop_id, // Use stop_id as problem_id for the backend
        problem_type: problemType,
        solution: solution
    };
    
    $.ajax({
        url: '/api/save_solution',
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify(data),
        success: function(response) {
            if (response.success) {
                // Update local data
                problem.solution = solution;
                problem.is_persistent = false; // When saving, it's not persistent yet
                
                // Re-render the specific issue container to show the solution
                const issueContainer = $(`#issue-${problem.id}`);
                const problemIndex = currentEntryProblems.findIndex(p => p.id === problem.id);
                if (issueContainer.length && problemIndex !== -1) {
                    const newHtml = renderSingleProblemUI(problem, currentProblemIndex, problemIndex, currentEntryProblems.length);
                    const isActive = issueContainer.hasClass('active');
                    
                    // Replace and re-apply active state
                    issueContainer.replaceWith(newHtml);
                    const newIssueContainer = $(`#issue-${problem.id}`);
                    if (isActive) {
                        newIssueContainer.addClass('active');
                    }
                    
                    // Re-observe the new element
                    if (observer) {
                        observer.observe(document.getElementById(`issue-${problem.id}`));
                    }
                }

                // Check if auto-persist is enabled and provide appropriate feedback
                let messageText, messageIcon;
                if (autoPersistEnabled) {
                    messageText = 'Solution saved as persistent data!';
                    messageIcon = 'database';
                    // Make the solution persistent automatically
                    makeSolutionPersistent(problem.id, problemType);
                } else {
                    messageText = 'Solution saved temporarily (non-persistent)!';
                    messageIcon = 'clock';
                }
                
                showTemporaryMessage(`${messageText} <i class="fas fa-${messageIcon}"></i>`, 'success');
                
                // Proceed to next problem after delay
                setTimeout(() => {
                    const hasMoreProblemsInEntry = currentEntryProblems.length > 1 && currentEntryProblemIndex < currentEntryProblems.length - 1;
                    
                    if (hasMoreProblemsInEntry) {
                        const nextProblemEl = $(`#issue-${currentEntryProblems[currentEntryProblemIndex + 1].id}`);
                        if (nextProblemEl.length) {
                             $('#problemContent').animate({
                                scrollTop: nextProblemEl.offset().top - $('#problemContent').offset().top + $('#problemContent').scrollTop()
                            }, 500);
                        }
                    } else {
                        navigateToNextProblem();
                    }
                }, 1000); // 1-second delay before moving

            } else {
                showTemporaryMessage(`Error: ${response.error}`, 'error');
                $(button).prop('disabled', false).html(originalButtonHtml);
            }
        },
        error: function(xhr, status, error) {
            showTemporaryMessage(`Error saving solution: ${error}`, 'error');
            $(button).prop('disabled', false).html(originalButtonHtml);
        }
    });
}

// Check if a solution is already persistent
function checkPersistentStatus(problem) {
    // This function is now OBSOLETE
}

// Make a solution persistent
function makeSolutionPersistent(problemId, problemType) {
    const problem = currentEntryProblems.find(p => p.id === problemId);
    
    if (!problem || !problem.solution) {
        showTemporaryMessage('No solution to make persistent', 'error');
        return;
    }
    
    // Provide visual feedback
    const button = $(`.make-persistent-btn[data-problem-id="${problemId}"]`);
    const originalButtonHtml = button.html();
    button.prop('disabled', true).html('<span class="spinner-border spinner-border-sm"></span> Saving...');
    
    $.ajax({
        url: '/api/make_solution_persistent',
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({
            problem_id: problem.stop_id, // Use stop_id for the backend
            problem_type: problemType
        }),
        success: function(response) {
            if (response.success) {
                // Update local data
                problem.is_persistent = true;
                
                // Re-render the specific issue container
                const issueContainer = $(`#issue-${problem.id}`);
                const problemIndex = currentEntryProblems.findIndex(p => p.id === problem.id);
                if (issueContainer.length && problemIndex !== -1) {
                    const newHtml = renderSingleProblemUI(problem, currentProblemIndex, problemIndex, currentEntryProblems.length);
                    const isActive = issueContainer.hasClass('active');
                    
                    // Replace and re-apply active state
                    issueContainer.replaceWith(newHtml);
                    const newIssueContainer = $(`#issue-${problem.id}`);
                    if (isActive) {
                        newIssueContainer.addClass('active');
                    }
                    
                    // Re-observe the new element
                    if (observer) {
                        observer.observe(document.getElementById(`issue-${problem.id}`));
                    }
                }
                
                showTemporaryMessage('Solution converted to persistent data! <i class="fas fa-database"></i>', 'success');
            } else {
                showTemporaryMessage(`Error: ${response.error}`, 'error');
                button.prop('disabled', false).html(originalButtonHtml);
            }
        },
        error: function(xhr, status, error) {
            showTemporaryMessage(`Error making solution persistent: ${error}`, 'error');
            button.prop('disabled', false).html(originalButtonHtml);
        }
    });
}

// Toggle context view
function toggleContext() {
    showContext = !showContext;
    const button = $('#toggleContextBtn');
    
    console.log("Toggle context called, showContext is now:", showContext);
    
    if (showContext) {
        button.removeClass('btn-outline-secondary').addClass('btn-secondary');
        button.html('<i class="fas fa-eye"></i> Context On');
        if (currentProblem) {
            loadContextData(currentProblem);
        } else {
            console.warn("No current problem to load context for.");
        }
    } else {
        button.removeClass('btn-secondary').addClass('btn-outline-secondary');
        button.html('<i class="fas fa-eye-slash"></i> Context Off');
        contextMarkersLayer.clearLayers();
        console.log("Context markers cleared");
    }
}

// Initialize modern resize functionality
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
            if (problemMap) {
                problemMap.invalidateSize();
            }
        }
    });
}

// Initialize filter panel toggle functionality
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
            if (window.problemMap) {
                problemMap.invalidateSize();
            }
        }, 350); // Slightly longer than CSS transition
    });
}

// Load and display notes for current problem
function loadNotesForProblem(problem) {
    currentProblem = problem;
    
    // Show notes section
    $('#notesSection').show();
    
    // Load ATLAS note
    if (problem.sloid) {
        $('#atlasNote').val(problem.atlas_note || '');
        $('#atlasNoteContainer').show();
        
        // Check if ATLAS note is persistent (using the new flag)
        const isAtlasNotePersistent = problem.atlas_note_is_persistent || false;
        const atlasCheckbox = $('#atlasNotePersistentCheckbox');

        if (atlasCheckbox.length === 0) {
            const persistentHtml = `
                <div class="form-check mt-2">
                    <input class="form-check-input" type="checkbox" id="atlasNotePersistentCheckbox" ${isAtlasNotePersistent ? 'checked' : ''}>
                    <label class="form-check-label" for="atlasNotePersistentCheckbox">
                        Make note persistent across imports
                        ${isAtlasNotePersistent ? '<span class="badge badge-success ml-2">Persistent</span>' : ''}
                    </label>
                </div>
            `;
            $('#atlasNoteContainer .input-group').after(persistentHtml);
        } else {
            atlasCheckbox.prop('checked', isAtlasNotePersistent);
            const label = atlasCheckbox.siblings('label');
            label.find('.badge').remove();
            if (isAtlasNotePersistent) {
                label.append('<span class="badge badge-success ml-2">Persistent</span>');
            }
        }
    } else {
        $('#atlasNoteContainer').hide();
    }
    
    // Load OSM note and editor link
    if (problem.osm_node_id) {
        $('#osmNote').val(problem.osm_note || '');
        $('#osmNoteContainer').show();
        
        // Check if OSM note is persistent (using the new flag)
        const isOsmNotePersistent = problem.osm_note_is_persistent || false;
        const osmCheckbox = $('#osmNotePersistentCheckbox');
        
        if (osmCheckbox.length === 0) {
            const persistentHtml = `
                <div class="form-check mt-2">
                    <input class="form-check-input" type="checkbox" id="osmNotePersistentCheckbox" ${isOsmNotePersistent ? 'checked' : ''}>
                    <label class="form-check-label" for="osmNotePersistentCheckbox">
                        Make note persistent across imports
                        ${isOsmNotePersistent ? '<span class="badge badge-success ml-2">Persistent</span>' : ''}
                    </label>
                </div>
            `;
            $('#osmNoteContainer .input-group').after(persistentHtml);
        } else {
            osmCheckbox.prop('checked', isOsmNotePersistent);
            const label = osmCheckbox.siblings('label');
            label.find('.badge').remove();
            if (isOsmNotePersistent) {
                label.append('<span class="badge badge-success ml-2">Persistent</span>');
            }
        }
        
        // Set up OSM iD editor link
        const osmEditorUrl = `https://www.openstreetmap.org/edit?node=${problem.osm_node_id}`;
        $('#osmEditorLink').attr('href', osmEditorUrl);
        $('#osmEditorLinkContainer').show();
    } else {
        $('#osmNoteContainer').hide();
        $('#osmEditorLinkContainer').hide();
    }
}

// Save notes functionality
function saveNote(noteType, noteContent) {
    if (!currentProblem) {
        showTemporaryMessage('No problem selected', 'error');
        return;
    }
    
    // Check if the persistent checkbox is checked or auto-persist is enabled
    const persistentCheckbox = $(`#${noteType}NotePersistentCheckbox`);
    const isCheckboxChecked = persistentCheckbox.length > 0 && persistentCheckbox.is(':checked');
    const isPersistent = isCheckboxChecked || autoPersistNotesEnabled;
    
    // If auto-persist is enabled but the checkbox doesn't reflect it, update the checkbox
    if (autoPersistNotesEnabled && persistentCheckbox.length > 0 && !persistentCheckbox.is(':checked')) {
        persistentCheckbox.prop('checked', true);
    }
    
    const data = {
        note: noteContent,
        problem_id: currentProblem.stop_id, // Use stop_id for backend context
        make_persistent: isPersistent
    };
    
    if (noteType === 'atlas' && currentProblem.sloid) {
        data.sloid = currentProblem.sloid;
    } else if (noteType === 'osm' && currentProblem.osm_node_id) {
        data.osm_node_id = currentProblem.osm_node_id;
    } else {
        showTemporaryMessage(`Cannot save ${noteType} note: missing required ID`, 'error');
        return;
    }
    
    // Show saving indicator
    const saveButton = $(`#save${noteType.charAt(0).toUpperCase() + noteType.slice(1)}Note`);
    const originalButtonText = saveButton.text();
    saveButton.prop('disabled', true).html('<span class="spinner-border spinner-border-sm"></span> Saving...');
    
    $.ajax({
        url: `/api/save_note/${noteType}`,
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify(data),
        success: function(response) {
            if (response.success) {
                // Update the checkbox and badge if needed
                const persistentCheckbox = $(`#${noteType}NotePersistentCheckbox`);
                const badge = persistentCheckbox.siblings('label').find('.badge');
                
                if (response.is_persistent) {
                    if (badge.length === 0) {
                        persistentCheckbox.siblings('label').append('<span class="badge badge-success ml-2">Persistent</span>');
                    }
                    persistentCheckbox.prop('checked', true);
                } else {
                    badge.remove();
                    persistentCheckbox.prop('checked', false);
                }
                
                // Update the current problem object with the new note and its persistent status
                if (noteType === 'atlas') {
                    currentProblem.atlas_note = noteContent;
                    currentProblem.atlas_note_is_persistent = response.is_persistent;
                } else {
                    currentProblem.osm_note = noteContent;
                    currentProblem.osm_note_is_persistent = response.is_persistent;
                }
                
                // Provide clear feedback about persistence status
                const persistenceStatus = response.is_persistent ? 'as persistent data' : 'temporarily (non-persistent)';
                const statusIcon = response.is_persistent ? 'database' : 'clock';
                showTemporaryMessage(`${noteType.toUpperCase()} note saved ${persistenceStatus}! <i class="fas fa-${statusIcon}"></i>`, 'success');
            } else {
                showTemporaryMessage(`Error saving ${noteType} note: ${response.error}`, 'error');
            }
            
            // Restore button
            saveButton.prop('disabled', false).text(originalButtonText);
        },
        error: function(xhr, status, error) {
            showTemporaryMessage(`Error saving ${noteType} note: ${error}`, 'error');
            saveButton.prop('disabled', false).text(originalButtonText);
        }
    });
}

// Dynamically changes the action buttons based on the current problem
function updateActionButtons(problem) {
    // This function is now replaced by renderSingleProblemUI
    // The content will be generated and placed inside each issue-container
    // Event handlers will be delegated
}

function generateDistanceActionButtons(problem) {
    const distance = problem.distance_m ? Math.round(problem.distance_m) : 'unknown';
    const distanceInfo = problem.distance_m ? 
        `The distance between ATLAS and OSM entries is ${distance} meters (threshold: 20m).` :
        'The distance between ATLAS and OSM entries is greater than 20 meters.';
    
    return `
        <div class="problem-section-item">
            <h6><i class="fas fa-tools"></i> Resolution Actions</h6>
            <div class="alert alert-info">
                <small><i class="fas fa-info-circle"></i> ${distanceInfo} Please determine which location is correct.</small>
            </div>
            <div class="d-flex flex-wrap gap-2">
                <button class="btn btn-success professional-button solution-btn" data-solution="Atlas correct">
                    <i class="fas fa-check-circle"></i> Atlas correct
                </button>
                <button class="btn btn-primary professional-button solution-btn" data-solution="OSM correct">
                    <i class="fas fa-check-circle"></i> OSM correct
                </button>
                <button class="btn btn-warning professional-button solution-btn" data-solution="Both correct">
                    <i class="fas fa-pause-circle"></i> Both correct
                </button>
                <button class="btn btn-danger professional-button solution-btn" data-solution="Not a match">
                    <i class="fas fa-times-circle"></i> Not a match
                </button>
            </div>
        </div>
    `;
}

function generateIsolatedActionButtons(problem) {
    if (problem.stop_type === 'unmatched') { // Isolated ATLAS
        return `
            <div class="problem-section-item">
                <h6><i class="fas fa-tools"></i> Resolution Actions</h6>
                <div class="alert alert-info">
                    <small><i class="fas fa-info-circle"></i> This ATLAS entry has no corresponding OSM entry within 50 meters.</small>
                </div>
                <div class="d-flex flex-wrap gap-2">
                    <button class="btn btn-danger professional-button solution-btn" data-solution="Should be deleted">
                        <i class="fas fa-trash"></i> Should be deleted
                    </button>
                    <button class="btn btn-info professional-button solution-btn" data-solution="Missing OSM">
                        <i class="fas fa-plus-circle"></i> Missing OSM
                    </button>
                </div>
            </div>
        `;
    } else if (problem.stop_type === 'osm') { // Isolated OSM
        return `
            <div class="problem-section-item">
                <h6><i class="fas fa-tools"></i> Resolution Actions</h6>
                <div class="alert alert-info">
                    <small><i class="fas fa-info-circle"></i> This OSM entry has no corresponding ATLAS entry.</small>
                </div>
                <div class="d-flex flex-wrap gap-2">
                    <button class="btn btn-danger professional-button solution-btn" data-solution="Should be deleted">
                        <i class="fas fa-trash"></i> Should be deleted
                    </button>
                    <button class="btn btn-info professional-button solution-btn" data-solution="Missing ATLAS">
                        <i class="fas fa-plus-circle"></i> Missing ATLAS
                    </button>
                </div>
            </div>
        `;
    }
    // Fallback for unexpected cases
    return `
        <div class="problem-section-item">
            <h6><i class="fas fa-exclamation-triangle text-danger"></i> Data Inconsistency</h6>
            <div class="alert alert-danger">
                This entry is flagged with an 'isolated' problem, but its type is <code>${problem.stop_type || 'undefined'}</code>, which is not expected for this problem type. Please report this issue.
            </div>
        </div>
    `;
}

function generateAttributesActionButtons(problem) {
    let html = '<div class="problem-section-item">';
    html += '<h6><i class="fas fa-tools"></i> Resolution Actions</h6>';
    
    const mismatches = getMismatchedAttributes(problem);
    let solution = {};
    if (problem.solution && problem.solution.trim() !== '' && problem.solution.trim().startsWith('{')) {
        try {
            solution = JSON.parse(problem.solution);
        } catch (e) {
            console.error("Error parsing solution JSON:", e);
            solution = {};
        }
    } else if (problem.solution) {
        // Handle legacy string solutions
        html += `<div class="alert alert-warning"><strong>Legacy Solution:</strong> ${problem.solution}</div>`;
    }

    if (mismatches.length > 0) {
        html += '<p><small><i class="fas fa-info-circle"></i> For each mismatched attribute, choose the correct source.</small></p>';
        html += '<table class="table table-sm attribute-resolution-table"><tbody>';

        mismatches.forEach(attr => {
            const atlasValue = problem[attr.atlas] || '<em>(empty)</em>';
            const osmValue = problem[attr.osm] || '<em>(empty)</em>';
            const resolvedValue = solution[attr.label];

            html += `<tr>
                <td><strong>${attr.label}</strong></td>
                <td class="attribute-value">${atlasValue}</td>
                <td class="attribute-value">${osmValue}</td>
                <td class="attribute-action">`;

            if (resolvedValue !== undefined) {
                html += `<div class="text-success"><i class="fas fa-check-circle"></i> <strong>${resolvedValue || '<em>(empty)</em>'}</strong></div>`;
            } else {
                html += `<div class="btn-group btn-group-sm">
                    <button class="btn btn-outline-info solution-btn" data-solution-type="attribute" data-attribute="${attr.label}" data-value="${problem[attr.atlas] || ''}">Use ATLAS</button>
                    <button class="btn btn-outline-primary solution-btn" data-solution-type="attribute" data-attribute="${attr.label}" data-value="${problem[attr.osm] || ''}">Use OSM</button>
                </div>`;
            }

            html += '</td></tr>';
        });

        html += '</tbody></table>';
    } else {
        html += '<div class="alert alert-success"><i class="fas fa-check-circle"></i> No attribute mismatches detected.</div>';
    }

    // Add global actions
    html += '<h6 class="mt-4"><i class="fas fa-globe"></i> Overall Status</h6>';
    html += '<div class="d-flex flex-wrap gap-2">';
    html += `<button class="btn btn-danger professional-button solution-btn" data-solution-type="global" data-solution="Not a valid match">
                <i class="fas fa-times-circle"></i> Not a valid match
            </button>`;
    html += `<button class="btn btn-secondary professional-button solution-btn" data-solution-type="global" data-solution="Skip / I do not know">
                <i class="fas fa-forward"></i> Skip
            </button>`;
    html += '</div>';

    html += '</div>';
    return html;
}

// Enable or disable the Previous/Next buttons
function updateNavButtons() {
    // Navigation should be disabled only if we are at the very beginning, or at the very end of ALL problems
    $('#prevProblemBtn').prop('disabled', currentProblemIndex <= 0 && currentPage === 1);
    $('#nextProblemBtn').prop('disabled', allProblems.length === totalProblems && currentProblemIndex >= problemsByEntry.length - 1);
}

function navigateToNextProblem() {
    const totalEntries = problemsByEntry.length;
    if (currentProblemIndex < totalEntries - 1) {
        currentProblemIndex++;
        currentEntryProblemIndex = 0; // Reset to first issue in the new entry
        displayProblem(currentProblemIndex);
        updateNavButtons();
        prefetchNextPageIfNeeded();
    } else if (allProblems.length < totalProblems) {
        // We are at the end of the loaded list, but more problems exist on the server
        showTemporaryMessage('Loading more problems...', 'info');
        fetchProblems(currentPage + 1);
    } else {
        // Truly the last problem
        showTemporaryMessage("You've reached the last problem! Great work!", 'success');
    }
}

// Initialize the problem type filter dropdown using data from the new stats endpoint
function initializeProblemTypeFilter() {
    const params = {};
    
    // Include operator filter in stats request
    if (selectedAtlasOperators.length > 0) {
        params.atlas_operator = selectedAtlasOperators.join(',');
    }
    
    $.getJSON("/api/problems/stats", params, function(stats) {
        const problemTypes = ['distance', 'isolated', 'attributes'];
        const dropdown = $('#problemTypeFilterDropdown');
        
        // Clear existing options
        dropdown.empty();
        
        // Add "All Problems" option
        dropdown.append(`
            <a class="dropdown-item problem-type-option" href="#" data-type="all" data-solution-filter="all">
                <i class="fas fa-list"></i> All Problems <span class="badge badge-secondary ml-2">${stats.all.all}</span>
            </a>
            <a class="dropdown-item problem-type-option problem-sub-filter" href="#" data-type="all" data-solution-filter="solved">
                <i class="fas fa-check-circle text-success"></i> All Solved <span class="badge badge-success ml-2">${stats.all.solved}</span>
            </a>
            <a class="dropdown-item problem-type-option problem-sub-filter" href="#" data-type="all" data-solution-filter="unsolved">
                <i class="fas fa-exclamation-circle text-warning"></i> All Unsolved <span class="badge badge-warning ml-2">${stats.all.unsolved}</span>
            </a>
        `);
        
        if (problemTypes.length > 0) {
            dropdown.append('<div class="dropdown-divider"></div>');
        }
        
        // Add individual problem types
        problemTypes.forEach(type => {
            const typeStats = stats[type];
            if (typeStats && typeStats.all > 0) {
                const displayName = type.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
                const icon = type === 'distance' ? 'fas fa-ruler' : 
                            type === 'isolated' ? 'fas fa-map-marker-alt' : 
                            type === 'attributes' ? 'fas fa-tags' : 'fas fa-exclamation-triangle';
                
                dropdown.append(`
                    <a class="dropdown-item problem-type-option" href="#" data-type="${type}" data-solution-filter="all">
                        <i class="${icon}"></i> ${displayName} <span class="badge badge-secondary ml-2">${typeStats.all}</span>
                    </a>
                    <a class="dropdown-item problem-type-option problem-sub-filter" href="#" data-type="${type}" data-solution-filter="solved">
                        <i class="fas fa-check-circle text-success"></i> Solved <span class="badge badge-success ml-2">${typeStats.solved}</span>
                    </a>
                    <a class="dropdown-item problem-type-option problem-sub-filter" href="#" data-type="${type}" data-solution-filter="unsolved">
                        <i class="fas fa-exclamation-circle text-warning"></i> Unsolved <span class="badge badge-warning ml-2">${typeStats.unsolved}</span>
                    </a>
                `);
            }
        });
    }).fail(function() {
        console.error("Failed to load problem filter statistics.");
        $('#problemTypeFilterDropdown').html('<a class="dropdown-item disabled" href="#">Error loading filters</a>');
    });
}

// Make all current solutions persistent
function batchMakePersistent() {
    if (batchPersistInProgress) {
        return; // Prevent multiple simultaneous batch operations
    }
    
    // Find all problems with solutions that aren't already persistent
    const problemsToMakePersistent = allProblems.filter(p => 
        p.solution && 
        p.solution.trim() !== '' && 
        !p.is_persistent
    );
    
    if (problemsToMakePersistent.length === 0) {
        showTemporaryMessage('No non-persistent solutions found to make persistent.', 'info');
        return;
    }
    
    // Show confirmation dialog
    if (!confirm(`Make ${problemsToMakePersistent.length} solutions persistent? This action cannot be undone.`)) {
        return;
    }
    
    batchPersistInProgress = true;
    
    // Update button to show progress
    const batchButton = $('#batchPersistBtn');
    const originalButtonHtml = batchButton.html();
    batchButton.prop('disabled', true).html('<span class="spinner-border spinner-border-sm"></span> Processing...');
    
    // Keep track of progress
    let completedCount = 0;
    let successCount = 0;
    let failCount = 0;
    
    // Process each problem sequentially to avoid overwhelming the server
    function processNextProblem(index) {
        if (index >= problemsToMakePersistent.length) {
            // All done
            batchPersistInProgress = false;
            batchButton.prop('disabled', false).html(originalButtonHtml);
            showTemporaryMessage(`Batch operation complete: ${successCount} solutions made persistent, ${failCount} failed.`, 
                                failCount > 0 ? 'warning' : 'success');
            
            // Refresh the current problem display to show updated persistence status
            if (currentProblemIndex >= 0) {
                displayProblem(currentProblemIndex);
            }
            return;
        }
        
        const problem = problemsToMakePersistent[index];
        
        $.ajax({
            url: '/api/make_solution_persistent',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({
                problem_id: problem.stop_id, // Use stop_id for the backend
                problem_type: problem.problem
            }),
            success: function(response) {
                completedCount++;
                
                if (response.success) {
                    problem.is_persistent = true;
                    successCount++;
                } else {
                    failCount++;
                }
                
                // Update progress on button
                const percentComplete = Math.round((completedCount / problemsToMakePersistent.length) * 100);
                batchButton.html(`<span class="spinner-border spinner-border-sm"></span> Processing... ${percentComplete}%`);
                
                // Process next problem
                processNextProblem(index + 1);
            },
            error: function() {
                completedCount++;
                failCount++;
                
                // Update progress on button
                const percentComplete = Math.round((completedCount / problemsToMakePersistent.length) * 100);
                batchButton.html(`<span class="spinner-border spinner-border-sm"></span> Processing... ${percentComplete}%`);
                
                // Process next problem
                processNextProblem(index + 1);
            }
        });
    }
    
    // Start processing
    processNextProblem(0);
}

$(document).ready(function(){
    console.log("=== PROBLEMS.JS INITIALIZATION ===");
    initProblemMap();
    setupIntersectionObserver();
    
    // Initialize operator dropdown for problems page
    window.operatorDropdownProblems = new OperatorDropdown('#atlasOperatorFilterProblems', {
        placeholder: 'Select operators...',
        multiple: true,
        onSelectionChange: function(selectedOperators) {
            selectedAtlasOperators = selectedOperators;
            
            // Reset problems and pagination when operator filter changes
            allProblems = [];
            currentPage = 1;
            totalProblems = 0;
            currentProblemIndex = -1;
            
            // Reload data with new operator filter
            initializeProblemTypeFilter(); // Update stats
            fetchProblems(); // Fetch filtered problems
        }
    });
    
    // Load auto-persist setting from localStorage
    autoPersistEnabled = localStorage.getItem('autoPersistEnabled') === 'true';
    autoPersistNotesEnabled = localStorage.getItem('autoPersistNotesEnabled') === 'true';
    $('#autoPersistToggle').prop('checked', autoPersistEnabled);
    $('#autoPersistNotesToggle').prop('checked', autoPersistNotesEnabled);
    
    initializeProblemTypeFilter(); // Fetch stats and build filter
    fetchProblems(); // Initial fetch for "All" problems
    initializeResize();
    initializeFilterToggle();
    
    // Show keyboard hint after page loads
    setTimeout(() => {
        showKeyboardHint();
    }, 2000);

    $('#prevProblemBtn').on('click', function() {
        if (currentProblemIndex > 0) {
            currentProblemIndex--;
            currentEntryProblemIndex = 0; // Reset to first problem in new entry
            displayProblem(currentProblemIndex);
            updateNavButtons();
        }
    });

    $('#nextProblemBtn').on('click', function() {
        navigateToNextProblem();
    });
    
    // Auto-persist toggle handler
    $('#autoPersistToggle').on('change', function() {
        autoPersistEnabled = $(this).is(':checked');
        localStorage.setItem('autoPersistEnabled', autoPersistEnabled);
        
        if (autoPersistEnabled) {
            showTemporaryMessage('Auto-persist enabled: Solutions will be saved as persistent data <i class="fas fa-database"></i>', 'info');
        } else {
            showTemporaryMessage('Auto-persist disabled: Solutions will be saved temporarily <i class="fas fa-clock"></i>', 'info');
        }
    });

    // Auto-persist notes toggle handler
    $('#autoPersistNotesToggle').on('change', function() {
        autoPersistNotesEnabled = $(this).is(':checked');
        localStorage.setItem('autoPersistNotesEnabled', autoPersistNotesEnabled);
        
        if (autoPersistNotesEnabled) {
            showTemporaryMessage('Auto-persist notes enabled: Notes will be saved as persistent data <i class="fas fa-database"></i>', 'info');
        } else {
            showTemporaryMessage('Auto-persist notes disabled: Notes will be saved temporarily <i class="fas fa-clock"></i>', 'info');
        }
    });
    
    // Batch persist button handler
    $('#batchPersistBtn').on('click', function() {
        batchMakePersistent();
    });
    
    // Entry problem navigation handlers
    $(document).on('click', '#prevEntryProblemBtn', function() {
        navigateEntryProblem('prev');
    });
    
    $(document).on('click', '#nextEntryProblemBtn', function() {
        navigateEntryProblem('next');
    });
    
    // Context toggle button click handler
    $('#toggleContextBtn').on('click', toggleContext);
    
    // Problem type filter dropdown handler
    $(document).on('click', '.problem-type-option', function(e) {
        e.preventDefault();
        const selectedType = $(this).data('type');
        const solutionFilter = $(this).data('solution-filter') || 'all';
        updateProblemTypeFilter(selectedType, solutionFilter);
        $('#problemTypeFilterCollapse').collapse('hide');
    });
    
    // Sorting option click handler
    $(document).on('click', '.sort-option', function(e) {
        e.preventDefault();
        const sortBy = $(this).data('sort-by');
        const sortOrder = $(this).data('sort-order');
        updateSorting(sortBy, sortOrder);
    });
    
    // Solution button click handlers
    $('#actionButtonsContent').on('click', '.solution-btn', function() {
        console.log("=== SOLUTION BUTTON CLICKED ===");
        
        const issueContainer = $(this).closest('.issue-container');
        const problemId = issueContainer.data('problem-id');
        const problem = currentEntryProblems.find(p => p.id === problemId);
        
        if (!problem) {
            showTemporaryMessage('Could not find problem data.', 'error');
            return;
        }

        const solutionType = $(this).data('solution-type');
        let solution;

        if (solutionType === 'attribute') {
            const attribute = $(this).data('attribute');
            const value = $(this).data('value');
            
            // Get existing solution or create new object
            let currentSolution = {};
            if (problem.solution && problem.solution.trim().startsWith('{')) {
                try {
                    currentSolution = JSON.parse(problem.solution);
                } catch(e) { /* ignore parse error */ }
            }
            
            // Update the specific attribute
            currentSolution[attribute] = value;
            solution = JSON.stringify(currentSolution);

        } else { // 'global' or legacy
            solution = $(this).data('solution');
        }
        
        console.log("Saving solution:", solution);
        
        if (problem && solution !== undefined) {
            saveSolution(this, problem.problem, solution);
        } else {
            console.error("Missing problem or solution data", { problem, solution });
            showTemporaryMessage('Missing problem or solution data', 'error');
        }
    });
    
    // Make persistent button handler
    $('#actionButtonsContent').on('click', '.make-persistent-btn', function() {
        console.log("=== MAKE PERSISTENT BUTTON CLICKED ===");
        const problemId = $(this).data('problem-id');
        const problemType = $(this).data('problem-type');
        makeSolutionPersistent(problemId, problemType);
    });
    
    // Clear solution button handler
    $('#actionButtonsContent').on('click', '.clear-solution-btn', function() {
        console.log("=== CLEAR SOLUTION BUTTON CLICKED ===");
        const problemId = $(this).data('problem-id');
        const problem = allProblems.find(p => p.id === problemId);
        if (problem) {
            console.log("Clear solution for problem:", problem);
            clearSolution(problem);
        } else {
            console.error("Could not find problem with id:", problemId);
        }
    });
    
    // Note saving button handlers
    $('#actionButtonsContent').on('click', '#saveAtlasNote', function() {
        const noteContent = $('#atlasNote').val();
        saveNote('atlas', noteContent);
    });
    
    $('#actionButtonsContent').on('click', '#saveOsmNote', function() {
        const noteContent = $('#osmNote').val();
        saveNote('osm', noteContent);
    });
    
    // Note saving from notes section (outside of actionButtonsContent)
    $(document).on('click', '#saveAtlasNote', function() {
        const noteContent = $('#atlasNote').val();
        saveNote('atlas', noteContent);
    });
    
    $(document).on('click', '#saveOsmNote', function() {
        const noteContent = $('#osmNote').val();
        saveNote('osm', noteContent);
    });
    
    // Keyboard shortcuts for faster problem solving
    $(document).on('keydown', function(e) {
        // Only activate shortcuts when not in input fields
        if (!$(e.target).is('input, textarea, select')) {
            hideKeyboardHint(); // Hide hint when user starts using shortcuts
            
            switch(e.key) {
                case 'ArrowRight':
                case ' ': // Spacebar
                    e.preventDefault();
                    navigateToNextProblem();
                    break;
                case 'ArrowLeft':
                    e.preventDefault();
                    $('#prevProblemBtn').click();
                    break;
                case 'ArrowUp':
                    e.preventDefault();
                    $('#problemContent').animate({ scrollTop: '-=150' }, 200);
                    break;
                case 'ArrowDown':
                    e.preventDefault();
                    $('#problemContent').animate({ scrollTop: '+=150' }, 200);
                    break;
                case '?':
                    e.preventDefault();
                    // Toggle keyboard hint
                    if ($('#keyboardHint').hasClass('show')) {
                        hideKeyboardHint();
                    } else {
                        showKeyboardHint();
                    }
                    break;
            }
        }
    });
}); 

// Helper to show a temporary message on the screen
function showTemporaryMessage(message, type = 'info') {
    const messageContainer = $('<div class="temporary-message"></div>');
    messageContainer.addClass(`alert alert-${type}`);
    messageContainer.text(message);
    
    // Add icon based on type
    let icon = '';
    switch(type) {
        case 'success': icon = '<i class="fas fa-check-circle"></i> '; break;
        case 'error': icon = '<i class="fas fa-exclamation-circle"></i> '; break;
        case 'warning': icon = '<i class="fas fa-exclamation-triangle"></i> '; break;
        case 'info': 
        default: icon = '<i class="fas fa-info-circle"></i> '; break;
    }
    messageContainer.html(icon + message);
    
    $('body').append(messageContainer);
    
    messageContainer.fadeIn(200).delay(3000).fadeOut(500, function() {
        $(this).remove();
    });
}

// Clear solution functionality
function clearSolution(problem) {
    const data = {
        problem_id: problem.stop_id, // Use stop_id for the backend
        problem_type: problem.problem,
        solution: ''
    };
    
    $.ajax({
        url: '/api/save_solution',
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify(data),
        success: function(response) {
            if (response.success) {
                // Update problem in local arrays
                problem.solution = '';
                problem.is_persistent = false; // Clearing a solution makes it non-persistent
                
                // Re-render the specific issue that was cleared
                const issueContainer = $(`#issue-${problem.id}`);
                const problemIndex = currentEntryProblems.findIndex(p => p.id === problem.id);
                
                if (issueContainer.length && problemIndex !== -1) {
                    const isActive = issueContainer.hasClass('active');
                    const newHtml = renderSingleProblemUI(problem, currentProblemIndex, problemIndex, currentEntryProblems.length);
                    issueContainer.replaceWith(newHtml);
                    
                    const newIssueContainer = $(`#issue-${problem.id}`);
                    if (isActive) {
                        newIssueContainer.addClass('active');
                    }
                    
                    // Re-observe the new element
                    if (observer) {
                        observer.observe(document.getElementById(`issue-${problem.id}`));
                    }
                }
                
                showTemporaryMessage('Solution cleared successfully!', 'info');
            } else {
                showTemporaryMessage(`Error: ${response.error}`, 'error');
            }
        },
        error: function(xhr, status, error) {
            showTemporaryMessage(`Error clearing solution: ${error}`, 'error');
        }
    });
} 