// Filter Management Module
// This module handles all filter-related functionality

// Unified global filters object - Initialized to a "no filters active" state
var activeFilters = {
    station: [],
    stationTypes: [],
    routeDirections: [],
    filterType: 'station', // Default type for the input field, not an active filter itself
    stopType: [], // Will be populated by updateActiveFilters based on UI
    nodeType: [], // Will be populated by updateActiveFilters
    matchMethods: [], // Will be populated by updateActiveFilters
    atlasOperators: [], // Will be populated by operator dropdown
    matchedOptions: {
        allSelected: false,
        methods: {
            exact: false,
            name: false
        },
        distanceMatching: {
            allSelected: false,
            stage1: false,
            stage2: false,
            stage3a: false,
            stage3b: false
        },
        routeMatching: {
            allSelected: false,
            gtfs: false,
            hrdf: false
        }
    },
    unmatchedOptions: {
        allSelected: false,
        reasons: {
            noNearbyOSM: false,
            osmNearby: false
        }
    },
    transportTypes: [],
    topN: null,
    showDuplicatesOnly: false
};

// Helper function to normalize route IDs for display
function normalizeRouteIdForDisplay(routeId) {
    if (!routeId) return routeId;
    // Replace year codes (j22, j24, j25, etc.) with jXX
    return routeId.replace(/-j\d+/g, '-jXX');
}

// Helper function to format direction display
function formatDirectionDisplay(direction) {
    if (!direction || direction === '') return 'Both';
    return 'Dir: ' + direction;
}

// Helper function to cycle through direction options
function getNextDirection(currentDirection) {
    switch(currentDirection) {
        case '': return '0';  // Both -> Direction 0
        case '0': return '1'; // Direction 0 -> Direction 1  
        case '1': return '';  // Direction 1 -> Both
        default: return '';   // Default to Both
    }
}

// Legacy function - replaced by setRouteDirection and dropdown functionality

// Function to filter by route
function filterByRoute(routeId, directions) {
    if (!routeId) {
        alert("No route ID available.");
        return;
    }
    
    // Check if this route filter is already applied
    var isDuplicate = false;
    for (var i = 0; i < activeFilters.station.length; i++) {
        if (activeFilters.stationTypes[i] === 'route' && 
            activeFilters.station[i] === routeId &&
            activeFilters.routeDirections[i] === directions) {
            isDuplicate = true;
            break;
        }
    }
    
    if (isDuplicate) {
        alert("This route filter is already applied: Route: " + routeId + (directions ? ", Direction: " + directions : ""));
        return;
    }
    
    // Set filter type to 'route' for the UI
    $('#filterTypeActual').val('route');
    toggleFilterInputs();
    
    // Add the route filter
    activeFilters.station.push(routeId);
    activeFilters.stationTypes.push('route');
    activeFilters.routeDirections.push(directions || '');
    activeFilters.filterType = 'route';
    
    updateFiltersUI();
    if (typeof window.invalidateViewportCache === 'function') window.invalidateViewportCache();
    loadDataForViewport();
    updateHeaderSummary();
}

// Function to add an HRDF route filter programmatically
function filterByHrdfRoute(lineName) {
    if (!lineName) return;

    const filterType = 'hrdf_route';

    // Check for duplicates
    var isDuplicate = false;
    for (var i = 0; i < activeFilters.station.length; i++) {
        if (activeFilters.stationTypes[i] === filterType && 
            activeFilters.station[i] === lineName) {
            isDuplicate = true;
            break;
        }
    }
    
    if (isDuplicate) {
        alert("This HRDF route filter is already applied: " + lineName);
        return;
    }
    
    // Add the filter
    activeFilters.station.push(lineName);
    activeFilters.stationTypes.push(filterType);
    activeFilters.routeDirections.push(''); // No direction for HRDF routes for now
    
    updateFiltersUI();
    if (typeof window.invalidateViewportCache === 'function') window.invalidateViewportCache();
    loadDataForViewport();
    updateHeaderSummary();
}

// Add a custom filter programmatically
function addCustomFilter(value, filterType) {
    if (!value) return;
    
    // Check if this filter is already applied
    var isDuplicate = false;
    for (var i = 0; i < activeFilters.station.length; i++) {
        if (activeFilters.stationTypes[i] === filterType && 
            activeFilters.station[i] === value) {
            isDuplicate = true;
            break;
        }
    }
    
    if (isDuplicate) {
        alert("This filter is already applied: " + filterType + ": " + value);
        return;
    }
    
    // Add the filter
    activeFilters.station.push(value);
    activeFilters.stationTypes.push(filterType);
    activeFilters.routeDirections.push('');
    
    updateFiltersUI();
    if (typeof window.invalidateViewportCache === 'function') window.invalidateViewportCache();
    loadDataForViewport();
    updateHeaderSummary();
}

