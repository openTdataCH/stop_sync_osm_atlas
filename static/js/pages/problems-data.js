// problems-data.js - Data fetching and processing for the Problem Identification Page

window.ProblemsData = (function () {
    'use strict';

    const DEFAULT_SORT_BY = 'priority';
    const DEFAULT_SORT_ORDER = 'asc';
    const PAGE_SIZE = 100;
    const ALL_PROBLEM_TYPES = [
        'attributes',
        'contradicts_route_matching',
        'distance',
        'duplicates',
        'unmatched',
        'disused',
        'identifier'
    ];

    function getNormalizedProblemTypeSelection(selectedTypes) {
        return Array.isArray(selectedTypes) ? selectedTypes : [];
    }

    function getEffectiveSelectedTypes(selectedTypes = getSelectedTypes()) {
        const normalizedSelection = getNormalizedProblemTypeSelection(selectedTypes);
        if (!normalizedSelection.length) {
            return ALL_PROBLEM_TYPES.slice();
        }
        return ALL_PROBLEM_TYPES.filter(type => normalizedSelection.includes(type));
    }

    function isAllProblemTypesSelected(selectedTypes = getSelectedTypes()) {
        return getNormalizedProblemTypeSelection(selectedTypes).length === 0;
    }

    function computeNextProblemTypeSelection(currentTypes, newType, isChecked) {
        if (newType === 'all') {
            return [];
        }

        let next = getEffectiveSelectedTypes(currentTypes);

        if (isChecked) {
            if (!next.includes(newType)) {
                next = next.concat([newType]);
            }
        } else {
            next = next.filter(type => type !== newType);
        }

        next = ALL_PROBLEM_TYPES.filter(type => next.includes(type));

        if (!next.length || next.length === ALL_PROBLEM_TYPES.length) {
            return [];
        }

        return next;
    }

    function getSelectedTypes() {
        return ProblemsState.getSelectedProblemTypes() || [];
    }

    function getSelectedPriorities() {
        return ProblemsState.getSelectedPriorities() || [];
    }

    function getProblemTypeParamValue() {
        const selectedTypes = getSelectedTypes();
        if (!selectedTypes.length) return 'all';
        return selectedTypes.join(',');
    }

    function groupProblemsByEntry(problems) {
        const grouped = {};
        const selectedTypes = getSelectedTypes();

        problems.forEach(problem => {
            let entryKey;
            const isGroup = problem.problem === 'duplicates' && typeof problem.id === 'string';
            
            if (isGroup) {
                entryKey = `group_${problem.id}`;
            } else if (problem.problem === 'duplicates') {
                // For individual duplicate problems, use the group ID as the key to group them together
                const groupKey = problem.duplicate_group_sloids || problem.duplicate_group_node_ids;
                if (groupKey) {
                    entryKey = `group_auto_${groupKey}`;
                } else {
                    entryKey = `dup_stop_${problem.stop_id || problem.id}`;
                }
            } else {
                entryKey = `${problem.stop_id || problem.id}_${problem.atlas_lat || problem.osm_lat}_${problem.atlas_lon || problem.osm_lon}`;
            }

            if (!grouped[entryKey]) grouped[entryKey] = [];
            grouped[entryKey].push(problem);
        });

        const orderGroup = (arr) => {
            if (!Array.isArray(arr)) return arr;
            return arr.slice().sort((a, b) => {
                const priorityA = Number.isFinite(Number(a.priority)) ? Number(a.priority) : 999;
                const priorityB = Number.isFinite(Number(b.priority)) ? Number(b.priority) : 999;
                if (priorityA !== priorityB) return priorityA - priorityB;

                if (selectedTypes.length > 0) {
                    const aMatch = selectedTypes.includes(a.problem) ? 1 : 0;
                    const bMatch = selectedTypes.includes(b.problem) ? 1 : 0;
                    if (aMatch !== bMatch) return bMatch - aMatch;
                }
                return String(a.problem).localeCompare(String(b.problem));
            });
        };

        Object.keys(grouped).forEach(key => {
            grouped[key] = orderGroup(grouped[key]);
        });

        return Object.values(grouped);
    }

    function updateTypeButtonDisplay() {
        const selectedTypes = getSelectedTypes();
        const effectiveSelectedTypes = getEffectiveSelectedTypes(selectedTypes);

        if (isAllProblemTypesSelected(selectedTypes)) {
            $('#typeFilterButtonProblems').text('Type: All');
        } else if (selectedTypes.length === 1) {
            const label = selectedTypes[0] === 'identifier'
                ? `OSM ${SharedUtils.sourceIdLabel()}`
                : selectedTypes[0].replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
            $('#typeFilterButtonProblems').text(`Type: ${label}`);
        } else {
            $('#typeFilterButtonProblems').text(`Type: ${selectedTypes.length} selected`);
        }

        $('#filterProblemTypeAll').prop('checked', isAllProblemTypesSelected(selectedTypes));
        $('#filterProblemTypeAttributes').prop('checked', effectiveSelectedTypes.includes('attributes'));
        $('#filterProblemTypeContradictsRouteMatching').prop('checked', effectiveSelectedTypes.includes('contradicts_route_matching'));
        $('#filterProblemTypeDistance').prop('checked', effectiveSelectedTypes.includes('distance'));
        $('#filterProblemTypeDuplicates').prop('checked', effectiveSelectedTypes.includes('duplicates'));
        $('#filterProblemTypeUnmatched').prop('checked', effectiveSelectedTypes.includes('unmatched'));
        $('#filterProblemTypeDisused').prop('checked', effectiveSelectedTypes.includes('disused'));
        $('#filterProblemTypeIdentifier').prop('checked', effectiveSelectedTypes.includes('identifier'));
    }

    function syncPrioritySelectionUi() {
        const selectedPriorities = getSelectedPriorities();
        $('#priorityFilterProblems .priority-circle').removeClass('selected');
        if (!selectedPriorities.length) {
            $('#priorityFilterProblems .priority-option[data-priority="all"] .priority-circle').addClass('selected');
            return;
        }
        selectedPriorities.forEach(pr => {
            $(`#priorityFilterProblems .priority-option[data-priority="${pr}"] .priority-circle`).addClass('selected');
        });
    }

    function reloadProblemsWithUpdatedFilters() {
        ProblemsState.resetPaginationState();
        fetchProblems();
        initializeProblemTypeFilter();
    }

    function updateProblemTypeFilter(newType, isChecked) {
        const current = getSelectedTypes();
        const next = computeNextProblemTypeSelection(current, newType, isChecked);

        ProblemsState.setSelectedProblemTypes(next);
        updateTypeButtonDisplay();
        reloadProblemsWithUpdatedFilters();
    }

    function updatePriorityFilter(priority = 'all') {
        const current = getSelectedPriorities();
        let next = [];

        if (String(priority) === 'all') {
            next = [];
        } else {
            const pr = String(priority);
            if (current.includes(pr)) {
                next = current.filter(p => p !== pr);
            } else {
                next = current.concat([pr]);
            }
        }

        ProblemsState.setSelectedPriorities(next);
        syncPrioritySelectionUi();
        reloadProblemsWithUpdatedFilters();
    }

    // Pages hold PAGE_SIZE stops (or duplicate groups), so the total in stops
    // tells whether a later page exists.
    function hasMorePages() {
        return ProblemsState.getCurrentPage() * PAGE_SIZE < ProblemsState.getTotalProblems();
    }

    // 1-based position of a loaded entry in the whole filtered list. A list
    // opened on page p starts at (p - 1) * PAGE_SIZE + 1. The total counts
    // stops while a stop's duplicate problem can form its own entry, so this
    // is approximate away from page 1, but numbers never change once shown.
    function entryNumber(index) {
        return ProblemsState.getEntryNumberOffset() + index + 1;
    }

    function syncPermalink() {
        if (window.ProblemsPermalink) window.ProblemsPermalink.sync();
    }

    /**
     * Load a page of problems.
     *
     * options.focus: { sloid, osm_node_id } from a permalink. The server answers
     *   with the page that holds that stop, which becomes the first loaded page,
     *   and the stop's entry is shown. options.onFocusMissing runs when the stop
     *   has no entry under the current filters.
     * options.prepend: load the page before the first loaded one (Prev at the
     *   start of a list opened from a permalink).
     */
    function fetchProblems(page = 1, options = {}) {
        if (ProblemsState.getIsLoadingMore()) return;
        ProblemsState.setIsLoadingMore(true);
        $('#problemTypeDisplay').text('Loading...');
        const mode = options.prepend ? 'prepend' : (options.focus || page === 1 ? 'fresh' : 'append');

        const params = {
            page: page,
            limit: PAGE_SIZE,
            problem_type: getProblemTypeParamValue(),
            sort_by: DEFAULT_SORT_BY,
            sort_order: DEFAULT_SORT_ORDER,
            include_routes: 1
        };

        const selectedOperators = ProblemsState.getSelectedAtlasOperators();
        if (selectedOperators.length > 0) {
            params.atlas_operator = selectedOperators.join(',');
        }

        const selectedPriorities = getSelectedPriorities();
        if (selectedPriorities.length > 0) {
            params.priority = selectedPriorities.join(',');
        }

        if (options.focus) {
            if (options.focus.sloid) params.focus_sloid = options.focus.sloid;
            if (options.focus.osm_node_id) params.focus_osm_node_id = options.focus.osm_node_id;
        }

        $.getJSON('/api/problems', params, function (data) {
            if (data.error) {
                $('#problemTypeDisplay').text('Error loading problems.');
                ProblemsState.setIsLoadingMore(false);
                return;
            }

            const shownEntry = ProblemsState.getCurrentEntryProblems() || [];
            const shownIndexBefore = ProblemsState.getCurrentProblemIndex();
            if (mode === 'fresh') {
                ProblemsState.setAllProblems(data.problems);
                ProblemsState.setTotalProblems(data.total);
                ProblemsState.setFirstLoadedPage(data.page);
                ProblemsState.setCurrentPage(data.page);
                ProblemsState.setEntryNumberOffset((data.page - 1) * PAGE_SIZE);
            } else if (mode === 'prepend') {
                ProblemsState.setAllProblems(data.problems.concat(ProblemsState.getAllProblems()));
                ProblemsState.setFirstLoadedPage(data.page);
            } else {
                ProblemsState.addProblems(data.problems);
                ProblemsState.setCurrentPage(data.page);
            }

            const problemsByEntry = groupProblemsByEntry(ProblemsState.getAllProblems());
            ProblemsState.setProblemsByEntry(problemsByEntry);

            const allProblems = ProblemsState.getAllProblems();
            if (allProblems.length === 0) {
                $('#problemTypeDisplay').text('No problems found for this filter combination.');
                $('#actionButtonsContent').empty();
                ProblemsState.setCurrentEntryProblems([]);
                syncPermalink();

                const markersLayer = ProblemsState.getProblemMarkersLayer();
                const linesLayer = ProblemsState.getProblemLinesLayer();
                const contextLayer = ProblemsState.getContextMarkersLayer();
                if (markersLayer) markersLayer.clearLayers();
                if (linesLayer) linesLayer.clearLayers();
                if (window.ProblemsMap && typeof window.ProblemsMap.clearContextData === 'function') {
                    window.ProblemsMap.clearContextData();
                } else if (contextLayer) {
                    contextLayer.clearLayers();
                }
                if (options.focus && typeof options.onFocusMissing === 'function') options.onFocusMissing();
            } else {
                if (mode === 'prepend') {
                    // Regrouping moved the entry on screen; keep its number and
                    // step back from it.
                    const shownIndex = Math.max(0, problemsByEntry.findIndex(entry => entry.includes(shownEntry[0])));
                    ProblemsState.setEntryNumberOffset(data.page === 1
                        ? 0
                        : ProblemsState.getEntryNumberOffset() - (shownIndex - shownIndexBefore));
                    ProblemsState.setCurrentProblemIndex(Math.max(0, shownIndex - 1));
                    ProblemsState.setCurrentEntryProblemIndex(0);
                } else if (options.focus) {
                    const focusIndex = problemsByEntry.findIndex(entry => window.ProblemsPermalink.entryMatchesFocus(entry, options.focus));
                    ProblemsState.setCurrentProblemIndex(Math.max(0, focusIndex));
                    if ((data.focus_found === false || focusIndex === -1) && typeof options.onFocusMissing === 'function') {
                        options.onFocusMissing();
                    }
                } else if (ProblemsState.getCurrentProblemIndex() === -1) {
                    ProblemsState.setCurrentProblemIndex(0);
                }
                if (window.ProblemsUI && window.ProblemsUI.displayProblem) {
                    window.ProblemsUI.displayProblem(ProblemsState.getCurrentProblemIndex());
                }
            }

            if (window.ProblemsUI && window.ProblemsUI.updateNavButtons) {
                window.ProblemsUI.updateNavButtons();
            }
            if (window.ProblemsPage && typeof window.ProblemsPage.renderFiltersSummary === 'function') {
                window.ProblemsPage.renderFiltersSummary();
            }

            ProblemsState.setIsLoadingMore(false);
        }).fail(function () {
            $('#problemTypeDisplay').text('Error loading problems.');
            ProblemsState.setIsLoadingMore(false);
        });
    }

    function initializeProblemTypeFilter() {
        const params = {};
        const selectedOperators = ProblemsState.getSelectedAtlasOperators();
        if (selectedOperators.length > 0) {
            params.atlas_operator = selectedOperators.join(',');
        }

        const selectedPriorities = getSelectedPriorities();
        if (selectedPriorities.length > 0) {
            params.priority = selectedPriorities.join(',');
        }

        $.getJSON('/api/problems/stats', params, function (stats) {
            $('#typeCountAll').text((stats.all && stats.all.all) || 0);
            $('#typeCountAttributes').text((stats.attributes && stats.attributes.all) || 0);
            $('#typeCountContradictsRouteMatching').text((stats.contradicts_route_matching && stats.contradicts_route_matching.all) || 0);
            $('#typeCountDistance').text((stats.distance && stats.distance.all) || 0);
            $('#typeCountDuplicates').text((stats.duplicates && stats.duplicates.all) || 0);
            $('#typeCountUnmatched').text((stats.unmatched && stats.unmatched.all) || 0);
            $('#typeCountDisused').text((stats.disused && stats.disused.all) || 0);
            $('#typeCountIdentifier').text((stats.identifier && stats.identifier.all) || 0);

            updateTypeButtonDisplay();
            syncPrioritySelectionUi();
        });
    }

    function prefetchNextPageIfNeeded() {
        const buffer = 20;
        const problemsByEntry = ProblemsState.getProblemsByEntry();
        const currentProblemIndex = ProblemsState.getCurrentProblemIndex();

        if (!ProblemsState.getIsLoadingMore() && hasMorePages() && (currentProblemIndex >= problemsByEntry.length - buffer)) {
            fetchProblems(ProblemsState.getCurrentPage() + 1);
        }
    }

    function navigateToNextProblem() {
        const problemsByEntry = ProblemsState.getProblemsByEntry();
        const currentProblemIndex = ProblemsState.getCurrentProblemIndex();
        const totalEntries = problemsByEntry.length;

        if (currentProblemIndex < totalEntries - 1) {
            ProblemsState.setCurrentProblemIndex(currentProblemIndex + 1);
            ProblemsState.setCurrentEntryProblemIndex(0);

            if (window.ProblemsUI && window.ProblemsUI.displayProblem) {
                window.ProblemsUI.displayProblem(ProblemsState.getCurrentProblemIndex());
            }
            if (window.ProblemsUI && window.ProblemsUI.updateNavButtons) {
                window.ProblemsUI.updateNavButtons();
            }
            prefetchNextPageIfNeeded();
        } else if (hasMorePages()) {
            if (window.ProblemsUI && window.ProblemsUI.showTemporaryMessage) {
                window.ProblemsUI.showTemporaryMessage('Loading more problems...', 'info');
            }
            fetchProblems(ProblemsState.getCurrentPage() + 1);
        } else {
            if (window.ProblemsUI && window.ProblemsUI.showTemporaryMessage) {
                window.ProblemsUI.showTemporaryMessage('You have reached the last entry for this filter combination.', 'success');
            }
        }
    }

    function navigateToPreviousProblem() {
        const currentProblemIndex = ProblemsState.getCurrentProblemIndex();
        if (currentProblemIndex > 0) {
            ProblemsState.setCurrentProblemIndex(currentProblemIndex - 1);
            ProblemsState.setCurrentEntryProblemIndex(0);
            if (window.ProblemsUI && window.ProblemsUI.displayProblem) {
                window.ProblemsUI.displayProblem(ProblemsState.getCurrentProblemIndex());
            }
            if (window.ProblemsUI && window.ProblemsUI.updateNavButtons) {
                window.ProblemsUI.updateNavButtons();
            }
        } else if (ProblemsState.getFirstLoadedPage() > 1) {
            fetchProblems(ProblemsState.getFirstLoadedPage() - 1, { prepend: true });
        }
    }

    return {
        ALL_PROBLEM_TYPES,
        PAGE_SIZE,
        hasMorePages,
        entryNumber,
        navigateToPreviousProblem,
        computeNextProblemTypeSelection,
        groupProblemsByEntry,
        updateProblemTypeFilter,
        updateTypeButtonDisplay,
        fetchProblems,
        prefetchNextPageIfNeeded,
        initializeProblemTypeFilter,
        navigateToNextProblem,
        updatePriorityFilter,
        getProblemTypeParamValue
    };
})();
