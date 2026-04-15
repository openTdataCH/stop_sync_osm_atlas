// Filter Management Module
// This module handles all filter-related functionality

// Unified global filters object - Initialized to a "no filters active" state
var activeFilters = {
    station: [],
    stationTypes: [],
    routeDirections: [],
    stopType: [],
    matchMethods: [],
    atlasOperators: [],
    matchedOptions: {
        allSelected: true,
        methods: { exact: false, name: false },
        distanceMatching: { allSelected: false, stage1: false, stage2: false, stage3a: false, stage3b: false },
        routeMatching: { allSelected: false, gtfs: false }
    },
    unmatchedOptions: {
        allSelected: true,
        reasons: { noNearbyOSM: false, osmNearby: false }
    },
    transportTypes: [],
    topN: null,
    showDuplicatesOnly: false,
    osmGroups: []
};

const SMART_SEARCH_VALIDATION_MESSAGE = 'Allowed formats: UIC (e.g. 8503000), ATLAS SLOID (ch:1:sloid:...), OSM node id (123456789), route (11-T-jXX-1 dir:0)';
const MATCHED_METHOD_CHECKBOX_SELECTORS = [
    '#filterExact',
    '#filterName',
    '#distanceMethodTrio',
    '#distanceMethodStage1',
    '#distanceMethodStage2',
    '#distanceMethodStage3a',
    '#distanceMethodStage3b',
    '#routeMethodGtfs'
];
const DISTANCE_METHOD_CHECKBOX_SELECTORS = [
    '#distanceMethodTrio',
    '#distanceMethodStage1',
    '#distanceMethodStage2',
    '#distanceMethodStage3a',
    '#distanceMethodStage3b'
];
const ROUTE_METHOD_CHECKBOX_SELECTORS = [
    '#routeMethodGtfs'
];

let isBulkCheckboxSyncInProgress = false;

function areAllFilterSelectorsChecked(selectors) {
    return selectors.length > 0 && selectors.every(function (selector) {
        return $(selector).is(':checked');
    });
}

function formatOsmGroupTypeLabel(groupType) {
    const labels = {
        osm_pair_uic: 'UIC-based pairs',
        osm_pair_uic_equal_15m: 'UIC perfect-count pairs (15m)',
        osm_pair_name: 'Name-based pairs',
        osm_pair_name_equal_15m: 'Name perfect-count pairs (15m)',
        osm_pair_tram: 'Tram pairs',
        osm_pair_tram_equal_15m: 'Tram perfect-count pairs (15m)',
        osm_trio: 'OSM trio'
    };

    return labels[groupType] || groupType;
}

function formatTransportTypeLabel(filter) {
    const labels = {
        non_node_osm_stop: 'Non-node OSM stops'
    };
    return labels[filter] || filter.replace(/_/g, ' ').split(' ').map(function (word) {
        return word.charAt(0).toUpperCase() + word.slice(1);
    }).join(' ');
}

function getSelectedMatchedMethodFiltersFromState() {
    const selectedMethods = [];

    if (!activeFilters.matchedOptions) {
        return selectedMethods;
    }

    Object.keys(activeFilters.matchedOptions.methods).forEach(function (method) {
        if (activeFilters.matchedOptions.methods[method]) {
            selectedMethods.push(method);
        }
    });

    Object.keys(activeFilters.matchedOptions.distanceMatching).forEach(function (stage) {
        if (stage !== 'allSelected' && activeFilters.matchedOptions.distanceMatching[stage]) {
            selectedMethods.push('distance_matching_' + stage.replace('stage', ''));
        }
    });

    if (activeFilters.matchedOptions.routeMatching.gtfs) {
        selectedMethods.push('route_gtfs');
    }

    return selectedMethods;
}

function getSelectedUnmatchedReasonFiltersFromState() {
    const selectedReasons = [];

    if (!activeFilters.unmatchedOptions) {
        return selectedReasons;
    }

    if (activeFilters.unmatchedOptions.reasons.noNearbyOSM) {
        selectedReasons.push('no_nearby_counterpart');
    }
    if (activeFilters.unmatchedOptions.reasons.osmNearby) {
        selectedReasons.push('osm_within_50m');
    }

    return selectedReasons;
}

