// problems-data.js - Data fetching and processing for the Problem Identification Page

window.ProblemsData = (function () {
    'use strict';

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

        let buttonText;
        if (isAllProblemTypesSelected(selectedTypes)) {
            buttonText = 'Type: All';
        } else if (selectedTypes.length === 1) {
            const label = selectedTypes[0] === 'identifier'
                ? `OSM ${SharedUtils.sourceIdLabel()}`
                : selectedTypes[0].replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
            buttonText = `Type: ${label}`;
        } else {
            buttonText = `Type: ${selectedTypes.length} selected`;
        }
        setText('typeFilterButtonProblems', buttonText);

        setChecked('filterProblemTypeAll', isAllProblemTypesSelected(selectedTypes));
        setChecked('filterProblemTypeAttributes', effectiveSelectedTypes.includes('attributes'));
        setChecked('filterProblemTypeContradictsRouteMatching', effectiveSelectedTypes.includes('contradicts_route_matching'));
        setChecked('filterProblemTypeDistance', effectiveSelectedTypes.includes('distance'));
        setChecked('filterProblemTypeDuplicates', effectiveSelectedTypes.includes('duplicates'));
        setChecked('filterProblemTypeUnmatched', effectiveSelectedTypes.includes('unmatched'));
        setChecked('filterProblemTypeDisused', effectiveSelectedTypes.includes('disused'));
        setChecked('filterProblemTypeIdentifier', effectiveSelectedTypes.includes('identifier'));
    }

    function setText(id, text) {
        const element = document.getElementById(id);
        if (element) element.textContent = text;
    }

    function setChecked(id, checked) {
        const element = document.getElementById(id);
        if (element) element.checked = checked;
    }

    function syncPrioritySelectionUi() {
        const selectedPriorities = getSelectedPriorities();
        const circle = priority => document.querySelector(`#priorityFilterProblems .priority-option[data-priority="${priority}"] .priority-circle`);
        document.querySelectorAll('#priorityFilterProblems .priority-circle').forEach(item => item.classList.remove('selected'));
        (selectedPriorities.length ? selectedPriorities : ['all']).forEach(pr => {
            const selected = circle(pr);
            if (selected) selected.classList.add('selected');
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

    // The operator, priority and area filters that both the list and the type
    // counts are requested with; fetchJson leaves out the empty ones.
    function filterParams() {
        const area = ProblemsState.getArea();
        return {
            atlas_operator: ProblemsState.getSelectedAtlasOperators().join(','),
            priority: getSelectedPriorities().join(','),
            bbox: area ? ProblemsArea.formatArea(area) : ''
        };
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
        setText('problemTypeDisplay', 'Loading...');
        const mode = options.prepend ? 'prepend' : (options.focus || page === 1 ? 'fresh' : 'append');

        const params = {
            page: page,
            limit: PAGE_SIZE,
            problem_type: getProblemTypeParamValue(),
            include_routes: 1,
            ...filterParams()
        };
        if (options.focus) {
            if (options.focus.sloid) params.focus_sloid = options.focus.sloid;
            if (options.focus.osm_node_id) params.focus_osm_node_id = options.focus.osm_node_id;
        }

        SharedUtils.fetchJson('/api/problems', params).then(function (data) {
            if (data.error) {
                setText('problemTypeDisplay', 'Error loading problems.');
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
                setText('problemTypeDisplay', 'No problems found for this filter combination.');
                document.getElementById('actionButtonsContent').innerHTML = '';
                ProblemsUI.updateFloatingChips(null);
                ProblemsState.setCurrentEntryProblems([]);
                ProblemsPermalink.sync();

                const markersLayer = ProblemsState.getProblemMarkersLayer();
                const linesLayer = ProblemsState.getProblemLinesLayer();
                if (markersLayer) markersLayer.clearLayers();
                if (linesLayer) linesLayer.clearLayers();
                ProblemsMap.releaseView();
                ProblemsMap.clearContextData();
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
                    const focusIndex = problemsByEntry.findIndex(entry => ProblemsPermalink.entryMatchesFocus(entry, options.focus));
                    ProblemsState.setCurrentProblemIndex(Math.max(0, focusIndex));
                    if ((data.focus_found === false || focusIndex === -1) && typeof options.onFocusMissing === 'function') {
                        options.onFocusMissing();
                    }
                } else if (ProblemsState.getCurrentProblemIndex() === -1) {
                    ProblemsState.setCurrentProblemIndex(0);
                }
                ProblemsUI.displayProblem(ProblemsState.getCurrentProblemIndex());
            }

            ProblemsUI.updateNavButtons();
            ProblemsPage.renderFiltersSummary();

            ProblemsState.setIsLoadingMore(false);
        }, function () {
            setText('problemTypeDisplay', 'Error loading problems.');
            ProblemsState.setIsLoadingMore(false);
        });
    }

    function initializeProblemTypeFilter() {
        SharedUtils.fetchJson('/api/problems/stats', filterParams()).then(function (stats) {
            const count = type => String((stats[type] && stats[type].all) || 0);
            setText('typeCountAll', count('all'));
            setText('typeCountAttributes', count('attributes'));
            setText('typeCountContradictsRouteMatching', count('contradicts_route_matching'));
            setText('typeCountDistance', count('distance'));
            setText('typeCountDuplicates', count('duplicates'));
            setText('typeCountUnmatched', count('unmatched'));
            setText('typeCountDisused', count('disused'));
            setText('typeCountIdentifier', count('identifier'));

            updateTypeButtonDisplay();
            syncPrioritySelectionUi();
        }, function (error) {
            console.warn('Could not load the problem counts:', error);
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

            ProblemsUI.displayProblem(ProblemsState.getCurrentProblemIndex());
            ProblemsUI.updateNavButtons();
            prefetchNextPageIfNeeded();
        } else if (hasMorePages()) {
            SharedUtils.showTemporaryMessage('Loading more problems...', 'info');
            fetchProblems(ProblemsState.getCurrentPage() + 1);
        } else {
            SharedUtils.showTemporaryMessage('You have reached the last entry for this filter combination.', 'success');
        }
    }

    function navigateToPreviousProblem() {
        const currentProblemIndex = ProblemsState.getCurrentProblemIndex();
        if (currentProblemIndex > 0) {
            ProblemsState.setCurrentProblemIndex(currentProblemIndex - 1);
            ProblemsState.setCurrentEntryProblemIndex(0);
            ProblemsUI.displayProblem(ProblemsState.getCurrentProblemIndex());
            ProblemsUI.updateNavButtons();
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
