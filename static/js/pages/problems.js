// problems.js - Main JavaScript for the Problem Identification Page
// This file coordinates all the modular components

/**
 * Main Problems Page Application
 * Depends on: ProblemsState, ProblemsMap, ProblemsData, ProblemsUI, ProblemsSolutions
 * Also depends on: OperatorDropdown, PopupRenderer, map utilities
 */

$(document).ready(function () {
    console.log("=== PROBLEMS.JS INITIALIZATION ===");
    // Enable Bootstrap tooltips (for persistence info icon)
    if (typeof $ !== 'undefined' && typeof $.fn.tooltip === 'function') {
        $('[data-toggle="tooltip"]').tooltip({ container: 'body', trigger: 'hover focus' });
    }
    // Ensure left panel and map fit viewport; adjust scrollable heights accordingly
    function setMainLayoutHeights() {
        const root = $('.problems-page-root');
        if (root.length === 0) return;
        const viewportH = window.innerHeight || document.documentElement.clientHeight;
        const rootTop = root.offset() ? root.offset().top : 0;
        const desiredHeight = Math.max(300, viewportH - rootTop); // safety minimum
        root.css('height', desiredHeight + 'px');
        // Force Leaflet map to reflow after size changes
        setTimeout(() => {
            if (window.ProblemsMap && window.ProblemsMap.invalidateMapSize) {
                try { window.ProblemsMap.invalidateMapSize(); } catch (e) { }
            } else if (typeof L !== 'undefined' && ProblemsState.getProblemMap()) {
                try { ProblemsState.getProblemMap().invalidateSize(); } catch (e) { }
            }
        }, 0);
        // Recompute dropdown height too
        setTimeout(computeProblemTypeDropdownMaxHeight, 0);
    }
    // Keep the persistence options visible by constraining the dropdown height dynamically
    function computeProblemTypeDropdownMaxHeight() {
        const panel = $('.filter-panel');
        const header = panel.find('.filter-header');
        const fixed = panel.find('.filter-fixed-controls');
        const body = panel.find('.filter-body');
        const dropdownWrapper = $('#problemTypeFilterCollapse');
        const dropdown = $('#problemTypeFilterDropdown');
        if (panel.length === 0 || body.length === 0 || dropdownWrapper.length === 0 || dropdown.length === 0) return;

        const containerHeight = panel.innerHeight();
        const headerHeight = header.outerHeight(true) || 0;
        const fixedHeight = fixed.outerHeight(true) || 0;
        const bodyPaddingTop = parseFloat(body.css('padding-top')) || 0;
        const bodyPaddingBottom = parseFloat(body.css('padding-bottom')) || 0;
        const bodyVerticalPadding = bodyPaddingTop + bodyPaddingBottom;
        // Position of the dropdown start within the scrollable body viewport
        const bodyScrollTop = body.scrollTop();
        const dropdownTopInBody = dropdownWrapper.position() ? dropdownWrapper.position().top - bodyScrollTop : 0;

        // Available space inside the body area, ensuring fixed controls remain visible
        const availableBodySpace = containerHeight - headerHeight - fixedHeight - bodyVerticalPadding - 12; // small safety margin
        const maxHeight = Math.max(120, availableBodySpace - dropdownTopInBody);
        dropdown.css({ maxHeight: maxHeight + 'px', overflowY: 'auto' });
    }
    // Helper to render/update chips consistently
    function renderProblemsChips() {
        window.FilterChipUtils.renderProblemChips('#problemsActiveFilters', {
            problemType: ProblemsState.getSelectedProblemType(),
            solutionFilter: ProblemsState.getCurrentSolutionFilter(),
            operators: ProblemsState.getSelectedAtlasOperators(),
            priority: ProblemsState.getSelectedPriority(),
            onClearProblemType: function () {
                ProblemsData.updateProblemTypeFilter('all', 'all');
            },
            onClearSolution: function () {
                ProblemsData.updateProblemTypeFilter(ProblemsState.getSelectedProblemType(), 'all');
            },
            onClearPriority: function () {
                ProblemsData.updatePriorityFilter('all');
                // Reflect in UI pills
                $('#priorityFilterProblems .priority-pill').removeClass('active');
                $('#priorityFilterProblems .priority-pill[data-priority="all"]').addClass('active');
            },
            onRemoveOperator: function (op) {
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
        onSelectionChange: function (selectedOperators) {
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
    // If inputs are disabled (anonymous), force them visually off
    if ($('#autoPersistToggle').is(':disabled')) {
        $('#autoPersistToggle').prop('checked', false);
    }

    // If toggles are disabled in the DOM (anonymous user), show a login hint on click
    function attachDisabledToggleHint(selector, itemLabel) {
        const el = $(selector);
        if (el.is(':disabled')) {
            const label = $('label[for="' + el.attr('id') + '"]');
            const handler = function (e) {
                e.preventDefault();
                if (window.ProblemsUI && typeof window.ProblemsUI.showTemporaryMessage === 'function') {
                    window.ProblemsUI.showTemporaryMessage('To make ' + itemLabel + ' persistent, please log in.', 'info');
                } else {
                    alert('To make ' + itemLabel + ' persistent, please log in.');
                }
            };
            // Bind both the input and its label to catch clicks
            el.on('click', handler);
            label.on('click', handler);
        }
    }
    attachDisabledToggleHint('#autoPersistToggle', 'solutions');

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

    // Recompute dropdown height when the dropdown opens/closes and on resize
    $(document).on('shown.bs.collapse show.bs.collapse', '#problemTypeFilterCollapse', function () {
        setTimeout(computeProblemTypeDropdownMaxHeight, 0);
    });
    $(window).on('resize', function () {
        setMainLayoutHeights();
        computeProblemTypeDropdownMaxHeight();
    });
    // Also recompute after the filter panel toggles width (collapse/expand)
    $('#filterToggleBtn').on('click', function () { setTimeout(computeProblemTypeDropdownMaxHeight, 310); }); // after CSS transition
    // Initial computation
    setTimeout(function () {
        setMainLayoutHeights();
        computeProblemTypeDropdownMaxHeight();
    }, 300);

    // ====== EVENT HANDLERS ======
    // Navigation buttons
    $('#prevProblemBtn').on('click', function () {
        const currentIndex = ProblemsState.getCurrentProblemIndex();
        if (currentIndex > 0) {
            ProblemsState.setCurrentProblemIndex(currentIndex - 1);
            ProblemsState.setCurrentEntryProblemIndex(0); // Reset to first problem in new entry
            ProblemsUI.displayProblem(ProblemsState.getCurrentProblemIndex());
            ProblemsUI.updateNavButtons();
        }
    });

    // Priority selection is handled inside the dropdown via ProblemsData.initializeProblemTypeFilter

    $('#nextProblemBtn').on('click', function () {
        ProblemsData.navigateToNextProblem();
    });

    // Auto-persist toggle handler
    $('#autoPersistToggle').on('change', function () {
        const enabled = $(this).is(':checked');
        ProblemsState.setAutoPersistEnabled(enabled);

        if (enabled) {
            ProblemsUI.showTemporaryMessage('Auto-persist enabled: Solutions will be saved as persistent data <i class="fas fa-database"></i>', 'info');
        } else {
            ProblemsUI.showTemporaryMessage('Auto-persist disabled: Solutions will be saved temporarily <i class="fas fa-clock"></i>', 'info');
        }
    });

    // Context toggle button click handler
    $('#toggleContextBtn').on('click', ProblemsMap.toggleContext);

    // Problem type filter dropdown handler
    $(document).on('click', '.problem-type-option', function (e) {
        e.preventDefault();
        const selectedType = $(this).data('type');
        const solutionFilter = $(this).data('solution-filter') || 'all';
        ProblemsData.updateProblemTypeFilter(selectedType, solutionFilter);
        $('#problemTypeFilterCollapse').collapse('hide');
    });

    // Sorting option click handler
    $(document).on('click', '.sort-option', function (e) {
        e.preventDefault();
        const sortBy = $(this).data('sort-by');
        const sortOrder = $(this).data('sort-order');
        ProblemsData.updateSorting(sortBy, sortOrder);
    });

    // Solution button click handlers
    $('#actionButtonsContent').on('click', '.solution-btn', function () {
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
                } catch (e) { /* ignore parse error */ }
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
    $('#actionButtonsContent').on('click', '.make-persistent-btn', function () {
        console.log("=== MAKE PERSISTENT BUTTON CLICKED ===");
        const problemId = $(this).data('problem-id');
        const problemType = $(this).data('problem-type');
        ProblemsSolutions.makeSolutionPersistent(problemId, problemType);
    });

    // Make persistent duplicates button handler
    $('#actionButtonsContent').on('click', '.make-persistent-duplicates-btn', function () {
        console.log("=== MAKE PERSISTENT DUPLICATES BUTTON CLICKED ===");
        const problemId = $(this).data('problem-id');
        const problemType = $(this).data('problem-type');
        const currentEntryProblems = ProblemsState.getCurrentEntryProblems();
        const problem = currentEntryProblems.find(p => String(p.id) === String(problemId));

        if (!problem || !problem.members) {
            ProblemsUI.showTemporaryMessage('Could not find duplicate problem data.', 'error');
            return;
        }

        // Make all member solutions persistent
        const solvedMembers = problem.members.filter(m => typeof m.solution === 'string' && m.solution.trim() !== '');
        if (solvedMembers.length === 0) {
            ProblemsUI.showTemporaryMessage('No solutions to make persistent.', 'warning');
            return;
        }

        const originalButtonHtml = $(this).html();
        $(this).prop('disabled', true).html('<span class="spinner-border spinner-border-sm"></span> Saving...');

        let processedCount = 0;
        const totalCount = solvedMembers.length;

        solvedMembers.forEach(member => {
            ProblemsSolutions.makeSolutionPersistentForStopId(member.stop_id, problemType);
            processedCount++;

            if (processedCount === totalCount) {
                setTimeout(() => {
                    $(this).prop('disabled', false).html(originalButtonHtml);
                    ProblemsUI.showTemporaryMessage(`Made ${totalCount} solutions persistent! <i class="fas fa-database"></i>`, 'success');
                    // Refresh the current problem display
                    const currentIndex = ProblemsState.getCurrentProblemIndex();
                    if (window.ProblemsData && window.ProblemsData.fetchProblems) {
                        ProblemsData.fetchProblems(ProblemsState.getCurrentPage());
                        setTimeout(() => {
                            ProblemsUI.displayProblem(currentIndex);
                        }, 500);
                    }
                }, 1000);
            }
        });
    });

    // Clear solution button handler
    $('#actionButtonsContent').on('click', '.clear-solution-btn', function () {
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

    // Clear duplicates solutions button handler
    $('#actionButtonsContent').on('click', '.clear-duplicates-solutions-btn', function () {
        console.log("=== CLEAR DUPLICATES SOLUTIONS BUTTON CLICKED ===");
        const problemId = $(this).data('problem-id');
        const problemType = $(this).data('problem-type');
        const currentEntryProblems = ProblemsState.getCurrentEntryProblems();
        const problem = currentEntryProblems.find(p => String(p.id) === String(problemId));

        if (!problem || !problem.members) {
            ProblemsUI.showTemporaryMessage('Could not find duplicate problem data.', 'error');
            return;
        }

        // Clear all member solutions
        const solvedMembers = problem.members.filter(m => typeof m.solution === 'string' && m.solution.trim() !== '');
        if (solvedMembers.length === 0) {
            ProblemsUI.showTemporaryMessage('No solutions to clear.', 'warning');
            return;
        }

        const originalButtonHtml = $(this).html();
        $(this).prop('disabled', true).html('<span class="spinner-border spinner-border-sm"></span> Clearing...');

        let processedCount = 0;
        const totalCount = solvedMembers.length;

        solvedMembers.forEach(member => {
            // Create a problem-like object for each member to use clearSolution
            const memberProblem = {
                stop_id: member.stop_id,
                problem: problemType,
                solution: member.solution,
                is_persistent: member.is_persistent
            };

            $.ajax({
                url: '/api/save_solution',
                method: 'POST',
                contentType: 'application/json',
                data: JSON.stringify({
                    problem_id: member.stop_id,
                    problem_type: problemType,
                    solution: ''
                }),
                success: function (response) {
                    processedCount++;
                    if (processedCount === totalCount) {
                        $(this).prop('disabled', false).html(originalButtonHtml);
                        ProblemsUI.showTemporaryMessage(`Cleared ${totalCount} solutions!`, 'info');
                        // Refresh the current problem display
                        const currentIndex = ProblemsState.getCurrentProblemIndex();
                        if (window.ProblemsData && window.ProblemsData.fetchProblems) {
                            ProblemsData.fetchProblems(ProblemsState.getCurrentPage());
                            setTimeout(() => {
                                ProblemsUI.displayProblem(currentIndex);
                            }, 500);
                        }
                    }
                }.bind(this),
                error: function () {
                    processedCount++;
                    if (processedCount === totalCount) {
                        $(this).prop('disabled', false).html(originalButtonHtml);
                        ProblemsUI.showTemporaryMessage('Error clearing some solutions', 'error');
                    }
                }.bind(this)
            });
        });
    });

    // Keyboard shortcuts for faster problem solving
    $(document).on('keydown', function (e) {
        // Only activate shortcuts when not in input fields
        if (!$(e.target).is('input, textarea, select')) {
            ProblemsUI.hideKeyboardHint(); // Hide hint when user starts using shortcuts

            switch (e.key) {
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