// Update active filters UI (badges)
function updateFiltersUI() {
    var container = $('#activeFilters');
    container.empty();
    
    let finalGroupStrings = []; // Array to hold HTML strings of final ANDed groups

    // Helper functions from shared utils (script is loaded before this file)
    const buildOrGroup = window.FilterChipUtils.buildOrGroupHtml;
    const joinWithAnd = window.FilterChipUtils.joinWithAndHtml;
    const buildRemovableChip = window.FilterChipUtils.buildRemovableChip;

    // --- 1. Node Type Filters ---
    let nodeTypeChips = [];
    activeFilters.nodeType.forEach(function(filter) {
        var chip = buildRemovableChip({
            label: 'Node: ' + filter,
            badgeClass: 'badge-success',
            data: { type: 'nodeType', filter: filter }
        });
        nodeTypeChips.push(chip);
    });
    const nodeTypeGroupHtml = buildOrGroup(nodeTypeChips);
    if (nodeTypeGroupHtml) finalGroupStrings.push(nodeTypeGroupHtml);

    // --- 2. Stop Status Filters (Matched OR Unmatched) ---
    let matchedDisplayString = '';
    if (activeFilters.matchedOptions && activeFilters.stopType.includes('matched')) {
        if (activeFilters.matchedOptions.allSelected) {
            matchedDisplayString = buildRemovableChip({
                label: 'Matched: All Methods',
                badgeClass: 'badge-primary',
                data: { type: 'masterMatched', target: '#masterMatchedCheckbox' }
            });
        } else {
            let matchedSubConditionStrings = [];
            
            let specificMethodChips = [];
            for (const method in activeFilters.matchedOptions.methods) {
                if (activeFilters.matchedOptions.methods[method]) {
                    var displayName = method.charAt(0).toUpperCase() + method.slice(1);
                    var targetId = '#filter' + displayName.charAt(0).toUpperCase() + displayName.slice(1);
                    var chip = buildRemovableChip({
                        label: 'Match: ' + displayName,
                        badgeClass: 'badge-primary',
                        data: { type: 'specificMatch', target: targetId }
                    });
                    specificMethodChips.push(chip);
                }
            }
            const specificMethodGroupHtml = buildOrGroup(specificMethodChips);
            if (specificMethodGroupHtml) matchedSubConditionStrings.push(specificMethodGroupHtml);

            if (activeFilters.matchedOptions.distanceMatching.allSelected && !activeFilters.matchedOptions.allSelected) { 
                var chipAllDist = buildRemovableChip({
                    label: 'Distance Match: All Stages',
                    badgeClass: 'badge-info',
                    data: { type: 'masterDistance', target: '#masterDistanceMatchingCheckbox' }
                });
                matchedSubConditionStrings.push(chipAllDist);
            } else if (!activeFilters.matchedOptions.distanceMatching.allSelected) {
                let distanceStageChips = [];
                for (const stage in activeFilters.matchedOptions.distanceMatching) {
                    if (stage !== 'allSelected' && activeFilters.matchedOptions.distanceMatching[stage]) {
                        let stageNum = stage.replace('stage', '');
                        var displayName = 'Dist. Stage ' + stageNum;
                        if (stage === 'stage1') displayName = 'Dist: Group Proximity';
                        if (stage === 'stage2') displayName = 'Dist: Local Ref Match';
                        if (stage === 'stage3a') displayName = 'Dist: Single Candidate';
                        if (stage === 'stage3b') displayName = 'Dist: Relative Distance';
                        var chip = buildRemovableChip({
                            label: displayName,
                            badgeClass: 'badge-info',
                            data: { type: 'specificDistance', target: '#distanceMethodStage' + stageNum }
                        });
                        distanceStageChips.push(chip);
                    }
                }
                const distanceStageGroupHtml = buildOrGroup(distanceStageChips);
                if (distanceStageGroupHtml) matchedSubConditionStrings.push(distanceStageGroupHtml);
            }

            // Always show specific route chips (GTFS/HRDF) based on selections, even if the master is checked
            let routeStageChips = [];
            if (activeFilters.matchedOptions.routeMatching.gtfs) {
                const chip = buildRemovableChip({
                    label: 'Route: GTFS',
                    badgeClass: 'badge-secondary',
                    data: { type: 'specificRoute', target: '#routeMethodGtfs' }
                });
                routeStageChips.push(chip);
            }
            if (activeFilters.matchedOptions.routeMatching.hrdf) {
                const chip = buildRemovableChip({
                    label: 'Route: HRDF',
                    badgeClass: 'badge-secondary',
                    data: { type: 'specificRoute', target: '#routeMethodHrdf' }
                });
                routeStageChips.push(chip);
            }
            const routeStageGroupHtml = buildOrGroup(routeStageChips);
            if (routeStageGroupHtml) matchedSubConditionStrings.push(routeStageGroupHtml);
            
            if (matchedSubConditionStrings.length > 0) {
                matchedDisplayString = joinWithAnd(matchedSubConditionStrings);
                if (matchedSubConditionStrings.length > 1) { 
                    matchedDisplayString = '( ' + matchedDisplayString + ' )';
                }
            }
        }
    }

    let unmatchedDisplayString = '';
    if (activeFilters.unmatchedOptions && activeFilters.stopType.includes('atlas_unmatched')) {
        if (activeFilters.unmatchedOptions.allSelected) {
            unmatchedDisplayString = buildRemovableChip({
                label: 'Unmatched: All Reasons',
                badgeClass: 'badge-warning',
                data: { type: 'masterUnmatched', target: '#masterUnmatchedCheckbox' }
            });
        } else {
            let unmatchedReasonChips = [];
            if (activeFilters.unmatchedOptions.reasons.noNearbyOSM) {
                var chip = buildRemovableChip({
                    label: 'Unmatched: No OSM within 50m',
                    badgeClass: 'badge-warning',
                    data: { type: 'specificUnmatched', target: '#filterNoNearbyOSM' }
                });
                unmatchedReasonChips.push(chip);
            }
            if (activeFilters.unmatchedOptions.reasons.osmNearby) { 
                var chip2 = buildRemovableChip({
                    label: 'Unmatched: OSM within 50m',
                    badgeClass: 'badge-warning',
                    data: { type: 'specificUnmatched', target: '#filterOSMNearby' }
                });
                unmatchedReasonChips.push(chip2);
            }
            unmatchedDisplayString = buildOrGroup(unmatchedReasonChips);
        }
    }

    let stopStatusGroupHtml = '';
    if (matchedDisplayString && unmatchedDisplayString) {
        stopStatusGroupHtml = '( ' + matchedDisplayString + ' <span class="filter-chip-operator">OR</span> ' + unmatchedDisplayString + ' )';
    } else if (matchedDisplayString) {
        stopStatusGroupHtml = matchedDisplayString;
    } else if (unmatchedDisplayString) {
        stopStatusGroupHtml = unmatchedDisplayString;
    }
    if (stopStatusGroupHtml) finalGroupStrings.push(stopStatusGroupHtml);
    
    let stationIdChips = [];
    activeFilters.station.forEach(function(filter, index) {
        var filterType = activeFilters.stationTypes[index] || activeFilters.filterType;
        var labelText = '';
        var badgeClass = '';
        var badgeHtmlContent = '';
        
        switch(filterType) {
            case 'atlas':
                labelText = 'ATLAS SloidID: '; badgeClass = 'badge-dark'; badgeHtmlContent = labelText + filter;
                break;
            case 'osm':
                labelText = 'OSM Node ID: '; badgeClass = 'badge-dark'; badgeHtmlContent = labelText + filter;
                break;
            case 'hrdf_route':
                labelText = 'HRDF Route: '; badgeClass = 'badge-info'; badgeHtmlContent = labelText + filter;
                break;
            case 'route':
                var direction = activeFilters.routeDirections[index] || '';
                var normalizedRoute = normalizeRouteIdForDisplay(filter);
                var directionDisplay = formatDirectionDisplay(direction);
                
                labelText = 'Route: '; badgeClass = 'badge-danger';
                badgeHtmlContent = labelText + normalizedRoute + ', ' + directionDisplay;
                break;
            case 'station': 
            default:
                labelText = 'UIC: '; badgeClass = 'badge-dark'; badgeHtmlContent = labelText + filter;
                break;
        }
        
        var badgeHtml;
        if (filterType === 'route') {
            // Special handling for route filters with direction dropdown
            var currentDirection = activeFilters.routeDirections[index] || '';
            var directionDropdownHtml = '<span class="direction-dropdown" data-index="' + index + '" data-current="' + currentDirection + '">' +
                '<span class="direction-current">' + directionDisplay + '</span>' +
                '<i class="fas fa-chevron-down direction-arrow"></i>' +
                '<div class="direction-options" style="display: none;">' +
                    '<div class="direction-option" data-direction="">Both</div>' +
                    '<div class="direction-option" data-direction="0">Dir: 0</div>' +
                    '<div class="direction-option" data-direction="1">Dir: 1</div>' +
                '</div>' +
                '</span>';
            
            badgeHtml = '<span class="badge ' + badgeClass + ' mr-1 mb-1">' + labelText + normalizedRoute + ' ' +
                directionDropdownHtml +
                ' <a href="#" class="text-dark remove-filter" data-type="station" data-index="' + index + '">×</a></span>';
        } else {
            badgeHtml = buildRemovableChip({
                label: badgeHtmlContent,
                badgeClass: badgeClass,
                data: { type: 'station', index: index },
                closeChar: '×'
            });
        }
        stationIdChips.push(badgeHtml);
    });
    const stationIdGroupHtml = buildOrGroup(stationIdChips);
    if (stationIdGroupHtml) finalGroupStrings.push(stationIdGroupHtml);

    let transportTypeChips = [];
    activeFilters.transportTypes.forEach(function(filter) {
        var displayName = filter.replace(/_/g, ' ').split(' ').map(word => word.charAt(0).toUpperCase() + word.slice(1)).join(' ');
        var chip = buildRemovableChip({
            label: 'Transport: ' + displayName,
            badgeClass: 'badge-success',
            data: { type: 'transportType', filter: filter }
        });
        transportTypeChips.push(chip);
    });
    const transportTypeGroupHtml = buildOrGroup(transportTypeChips);
    if (transportTypeGroupHtml) finalGroupStrings.push(transportTypeGroupHtml);

    // --- 6. Atlas Operator Filters ---
    const operatorGroupHtml = window.FilterChipUtils.generateOperatorChipsHtml(activeFilters.atlasOperators, { context: 'index' });
    if (operatorGroupHtml) finalGroupStrings.push(operatorGroupHtml);

    if(activeFilters.topN) {
        var chipTopN = buildRemovableChip({
            label: 'Top N Distances (' + activeFilters.topN + ')',
            badgeClass: 'badge-info',
            data: { type: 'topN', filter: 'topN' }
        });
        finalGroupStrings.push(chipTopN);
    }
    if(activeFilters.showDuplicatesOnly) {
        var dupChip = buildRemovableChip({
            label: 'Duplicate ATLAS',
            badgeClass: 'badge-secondary',
            data: { type: 'showDuplicatesOnly' }
        });
        finalGroupStrings.push(dupChip);
    }

    if (finalGroupStrings.length > 0) {
        var finalHtml = joinWithAnd(finalGroupStrings);
                container.html(finalHtml);
    } else {
        container.html('<span class="badge badge-secondary mr-1 mb-1">All entries</span>');
    }

}

