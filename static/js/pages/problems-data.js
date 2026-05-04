// problems-data.js - Data fetching and processing for the Problem Identification Page

window.ProblemsData = (function () {
    'use strict';

    const DEFAULT_SORT_BY = 'priority';
    const DEFAULT_SORT_ORDER = 'asc';

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

    function getPriorityParamValue() {
        const selectedPriorities = getSelectedPriorities();
        if (!selectedPriorities.length) return 'all';
        return selectedPriorities.join(',');
    }

    function updateCountBadge(total) {
        const countText = `${total} ${total === 1 ? 'entry' : 'entries'}`;
        $('#problemsResultsCount').text(countText);
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
        if (!selectedTypes.length) {
            $('#typeFilterButtonProblems').text('Type: All');
        } else if (selectedTypes.length === 1) {
            const label = selectedTypes[0].replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
            $('#typeFilterButtonProblems').text(`Type: ${label}`);
        } else {
            $('#typeFilterButtonProblems').text(`Type: ${selectedTypes.length} selected`);
        }

        $('#filterProblemTypeAll').prop('checked', selectedTypes.length === 0);
        $('#filterProblemTypeAttributes').prop('checked', selectedTypes.includes('attributes'));
        $('#filterProblemTypeDistance').prop('checked', selectedTypes.includes('distance'));
        $('#filterProblemTypeDuplicates').prop('checked', selectedTypes.includes('duplicates'));
        $('#filterProblemTypeUnmatched').prop('checked', selectedTypes.includes('unmatched'));
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
        let next = [];

        if (newType === 'all') {
            next = [];
        } else {
            if (isChecked) {
                next = current.includes(newType) ? current : current.concat([newType]);
            } else {
                next = current.filter(t => t !== newType);
            }
        }

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

    function fetchProblems(page = 1) {
        if (ProblemsState.getIsLoadingMore()) return;
        ProblemsState.setIsLoadingMore(true);
        $('#problemTypeDisplay').text('Loading...');

        const params = {
            page: page,
            limit: 100,
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

        $.getJSON('/api/problems', params, function (data) {
            if (data.error) {
                $('#problemTypeDisplay').text('Error loading problems.');
                ProblemsState.setIsLoadingMore(false);
                return;
            }

            if (page === 1) {
                ProblemsState.setAllProblems(data.problems);
                ProblemsState.setTotalProblems(data.total);
            } else {
                ProblemsState.addProblems(data.problems);
            }

            ProblemsState.setCurrentPage(data.page);
            updateCountBadge(ProblemsState.getTotalProblems());

            const problemsByEntry = groupProblemsByEntry(ProblemsState.getAllProblems());
            ProblemsState.setProblemsByEntry(problemsByEntry);

            const allProblems = ProblemsState.getAllProblems();
            if (allProblems.length === 0) {
                $('#problemTypeDisplay').text('No problems found for this filter combination.');
                $('#actionButtonsContent').empty();
                $('#actionButtonsContent').find('.scroll-indicator').remove();

                const markersLayer = ProblemsState.getProblemMarkersLayer();
                const linesLayer = ProblemsState.getProblemLinesLayer();
                const contextLayer = ProblemsState.getContextMarkersLayer();
                if (markersLayer) markersLayer.clearLayers();
                if (linesLayer) linesLayer.clearLayers();
                if (contextLayer) contextLayer.clearLayers();
            } else {
                if (ProblemsState.getCurrentProblemIndex() === -1) {
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
            $('#typeCountDistance').text((stats.distance && stats.distance.all) || 0);
            $('#typeCountDuplicates').text((stats.duplicates && stats.duplicates.all) || 0);
            $('#typeCountUnmatched').text((stats.unmatched && stats.unmatched.all) || 0);

            updateTypeButtonDisplay();
            syncPrioritySelectionUi();
        });
    }

    function prefetchNextPageIfNeeded() {
        const buffer = 20;
        const allProblems = ProblemsState.getAllProblems();
        const totalProblems = ProblemsState.getTotalProblems();
        const currentProblemIndex = ProblemsState.getCurrentProblemIndex();
        const hasMorePages = allProblems.length < totalProblems;

        if (!ProblemsState.getIsLoadingMore() && hasMorePages && (currentProblemIndex >= allProblems.length - buffer)) {
            fetchProblems(ProblemsState.getCurrentPage() + 1);
        }
    }

    function navigateToNextProblem() {
        const problemsByEntry = ProblemsState.getProblemsByEntry();
        const currentProblemIndex = ProblemsState.getCurrentProblemIndex();
        const allProblems = ProblemsState.getAllProblems();
        const totalProblems = ProblemsState.getTotalProblems();
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
        } else if (allProblems.length < totalProblems) {
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

    return {
        groupProblemsByEntry,
        updateProblemTypeFilter,
        fetchProblems,
        prefetchNextPageIfNeeded,
        initializeProblemTypeFilter,
        navigateToNextProblem,
        updatePriorityFilter,
        updateCountBadge,
        getProblemTypeParamValue,
        getPriorityParamValue
    };
})();