function isMatchedScopeActive() {
    return activeFilters.stopType.includes('matched') || getSelectedMatchedMethodFiltersFromState().length > 0;
}

function isAtlasUnmatchedScopeActive() {
    return activeFilters.stopType.includes('atlas_unmatched') || getSelectedUnmatchedReasonFiltersFromState().length > 0;
}

function getActiveFilterCount() {
    let count = 0;
    const showMatchedFilters = isMatchedScopeActive();
    const showUnmatchedAtlasFilters = isAtlasUnmatchedScopeActive();

    if (activeFilters.matchedOptions && showMatchedFilters) {
        if (activeFilters.matchedOptions.allSelected) {
            count += 1;
        } else {
            Object.keys(activeFilters.matchedOptions.methods).forEach(function (method) {
                if (activeFilters.matchedOptions.methods[method]) count += 1;
            });

            if (activeFilters.matchedOptions.distanceMatching.allSelected) {
                count += 1;
            } else {
                Object.keys(activeFilters.matchedOptions.distanceMatching).forEach(function (stage) {
                    if (stage !== 'allSelected' && activeFilters.matchedOptions.distanceMatching[stage]) count += 1;
                });
            }

            if (activeFilters.matchedOptions.routeMatching.allSelected) {
                count += 1;
            } else {
                if (activeFilters.matchedOptions.routeMatching.gtfs) count += 1;
            }
        }
    }

    if (activeFilters.unmatchedOptions && showUnmatchedAtlasFilters) {
        if (activeFilters.unmatchedOptions.allSelected) {
            count += 1;
        } else {
            if (activeFilters.unmatchedOptions.reasons.noNearbyOSM) count += 1;
            if (activeFilters.unmatchedOptions.reasons.osmNearby) count += 1;
        }
    }

    if (activeFilters.stopType.includes('osm_unmatched')) count += 1;

    count += activeFilters.station.length;
    count += activeFilters.transportTypes.length;
    count += activeFilters.atlasOperators.length;

    if (activeFilters.osmGroups && activeFilters.osmGroups.length > 0) {
        count += activeFilters.osmGroups.includes('all') ? 1 : activeFilters.osmGroups.length;
    }

    if (activeFilters.topN) count += 1;
    if (activeFilters.showDuplicatesOnly) count += 1;

    return count;
}

function getActiveFilterCountText() {
    const count = getActiveFilterCount();
    return count + ' filter' + (count !== 1 ? 's' : '') + ' active';
}

function showSmartSearchError(message, showHint = true) {
    const errorEl = $('#smartSearchError');
    if (!errorEl.length) return;

    if (message) {
        const docLink = ' <a href="/docs/5.3 Filters and Search logic" class="smart-search-doc-link" target="_blank" rel="noopener noreferrer" title="Open docs"><i class="fas fa-info-circle"></i></a>';
        errorEl.html($('<span>').text(message).html() + docLink).removeClass('d-none');
        if (showHint) {
            $('#smartSearchHint').removeClass('d-none');
        } else {
            // Keep hint hidden if it's not relevant to this error (like "not found")
            $('#smartSearchHint').addClass('d-none');
        }
    } else {
        errorEl.text('').addClass('d-none');
    }
}

function parseSmartSearchInput(rawValue) {
    const value = rawValue.trim();

    if (!value) {
        return { error: 'Enter a search value.' };
    }

    if (/^ch:\d+:sloid:[^\s]+$/i.test(value)) {
        return { kind: 'atlas', value: value };
    }

    const uicMatch = value.match(/^85\d{5}(?::\d+)?$/);
    if (uicMatch) {
        return { kind: 'station', value: value };
    }

    const digitMatch = value.match(/^(?:node\/)?(\d+)$/i);
    if (digitMatch) {
        return { kind: 'osm', value: digitMatch[1] };
    }

    // For routes, either they explicitly start with "route:" followed by any non-whitespace characters
    // OR they look implicitly like a route ID with alphanumeric chunks separated by single dashes (e.g. 11-T-j25-1).
    const routeMatch = value.match(/^(?:route:([^\s]+)|([a-zA-Z0-9]+(?:-[a-zA-Z0-9]+)+))(?:\s+dir:(0|1))?$/i);
    if (routeMatch) {
        const routeId = (routeMatch[1] || routeMatch[2]).trim();
        if (!routeId) {
            return { error: SMART_SEARCH_VALIDATION_MESSAGE };
        }

        return {
            kind: 'route',
            value: routeId,
            direction: routeMatch[3] || ''
        };
    }

    return { error: SMART_SEARCH_VALIDATION_MESSAGE };
}