// Function to toggle between standard filter input and route filter input based on filter type
function toggleFilterInputs() {
    var filterType = $('#filterTypeActual').val(); // Read from hidden input
    const stationFilterInput = $('#stationFilter');
    const stationFilterAddButton = $('#addStationFilterContainer');
    const routeFilterGroup = $('#routeFilterInput');

    if (filterType === 'route') {
        stationFilterInput.hide();
        stationFilterAddButton.hide();
        routeFilterGroup.css('display', 'flex'); // Use .css('display', 'flex') for input-group
        $('#routeIdFilter').focus(); // Focus route ID input when switched to route
    } else {
        stationFilterInput.show();
        stationFilterAddButton.css('display', 'flex'); // Use .css('display', 'flex') for input-group-append
        routeFilterGroup.hide();
        $('#stationFilter').focus(); // Focus standard input when switched
    }
}

// Function to add a standard filter from the text input
function addTextFilter() {
    var filterVal = $('#stationFilter').val().trim();
    var filterType = $('#filterTypeActual').val(); // Get type from hidden input
    
    if (filterVal) { // Allow adding if filterVal is not empty, even if it's already in activeFilters.station (the UI will prevent duplicates via alert)
        activeFilters.station.push(filterVal);
        activeFilters.stationTypes.push(filterType); // Store the type for this filter
        activeFilters.routeDirections.push(''); // No direction for standard filters
        $('#stationFilter').val(''); // Clear input field after adding
        updateFiltersUI();
        if (typeof window.invalidateViewportCache === 'function') window.invalidateViewportCache();
        loadDataForViewport(); // Load data based on all active filters
        updateHeaderSummary();

        // If the filter is for ATLAS Sloid or OSM Node, also center on it
        if (filterType === 'atlas' || filterType === 'osm') {
            fetchAndCenterSpecificStop(filterVal, filterType);
        }

    }
}

