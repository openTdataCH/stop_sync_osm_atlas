// problems-solutions.js - Solution management for the Problem Identification Page

/**
 * ProblemsSolutions - Solution saving, persistence, and management functionality
 * Depends on: ProblemsState, ProblemsUI
 */
window.ProblemsSolutions = (function () {
    'use strict';

    // Setup CSRF token for AJAX requests
    SharedUtils.setupCSRFToken();

    /**
     * Local storage helper keys format:
     * 'draft_solution_${problemId}_${problemType}'
     */
    function getDraftKey(problemId, problemType) {
        return `draft_solution_${problemId}_${problemType}`;
    }

    /**
     * Save solution to local storage draft
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

        // Save directly to localStorage instead of API
        const draftKey = getDraftKey(problem.stop_id, problemType);
        window.localStorage.setItem(draftKey, solution);

        // Update local data
        problem.solution = solution;
        problem.is_persistent = false; // When saving locally, it's not persistent

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
            messageText = 'Local draft saved to browser!';
            messageIcon = 'edit';
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
    }

    /**
     * Save solution for a specific stop_id directly to browser drafts
     */
    function saveSolutionForStopId(button, stopId, problemType, solution) {

        const draftKey = getDraftKey(stopId, problemType);
        window.localStorage.setItem(draftKey, solution);

        const autoPersistEnabled = ProblemsState.getAutoPersistEnabled && ProblemsState.getAutoPersistEnabled();
        const proceedAfterPersist = () => {
            if (window.ProblemsUI && window.ProblemsUI.showTemporaryMessage) {
                window.ProblemsUI.showTemporaryMessage(autoPersistEnabled ? 'Solution saved as persistent data! <i class="fas fa-database"></i>' : 'Local draft saved to browser <i class="fas fa-edit"></i>', 'success');
            }
            // Refresh current display to reflect new solutions
            const currentIndex = ProblemsState.getCurrentProblemIndex();
            // Need to update the active item directly since we don't refetch the database for local drafts
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
                data: JSON.stringify({ problem_id: stopId, problem_type: problemType, solution: solution })
            }).always(proceedAfterPersist);

            // Clear local draft once persistent
            window.localStorage.removeItem(draftKey);
        } else {
            proceedAfterPersist();
        }
    }

    /**
     * Make a solution persistent by sending local draft to the backend
     */
    function makeSolutionPersistent(problemId, problemType) {
        const currentEntryProblems = ProblemsState.getCurrentEntryProblems();
        const problem = currentEntryProblems.find(p => p.id === problemId);

        if (!problem) {
            return;
        }

        // Grab solution from local state or localStorage
        let solutionBody = problem.solution;
        const draftKey = getDraftKey(problem.stop_id, problemType);
        const localDraft = window.localStorage.getItem(draftKey);
        if (localDraft) {
            solutionBody = localDraft;
        }

        if (!solutionBody) {
            if (window.ProblemsUI && window.ProblemsUI.showTemporaryMessage) {
                window.ProblemsUI.showTemporaryMessage('No solution draft available to make persistent', 'error');
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
                problem_type: problemType,
                solution: solutionBody
            }),
            success: function (response) {
                if (response.success) {
                    // Clean up local draft since it's now handled by the server
                    window.localStorage.removeItem(draftKey);

                    // Update local data
                    problem.is_persistent = true;
                    problem.solution = response.solution;

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
            error: function (xhr, status, error) {
                if (window.ProblemsUI && window.ProblemsUI.showTemporaryMessage) {
                    window.ProblemsUI.showTemporaryMessage(`Error making solution persistent: ${error}`, 'error');
                }
                button.prop('disabled', false).html(originalButtonHtml);
            }
        });
    }

    /**
     * Make a solution persistent for a specific stop_id (used for duplicates members)
     */
    function makeSolutionPersistentForStopId(stopId, problemType) {

        // Grab solution from localStorage first
        const draftKey = getDraftKey(stopId, problemType);
        const localDraft = window.localStorage.getItem(draftKey);

        let payload = { problem_id: stopId, problem_type: problemType };
        if (localDraft) {
            payload.solution = localDraft;
        }

        $.ajax({
            url: '/api/make_solution_persistent',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify(payload),
            complete: function () {
                // Clear local draft when persisting successfully
                window.localStorage.removeItem(draftKey);

                // Refresh current display to reflect persistence state
                const currentIndex = ProblemsState.getCurrentProblemIndex && ProblemsState.getCurrentProblemIndex();
                if (window.ProblemsData && window.ProblemsData.fetchProblems) {
                    ProblemsData.fetchProblems(ProblemsState.getCurrentPage ? ProblemsState.getCurrentPage() : 1);
                    setTimeout(() => {
                        if (window.ProblemsUI && window.ProblemsUI.displayProblem && typeof currentIndex === 'number') {
                            window.ProblemsUI.displayProblem(currentIndex);
                        }
                    }, 500);
                }
            }
        });
    }

    /**
     * Clear solution functionality (Removes from localStorage directly)
     */
    function clearSolution(problem) {
        const draftKey = getDraftKey(problem.stop_id, problem.problem);
        window.localStorage.removeItem(draftKey);

        // Clear locally on DOM
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
            window.ProblemsUI.showTemporaryMessage('Local draft cleared!', 'info');
        }
    }

    // Public API
    return {
        saveSolution,
        saveSolutionForStopId,
        makeSolutionPersistent,
        makeSolutionPersistentForStopId,
        clearSolution,
        getDraftKey // expose it so the data loader can pick it up
    };
})();