function addSearchToken(token) {
    let filterType = token.kind;
    let filterValue = token.value;
    let direction = token.direction || '';

    if (filterType === 'route') {
        for (var i = 0; i < activeFilters.station.length; i++) {
            if (activeFilters.stationTypes[i] === 'route' &&
                activeFilters.station[i] === filterValue &&
                activeFilters.routeDirections[i] === direction) {
                alert('This route and direction combination is already filtered.');
                return;
            }
        }
    } else {
        for (var j = 0; j < activeFilters.station.length; j++) {
            if (activeFilters.stationTypes[j] === filterType && activeFilters.station[j] === filterValue) {
                alert('This filter is already applied: ' + filterValue);
                return;
            }
        }
    }

    activeFilters.station.push(filterValue);
    activeFilters.stationTypes.push(filterType);
    activeFilters.routeDirections.push(direction);

    // Call the backend first to see if the entry exists
    fetchAndCenterSpecificStop(filterValue, filterType)
        .then(function () {
            // Update UI only if the stop was found successfully
            updateFiltersUI();
            if (typeof window.invalidateViewportCache === 'function') window.invalidateViewportCache();
            loadDataForViewport();
            updateHeaderSummary();
        })
        .catch(function (errorMessage) {
            // Revert the filter addition if not found
            activeFilters.station.pop();
            activeFilters.stationTypes.pop();
            activeFilters.routeDirections.pop();

            showSmartSearchError(errorMessage, false);
        });
}

