// Filter Management Module
// This module handles all filter-related functionality

// Matched-stop filters by group. Each value is a matching rule key or one match
// type; backend/services/matching_rules.py expands it to match types.
const MATCH_METHOD_FILTERS = {
    methods: [
        { value: 'identifier', selector: '#filterIdentifier', label: 'SLOID in OSM' },
        { value: 'two_sided_stop', selector: '#filterTwoSidedStop', label: 'UIC two-sided stop' },
        { value: 'reference', selector: '#filterReference', label: 'UIC reference' },
        { value: 'name', selector: '#filterName', label: 'Name' }
    ],
    distanceMatching: [
        { value: 'group_distance', selector: '#distanceMethodGroup', label: 'Group distance (50 m)' },
        { value: 'group_long_distance', selector: '#distanceMethodGroupLong', label: 'Group long distance (150 m)' },
        { value: 'local_ref_distance', selector: '#distanceMethodLocalRef', label: 'local_ref distance' },
        { value: 'distance_only_candidate', selector: '#distanceMethodOnlyCandidate', label: 'Only candidate' },
        { value: 'distance_ratio', selector: '#distanceMethodRatio', label: 'Distance ratio' }
    ],
    routeMatching: [
        { value: 'gtfs_shared_route', selector: '#routeMethodSharedRoute', label: 'Shared GTFS route' },
        { value: 'gtfs_shared_direction', selector: '#routeMethodSharedDirection', label: 'Shared GTFS direction' }
    ]
};

function matchMethodFlags(group, readChecked, withAllSelected) {
    const flags = withAllSelected === undefined ? {} : { allSelected: withAllSelected };
    MATCH_METHOD_FILTERS[group].forEach(function (filter) {
        flags[filter.value] = readChecked ? $(filter.selector).is(':checked') : false;
    });
    return flags;
}

// Unified global filters object - Initialized to a "no filters active" state
var activeFilters = {
    station: [],
    stationTypes: [],
    routeDirections: [],
    // One entry per station filter: null, or for a route filter narrowed to
    // variants { atlas, osm, label } (see setRouteVariants).
    routeVariants: [],
    stopType: [],
    matchMethods: [],
    atlasOperators: [],
    osmOperators: [],
    osmOperatorWikidata: [],
    missingOsmOperatorWikidata: false,
    matchedOptions: {
        allSelected: true,
        methods: matchMethodFlags('methods', false),
        distanceMatching: matchMethodFlags('distanceMatching', false, false),
        routeMatching: matchMethodFlags('routeMatching', false, false)
    },
    unmatchedOptions: {
        allSelected: true,
        reasons: { noNearbyOSM: false, osmNearby: false }
    },
    transportTypes: [],
    osmEntityTypes: [],
    topN: null,
    showDuplicatesOnly: false,
    osmGroups: []
};

function smartSearchValidationMessage() {
    return `Allowed formats: source:… (${SharedUtils.sourceLabel()} ${SharedUtils.sourceIdLabel()}), node/123456789 (OSM node)`
        + (SharedUtils.hasCapability('gtfs_identity') ? ', UIC (8503000), SLOID (ch:1:sloid:…)' : '')
        + (SharedUtils.hasCapability('routes') ? ', route:… (optional dir:0 or dir:1)' : '');
}
const DISTANCE_METHOD_CHECKBOX_SELECTORS = MATCH_METHOD_FILTERS.distanceMatching.map(function (filter) { return filter.selector; });
const ROUTE_METHOD_CHECKBOX_SELECTORS = MATCH_METHOD_FILTERS.routeMatching.map(function (filter) { return filter.selector; });

let isBulkCheckboxSyncDepth = 0;

function areAllFilterSelectorsChecked(selectors) {
    return selectors.length > 0 && selectors.every(function (selector) {
        return $(selector).is(':checked');
    });
}

function formatOsmGroupTypeLabel(groupType) {
    const labels = {
        ptv2_pair_uic_ref: 'UIC-based pairs',
        ptv2_pair_uic_ref_equal_count: 'UIC equal-count pairs (15 m)',
        ptv2_pair_name: 'Name-based pairs',
        ptv2_pair_name_equal_count: 'Name equal-count pairs (15 m)',
        tram_stop_pair: 'Tram stop pairs',
        tram_stop_pair_equal_count: 'Tram stop equal-count pairs (15 m)',
        ptv2_two_sided_stop: 'PTv2 two-sided stops'
    };

    return labels[groupType] || groupType;
}

function formatTransportTypeLabel(filter) {
    const labels = {
        osm_way: 'Osm ways'
    };
    return labels[filter] || filter.replace(/_/g, ' ').split(' ').map(function (word) {
        return word.charAt(0).toUpperCase() + word.slice(1);
    }).join(' ');
}

function formatOsmEntityTypeLabel(filter) {
    return 'OSM: ' + (filter === 'way' ? 'Ways' : filter);
}

function removeValueFromArray(values, value) {
    const index = values.indexOf(value);
    if (index === -1) {
        return false;
    }

    values.splice(index, 1);
    return true;
}

