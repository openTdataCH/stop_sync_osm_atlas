// problems-solutions.js - Solution management for the Problem Identification Page

/**
 * ProblemsSolutions - Solution saving, persistence, and management functionality
 * Depends on: ProblemsState, ProblemsUI
 */
window.ProblemsSolutions = (function() {
    'use strict';

    /**
     * Save solution to database
     */
    function saveSolution(button, problemType, solution) {
        const problemId = $(button).closest('.issue-container').data('problem-id');
        const currentEntryProblems = ProblemsState.getCurrentEntryProblems();
        const problem = currentEntryProblems.find(p => p.id === problemId);

        if (!problem) {
            if (window.ProblemsUI && window.ProblemsUI.showTemporaryMessage) {
                window.ProblemsUI.showTemporaryMessage('Could not find problem data to save.', 'error');
            }
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
                    const currentProblemIndex = ProblemsState.getCurrentProblemIndex();
                    
                    if (issueContainer.length && problemIndex !== -1 && window.ProblemsUI && window.ProblemsUI.renderSingleProblemUI) {
                        const newHtml = window.ProblemsUI.renderSingleProblemUI(problem, currentProblemIndex, problemIndex, currentEntryProblems.length);
                        const isActive = issueContainer.hasClass('active');
                        
                        // Replace and re-apply active state
                        issueContainer.replaceWith(newHtml);
                        const newIssueContainer = $(`#issue-${problem.id}`);
                        if (isActive) {
                            newIssueContainer.addClass('active');
                        }
                        
                        // Re-observe the new element
                        const observer = ProblemsState.getObserver();
                        if (observer) {
                            observer.observe(document.getElementById(`issue-${problem.id}`));
                        }
                    }

                    // Check if auto-persist is enabled and provide appropriate feedback
                    let messageText, messageIcon;
                    const autoPersistEnabled = ProblemsState.getAutoPersistEnabled();
                    if (autoPersistEnabled) {
                        messageText = 'Solution saved as persistent data!';
                        messageIcon = 'database';
                        // Make the solution persistent automatically
                        makeSolutionPersistent(problem.id, problemType);
                    } else {
                        messageText = 'Solution saved temporarily (non-persistent)!';
                        messageIcon = 'clock';
                    }
                    
                    if (window.ProblemsUI && window.ProblemsUI.showTemporaryMessage) {
                        window.ProblemsUI.showTemporaryMessage(`${messageText} <i class="fas fa-${messageIcon}"></i>`, 'success');
                    }
                    
                    // Proceed to next problem after delay
                    setTimeout(() => {
                        const currentEntryProblemIndex = ProblemsState.getCurrentEntryProblemIndex();
                        const hasMoreProblemsInEntry = currentEntryProblems.length > 1 && currentEntryProblemIndex < currentEntryProblems.length - 1;
                        
                        if (hasMoreProblemsInEntry) {
                            const nextProblemEl = $(`#issue-${currentEntryProblems[currentEntryProblemIndex + 1].id}`);
                            if (nextProblemEl.length) {
                                 $('#problemContent').animate({
                                    scrollTop: nextProblemEl.offset().top - $('#problemContent').offset().top + $('#problemContent').scrollTop()
                                }, 500);
                            }
                        } else {
                            if (window.ProblemsData && window.ProblemsData.navigateToNextProblem) {
                                window.ProblemsData.navigateToNextProblem();
                            }
                        }
                    }, 1000); // 1-second delay before moving

                } else {
                    if (window.ProblemsUI && window.ProblemsUI.showTemporaryMessage) {
                        window.ProblemsUI.showTemporaryMessage(`Error: ${response.error}`, 'error');
                    }
                    $(button).prop('disabled', false).html(originalButtonHtml);
                }
            },
            error: function(xhr, status, error) {
                if (window.ProblemsUI && window.ProblemsUI.showTemporaryMessage) {
                    window.ProblemsUI.showTemporaryMessage(`Error saving solution: ${error}`, 'error');
                }
                $(button).prop('disabled', false).html(originalButtonHtml);
            }
        });
    }

    /**
     * Save solution for a specific stop_id directly (used for duplicates members)
     */
    function saveSolutionForStopId(button, stopId, problemType, solution) {
        // Visual feedback
        const originalButtonHtml = $(button).html();
        $(button).prop('disabled', true).html('<span class="spinner-border spinner-border-sm"></span> Saving...');

        const data = {
            problem_id: stopId,
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
                    const autoPersistEnabled = ProblemsState.getAutoPersistEnabled && ProblemsState.getAutoPersistEnabled();
                    const proceedAfterPersist = () => {
                        if (window.ProblemsUI && window.ProblemsUI.showTemporaryMessage) {
                            window.ProblemsUI.showTemporaryMessage(autoPersistEnabled ? 'Solution saved as persistent data! <i class="fas fa-database"></i>' : 'Solution saved temporarily <i class="fas fa-clock"></i>', 'success');
                        }
                        // Refresh current display to reflect new solutions
                        const currentIndex = ProblemsState.getCurrentProblemIndex();
                        if (window.ProblemsData && window.ProblemsData.fetchProblems) {
                            ProblemsData.fetchProblems(ProblemsState.getCurrentPage());
                            setTimeout(() => {
                                if (window.ProblemsUI && window.ProblemsUI.displayProblem) {
                                    window.ProblemsUI.displayProblem(currentIndex);
                                }
                            }, 500);
                        }
                    };

                    if (autoPersistEnabled) {
                        $.ajax({
                            url: '/api/make_solution_persistent',
                            method: 'POST',
                            contentType: 'application/json',
                            data: JSON.stringify({ problem_id: stopId, problem_type: problemType })
                        }).always(proceedAfterPersist);
                    } else {
                        proceedAfterPersist();
                    }
                } else {
                    if (window.ProblemsUI && window.ProblemsUI.showTemporaryMessage) {
                        window.ProblemsUI.showTemporaryMessage(`Error: ${response.error}`, 'error');
                    }
                    $(button).prop('disabled', false).html(originalButtonHtml);
                }
            },
            error: function(xhr, status, error) {
                if (window.ProblemsUI && window.ProblemsUI.showTemporaryMessage) {
                    window.ProblemsUI.showTemporaryMessage(`Error saving solution: ${error}`, 'error');
                }
                $(button).prop('disabled', false).html(originalButtonHtml);
            }
        });
    }

    /**
     * Make a solution persistent
     */
    function makeSolutionPersistent(problemId, problemType) {
        const currentEntryProblems = ProblemsState.getCurrentEntryProblems();
        const problem = currentEntryProblems.find(p => p.id === problemId);
        
        if (!problem || !problem.solution) {
            if (window.ProblemsUI && window.ProblemsUI.showTemporaryMessage) {
                window.ProblemsUI.showTemporaryMessage('No solution to make persistent', 'error');
            }
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
                    const currentProblemIndex = ProblemsState.getCurrentProblemIndex();
                    
                    if (issueContainer.length && problemIndex !== -1 && window.ProblemsUI && window.ProblemsUI.renderSingleProblemUI) {
                        const newHtml = window.ProblemsUI.renderSingleProblemUI(problem, currentProblemIndex, problemIndex, currentEntryProblems.length);
                        const isActive = issueContainer.hasClass('active');
                        
                        // Replace and re-apply active state
                        issueContainer.replaceWith(newHtml);
                        const newIssueContainer = $(`#issue-${problem.id}`);
                        if (isActive) {
                            newIssueContainer.addClass('active');
                        }
                        
                        // Re-observe the new element
                        const observer = ProblemsState.getObserver();
                        if (observer) {
                            observer.observe(document.getElementById(`issue-${problem.id}`));
                        }
                    }
                    
                    if (window.ProblemsUI && window.ProblemsUI.showTemporaryMessage) {
                        window.ProblemsUI.showTemporaryMessage('Solution converted to persistent data! <i class="fas fa-database"></i>', 'success');
                    }
                } else {
                    if (window.ProblemsUI && window.ProblemsUI.showTemporaryMessage) {
                        window.ProblemsUI.showTemporaryMessage(`Error: ${response.error}`, 'error');
                    }
                    button.prop('disabled', false).html(originalButtonHtml);
                }
            },
            error: function(xhr, status, error) {
                if (window.ProblemsUI && window.ProblemsUI.showTemporaryMessage) {
                    window.ProblemsUI.showTemporaryMessage(`Error making solution persistent: ${error}`, 'error');
                }
                button.prop('disabled', false).html(originalButtonHtml);
            }
        });
    }

    /**
     * Clear solution functionality
     */
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
                    const currentEntryProblems = ProblemsState.getCurrentEntryProblems();
                    const problemIndex = currentEntryProblems.findIndex(p => p.id === problem.id);
                    const currentProblemIndex = ProblemsState.getCurrentProblemIndex();
                    
                    if (issueContainer.length && problemIndex !== -1 && window.ProblemsUI && window.ProblemsUI.renderSingleProblemUI) {
                        const isActive = issueContainer.hasClass('active');
                        const newHtml = window.ProblemsUI.renderSingleProblemUI(problem, currentProblemIndex, problemIndex, currentEntryProblems.length);
                        issueContainer.replaceWith(newHtml);
                        
                        const newIssueContainer = $(`#issue-${problem.id}`);
                        if (isActive) {
                            newIssueContainer.addClass('active');
                        }
                        
                        // Re-observe the new element
                        const observer = ProblemsState.getObserver();
                        if (observer) {
                            observer.observe(document.getElementById(`issue-${problem.id}`));
                        }
                    }
                    
                    if (window.ProblemsUI && window.ProblemsUI.showTemporaryMessage) {
                        window.ProblemsUI.showTemporaryMessage('Solution cleared successfully!', 'info');
                    }
                } else {
                    if (window.ProblemsUI && window.ProblemsUI.showTemporaryMessage) {
                        window.ProblemsUI.showTemporaryMessage(`Error: ${response.error}`, 'error');
                    }
                }
            },
            error: function(xhr, status, error) {
                if (window.ProblemsUI && window.ProblemsUI.showTemporaryMessage) {
                    window.ProblemsUI.showTemporaryMessage(`Error clearing solution: ${error}`, 'error');
                }
            }
        });
    }

    // Public API
    return {
        saveSolution,
        saveSolutionForStopId,
        makeSolutionPersistent,
        clearSolution
    };
})();