function submitSmartSearch() {
    const input = $('#smartSearchInput');
    const parsed = parseSmartSearchInput(input.val() || '');

    if (parsed.error) {
        showSmartSearchError(parsed.error, true);
        return;
    }

    showSmartSearchError('');
    addSearchToken(parsed);

    // We will let addSearchToken clear the input if it succeeds or keep it if it fails
    // However since addSearchToken is now async, we don't clear it here directly
    // Let's clear it conditionally or let the promise handle it.
    // Actually, it's safer to clear it, but maybe just leave it so they can fix typose?
    // Let's clear it if the user hit enter, assuming they want to proceed.
    input.val('');
}

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
    switch (currentDirection) {
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
    let finalGroupStrings = [];
    const buildOrGroup = window.FilterChipUtils.buildOrGroupHtml;
    const joinWithAnd = window.FilterChipUtils.joinWithAndHtml;
    const buildRemovableChip = window.FilterChipUtils.buildRemovableChip;
    const showMatchedFilters = isMatchedScopeActive();
    const showUnmatchedAtlasFilters = isAtlasUnmatchedScopeActive();

    let matchedDisplayString = '';
    if (activeFilters.matchedOptions && showMatchedFilters) {
        if (activeFilters.matchedOptions.allSelected) {
            matchedDisplayString = buildRemovableChip({
                label: 'Matched Stops',
                badgeClass: 'filter-chip-matched',
                data: { type: 'masterMatched', target: '#masterMatchedCheckbox' }
            });
        } else {
            let matchedSubConditionStrings = [];
            let specificMethodChips = [];
            for (const method in activeFilters.matchedOptions.methods) {
                if (activeFilters.matchedOptions.methods[method]) {
                    var dName = method.charAt(0).toUpperCase() + method.slice(1);
                    specificMethodChips.push(buildRemovableChip({
                        label: 'Match: ' + dName, badgeClass: 'filter-chip-matched',
                        data: { type: 'specificMatch', target: '#filter' + dName }
                    }));
                }
            }
            const smGrp = buildOrGroup(specificMethodChips);
            if (smGrp) matchedSubConditionStrings.push(smGrp);

            if (activeFilters.matchedOptions.distanceMatching.allSelected) {
                matchedSubConditionStrings.push(buildRemovableChip({ label: 'Distance Match: All Stages', badgeClass: 'filter-chip-matched', data: { type: 'masterDistance', target: '#masterDistanceMatchingCheckbox' } }));
            } else {
                let distanceStageChips = [];
                for (const stage in activeFilters.matchedOptions.distanceMatching) {
                    if (stage !== 'allSelected' && activeFilters.matchedOptions.distanceMatching[stage]) {
                        let stageNum = stage.replace('stage', '');
                        var dLabel = 'Dist. Stage ' + stageNum;
                        let target = '#distanceMethodStage' + stageNum;
                        if (stage === 'trio') {
                            dLabel = 'Dist: Trio distance';
                            target = '#distanceMethodTrio';
                        }
                        if (stage === 'stage1') dLabel = 'Dist: Group Proximity';
                        if (stage === 'stage2') dLabel = 'Dist: Local Ref Match';
                        if (stage === 'stage3a') dLabel = 'Dist: Single Candidate';
                        if (stage === 'stage3b') dLabel = 'Dist: Relative Distance';
                        distanceStageChips.push(buildRemovableChip({
                            label: dLabel, badgeClass: 'filter-chip-matched', data: { type: 'specificDistance', target: target }
                        }));
                    }
                }
                const distGrp = buildOrGroup(distanceStageChips);
                if (distGrp) matchedSubConditionStrings.push(distGrp);
            }

            if (activeFilters.matchedOptions.routeMatching.allSelected) {
                matchedSubConditionStrings.push(buildRemovableChip({ label: 'Route Match: All', badgeClass: 'filter-chip-matched', data: { type: 'masterRoute', target: '#masterRouteMatchingCheckbox' } }));
            } else {
                let routeStageChips = [];
                if (activeFilters.matchedOptions.routeMatching.gtfs) {
                    routeStageChips.push(buildRemovableChip({ label: 'Route: GTFS', badgeClass: 'filter-chip-matched', data: { type: 'specificRoute', target: '#routeMethodGtfs' } }));
                }
                const rGrp = buildOrGroup(routeStageChips);
                if (rGrp) matchedSubConditionStrings.push(rGrp);
            }

            if (matchedSubConditionStrings.length > 0) {
                matchedDisplayString = joinWithAnd(matchedSubConditionStrings);
                if (matchedSubConditionStrings.length > 1) matchedDisplayString = '( ' + matchedDisplayString + ' )';
            }
        }
    }

    let unmatchedAtlasString = '';
    if (activeFilters.unmatchedOptions && showUnmatchedAtlasFilters) {
        if (activeFilters.unmatchedOptions.allSelected) {
            unmatchedAtlasString = buildRemovableChip({ label: 'Unmatched ATLAS', badgeClass: 'filter-chip-unmatched', data: { type: 'masterUnmatchedAtlas', target: '#masterUnmatchedAtlasCheckbox' } });
        } else {
            let reasonChips = [];
            if (activeFilters.unmatchedOptions.reasons.noNearbyOSM) {
                reasonChips.push(buildRemovableChip({ label: 'Unmatched ATLAS: No OSM < 50m', badgeClass: 'filter-chip-unmatched', data: { type: 'specificUnmatched', target: '#filterNoNearbyOSM' } }));
            }
            if (activeFilters.unmatchedOptions.reasons.osmNearby) {
                reasonChips.push(buildRemovableChip({ label: 'Unmatched ATLAS: OSM < 50m', badgeClass: 'filter-chip-unmatched', data: { type: 'specificUnmatched', target: '#filterOSMNearby' } }));
            }
            unmatchedAtlasString = buildOrGroup(reasonChips);
        }
    }

    let unmatchedOsmString = '';
    if (activeFilters.stopType.includes('osm_unmatched')) {
        unmatchedOsmString = buildRemovableChip({ label: 'Unmatched OSM', badgeClass: 'filter-chip-unmatched', data: { type: 'masterUnmatchedOsm', target: '#masterUnmatchedOsmCheckbox' } });
    }

    let visibilityChips = [];
    if (matchedDisplayString) visibilityChips.push(matchedDisplayString);
    if (unmatchedAtlasString) visibilityChips.push(unmatchedAtlasString);
    if (unmatchedOsmString) visibilityChips.push(unmatchedOsmString);
    if (visibilityChips.length > 0) finalGroupStrings.push(buildOrGroup(visibilityChips));

    let stationIdChips = [];
    activeFilters.station.forEach(function (filter, index) {
        var filterType = activeFilters.stationTypes[index];
        var direction = activeFilters.routeDirections[index] || '';
        var labelText = '', badgeClass = '', badgeHtmlContent = '';
        switch (filterType) {
            case 'atlas': labelText = 'ATLAS SloidID: '; badgeClass = 'filter-chip-atlas'; badgeHtmlContent = labelText + filter; break;
            case 'osm': labelText = 'OSM Node ID: '; badgeClass = 'filter-chip-osm'; badgeHtmlContent = labelText + filter; break;
            case 'route':
                var normalizedRoute = normalizeRouteIdForDisplay(filter);
                var directionDisplay = formatDirectionDisplay(direction);
                labelText = 'Route: '; badgeClass = 'filter-chip-secondary'; badgeHtmlContent = labelText + normalizedRoute + ', ' + directionDisplay;
                break;
            case 'station':
            default: labelText = 'UIC: '; badgeClass = 'filter-chip-secondary'; badgeHtmlContent = labelText + filter; break;
        }
        var badgeHtml;
        if (filterType === 'route') {
            var currentDirection = activeFilters.routeDirections[index] || '';
            var directionDropdownHtml = '<span class="direction-dropdown" data-index="' + index + '" data-current="' + currentDirection + '">' +
                '<span class="direction-current">' + directionDisplay + '</span><i class="fas fa-chevron-down direction-arrow"></i>' +
                '<div class="direction-options" style="display: none;"><div class="direction-option" data-direction="">Both</div><div class="direction-option" data-direction="0">Dir: 0</div><div class="direction-option" data-direction="1">Dir: 1</div></div></span>';
            badgeHtml = '<span class="badge filter-chip-badge ' + badgeClass + ' me-1 mb-1">' + labelText + normalizedRoute + ' ' + directionDropdownHtml + ' <a href="#" class="remove-filter" data-type="station" data-index="' + index + '">×</a></span>';
        } else {
            badgeHtml = buildRemovableChip({ label: badgeHtmlContent, badgeClass: badgeClass, data: { type: 'station', index: index }, closeChar: '×' });
        }
        stationIdChips.push(badgeHtml);
    });
    const stationIdGroupHtml = buildOrGroup(stationIdChips);
    if (stationIdGroupHtml) finalGroupStrings.push(stationIdGroupHtml);

    let transportTypeChips = [];
    activeFilters.transportTypes.forEach(function (filter) {
        var dName = formatTransportTypeLabel(filter);
        transportTypeChips.push(buildRemovableChip({ label: dName, badgeClass: 'filter-chip-osm', data: { type: 'transportType', filter: filter } }));
    });
    const transportTypeGroupHtml = buildOrGroup(transportTypeChips);
    if (transportTypeGroupHtml) finalGroupStrings.push(transportTypeGroupHtml);

    const operatorGroupHtml = window.FilterChipUtils.generateOperatorChipsHtml(activeFilters.atlasOperators, { context: 'index' });
    if (operatorGroupHtml) finalGroupStrings.push(operatorGroupHtml);

    if (activeFilters.osmGroups && activeFilters.osmGroups.length > 0) {
        if (activeFilters.osmGroups.includes('all')) {
            finalGroupStrings.push(buildRemovableChip({ label: 'OSM Groups: All', badgeClass: 'filter-chip-osm', data: { type: 'osmGroup', target: '#filterOsmGroup' } }));
        } else {
            let groupChips = [];
            activeFilters.osmGroups.forEach(function (g) {
                groupChips.push(buildRemovableChip({ label: 'OSM Group: ' + formatOsmGroupTypeLabel(g), badgeClass: 'filter-chip-osm', data: { type: 'specificOsmGroup', filter: g } }));
            });
            const grpHtml = buildOrGroup(groupChips);
            if (grpHtml) finalGroupStrings.push(grpHtml);
        }
    }

    if (activeFilters.topN) finalGroupStrings.push(buildRemovableChip({ label: 'Top N Distances (' + activeFilters.topN + ')', badgeClass: 'filter-chip-secondary', data: { type: 'topN', filter: 'topN' } }));
    if (activeFilters.showDuplicatesOnly) finalGroupStrings.push(buildRemovableChip({ label: 'Duplicate ATLAS', badgeClass: 'filter-chip-atlas', data: { type: 'showDuplicatesOnly' } }));

    if (finalGroupStrings.length > 0) {
        if (getActiveFilterCount() === 1) {
            container.html('<span class="header-summary__filters-prefix">Filter:</span>' + joinWithAnd(finalGroupStrings));
        } else {
            container.html(joinWithAnd(finalGroupStrings));
        }
    }
    else container.html('<span class="badge filter-chip-badge filter-chip-secondary me-1 mb-1">All entries</span>');

    container.attr('data-active-filter-count', String(getActiveFilterCount()));
}