const SIMPLE_ARRAY_FILTER_DEFINITIONS = [
    {
        stateKey: 'transportTypes',
        filterType: 'transportType',
        renderGroup: function (values, helpers) {
            const chips = values.map(function (filter) {
                return helpers.buildRemovableChip({
                    label: formatTransportTypeLabel(filter),
                    badgeClass: 'filter-chip-osm',
                    data: { type: 'transportType', filter: filter }
                });
            });
            return helpers.buildOrGroup(chips);
        },
        remove: function (value) {
            $('.filter-transport-type[value="' + value + '"]').prop('checked', false).trigger('change');
            return false;
        }
    },
    {
        stateKey: 'osmEntityTypes',
        filterType: 'osmEntityType',
        renderGroup: function (values, helpers) {
            const chips = values.map(function (filter) {
                return helpers.buildRemovableChip({
                    label: formatOsmEntityTypeLabel(filter),
                    badgeClass: 'filter-chip-osm',
                    data: { type: 'osmEntityType', filter: filter }
                });
            });
            return helpers.buildOrGroup(chips);
        },
        remove: function (value) {
            $('.filter-osm-entity-type[value="' + value + '"]').prop('checked', false).trigger('change');
            return false;
        }
    },
    {
        stateKey: 'atlasOperators',
        filterType: 'atlasOperator',
        renderGroup: function (values) {
            return window.FilterChipUtils.generateOperatorChipsHtml(values, {
                context: 'index',
                labelPrefix: SharedUtils.sourceLabel() + ' Operator'
            });
        },
        remove: function (value) {
            if (!removeValueFromArray(activeFilters.atlasOperators, value)) {
                return true;
            }
            if (window.operatorDropdown) {
                window.operatorDropdown.setSelection(activeFilters.atlasOperators);
            }
            return true;
        }
    },
    {
        stateKey: 'osmOperators',
        filterType: 'osmOperator',
        renderGroup: function (values) {
            return window.FilterChipUtils.generateOperatorChipsHtml(values, {
                context: 'index',
                labelPrefix: 'OSM Stop Operator',
                chipType: 'osmOperator',
                badgeClass: 'filter-chip-osm'
            });
        },
        remove: function (value) {
            if (!removeValueFromArray(activeFilters.osmOperators, value)) {
                return true;
            }
            if (window.osmOperatorDropdown) {
                window.osmOperatorDropdown.setSelection(activeFilters.osmOperators);
            }
            return true;
        }
    },
    {
        stateKey: 'osmOperatorWikidata',
        filterType: 'osmOperatorWikidata',
        renderGroup: function (values) {
            return window.FilterChipUtils.generateOperatorChipsHtml(values, {
                context: 'index',
                labelPrefix: 'OSM Operator Wikidata',
                chipType: 'osmOperatorWikidata',
                badgeClass: 'filter-chip-osm'
            });
        },
        remove: function (value) {
            if (!removeValueFromArray(activeFilters.osmOperatorWikidata, value)) {
                return true;
            }
            if (window.osmOperatorWikidataDropdown) {
                window.osmOperatorWikidataDropdown.setSelection(activeFilters.osmOperatorWikidata);
            }
            return true;
        }
    }
];

function countSimpleArrayFilters() {
    return SIMPLE_ARRAY_FILTER_DEFINITIONS.reduce(function (count, definition) {
        const values = activeFilters[definition.stateKey] || [];
        return count + values.length;
    }, 0);
}

function appendSimpleArrayFilterGroups(finalGroupStrings, helpers) {
    SIMPLE_ARRAY_FILTER_DEFINITIONS.forEach(function (definition) {
        const values = activeFilters[definition.stateKey] || [];
        const groupHtml = definition.renderGroup(values, helpers);
        if (groupHtml) {
            finalGroupStrings.push(groupHtml);
        }
    });
}

function removeSimpleArrayFilter(filterType, filterValue) {
    const definition = SIMPLE_ARRAY_FILTER_DEFINITIONS.find(function (entry) {
        return entry.filterType === filterType;
    });

    if (!definition) {
        return null;
    }

    return definition.remove(filterValue);
}

