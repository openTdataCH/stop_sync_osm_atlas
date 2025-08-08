// problems-data.js - Data fetching and processing for the Problem Identification Page

/**
 * ProblemsData - Data fetching, processing, and filtering functionality
 * Depends on: ProblemsState
 */
window.ProblemsData = (function() {
    'use strict';

    /**
     * Group problems by entry (same location/stop)
     */
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

    /**
     * Filter problems by type with support for solved/unsolved
     * This will now mainly be used for client-side display counts, as filtering is done on the backend
     */
    function filterProblemsOnClient(problems, problemType, solutionFilter = 'all') {
        let filtered = [];
        
        if (problemType === 'all') {
            filtered = ProblemsState.getAllProblems();
        } else {
            filtered = ProblemsState.getAllProblems().filter(problem => problem.problem === problemType);
        }
        
        // Apply solution filter
        if (solutionFilter === 'solved') {
            filtered = filtered.filter(problem => problem.solution && problem.solution.trim() !== '');
        } else if (solutionFilter === 'unsolved') {
            filtered = filtered.filter(problem => !problem.solution || problem.solution.trim() === '');
        }
        
        return filtered;
    }

    /**
     * Update the problem type filter
     */
    function updateProblemTypeFilter(newType, solutionFilter = 'all') {
        ProblemsState.setSelectedProblemType(newType);
        ProblemsState.setCurrentSolutionFilter(solutionFilter);

        // Reset problems and pagination
        ProblemsState.clearAllProblems();
        ProblemsState.setCurrentPage(1);
        ProblemsState.setTotalProblems(0);
        ProblemsState.setCurrentProblemIndex(-1);
        
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

    /**
     * Update sorting options visibility based on problem type
     */
    function updateSortingOptionsVisibility(problemType) {
        const sortingControls = $('#sortingControls');
        if (problemType === 'distance') {
            sortingControls.show();
        } else {
            sortingControls.hide();
            // Reset to default sorting when hiding
            ProblemsState.setCurrentSortBy('default');
            ProblemsState.setCurrentSortOrder('asc');
            updateSortingButtonDisplay();
        }
    }

    /**
     * Update sorting button display
     */
    function updateSortingButtonDisplay() {
        const sortButton = $('#sortButton');
        const currentSortBy = ProblemsState.getCurrentSortBy();
        const currentSortOrder = ProblemsState.getCurrentSortOrder();
        
        if (currentSortBy === 'distance') {
            const orderText = currentSortOrder === 'asc' ? 'Nearest First' : 'Farthest First';
            const orderIcon = currentSortOrder === 'asc' ? 'fas fa-sort-numeric-down' : 'fas fa-sort-numeric-up';
            sortButton.html(`<i class="${orderIcon}"></i> ${orderText}`);
        } else {
            sortButton.html('<i class="fas fa-sort"></i> Default Order');
        }
    }

    /**
     * Update sorting
     */
    function updateSorting(sortBy, sortOrder) {
        ProblemsState.setCurrentSortBy(sortBy);
        ProblemsState.setCurrentSortOrder(sortOrder);
        
        // Reset problems and pagination
        ProblemsState.clearAllProblems();
        ProblemsState.setCurrentPage(1);
        ProblemsState.setTotalProblems(0);
        ProblemsState.setCurrentProblemIndex(-1);
        
        // Update button display
        updateSortingButtonDisplay();
        
        // Fetch the first page with new sorting
        fetchProblems();
    }

    /**
     * Fetch problems from the backend on page load or when filters change
     */
    function fetchProblems(page = 1) {
        if (ProblemsState.getIsLoadingMore()) return;
        ProblemsState.setIsLoadingMore(true);
        $('#problemTypeDisplay').text('Loading...');

        const params = {
            page: page,
            limit: 100,
            problem_type: ProblemsState.getSelectedProblemType(),
            solution_status: ProblemsState.getCurrentSolutionFilter(),
            sort_by: ProblemsState.getCurrentSortBy(),
            sort_order: ProblemsState.getCurrentSortOrder()
        };
        
        // Add operator filter if operators are selected
        const selectedOperators = ProblemsState.getSelectedAtlasOperators();
        if (selectedOperators.length > 0) {
            params.atlas_operator = selectedOperators.join(',');
        }

        $.getJSON("/api/problems", params, function(data) {
            if (data.error) {
                console.error("Error fetching problems:", data.error);
                $('#problemTypeDisplay').text("Error loading problems.");
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

            // Group problems by entry
            const problemsByEntry = groupProblemsByEntry(ProblemsState.getAllProblems());
            ProblemsState.setProblemsByEntry(problemsByEntry);
            
            const allProblems = ProblemsState.getAllProblems();
            if (allProblems.length === 0) {
                const selectedProblemType = ProblemsState.getSelectedProblemType();
                const problemTypeDisplayText = selectedProblemType === 'all' ? 'problems' : 
                                             `${selectedProblemType.replace(/_/g, ' ')} problems`;
                $('#problemTypeDisplay').text(`No more ${problemTypeDisplayText}, good job!`);
                $('#actionButtonsContent').empty();
                const markersLayer = ProblemsState.getProblemMarkersLayer();
                const linesLayer = ProblemsState.getProblemLinesLayer();
                const contextLayer = ProblemsState.getContextMarkersLayer();
                if (markersLayer) markersLayer.clearLayers();
                if (linesLayer) linesLayer.clearLayers();
                if (contextLayer) contextLayer.clearLayers();
            } else {
                const currentIndex = ProblemsState.getCurrentProblemIndex();
                if (currentIndex === -1) {
                    ProblemsState.setCurrentProblemIndex(0);
                }
                // Note: displayProblem will be called from the UI module
                if (window.ProblemsUI && window.ProblemsUI.displayProblem) {
                    window.ProblemsUI.displayProblem(ProblemsState.getCurrentProblemIndex());
                }
            }
            
            // Note: updateNavButtons will be called from the UI module
            if (window.ProblemsUI && window.ProblemsUI.updateNavButtons) {
                window.ProblemsUI.updateNavButtons();
            }
            ProblemsState.setIsLoadingMore(false);
        }).fail(function() {
            $('#problemTypeDisplay').text('Error loading problems.');
            ProblemsState.setIsLoadingMore(false);
        });
    }

    /**
     * Pre-fetch next page of problems if user is nearing the end of the current list
     */
    function prefetchNextPageIfNeeded() {
        const buffer = 20; // Load next page when user is 20 problems away from the end
        const allProblems = ProblemsState.getAllProblems();
        const totalProblems = ProblemsState.getTotalProblems();
        const currentProblemIndex = ProblemsState.getCurrentProblemIndex();
        const hasMorePages = allProblems.length < totalProblems;

        if (!ProblemsState.getIsLoadingMore() && hasMorePages && (currentProblemIndex >= allProblems.length - buffer)) {
            fetchProblems(ProblemsState.getCurrentPage() + 1);
        }
    }

    /**
     * Initialize the problem type filter dropdown using data from the new stats endpoint
     */
    function initializeProblemTypeFilter() {
        const params = {};
        
        // Include operator filter in stats request
        const selectedOperators = ProblemsState.getSelectedAtlasOperators();
        if (selectedOperators.length > 0) {
            params.atlas_operator = selectedOperators.join(',');
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

    /**
     * Navigate to next problem
     */
    function navigateToNextProblem() {
        const problemsByEntry = ProblemsState.getProblemsByEntry();
        const currentProblemIndex = ProblemsState.getCurrentProblemIndex();
        const allProblems = ProblemsState.getAllProblems();
        const totalProblems = ProblemsState.getTotalProblems();
        const totalEntries = problemsByEntry.length;
        
        if (currentProblemIndex < totalEntries - 1) {
            ProblemsState.setCurrentProblemIndex(currentProblemIndex + 1);
            ProblemsState.setCurrentEntryProblemIndex(0); // Reset to first issue in the new entry
            
            if (window.ProblemsUI && window.ProblemsUI.displayProblem) {
                window.ProblemsUI.displayProblem(ProblemsState.getCurrentProblemIndex());
            }
            if (window.ProblemsUI && window.ProblemsUI.updateNavButtons) {
                window.ProblemsUI.updateNavButtons();
            }
            prefetchNextPageIfNeeded();
        } else if (allProblems.length < totalProblems) {
            // We are at the end of the loaded list, but more problems exist on the server
            if (window.ProblemsUI && window.ProblemsUI.showTemporaryMessage) {
                window.ProblemsUI.showTemporaryMessage('Loading more problems...', 'info');
            }
            fetchProblems(ProblemsState.getCurrentPage() + 1);
        } else {
            // Truly the last problem
            if (window.ProblemsUI && window.ProblemsUI.showTemporaryMessage) {
                window.ProblemsUI.showTemporaryMessage("You've reached the last problem! Great work!", 'success');
            }
        }
    }

    // Public API
    return {
        groupProblemsByEntry,
        filterProblemsOnClient,
        updateProblemTypeFilter,
        updateSortingOptionsVisibility,
        updateSortingButtonDisplay,
        updateSorting,
        fetchProblems,
        prefetchNextPageIfNeeded,
        initializeProblemTypeFilter,
        navigateToNextProblem
    };
})();