// Function to add a route+direction filter
function addRouteFilter() {
    var routeId = $('#routeIdFilter').val().trim();
    var direction = $('#directionFilter').val().trim();
    
    if (routeId) {
        // Check if this exact route+direction combination already exists
        var isDuplicate = false;
        for (var i = 0; i < activeFilters.station.length; i++) {
            if (activeFilters.stationTypes[i] === 'route' && 
                activeFilters.station[i] === routeId && 
                activeFilters.routeDirections[i] === direction) {
                isDuplicate = true;
                break;
            }
        }
        
        if (!isDuplicate) {
            activeFilters.station.push(routeId);
            activeFilters.stationTypes.push('route');
            activeFilters.routeDirections.push(direction);
            
            // Clear input fields after adding
            $('#routeIdFilter').val('');
            $('#directionFilter').val('');
            
            updateFiltersUI();
            if (typeof window.invalidateViewportCache === 'function') window.invalidateViewportCache();
            loadDataForViewport();
            updateHeaderSummary();
        } else {
            alert('This route and direction combination is already filtered.');
        }
    } else {
        alert('Please enter a Route ID.');
    }
}

function filterByStation(stopId, stopCategory) {
    var selectedStop = stopsById[stopId];
    if (!selectedStop) {
      alert("Stop data not found.");
      return;
    }
    
    // Always filter by UIC ref (station) when the "Filter by station" button is clicked
    var filterType = 'station';
    var filterValue = selectedStop.uic_ref || '';
    
    if (!filterValue) {
      alert("No UIC reference available for this stop.");
      return;
    }
    
    // Check if this filter is already applied
    var isDuplicate = false;
    for (var i = 0; i < activeFilters.station.length; i++) {
        if (activeFilters.stationTypes[i] === filterType && 
            activeFilters.station[i] === filterValue) {
            isDuplicate = true;
            break;
        }
    }
    
    if (isDuplicate) {
      alert("This filter is already applied: " + filterType + ": " + filterValue);
      return;
    }
    
    // Update the filter type dropdown for the UI (doesn't affect existing filters)
    $('#filterTypeActual').val(filterType);
    toggleFilterInputs();
    
    // Add the filter to the existing filters rather than replacing them
    activeFilters.station.push(filterValue);
    activeFilters.stationTypes.push(filterType);
    activeFilters.routeDirections.push('');
    activeFilters.filterType = filterType;
    
    updateFiltersUI();
    if (typeof window.invalidateViewportCache === 'function') window.invalidateViewportCache();
    loadDataForViewport();
    updateHeaderSummary();
}