function clearAllFilters() {
    // Uncheck all filter checkboxes
    $('#masterMatchedCheckbox').prop('checked', false);
    $('#masterUnmatchedAtlasCheckbox').prop('checked', false);
    $('#masterUnmatchedOsmCheckbox').prop('checked', false);
    $('#filterDuplicatesOnly').prop('checked', false);
    $('.filter-match-method, .filter-distance-method, .filter-route-method').prop('checked', false);
    $('#masterDistanceMatchingCheckbox, #masterRouteMatchingCheckbox').prop('checked', false);
    $('.filter-unmatched-method').prop('checked', false);
    $('.filter-transport-type').prop('checked', false);
    $('.filter-osm-group, .filter-osm-group-type').prop('checked', false);

    // Clear array-based filters
    activeFilters.station = [];
    activeFilters.stationTypes = [];
    activeFilters.routeDirections = [];

    // Clear operators and reset dropdown
    activeFilters.atlasOperators = [];
    if (window.operatorDropdown) {
        window.operatorDropdown.setSelection([]);
    }

    // Clear top N
    activeFilters.topN = null;
    $('#topDistance').val(10);
    $('#toggleTopNBtn').html('<i class="fas fa-filter"></i> Activate Top N');
    if (typeof topNLayer !== 'undefined') topNLayer.clearLayers();
    $('#topNDistancesMessage').empty();

    updateActiveFilters();
    updateHeaderSummary();
}