function getSelectedMatchedMethodFiltersFromState() {
    const selectedMethods = [];

    if (!activeFilters.matchedOptions) {
        return selectedMethods;
    }

    Object.keys(MATCH_METHOD_FILTERS).forEach(function (group) {
        const flags = activeFilters.matchedOptions[group] || {};
        MATCH_METHOD_FILTERS[group].forEach(function (filter) {
            if (flags[filter.value]) {
                selectedMethods.push(filter.value);
            }
        });
    });

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

function countSelectedFlags(flags, excludedKeys = []) {
    if (!flags) {
        return 0;
    }

    return Object.keys(flags).reduce(function (count, key) {
        if (excludedKeys.includes(key) || !flags[key]) {
            return count;
        }
        return count + 1;
    }, 0);
}

function getActiveFilterCount() {
    let count = 0;
    const showMatchedFilters = isMatchedScopeActive();
    const showUnmatchedAtlasFilters = isAtlasUnmatchedScopeActive();

    if (activeFilters.matchedOptions && showMatchedFilters) {
        if (activeFilters.matchedOptions.allSelected) {
            count += 1;
        } else {
            count += countSelectedFlags(activeFilters.matchedOptions.methods);

            if (activeFilters.matchedOptions.distanceMatching.allSelected) {
                count += 1;
            } else {
                count += countSelectedFlags(activeFilters.matchedOptions.distanceMatching, ['allSelected']);
            }

            if (activeFilters.matchedOptions.routeMatching.allSelected) {
                count += 1;
            } else {
                count += countSelectedFlags(activeFilters.matchedOptions.routeMatching, ['allSelected']);
            }
        }
    }

    if (activeFilters.unmatchedOptions && showUnmatchedAtlasFilters) {
        if (activeFilters.unmatchedOptions.allSelected) {
            count += 1;
        } else {
            count += countSelectedFlags(activeFilters.unmatchedOptions.reasons);
        }
    }

    if (activeFilters.stopType.includes('osm_unmatched')) count += 1;
    if (activeFilters.stopType.includes('osm_disused')) count += 1;

    count += activeFilters.station.length;
    count += countSimpleArrayFilters();
    if (activeFilters.missingOsmOperatorWikidata) count += 1;

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
        const docLink = ' <a href="/docs/filters_and_search_logic" class="smart-search-doc-link" target="_blank" rel="noopener noreferrer" title="Open docs"><i class="fas fa-info-circle"></i></a>';
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

    const sourceMatch = value.match(/^source:(.+)$/i);
    if (sourceMatch && sourceMatch[1].trim()) {
        return { kind: 'atlas', value: sourceMatch[1].trim() };
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
        if (!SharedUtils.hasCapability('routes')) return { error: 'Route review is unavailable for this dataset.' };
        const routeId = (routeMatch[1] || routeMatch[2]).trim();
        if (!routeId) {
            return { error: smartSearchValidationMessage() };
        }

        return {
            kind: 'route',
            value: routeId,
            direction: routeMatch[3] || '',
            // A dashed ID without "route:" may also be a stop name, such as Saint-Imier.
            implicit: !routeMatch[1]
        };
    }

    return { error: smartSearchValidationMessage() };
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
    activeFilters.routeVariants.push(null);

    // Call the backend first to see if the entry exists
    fetchAndCenterSpecificStop(filterValue, filterType)
        .then(function (data) {
            var name = token.name || searchTokenNameFromStop(filterType, data && data.stop);
            if (name) searchTokenNames[searchTokenKey(filterType, filterValue)] = name;
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
            activeFilters.routeVariants.pop();

            showSmartSearchError(errorMessage, false);
        });
}

// The search box's suggestions (static/js/components/search-suggest.js).
var searchSuggest = null;
// The name shown in the chip of a station, stop or OSM element filter, by searchTokenKey().
var searchTokenNames = {};

function searchTokenKey(kind, value) {
    return kind + ':' + value;
}

function searchTokenNameFromStop(kind, stop) {
    if (!stop) return '';
    if (kind === 'station' || kind === 'atlas') return stop.atlas_designation_official || '';
    if (kind === 'osm') return stop.osm_name || '';
    return '';
}

// Enter picks the first suggestion unless the text is an identifier.
function shouldPreselectSuggestion(query) {
    const parsed = parseSmartSearchInput(query);
    return Boolean(parsed.error || parsed.implicit);
}

function pickSearchSuggestion(item) {
    showSmartSearchError('');
    $('#smartSearchInput').val('');
    addSearchToken({ kind: item.kind, value: item.value, name: item.name });
}

function searchTypedToken(parsed) {
    if (searchSuggest) searchSuggest.close();
    showSmartSearchError('');
    addSearchToken(parsed);
    $('#smartSearchInput').val('');
}

function submitSmartSearch() {
    const raw = ($('#smartSearchInput').val() || '').trim();
    const parsed = parseSmartSearchInput(raw);

    if (!parsed.error && !parsed.implicit) {
        searchTypedToken(parsed);
        return;
    }
    if (!raw || !searchSuggest) {
        if (parsed.error) showSmartSearchError(parsed.error, true);
        else searchTypedToken(parsed);
        return;
    }
    // A name, or a dashed text that may be a name or a route ID: the best suggestion wins.
    searchSuggest.request(raw).then(function (results) {
        if (results === null) return;  // the text changed meanwhile
        if (results.length > 0) {
            searchSuggest.close();
            pickSearchSuggestion(results[0]);
        } else if (!parsed.error) {
            searchTypedToken(parsed);
        } else {
            showSmartSearchError('No stop found named "' + raw + '". ' + parsed.error, true);
        }
    }, function () {
        if (parsed.error) showSmartSearchError(parsed.error, true);
        else searchTypedToken(parsed);
    });
}

function initSearchSuggestions() {
    const input = document.getElementById('smartSearchInput');
    const list = document.getElementById('smartSearchSuggestions');
    if (!input || !list || !window.SearchSuggest) return;
    searchSuggest = window.SearchSuggest.attach({
        input: input,
        list: list,
        onPick: pickSearchSuggestion,
        preselectFirst: shouldPreselectSuggestion
    });
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
    activeFilters.routeVariants.push(null);
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
    activeFilters.routeVariants.push(null);

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
            const chipsFor = function (group, type) {
                const flags = activeFilters.matchedOptions[group];
                return MATCH_METHOD_FILTERS[group].filter(function (filter) { return flags[filter.value]; }).map(function (filter) {
                    return buildRemovableChip({
                        label: 'Match: ' + filter.label, badgeClass: 'filter-chip-matched',
                        data: { type: type, target: filter.selector }
                    });
                });
            };
            const smGrp = buildOrGroup(chipsFor('methods', 'specificMatch'));
            if (smGrp) matchedSubConditionStrings.push(smGrp);

            if (activeFilters.matchedOptions.distanceMatching.allSelected) {
                matchedSubConditionStrings.push(buildRemovableChip({ label: 'Distance Match: All Rules', badgeClass: 'filter-chip-matched', data: { type: 'masterDistance', target: '#masterDistanceMatchingCheckbox' } }));
            } else {
                const distGrp = buildOrGroup(chipsFor('distanceMatching', 'specificDistance'));
                if (distGrp) matchedSubConditionStrings.push(distGrp);
            }

            if (activeFilters.matchedOptions.routeMatching.allSelected) {
                matchedSubConditionStrings.push(buildRemovableChip({ label: 'GTFS Route Match: All', badgeClass: 'filter-chip-matched', data: { type: 'masterRoute', target: '#masterRouteMatchingCheckbox' } }));
            } else {
                const rGrp = buildOrGroup(chipsFor('routeMatching', 'specificRoute'));
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
            unmatchedAtlasString = buildRemovableChip({ label: 'Unmatched ' + SharedUtils.sourceLabel(), badgeClass: 'filter-chip-unmatched', data: { type: 'masterUnmatchedAtlas', target: '#masterUnmatchedAtlasCheckbox' } });
        } else {
            let reasonChips = [];
            if (activeFilters.unmatchedOptions.reasons.noNearbyOSM) {
                reasonChips.push(buildRemovableChip({ label: 'Unmatched ' + SharedUtils.sourceLabel() + ': No OSM < 50m', badgeClass: 'filter-chip-unmatched', data: { type: 'specificUnmatched', target: '#filterNoNearbyOSM' } }));
            }
            if (activeFilters.unmatchedOptions.reasons.osmNearby) {
                reasonChips.push(buildRemovableChip({ label: 'Unmatched ' + SharedUtils.sourceLabel() + ': OSM < 50m', badgeClass: 'filter-chip-unmatched', data: { type: 'specificUnmatched', target: '#filterOSMNearby' } }));
            }
            unmatchedAtlasString = buildOrGroup(reasonChips);
        }
    }

    let unmatchedOsmString = '';
    if (activeFilters.stopType.includes('osm_unmatched')) {
        unmatchedOsmString = buildRemovableChip({ label: 'Unmatched OSM', badgeClass: 'filter-chip-unmatched', data: { type: 'masterUnmatchedOsm', target: '#masterUnmatchedOsmCheckbox' } });
    }

    let disusedOsmString = '';
    if (activeFilters.stopType.includes('osm_disused')) {
        disusedOsmString = buildRemovableChip({ label: 'Disused OSM', badgeClass: 'filter-chip-unmatched', data: { type: 'masterDisusedOsm', target: '#masterDisusedOsmCheckbox' } });
    }

    let visibilityChips = [];
    if (matchedDisplayString) visibilityChips.push(matchedDisplayString);
    if (unmatchedAtlasString) visibilityChips.push(unmatchedAtlasString);
    if (unmatchedOsmString) visibilityChips.push(unmatchedOsmString);
    if (disusedOsmString) visibilityChips.push(disusedOsmString);
    if (visibilityChips.length > 0) finalGroupStrings.push(buildOrGroup(visibilityChips));

    let stationIdChips = [];
    activeFilters.station.forEach(function (filter, index) {
        var filterType = activeFilters.stationTypes[index];
        var direction = activeFilters.routeDirections[index] || '';
        var labelText = '', badgeClass = '', badgeHtmlContent = '';
        switch (filterType) {
            case 'atlas': labelText = SharedUtils.sourceLabel() + ' ' + SharedUtils.sourceIdLabel() + ': '; badgeClass = 'filter-chip-atlas'; badgeHtmlContent = labelText + filter; break;
            case 'osm': labelText = 'OSM Node ID: '; badgeClass = 'filter-chip-osm'; badgeHtmlContent = labelText + filter; break;
            case 'route':
                var normalizedRoute = normalizeRouteIdForDisplay(filter);
                var directionDisplay = formatDirectionDisplay(direction);
                labelText = 'Route: '; badgeClass = 'filter-chip-secondary'; badgeHtmlContent = labelText + normalizedRoute + ', ' + directionDisplay;
                break;
            case 'station':
            default: labelText = 'UIC: '; badgeClass = 'filter-chip-secondary'; badgeHtmlContent = labelText + filter; break;
        }
        var tokenName = filterType === 'route' ? '' : searchTokenNames[searchTokenKey(filterType || 'station', filter)];
        if (tokenName) badgeHtmlContent = tokenName + ' · ' + badgeHtmlContent;
        var badgeHtml;
        if (filterType === 'route') {
            var currentDirection = activeFilters.routeDirections[index] || '';
            var variants = activeFilters.routeVariants[index];
            badgeHtml = window.FilterChipUtils.buildDirectionDropdownHtml({
                direction: currentDirection,
                mapIndex: index,
                routeLabel: labelText + normalizedRoute,
                showClose: true,
                routeId: filter,
                variantLabel: variants ? variants.label : '',
                variantTitle: variants ? variants.title : ''
            });
        } else {
            badgeHtml = buildRemovableChip({ label: badgeHtmlContent, badgeClass: badgeClass, data: { type: 'station', index: index }, closeChar: '×' });
        }
        stationIdChips.push(badgeHtml);
    });
    const stationIdGroupHtml = buildOrGroup(stationIdChips);
    if (stationIdGroupHtml) finalGroupStrings.push(stationIdGroupHtml);

    if (activeFilters.missingOsmOperatorWikidata) {
        finalGroupStrings.push(buildRemovableChip({
            label: 'No Wikidata tag', badgeClass: 'filter-chip-osm',
            data: { type: 'missingOsmOperatorWikidata', target: '#filterMissingOsmOperatorWikidata' }
        }));
    }

    appendSimpleArrayFilterGroups(finalGroupStrings, {
        buildRemovableChip: buildRemovableChip,
        buildOrGroup: buildOrGroup
    });

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
    if (activeFilters.showDuplicatesOnly) finalGroupStrings.push(buildRemovableChip({ label: 'Duplicate ' + SharedUtils.sourceLabel(), badgeClass: 'filter-chip-atlas', data: { type: 'showDuplicatesOnly' } }));

    if (finalGroupStrings.length > 0) {
        if (getActiveFilterCount() === 1) {
            container.html('<span class="header-summary__filters-prefix">Filter:</span>' + joinWithAnd(finalGroupStrings));
        } else {
            container.html(joinWithAnd(finalGroupStrings));
        }
    }
    else container.html('<span class="badge filter-chip-badge filter-chip-secondary me-1 mb-1">All entries</span>');

    container.attr('data-active-filter-count', String(getActiveFilterCount()));
    syncFilterUrl();
}