// Update the activeFilters object from the UI inputs
function updateActiveFilters() {
    // Gather matching filters (stop type) - based on master checkboxes
    activeFilters.stopType = [];
    if ($('#masterMatchedCheckbox').is(':checked')) {
        activeFilters.stopType.push('matched');
    }
    if ($('#masterUnmatchedCheckbox').is(':checked')) {
        activeFilters.stopType.push('atlas_unmatched');
    }

    // Gather node type filters for matched stops
    activeFilters.nodeType = $('.filter-node-type:checked').map(function() {
        return this.value;
    }).get();
    
    // Gather transport type filters (New)
    activeFilters.transportTypes = $('.filter-transport-type:checked').map(function() {
        return this.value;
    }).get();
    
    // Combined Station or Stop filter: read text input (if any)
    var filterVal = $('#stationFilter').val().trim();
    // Don't replace, just clear if empty
    if (filterVal === '') {
        $('#stationFilter').val('');
    }
    
    // Get the filter type from the hidden input
    activeFilters.filterType = $('#filterTypeActual').val();
    
    // --- Matched Filters Logic ---
    activeFilters.matchedOptions = {
        allSelected: $('#masterMatchedCheckbox').is(':checked'),
        methods: {
            exact: $('#filterExact').is(':checked'),
            name: $('#filterName').is(':checked')
        },
        distanceMatching: {
            allSelected: $('#masterDistanceMatchingCheckbox').is(':checked'),
            stage1: $('#distanceMethodStage1').is(':checked'),
            stage2: $('#distanceMethodStage2').is(':checked'),
            stage3a: $('#distanceMethodStage3a').is(':checked'),
            stage3b: $('#distanceMethodStage3b').is(':checked')
        },
        routeMatching: {
            allSelected: $('#masterRouteMatchingCheckbox').is(':checked'),
            gtfs: $('#routeMethodGtfs').is(':checked'),
            hrdf: $('#routeMethodHrdf').is(':checked')
        }
    };

    // --- Unmatched Filters Logic ---
    activeFilters.unmatchedOptions = {
        allSelected: $('#masterUnmatchedCheckbox').is(':checked'),
        reasons: {
            noNearbyOSM: $('#filterNoNearbyOSM').is(':checked'),
            osmNearby: $('#filterOSMNearby').is(':checked') // Added new filter
        }
    };

    // --- Populate activeFilters.stopType and activeFilters.matchMethods ---
    activeFilters.stopType = [];
    activeFilters.matchMethods = [];

    let anyMatchedMethodActive = false;
    // Check standard matching methods
    for (const method in activeFilters.matchedOptions.methods) {
        if (activeFilters.matchedOptions.methods[method]) {
            activeFilters.matchMethods.push(method);
            anyMatchedMethodActive = true;
        }
    }
    // Check distance matching stages
    for (const stage in activeFilters.matchedOptions.distanceMatching) {
        if (stage !== 'allSelected' && activeFilters.matchedOptions.distanceMatching[stage]) {
            activeFilters.matchMethods.push('distance_matching_' + stage.replace('stage', '')); // e.g., distance_matching_1
            anyMatchedMethodActive = true;
        }
    }
    // Check route matching stages
    if (activeFilters.matchedOptions.routeMatching.gtfs) {
        activeFilters.matchMethods.push('route_gtfs');
        anyMatchedMethodActive = true;
    }
    if (activeFilters.matchedOptions.routeMatching.hrdf) {
        activeFilters.matchMethods.push('route_hrdf');
        anyMatchedMethodActive = true;
    }

    if (anyMatchedMethodActive) {
        if (!activeFilters.stopType.includes('matched')) {
            activeFilters.stopType.push('matched');
        }
    }

    // --- Populate stopType for Unmatched ---
    let anyUnmatchedReasonActive = false;
    if (activeFilters.unmatchedOptions.reasons.noNearbyOSM) {
        activeFilters.matchMethods.push('no_nearby_counterpart'); 
        anyUnmatchedReasonActive = true;
    }
    if (activeFilters.unmatchedOptions.reasons.osmNearby) { // Added new filter logic
        activeFilters.matchMethods.push('osm_within_50m'); 
        anyUnmatchedReasonActive = true;
    }
    // Add other unmatched reasons here if they push to matchMethods or directly influence stopType

    if (anyUnmatchedReasonActive) {
        if (!activeFilters.stopType.includes('atlas_unmatched')) {
            activeFilters.stopType.push('atlas_unmatched');
        }
    }
    
    // --- Top N Filter Logic (remains largely the same but check against anyMatchedMethodActive) ---
    if (activeFilters.topN && !anyMatchedMethodActive && !activeFilters.stopType.includes('matched')) {
        // If TopN was active but no matched methods are selected anymore, deactivate TopN
            activeFilters.topN = null;
        $('#toggleTopNBtn').html('<i class="fas fa-filter"></i> Activate Top N'); // Reset text
            topNLayer.clearLayers();
            $('#topNDistancesMessage').empty();
        }
    // Visibility of Top N container depends on if any matched context is active
    if (anyMatchedMethodActive || activeFilters.stopType.includes('matched')) {
        $('#topNDistancesContainer').show();
    } else {
        $('#topNDistancesContainer').hide();
        // Also deactivate TopN if its context disappears
        if (activeFilters.topN) {
            activeFilters.topN = null;
            $('#toggleTopNBtn').html('<i class="fas fa-filter"></i> Activate Top N');
            topNLayer.clearLayers();
            $('#topNDistancesMessage').empty();
        }
    }

    // Operator Mismatch and Show Duplicates (their values are read directly when needed)
    activeFilters.showDuplicatesOnly = $('#filterDuplicatesOnly').is(':checked');
    
    updateFiltersUI();
    
    // Invalidate viewport cache when filters change to ensure fresh data is fetched
    if (typeof window.invalidateViewportCache === 'function') {
        window.invalidateViewportCache();
    }
    
    loadDataForViewport();
    
    if(activeFilters.topN && (anyMatchedMethodActive || activeFilters.stopType.includes('matched'))) {
        loadTopNMatches();
    } else if (!activeFilters.topN) { // Ensure TopN layer is cleared if not active
        topNLayer.clearLayers();
        $('#topNDistancesMessage').empty();
    }
}