window.getActiveFilterCount = getActiveFilterCount;
window.getActiveFilterCountText = getActiveFilterCountText;
window.clearAllFilters = clearAllFilters;
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

    // Add the filter to the existing filters rather than replacing them
    activeFilters.station.push(filterValue);
    activeFilters.stationTypes.push(filterType);
    activeFilters.routeDirections.push('');

    updateFiltersUI();
    if (typeof window.invalidateViewportCache === 'function') window.invalidateViewportCache();
    loadDataForViewport();
    updateHeaderSummary();
}

// Update the activeFilters object from the UI inputs
function updateActiveFilters() {
    var allDistanceMethodsSelected = areAllFilterSelectorsChecked(DISTANCE_METHOD_CHECKBOX_SELECTORS);
    var allRouteMethodsSelected = areAllFilterSelectorsChecked(ROUTE_METHOD_CHECKBOX_SELECTORS);

    // Note: master checkbox sync is handled by setupMasterCheckbox() bidirectional handlers.
    // Do NOT force-sync here — it races with setupMasterCheckbox's change propagation.

    activeFilters.stopType = [];
    if ($('#masterMatchedCheckbox').is(':checked')) activeFilters.stopType.push('matched');
    if ($('#masterUnmatchedAtlasCheckbox').is(':checked')) activeFilters.stopType.push('atlas_unmatched');
    if ($('#masterUnmatchedOsmCheckbox').is(':checked')) activeFilters.stopType.push('osm_unmatched');

    activeFilters.showDuplicatesOnly = $('#filterDuplicatesOnly').is(':checked');
    activeFilters.transportTypes = $('.filter-transport-type:checked').map(function () { return this.value; }).get();

    activeFilters.osmGroups = [];
    var osmGroupMasterChecked = $('#filterOsmGroup').is(':checked');
    var selectedOsmGroupTypes = $('.filter-osm-group-type:checked').map(function () { return this.value; }).get();
    var anyOsmGroupTypeChecked = selectedOsmGroupTypes.length > 0;
    if (osmGroupMasterChecked) {
        activeFilters.osmGroups = ['all'];
    } else if (anyOsmGroupTypeChecked) {
        activeFilters.osmGroups = selectedOsmGroupTypes;
    }

    activeFilters.matchedOptions = {
        allSelected: $('#masterMatchedCheckbox').is(':checked'),
        methods: {
            exact: $('#filterExact').is(':checked'),
            name: $('#filterName').is(':checked')
        },
        distanceMatching: {
            allSelected: allDistanceMethodsSelected,
            trio: $('#distanceMethodTrio').is(':checked'),
            stage1: $('#distanceMethodStage1').is(':checked'),
            stage2: $('#distanceMethodStage2').is(':checked'),
            stage3a: $('#distanceMethodStage3a').is(':checked'),
            stage3b: $('#distanceMethodStage3b').is(':checked')
        },
        routeMatching: {
            allSelected: allRouteMethodsSelected,
            gtfs: $('#routeMethodGtfs').is(':checked')
        }
    };

    activeFilters.unmatchedOptions = {
        allSelected: $('#masterUnmatchedAtlasCheckbox').is(':checked'),
        reasons: {
            noNearbyOSM: $('#filterNoNearbyOSM').is(':checked'),
            osmNearby: $('#filterOSMNearby').is(':checked')
        }
    };

    activeFilters.matchMethods = [];
    const selectedMatchedMethods = getSelectedMatchedMethodFiltersFromState();
    const selectedUnmatchedReasons = getSelectedUnmatchedReasonFiltersFromState();
    const hasMatchedScope = activeFilters.matchedOptions.allSelected || selectedMatchedMethods.length > 0;

    if (!activeFilters.matchedOptions.allSelected) {
        activeFilters.matchMethods = activeFilters.matchMethods.concat(selectedMatchedMethods);
    }
    if (!activeFilters.unmatchedOptions.allSelected) {
        activeFilters.matchMethods = activeFilters.matchMethods.concat(selectedUnmatchedReasons);
    }

    if (activeFilters.topN && !hasMatchedScope) {
        activeFilters.topN = null;
        $('#toggleTopNBtn').html('<i class="fas fa-filter"></i> Activate Top N');
        if (typeof topNLayer !== 'undefined') topNLayer.clearLayers();
        $('#topNDistancesMessage').empty();
    }
    if (hasMatchedScope) {
        $('#topNDistancesContainer').show();
    } else {
        $('#topNDistancesContainer').hide();
        if (activeFilters.topN) {
            activeFilters.topN = null;
            $('#toggleTopNBtn').html('<i class="fas fa-filter"></i> Activate Top N');
            if (typeof topNLayer !== 'undefined') topNLayer.clearLayers();
            $('#topNDistancesMessage').empty();
        }
    }

    updateFiltersUI();
    if (typeof window.invalidateViewportCache === 'function') {
        window.invalidateViewportCache();
    }
    loadDataForViewport();
    if (activeFilters.topN && hasMatchedScope) {
        loadTopNMatches();
    } else if (!activeFilters.topN && typeof topNLayer !== 'undefined') {
        topNLayer.clearLayers();
        $('#topNDistancesMessage').empty();
    }
}
// Function to handle master checkbox logic
function setupMasterCheckbox(masterCheckboxSelector, childCheckboxSelector) {
    const masterCheckbox = $(masterCheckboxSelector);
    const childCheckboxes = $(childCheckboxSelector);

    // Master controls children
    masterCheckbox.on('change', function () {
        isBulkCheckboxSyncInProgress = true;
        try {
            childCheckboxes.prop('checked', $(this).is(':checked')).trigger('change'); // Trigger child listeners while suppressing expensive bulk reloads
        } finally {
            isBulkCheckboxSyncInProgress = false;
        }
    });

    // Children control master
    childCheckboxes.on('change', function () {
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
        $('.direction-dropdown.open').each(function () {
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
    $(document).on('click', '.remove-filter', function (e) {
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
                case 'osmGroup':
                    $('#filterOsmGroup').prop('checked', false).trigger('change');
                    break;
                case 'specificOsmGroup':
                    var remainingOsmGroupTypes = $('.filter-osm-group-type:checked').not('[value="' + filterValue + '"]');
                    if (remainingOsmGroupTypes.length === 0) {
                        $('#filterOsmGroup').prop('checked', false).trigger('change');
                    } else {
                        $('.filter-osm-group-type[value="' + filterValue + '"]').prop('checked', false).trigger('change');
                    }
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
    $(document).on('click', '.direction-dropdown', function (e) {
        e.preventDefault();
        e.stopPropagation(); // Prevent event bubbling

        var index = $(this).data('index');
        toggleDirectionDropdown(index);
    });

    // Direction option selection handler
    $(document).on('click', '.direction-option', function (e) {
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
    $(document).on('click', function (e) {
        if (!$(e.target).closest('.direction-dropdown').length) {
            $('.direction-dropdown.open').each(function () {
                $(this).find('.direction-options').slideUp(200);
                $(this).find('.direction-arrow').removeClass('rotated');
                $(this).removeClass('open');
            });
        }
    });

    // Setup subgroup master checkboxes BEFORE the general change handler,
    // so master checkbox state is updated before updateActiveFilters() reads it.
    // Order matters: set up leaf-level masters first, then the top-level master.
    setupMasterCheckbox('#masterUnmatchedAtlasCheckbox', '.filter-unmatched-method');
    setupMasterCheckbox('#masterDistanceMatchingCheckbox', '.filter-distance-method');
    setupMasterCheckbox('#masterRouteMatchingCheckbox', '.filter-route-method');
    setupMasterCheckbox('#filterOsmGroup', '.filter-osm-group-type');
    // "All Matched" controls all matched method checkboxes (Exact, Name, Distance stages, Route methods)
    setupMasterCheckbox('#masterMatchedCheckbox', '.filter-match-method, .filter-distance-method, .filter-route-method');

    // Attach change handlers to filter checkboxes and input elements.
    $('.master-filter-checkbox, .visibility-checkbox, .filter-match-method, .filter-distance-method, .filter-route-method, .filter-unmatched-method, .filter-duplicates-only, .filter-transport-type, .filter-osm-group, .filter-osm-group-type, #masterUnmatchedAtlasCheckbox, #masterUnmatchedOsmCheckbox').on('change', function () {
        if (isBulkCheckboxSyncInProgress) {
            return;
        }
        updateActiveFilters();
        updateHeaderSummary();
    });

    $('#addSmartSearchFilter').on('click', function (e) {
        e.preventDefault();
        submitSmartSearch();
    });

    $('#smartSearchInput').on('input', function () {
        showSmartSearchError('');
    });

    // Show/hide search format hint on focus/blur
    $('#smartSearchInput').on('focus', function () {
        var hint = $('#smartSearchHint');
        if (hint.length && !$(this).val().trim()) {
            hint.removeClass('d-none');
        }
    });

    $('#smartSearchInput').on('blur', function () {
        // Small delay so the hint doesn't flicker if user clicks inside it
        setTimeout(function () {
            $('#smartSearchHint').addClass('d-none');
        }, 150);
    });

    $('#smartSearchInput').on('input', function () {
        var hint = $('#smartSearchHint');
        const hasError = $('#smartSearchInput').hasClass('is-invalid');
        if ($(this).val().trim() && !hasError) {
            hint.addClass('d-none');
        } else if (!$(this).val().trim()) {
            hint.removeClass('d-none');
        }
    });

    $('#smartSearchInput').on('keypress', function (e) {
        if (e.which === 13) { // Enter key
            e.preventDefault();
            submitSmartSearch();
        }
    });

    // Toggle button for Top N filter
    $('#toggleTopNBtn').on('click', function () {
        if (activeFilters.topN) {
            activeFilters.topN = null;
            $(this).html('<i class="fas fa-filter"></i> Activate Top N');
            // updateActiveFilters will handle layer clearing and data reload
        } else {
            var n = parseInt($('#topDistance').val());
            if (n > 0) {
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
}