function clearAllFilters() {
    // Uncheck all filter checkboxes
    $('#masterMatchedCheckbox').prop('checked', false);
    $('#masterUnmatchedAtlasCheckbox').prop('checked', false);
    $('#masterUnmatchedOsmCheckbox').prop('checked', false);
    $('#masterDisusedOsmCheckbox').prop('checked', false);
    $('#filterDuplicatesOnly').prop('checked', false);
    $('#filterMissingOsmOperatorWikidata').prop('checked', false);
    activeFilters.missingOsmOperatorWikidata = false;
    $('.filter-match-method, .filter-distance-method, .filter-route-method').prop('checked', false);
    $('#masterDistanceMatchingCheckbox, #masterRouteMatchingCheckbox').prop('checked', false);
    $('.filter-unmatched-method').prop('checked', false);
    $('.filter-transport-type').prop('checked', false);
    $('.filter-osm-entity-type').prop('checked', false);
    $('.filter-osm-group, .filter-osm-pair-master, .filter-osm-group-type').prop('checked', false);

    // Clear array-based filters
    activeFilters.station = [];
    activeFilters.stationTypes = [];
    activeFilters.routeDirections = [];
    activeFilters.routeVariants = [];
    syncRouteVariantUrl();

    // Clear operators and reset dropdowns
    activeFilters.atlasOperators = [];
    if (window.operatorDropdown) {
        window.operatorDropdown.setSelection([]);
    }
    activeFilters.osmOperators = [];
    if (window.osmOperatorDropdown) {
        window.osmOperatorDropdown.setSelection([]);
    }

    activeFilters.osmOperatorWikidata = [];
    if (window.osmOperatorWikidataDropdown) {
        window.osmOperatorWikidataDropdown.setSelection([]);
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
    activeFilters.routeVariants.push(null);

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
    if ($('#masterDisusedOsmCheckbox').is(':checked')) activeFilters.stopType.push('osm_disused');

    activeFilters.showDuplicatesOnly = $('#filterDuplicatesOnly').is(':checked');
    activeFilters.missingOsmOperatorWikidata = $('#filterMissingOsmOperatorWikidata').is(':checked');
    activeFilters.transportTypes = $('.filter-transport-type:checked').map(function () { return this.value; }).get();
    activeFilters.osmEntityTypes = $('.filter-osm-entity-type:checked').map(function () { return this.value; }).get();

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
        methods: matchMethodFlags('methods', true),
        distanceMatching: matchMethodFlags('distanceMatching', true, allDistanceMethodsSelected),
        routeMatching: matchMethodFlags('routeMatching', true, allRouteMethodsSelected)
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
        isBulkCheckboxSyncDepth++;
        try {
            childCheckboxes.prop('checked', $(this).is(':checked')).trigger('change'); // Trigger child listeners while suppressing expensive bulk reloads
        } finally {
            isBulkCheckboxSyncDepth--;
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
        activeFilters.routeVariants[index] = null;
        syncRouteVariantUrl();

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
        loadRouteVariantOptions(dropdown);
        options.slideDown(200);
        arrow.addClass('rotated');
        dropdown.addClass('open');
    }
}

// ==========================================
// Route variants
// ==========================================
// A route filter can be narrowed to exact variants: an ATLAS itinerary, an
// OSM route relation, or both. They are named with the routes page's keys,
// atlas_variant and osm_variant, which the address bar also carries.

var ROUTE_VARIANT_KEYS = ['atlas_variant', 'osm_variant'];
var routeVariantRequests = {};
var loadedRouteVariants = {};  // route id -> variants, for the dropdown's options

// GET /api/routes/variants, once per query.
function fetchRouteVariants(params) {
    var query = Object.keys(params).filter(function (key) { return params[key]; }).sort().map(function (key) {
        return encodeURIComponent(key) + '=' + encodeURIComponent(params[key]);
    }).join('&');
    if (!routeVariantRequests[query]) {
        routeVariantRequests[query] = fetch('/api/routes/variants?' + query, { headers: { Accept: 'application/json' } })
            .then(function (response) {
                if (!response.ok) throw new Error('Route variants request failed with HTTP ' + response.status);
                return response.json();
            })
            .catch(function (error) {
                delete routeVariantRequests[query];
                throw error;
            });
    }
    return routeVariantRequests[query];
}

// A variant's name as shown: "A -> B" reads "A → B".
function routeVariantName(variant) {
    return String(variant.name || variant.key).replace(/\s*->\s*/g, ' → ');
}

// The chip's label: the variant's name (ATLAS first), and which source it is
// when only one side is shown.
function routeVariantLabel(atlas, osm) {
    var name = routeVariantName(atlas || osm);
    if (atlas && osm) return name;
    return name + ' · ' + (atlas ? SharedUtils.sourceLabel() : 'OSM') + ' only';
}

// The request parameter: a JSON list aligned with station_filter, or null
// when no route filter is narrowed (commas in headsigns rule out a comma list).
function routeVariantsParam() {
    if (!activeFilters.routeVariants.some(Boolean)) return null;
    return JSON.stringify(activeFilters.station.map(function (value, index) {
        var variants = activeFilters.routeVariants[index];
        return variants ? { atlas: variants.atlas, osm: variants.osm } : null;
    }));
}

// The address bar names the variants of the last narrowed route filter.
function syncRouteVariantUrl() {
    if (!window.Permalinks) return;
    var last = null;
    activeFilters.routeVariants.forEach(function (variants) { if (variants) last = variants; });
    Permalinks.replaceUrl({
        search: Permalinks.buildSearch(window.location.search, ROUTE_VARIANT_KEYS,
            last ? Permalinks.encodeParams({ atlas_variant: last.atlas, osm_variant: last.osm }) : '')
    });
}

// atlas and osm: variant summaries from /api/routes/variants, or null.
function setRouteVariants(index, atlas, osm) {
    if (index < 0 || index >= activeFilters.station.length || (!atlas && !osm)) return;
    activeFilters.routeDirections[index] = '';
    activeFilters.routeVariants[index] = {
        atlas: atlas ? atlas.key : null,
        osm: osm ? osm.key : null,
        label: routeVariantLabel(atlas, osm),
        title: routeVariantTitle(atlas, osm)
    };
    syncRouteVariantUrl();
    updateFiltersUI();
    if (typeof window.invalidateViewportCache === 'function') window.invalidateViewportCache();
    loadDataForViewport();
    updateHeaderSummary();
}

// Adds the route filter a variant link names (data: /api/routes/variants).
function addRouteVariantFilter(data) {
    activeFilters.station.push(data.route_id);
    activeFilters.stationTypes.push('route');
    activeFilters.routeDirections.push('');
    activeFilters.routeVariants.push(null);
    setRouteVariants(activeFilters.station.length - 1, data.selected.atlas, data.selected.osm);
}

// Both sides, named as their sources name them: the tooltip of a variant.
function routeVariantTitle(atlas, osm) {
    return [atlas && SharedUtils.sourceLabel() + ': ' + atlas.name, osm && 'OSM: ' + osm.name].filter(Boolean).join('\n');
}

// One variant option: its name once, the OSM name below when the pair's names
// differ, and the sources it shows as small tags.
function routeVariantOptionHtml(entry, i, isCurrent) {
    var esc = SharedUtils.escapeHtml;
    var name = routeVariantName(entry.atlas || entry.osm);
    var other = entry.atlas && entry.osm && routeVariantName(entry.osm) !== name ? routeVariantName(entry.osm) : '';
    var title = routeVariantTitle(entry.atlas, entry.osm);
    return '<div class="direction-option direction-option--variant' + (isCurrent ? ' is-current' : '') +
        '" data-variant="' + i + '" title="' + esc(title) + '">' +
        '<span class="variant-option__name">' + esc(name) +
        (other ? '<span class="variant-option__other">OSM: ' + esc(other) + '</span>' : '') + '</span>' +
        '<span class="variant-option__sources">' +
        (entry.atlas ? '<span class="source-tag source-tag--atlas">' + SharedUtils.sourceLabelHtml() + '</span>' : '') +
        (entry.osm ? '<span class="source-tag source-tag--osm">OSM</span>' : '') +
        '</span></div>';
}

// Fills a route chip's dropdown with the route's variants under their direction.
function loadRouteVariantOptions(dropdown) {
    var container = dropdown.find('.direction-variants');
    var routeId = dropdown.attr('data-route-id');
    if (!container.length || !routeId || container.attr('data-state')) return;
    container.attr('data-state', 'loading');
    var selected = activeFilters.routeVariants[Number(dropdown.attr('data-index'))];
    fetchRouteVariants({ route_id: routeId }).then(function (data) {
        var html = '';
        data.variants.forEach(function (entry, i) {
            var direction = entry.direction_id;
            if (i === 0 || direction !== data.variants[i - 1].direction_id) {
                // A direction is an option (all its variants); variants without one only get a heading.
                html += direction === '0' || direction === '1'
                    ? '<div class="direction-option direction-option--direction" data-direction="' + direction + '">Direction ' +
                        direction + '<span class="direction-option__hint">all variants</span></div>'
                    : '<div class="direction-group">Other variants</div>';
            }
            var isCurrent = selected && selected.atlas === (entry.atlas && entry.atlas.key) &&
                selected.osm === (entry.osm && entry.osm.key);
            html += routeVariantOptionHtml(entry, i, isCurrent);
        });
        loadedRouteVariants[routeId] = data.variants;
        if (html) container.html(html);
        container.attr('data-state', 'loaded');
    }).catch(function () {
        // The directions stay; opening the list again retries.
        container.attr('data-state', '');
    });
}

// Initialize filter-related event handlers
// ==========================================
// Filter links
// ==========================================
// The address bar keeps every map filter, so a copied link opens the same
// filtered view. Names follow the /api/data parameters; search filters are
// repeated search= values. See documentation/2.9 Permalinks.md#map.
var FILTER_URL_KEYS = ['stop_filter', 'match_method', 'transport_types', 'osm_entity_types', 'osm_group_types',
    'show_duplicates_only', 'atlas_operator', 'osm_operator', 'osm_operator_wikidata',
    'missing_osm_operator_wikidata', 'top_n', 'search'];
// Off until the filters of the opening link are restored, so a half-built state never replaces them.
var filterUrlSyncEnabled = false;

// A search filter as link text: uic:8503000, source:<id>, node/123, way/45, route:<id> dir:0.
function searchFilterText(kind, value, direction) {
    if (kind === 'station') return 'uic:' + value;
    if (kind === 'atlas') return 'source:' + value;
    if (kind === 'osm') {
        if (/^\d+$/.test(value)) return 'node/' + value;
        if (/^way_\d+$/.test(value)) return 'way/' + value.slice(4);
        return 'osm:' + value;
    }
    if (kind === 'route') return 'route:' + value + (direction ? ' dir:' + direction : '');
    return null;
}

function parseSearchFilterText(text) {
    text = String(text || '').trim();
    var match;
    if ((match = /^uic:(.+)$/.exec(text))) return { kind: 'station', value: match[1] };
    if ((match = /^source:(.+)$/.exec(text))) return { kind: 'atlas', value: match[1] };
    if ((match = /^node\/(\d+)$/.exec(text))) return { kind: 'osm', value: match[1] };
    if ((match = /^way\/(\d+)$/.exec(text))) return { kind: 'osm', value: 'way_' + match[1] };
    if ((match = /^osm:(\S+)$/.exec(text))) return { kind: 'osm', value: match[1] };
    if ((match = /^route:(\S+)(?: dir:([01]))?$/.exec(text))) {
        return SharedUtils.hasCapability('routes') ? { kind: 'route', value: match[1], direction: match[2] || '' } : null;
    }
    return null;
}

// [key, value] pairs of the current filters, in a fixed order.
function filterUrlPairs() {
    var pairs = [];
    function addList(key, values) {
        if (values && values.length) pairs.push([key, values.join(',')]);
    }
    addList('stop_filter', activeFilters.stopType);
    addList('match_method', activeFilters.matchMethods);
    addList('transport_types', activeFilters.transportTypes);
    addList('osm_entity_types', activeFilters.osmEntityTypes);
    addList('osm_group_types', activeFilters.osmGroups);
    if (activeFilters.showDuplicatesOnly) pairs.push(['show_duplicates_only', 'true']);
    addList('atlas_operator', activeFilters.atlasOperators);
    addList('osm_operator', activeFilters.osmOperators);
    addList('osm_operator_wikidata', activeFilters.osmOperatorWikidata);
    if (activeFilters.missingOsmOperatorWikidata) pairs.push(['missing_osm_operator_wikidata', 'true']);
    if (activeFilters.topN) pairs.push(['top_n', String(activeFilters.topN)]);
    // The last route filter narrowed to variants is named by atlas_variant / osm_variant.
    var variantIndex = -1;
    activeFilters.routeVariants.forEach(function (variants, index) { if (variants) variantIndex = index; });
    activeFilters.station.forEach(function (value, index) {
        if (index === variantIndex) return;
        var text = searchFilterText(activeFilters.stationTypes[index], value, activeFilters.routeDirections[index]);
        if (text) pairs.push(['search', text]);
    });
    return pairs;
}

function filterUrlQuery() {
    return filterUrlPairs().map(function (pair) {
        var param = {};
        param[pair[0]] = pair[1];
        return Permalinks.encodeParams(param);
    }).join('&');
}

function syncFilterUrl() {
    if (!filterUrlSyncEnabled || !window.Permalinks) return;
    Permalinks.replaceUrl({ search: Permalinks.buildSearch(window.location.search, FILTER_URL_KEYS, filterUrlQuery()) });
}

function enableFilterUrlSync() {
    filterUrlSyncEnabled = true;
    syncFilterUrl();
}

function checkFilterBoxes(selector, values) {
    $(selector).each(function () {
        if (values.indexOf(this.value) !== -1) $(this).prop('checked', true).trigger('change');
    });
}

function pushSearchFilter(token) {
    for (var i = 0; i < activeFilters.station.length; i++) {
        if (activeFilters.stationTypes[i] === token.kind && activeFilters.station[i] === token.value
            && (activeFilters.routeDirections[i] || '') === (token.direction || '')) return;
    }
    activeFilters.station.push(token.value);
    activeFilters.stationTypes.push(token.kind);
    activeFilters.routeDirections.push(token.direction || '');
    activeFilters.routeVariants.push(null);
}

// Names the chips of restored stop filters from the public lookup.
function loadSearchFilterNames(tokens) {
    var keys = { station: 'uic_ref', atlas: 'sloid', osm: 'osm' };
    tokens.filter(function (token) { return keys[token.kind]; }).slice(0, 10).forEach(function (token) {
        var value = token.kind === 'osm' ? searchFilterText('osm', token.value) : token.value;
        if (/^osm:/.test(value)) return;
        var query = {};
        query[keys[token.kind]] = value;
        fetch('/api/lookup?' + Permalinks.encodeParams(query), { headers: { Accept: 'application/json' } })
            .then(function (response) { return response.ok ? response.json() : null; })
            .then(function (data) {
                var first = data && data.results && data.results[0];
                var side = first && (token.kind === 'osm' ? first.osm : first.source);
                if (!side || !side.name) return;
                searchTokenNames[searchTokenKey(token.kind, token.value)] = side.name;
                updateFiltersUI();
            })
            .catch(function () { /* the chip keeps its identifier */ });
    });
}

// Sets the controls and search filters a link names; the caller then runs updateActiveFilters().
// The operator filters are restored by restoreOperatorFiltersFromUrl() in main.js.
function restoreFiltersFromUrl(search) {
    var params = new URLSearchParams(search === undefined ? window.location.search : search);
    function list(key) {
        return params.getAll(key).flatMap(function (value) { return value.split(','); })
            .map(function (value) { return value.trim(); }).filter(Boolean);
    }
    isBulkCheckboxSyncDepth++;
    try {
        var scope = list('stop_filter');
        [['matched', '#masterMatchedCheckbox'], ['atlas_unmatched', '#masterUnmatchedAtlasCheckbox'],
            ['osm_unmatched', '#masterUnmatchedOsmCheckbox'], ['osm_disused', '#masterDisusedOsmCheckbox']
        ].forEach(function (entry) {
            if (scope.indexOf(entry[0]) !== -1) $(entry[1]).prop('checked', true).trigger('change');
        });
        checkFilterBoxes('.filter-match-method, .filter-distance-method, .filter-route-method, .filter-unmatched-method', list('match_method'));
        checkFilterBoxes('.filter-transport-type', list('transport_types'));
        checkFilterBoxes('.filter-osm-entity-type', list('osm_entity_types'));
        var groups = list('osm_group_types');
        if (groups.indexOf('all') !== -1) $('#filterOsmGroup').prop('checked', true).trigger('change');
        else checkFilterBoxes('.filter-osm-group-type', groups);
        if (params.get('show_duplicates_only') === 'true') $('#filterDuplicatesOnly').prop('checked', true);
    } finally {
        isBulkCheckboxSyncDepth--;
    }
    var topN = parseInt(params.get('top_n'), 10);
    if (topN > 0) {
        activeFilters.topN = topN;
        $('#topDistance').val(topN);
        $('#toggleTopNBtn').html('<i class="fas fa-times-circle"></i> Remove Top N');
    }
    var tokens = params.getAll('search').map(parseSearchFilterText).filter(Boolean);
    tokens.forEach(pushSearchFilter);
    loadSearchFilterNames(tokens);
}

window.restoreFiltersFromUrl = restoreFiltersFromUrl;
window.enableFilterUrlSync = enableFilterUrlSync;
window.filterUrlQuery = filterUrlQuery;

function initFilterEventHandlers() {
    $('#filterMissingOsmOperatorWikidata').on('change', function () {
        if (this.checked) {
            activeFilters.osmOperatorWikidata = [];
            if (window.osmOperatorWikidataDropdown) window.osmOperatorWikidataDropdown.setSelection([]);
        }
        updateActiveFilters();
        updateHeaderSummary();
    });

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
            $(targetCheckboxId).prop('checked', false).trigger('change');
        } else {
            const simpleArrayRemoval = removeSimpleArrayFilter(type, filterValue);
            if (simpleArrayRemoval !== null) {
                needsManualUpdateCall = simpleArrayRemoval;
            } else {
            // Handle types that don't use data-target but have corresponding UI elements or direct activeFilters manipulation
                switch (type) {
                    case 'station': // For UIC, Sloid, OSM Node ID, Route ID filters
                        if (index !== undefined && index >= 0 && index < activeFilters.station.length) {
                            activeFilters.station.splice(index, 1);
                            activeFilters.stationTypes.splice(index, 1);
                            activeFilters.routeDirections.splice(index, 1);
                            activeFilters.routeVariants.splice(index, 1);
                            syncRouteVariantUrl();
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
        // A heading in the variant list is not an option: keep it open.
        if ($(e.target).closest('.direction-options').length && !$(e.target).closest('.direction-option').length) return;

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
        var variant = $(this).attr('data-variant');

        if (variant) {
            var entry = (loadedRouteVariants[dropdown.attr('data-route-id')] || [])[Number(variant)];
            if (entry) setRouteVariants(Number(index), entry.atlas, entry.osm);
        } else {
            setRouteDirection(Number(index), direction);
        }

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
    setupMasterCheckbox('#filterOsmPairMaster', '.filter-osm-pair-type');
    setupMasterCheckbox('#filterOsmGroup', '.filter-osm-group-type, #filterOsmPairMaster');
    // "All Matched" controls all matched method checkboxes (Exact, Name, Distance stages, Route methods)
    setupMasterCheckbox('#masterMatchedCheckbox', '.filter-match-method, .filter-distance-method, .filter-route-method');

    // Attach change handlers to filter checkboxes and input elements.
    $('.master-filter-checkbox, .visibility-checkbox, .filter-match-method, .filter-distance-method, .filter-route-method, .filter-unmatched-method, .filter-duplicates-only, .filter-transport-type, .filter-osm-entity-type, .filter-osm-group, .filter-osm-pair-master, .filter-osm-group-type, #masterUnmatchedAtlasCheckbox, #masterUnmatchedOsmCheckbox, #masterDisusedOsmCheckbox').on('change', function () {
        if (isBulkCheckboxSyncDepth > 0) {
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

    initSearchSuggestions();
    $('#smartSearchInput').on('keydown', function (e) {
        if (searchSuggest && searchSuggest.handleKeydown(e)) return;
        if (e.key === 'Enter') {
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