// Function to handle master checkbox logic
function setupMasterCheckbox(masterCheckboxSelector, childCheckboxSelector) {
    const masterCheckbox = $(masterCheckboxSelector);
    const childCheckboxes = $(childCheckboxSelector);

    // Master controls children
    masterCheckbox.on('change', function() {
        childCheckboxes.prop('checked', $(this).is(':checked')).trigger('change'); // Trigger change on children for other listeners
    });

    // Children control master
    childCheckboxes.on('change', function() {
        if (!$(this).is(':checked')) {
            masterCheckbox.prop('checked', false);
        }
        // Check if all children are checked
        else if (childCheckboxes.filter(':checked').length === childCheckboxes.length) {
            masterCheckbox.prop('checked', true);
        }
        // Propagate change up to higher-level master if exists (e.g., Distance/Route to Matched)
        const parentMasterSelector = masterCheckbox.closest('.nested-accordion-content').prev('.nested-accordion-header').find('.master-filter-checkbox').attr('id');
        if (parentMasterSelector) {
            // This logic is a bit tricky for deep nesting and might need refinement
            // For now, focus on direct parent-child relationship for master checkboxes
        }
    });
}

// Function to set direction for a route filter
function setRouteDirection(index, direction) {
    if (index >= 0 && index < activeFilters.routeDirections.length) {
        activeFilters.routeDirections[index] = direction;
        
        updateFiltersUI();
        if (typeof window.invalidateViewportCache === 'function') window.invalidateViewportCache();
        loadDataForViewport(); // Reload data with new direction filter
        updateHeaderSummary();
    }
}

