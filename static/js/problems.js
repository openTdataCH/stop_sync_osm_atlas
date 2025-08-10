// problems.js - Main JavaScript for the Problem Identification Page
// This file coordinates all the modular components

/**
 * Main Problems Page Application
 * Depends on: ProblemsState, ProblemsMap, ProblemsData, ProblemsUI, ProblemsSolutions, ProblemsNotes
 * Also depends on: OperatorDropdown, PopupRenderer, map utilities
 */

$(document).ready(function(){
    console.log("=== PROBLEMS.JS INITIALIZATION ===");
    // Helper to render/update chips consistently
    function renderProblemsChips() {
        if (!window.FilterChipUtils) return;
        window.FilterChipUtils.renderProblemChips('#problemsActiveFilters', {
            problemType: ProblemsState.getSelectedProblemType(),
            solutionFilter: ProblemsState.getCurrentSolutionFilter(),
            operators: ProblemsState.getSelectedAtlasOperators(),
            priority: ProblemsState.getSelectedPriority(),
            onClearProblemType: function() {
                ProblemsData.updateProblemTypeFilter('all', 'all');
            },
            onClearSolution: function() {
                ProblemsData.updateProblemTypeFilter(ProblemsState.getSelectedProblemType(), 'all');
            },
            onClearPriority: function() {
                ProblemsData.updatePriorityFilter('all');
                // Reflect in UI pills
                $('#priorityFilterProblems .priority-pill').removeClass('active');
                $('#priorityFilterProblems .priority-pill[data-priority="all"]').addClass('active');
            },
            onRemoveOperator: function(op) {
                const current = ProblemsState.getSelectedAtlasOperators().filter(o => o !== op);
                ProblemsState.setSelectedAtlasOperators(current);
                if (window.operatorDropdownProblems && window.operatorDropdownProblems.setSelection) {
                    window.operatorDropdownProblems.setSelection(current);
                }
                ProblemsState.resetPaginationState();
                ProblemsData.initializeProblemTypeFilter();
                ProblemsData.fetchProblems();
                renderProblemsChips();
            }
        });
    }

    
    // Initialize state management first
    ProblemsState.initializeSettings();
    
    // Initialize map
    ProblemsMap.initProblemMap();
    
    // Initialize UI components
    ProblemsUI.setupIntersectionObserver();
    
    // Initialize operator dropdown for problems page
    window.operatorDropdownProblems = new OperatorDropdown('#atlasOperatorFilterProblems', {
        placeholder: 'Select operators...',
        multiple: true,
        onSelectionChange: function(selectedOperators) {
            ProblemsState.setSelectedAtlasOperators(selectedOperators);
            
            // Reset problems and pagination when operator filter changes
            ProblemsState.resetPaginationState();
            
            // Reload data with new operator filter
            ProblemsData.initializeProblemTypeFilter(); // Update stats
            ProblemsData.fetchProblems(); // Fetch filtered problems
            renderProblemsChips();
        }
    });
    
    // Load auto-persist settings and update UI
    $('#autoPersistToggle').prop('checked', ProblemsState.getAutoPersistEnabled());
    $('#autoPersistNotesToggle').prop('checked', ProblemsState.getAutoPersistNotesEnabled());
    
    // Initialize filters and data
    ProblemsData.initializeProblemTypeFilter(); // Fetch stats and build filter
    ProblemsData.fetchProblems(); // Initial fetch for "All" problems

    // Initial chips render
    renderProblemsChips();
    
    // Initialize UI components
    ProblemsMap.initializeResize();
    ProblemsMap.initializeFilterToggle();
    
    // Show keyboard hint after page loads
    setTimeout(() => {
        ProblemsUI.showKeyboardHint();
    }, 2000);

    // ====== EVENT HANDLERS ======
    // Manual matching action buttons
    $('#actionButtonsContent').on('click', 'button[data-action="manual-match-atlas"]', function() {
        const currentProblem = ProblemsState.getCurrentProblem();
        if (!currentProblem) return;
        // Ensure context markers are visible for selecting the opposite entry
        try {
            if (typeof ProblemsState !== 'undefined' && ProblemsState.getShowContext && !ProblemsState.getShowContext()) {
                if (window.ProblemsMap && typeof window.ProblemsMap.toggleContext === 'function') {
                    window.ProblemsMap.toggleContext();
                }
            }
        } catch (e) {}
        showPersistentManualMatchBanner('atlas', currentProblem.stop_id);
    });

    $('#actionButtonsContent').on('click', 'button[data-action="manual-match-osm"]', function() {
        const currentProblem = ProblemsState.getCurrentProblem();
        if (!currentProblem) return;
        // Ensure context markers are visible for selecting the opposite entry
        try {
            if (typeof ProblemsState !== 'undefined' && ProblemsState.getShowContext && !ProblemsState.getShowContext()) {
                if (window.ProblemsMap && typeof window.ProblemsMap.toggleContext === 'function') {
                    window.ProblemsMap.toggleContext();
                }
            }
        } catch (e) {}
        showPersistentManualMatchBanner('osm', currentProblem.stop_id);
    });

    // Helper: persistent banner for manual matching selection, with cancel
    function showPersistentManualMatchBanner(fromType, stopId) {
        // Remove existing banner if any
        $('.manual-match-banner').remove();
        window.manualMatchContext = { from: fromType, stopId: stopId };
        const targetText = fromType === 'atlas' ? 'Select an OSM entry to complete the match' : 'Select an ATLAS entry to complete the match';
        const banner = $(`
            <div class="manual-match-banner alert alert-info" role="alert" style="position:fixed; top:10px; left:50%; transform:translateX(-50%); z-index:2000;">
                ${targetText}
                <button type="button" class="btn btn-sm btn-outline-secondary ml-2" id="cancelManualMatch">Cancel</button>
            </div>
        `);
        $('body').append(banner);
        $('#cancelManualMatch').on('click', function(){
            window.manualMatchContext = null;
            $('.manual-match-banner').remove();
            if (typeof window.updateManualMatchButtonsUI === 'function') {
                window.updateManualMatchButtonsUI();
            }
        });
        if (typeof window.updateManualMatchButtonsUI === 'function') {
            window.updateManualMatchButtonsUI();
        }
    }

    // Navigation buttons
    $('#prevProblemBtn').on('click', function() {
        const currentIndex = ProblemsState.getCurrentProblemIndex();
        if (currentIndex > 0) {
            ProblemsState.setCurrentProblemIndex(currentIndex - 1);
            ProblemsState.setCurrentEntryProblemIndex(0); // Reset to first problem in new entry
            ProblemsUI.displayProblem(ProblemsState.getCurrentProblemIndex());
            ProblemsUI.updateNavButtons();
        }
    });

    // Priority selection is handled inside the dropdown via ProblemsData.initializeProblemTypeFilter

    $('#nextProblemBtn').on('click', function() {
        ProblemsData.navigateToNextProblem();
    });
    
    // Auto-persist toggle handler
    $('#autoPersistToggle').on('change', function() {
        const enabled = $(this).is(':checked');
        ProblemsState.setAutoPersistEnabled(enabled);
        
        if (enabled) {
            ProblemsUI.showTemporaryMessage('Auto-persist enabled: Solutions will be saved as persistent data <i class="fas fa-database"></i>', 'info');
        } else {
            ProblemsUI.showTemporaryMessage('Auto-persist disabled: Solutions will be saved temporarily <i class="fas fa-clock"></i>', 'info');
        }
    });

    // Auto-persist notes toggle handler
    $('#autoPersistNotesToggle').on('change', function() {
        const enabled = $(this).is(':checked');
        ProblemsState.setAutoPersistNotesEnabled(enabled);
        
        if (enabled) {
            ProblemsUI.showTemporaryMessage('Auto-persist notes enabled: Notes will be saved as persistent data <i class="fas fa-database"></i>', 'info');
        } else {
            ProblemsUI.showTemporaryMessage('Auto-persist notes disabled: Notes will be saved temporarily <i class="fas fa-clock"></i>', 'info');
        }
    });
    
    // Context toggle button click handler
    $('#toggleContextBtn').on('click', ProblemsMap.toggleContext);
    
    // Problem type filter dropdown handler
    $(document).on('click', '.problem-type-option', function(e) {
        e.preventDefault();
        const selectedType = $(this).data('type');
        const solutionFilter = $(this).data('solution-filter') || 'all';
        ProblemsData.updateProblemTypeFilter(selectedType, solutionFilter);
        $('#problemTypeFilterCollapse').collapse('hide');
    });
    
    // Sorting option click handler
    $(document).on('click', '.sort-option', function(e) {
        e.preventDefault();
        const sortBy = $(this).data('sort-by');
        const sortOrder = $(this).data('sort-order');
        ProblemsData.updateSorting(sortBy, sortOrder);
    });
    
    // Solution button click handlers
    $('#actionButtonsContent').on('click', '.solution-btn', function() {
        console.log("=== SOLUTION BUTTON CLICKED ===");
        
        const issueContainer = $(this).closest('.issue-container');
        const problemId = issueContainer.data('problem-id');
        const currentEntryProblems = ProblemsState.getCurrentEntryProblems();
        // For grouped duplicates problems, id is a string group id. Otherwise numeric.
        const problem = currentEntryProblems.find(p => String(p.id) === String(problemId));
        
        if (!problem) {
            ProblemsUI.showTemporaryMessage('Could not find problem data.', 'error');
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
            // If this is a duplicates group action on a member row, send it for that member's stop_id
            const targetStopId = $(this).data('target-stop-id');
            if (problem.problem === 'duplicates' && targetStopId) {
                // Forward directly to save for member stop
                ProblemsSolutions.saveSolutionForStopId(this, targetStopId, 'duplicates', solution);
                return;
            }
        }
        
        console.log("Saving solution:", solution);
        
        if (problem && solution !== undefined) {
            ProblemsSolutions.saveSolution(this, problem.problem, solution);
        } else {
            console.error("Missing problem or solution data", { problem, solution });
            ProblemsUI.showTemporaryMessage('Missing problem or solution data', 'error');
        }
    });
    
    // Make persistent button handler
    $('#actionButtonsContent').on('click', '.make-persistent-btn', function() {
        console.log("=== MAKE PERSISTENT BUTTON CLICKED ===");
        const problemId = $(this).data('problem-id');
        const problemType = $(this).data('problem-type');
        ProblemsSolutions.makeSolutionPersistent(problemId, problemType);
    });
    
    // Clear solution button handler
    $('#actionButtonsContent').on('click', '.clear-solution-btn', function() {
        console.log("=== CLEAR SOLUTION BUTTON CLICKED ===");
        const problemId = $(this).data('problem-id');
        const allProblems = ProblemsState.getAllProblems();
        const problem = allProblems.find(p => p.id === problemId);
        if (problem) {
            console.log("Clear solution for problem:", problem);
            ProblemsSolutions.clearSolution(problem);
        } else {
            console.error("Could not find problem with id:", problemId);
        }
    });
    
    // Note saving handler (delegate once)
    $(document).on('click', '#saveAtlasNote', function() {
        const noteContent = $('#atlasNote').val();
        ProblemsNotes.saveNote('atlas', noteContent);
    });
    $(document).on('click', '#saveOsmNote', function() {
        const noteContent = $('#osmNote').val();
        ProblemsNotes.saveNote('osm', noteContent);
    });
    
    // Keyboard shortcuts for faster problem solving
    $(document).on('keydown', function(e) {
        // Only activate shortcuts when not in input fields
        if (!$(e.target).is('input, textarea, select')) {
            ProblemsUI.hideKeyboardHint(); // Hide hint when user starts using shortcuts
            
            switch(e.key) {
                case 'ArrowRight':
                case ' ': // Spacebar
                    e.preventDefault();
                    ProblemsData.navigateToNextProblem();
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
                        ProblemsUI.hideKeyboardHint();
                    } else {
                        ProblemsUI.showKeyboardHint();
                    }
                    break;
            }
        }
    });
});