// Function to toggle direction dropdown
function toggleDirectionDropdown(index) {
    var dropdown = $('.direction-dropdown[data-index="' + index + '"]');
    var options = dropdown.find('.direction-options');
    var arrow = dropdown.find('.direction-arrow');
    
    if (options.is(':visible')) {
        // Close dropdown
        options.slideUp(200);
        arrow.removeClass('rotated');
        dropdown.removeClass('open');
    } else {
        // Close any other open dropdowns first
        $('.direction-dropdown.open').each(function() {
            $(this).find('.direction-options').slideUp(200);
            $(this).find('.direction-arrow').removeClass('rotated');
            $(this).removeClass('open');
        });
        
        // Open this dropdown
        options.slideDown(200);
        arrow.addClass('rotated');
        dropdown.addClass('open');
    }
}

// Initialize filter-related event handlers
function initFilterEventHandlers() {
    // Remove filter badge and update filters
    $(document).on('click', '.remove-filter', function(e) {
        e.preventDefault();
        e.stopPropagation(); // Prevent event bubbling

        var type = $(this).data('type');
        var filterValue = $(this).data('filter'); 
        var index = $(this).data('index');
        var targetCheckboxId = $(this).data('target');

        let needsManualUpdateCall = false;

        if (targetCheckboxId) {
            // This covers most checkbox-driven filters linked by data-target
            // (masterMatched, specificMatch, masterDistance, specificDistance, masterRoute, specificRoute, specificUnmatched)
            if (type === 'specificRoute') {
                $(targetCheckboxId).prop('checked', false).trigger('change');
            } else {
                $(targetCheckboxId).prop('checked', false).trigger('change');
            }
        } else {
            // Handle types that don't use data-target but have corresponding UI elements or direct activeFilters manipulation
            switch (type) {
                case 'nodeType':
                    $('.filter-node-type[value="' + filterValue + '"]').prop('checked', false).trigger('change');
                    break;
                case 'transportType':
                    $('.filter-transport-type[value="' + filterValue + '"]').prop('checked', false).trigger('change');
                    break;
                case 'atlasOperator':
                    // Remove from activeFilters.atlasOperators array
                    const operatorIndex = activeFilters.atlasOperators.indexOf(filterValue);
                    if (operatorIndex > -1) {
                        activeFilters.atlasOperators.splice(operatorIndex, 1);
                    }
                    // Update the operator dropdown if it exists
                    if (window.operatorDropdown) {
                        window.operatorDropdown.setSelection(activeFilters.atlasOperators);
                    }
                    needsManualUpdateCall = true;
                    break;
                case 'station': // For UIC, Sloid, OSM Node ID, Route ID filters
                    if (index !== undefined && index >= 0 && index < activeFilters.station.length) {
                        activeFilters.station.splice(index, 1);
                        activeFilters.stationTypes.splice(index, 1);
                        activeFilters.routeDirections.splice(index, 1);
                    }
                    needsManualUpdateCall = true;
                    break;
                case 'topN':
                    activeFilters.topN = null;
                    $('#topDistance').val(10); // Reset input field as well
                    $('#toggleTopNBtn').html('<i class="fas fa-filter"></i> Activate Top N');
                    // updateActiveFilters will handle clearing layers via loadDataForViewport or loadTopNMatches
                    needsManualUpdateCall = true;
                    break;
                case 'showDuplicatesOnly':
                    $('#filterDuplicatesOnly').prop('checked', false).trigger('change');
                    break;
                // Add other special cases if any are not covered by data-target or a standard checkbox classes
                default:
                    // If a type is missed, it might require manual update or a new case.
                    // For safety, if no specific handling and no targetCheckboxId, consider manual update.
                    // However, most filter chips should have a data-target or fall into one of these categories.
                    console.warn('Unhandled filter removal type or missing data-target:', type);
                    needsManualUpdateCall = true; 
            }
        }

        if (needsManualUpdateCall) {
            updateActiveFilters(); // This calls updateFiltersUI and loadDataForViewport/loadTopNMatches
            updateHeaderSummary();
        }
        // If .trigger('change') was called on a checkbox, updateActiveFilters is invoked by that checkbox's change handler.
    });

    // Legacy direction toggle handler - replaced by dropdown handlers

    // Direction dropdown handler for route filters
    $(document).on('click', '.direction-dropdown', function(e) {
        e.preventDefault();
        e.stopPropagation(); // Prevent event bubbling

        var index = $(this).data('index');
        toggleDirectionDropdown(index);
    });

    // Direction option selection handler
    $(document).on('click', '.direction-option', function(e) {
        e.preventDefault();
        e.stopPropagation(); // Prevent event bubbling

        var direction = $(this).data('direction');
        var dropdown = $(this).closest('.direction-dropdown');
        var index = dropdown.data('index');
        
        // Set the new direction
        setRouteDirection(index, direction);
        
        // Close the dropdown
        dropdown.find('.direction-options').slideUp(200);
        dropdown.find('.direction-arrow').removeClass('rotated');
        dropdown.removeClass('open');
    });

    // Close direction dropdowns when clicking outside
    $(document).on('click', function(e) {
        if (!$(e.target).closest('.direction-dropdown').length) {
            $('.direction-dropdown.open').each(function() {
                $(this).find('.direction-options').slideUp(200);
                $(this).find('.direction-arrow').removeClass('rotated');
                $(this).removeClass('open');
            });
        }
    });

    // Attach change handlers to filter checkboxes and input elements.
    $('.master-filter-checkbox, .filter-node-type, .filter-match-method, .filter-distance-method, .filter-route-method, .filter-unmatched-method, .filter-duplicates-only, .filter-transport-type').on('change', function() {
        updateActiveFilters();
        updateHeaderSummary(); 
    });

    // Setup Add button for station filter
    $('#addStationFilter').on('click', function(e) {
        e.preventDefault();
        addTextFilter();
    });

    // Setup Add button for route filter
    $('#addRouteFilter').on('click', function(e) {
        e.preventDefault();
        addRouteFilter();
    });

    // Also allow adding by pressing Enter in the text inputs
    $('#stationFilter').on('keypress', function(e) {
        if (e.which === 13) { // Enter key
            e.preventDefault();
            addTextFilter();
        }
    });

    $('#routeIdFilter, #directionFilter').on('keypress', function(e) {
        if (e.which === 13) { // Enter key
            e.preventDefault();
            addRouteFilter();
        }
    });

    // Toggle button for Top N filter
    $('#toggleTopNBtn').on('click', function() {
        if(activeFilters.topN) {
            activeFilters.topN = null;
            $(this).html('<i class="fas fa-filter"></i> Activate Top N'); 
            // updateActiveFilters will handle layer clearing and data reload
        } else {
            var n = parseInt($('#topDistance').val());
            if(n > 0) {
                activeFilters.topN = n;
                $(this).html('<i class="fas fa-times-circle"></i> Remove Top N');
            } else {
                alert("Please enter a valid number for Top N filter.");
                return; // Don't proceed if N is invalid
            }
        }
        updateActiveFilters(); // Update based on new topN state (or null)
        updateHeaderSummary(); 
    });

    // Setup master checkboxes (ensure this is called only once)
    setupMasterCheckbox('#masterMatchedCheckbox', '#collapseMatchedStopType .form-check-input');
    setupMasterCheckbox('#masterUnmatchedCheckbox', '#collapseUnmatchedStopType .form-check-input');
    setupMasterCheckbox('#masterDistanceMatchingCheckbox', '#collapseDistanceMatching .form-check-input');
    setupMasterCheckbox('#masterRouteMatchingCheckbox', '#collapseRouteMatching .form-check-input');

    // Special handling for sub-masters updating the main master (#masterMatchedCheckbox)
    $('#masterDistanceMatchingCheckbox, #masterRouteMatchingCheckbox').on('change', function() {
        const allMatchedChildren = $('#collapseMatchedStopType .form-check-input:not(#masterDistanceMatchingCheckbox, #masterRouteMatchingCheckbox)');
        const allSubMastersAndChildrenChecked = 
            allMatchedChildren.filter(':checked').length === allMatchedChildren.length &&
            $('#masterDistanceMatchingCheckbox').is(':checked') &&
            $('#masterRouteMatchingCheckbox').is(':checked');
        
        $('#masterMatchedCheckbox').prop('checked', allSubMastersAndChildrenChecked);
        // No .trigger('change') on #masterMatchedCheckbox here to avoid potential loops if not careful,
        // as this is a derived state. The main change handler for all checkboxes will call updateActiveFilters.
    });
} 