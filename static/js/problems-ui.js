// problems-ui.js - UI rendering and helpers for the Problem Identification Page

/**
 * ProblemsUI - UI rendering, display, and interaction functionality
 * Depends on: ProblemsState, PopupRenderer (from popup-renderer.js)
 */
window.ProblemsUI = (function() {
    'use strict';

    /**
     * Show keyboard shortcuts hint
     */
    function showKeyboardHint() {
        if (!ProblemsState.getKeyboardHintShown()) {
            const hint = $('#keyboardHint');
            hint.addClass('show');
            ProblemsState.setKeyboardHintShown(true);
            
            // Auto-hide after 5 seconds
            const timeout = setTimeout(() => {
                hideKeyboardHint();
            }, 5000);
            ProblemsState.setKeyboardHintTimeout(timeout);
        }
    }

    /**
     * Hide keyboard shortcuts hint
     */
    function hideKeyboardHint() {
        const hint = $('#keyboardHint');
        hint.removeClass('show');
        const timeout = ProblemsState.getKeyboardHintTimeout();
        if (timeout) {
            clearTimeout(timeout);
            ProblemsState.setKeyboardHintTimeout(null);
        }
    }

    /**
     * Generate attribute comparison HTML for attributes problems
     */
    function generateAttributeComparisonHtml(problem) {
        let html = '<div class="problem-section-item">';
        html += '<h6><i class="fas fa-exchange-alt"></i> Attribute Comparison</h6>';
        html += '<div class="row">';
        
        // ATLAS column
        html += '<div class="col-md-6">';
        html += '<h6 class="text-info mb-3"><i class="fas fa-map-marker-alt"></i> ATLAS Entry</h6>';
        if (typeof PopupRenderer !== 'undefined') {
            // Create a temporary ATLAS data object
            const atlasData = {
                sloid: problem.sloid,
                atlas_lat: problem.atlas_lat,
                atlas_lon: problem.atlas_lon,
                atlas_business_org_abbr: problem.atlas_business_org_abbr,
                atlas_designation_official: problem.atlas_designation_official,
                atlas_designation: problem.atlas_designation,
                stop_type: problem.stop_type,
                uic_ref: problem.uic_ref,
                match_type: problem.match_type
            };
            // Add any other atlas_ prefixed properties from problem that might be needed
            Object.keys(problem).forEach(key => {
                if (key.startsWith('atlas_')) {
                    if (!atlasData.hasOwnProperty(key)) {
                        atlasData[key] = problem[key];
                    }
                }
            });
            html += PopupRenderer.generatePopupHtml(atlasData, 'atlas');
        } else {
            html += '<div class="alert alert-warning">ATLAS info not available</div>';
        }
        html += '</div>';
        
        // OSM column
        html += '<div class="col-md-6">';
        html += '<h6 class="text-primary mb-3"><i class="fas fa-map"></i> OSM Entry</h6>';
        
        if (typeof PopupRenderer !== 'undefined') {
            // Create a temporary OSM data object
            const osmData = {
                osm_node_id: problem.osm_node_id,
                osm_lat: problem.osm_lat,
                osm_lon: problem.osm_lon,
                osm_operator: problem.osm_operator,
                osm_name: problem.osm_name,
                osm_local_ref: problem.osm_local_ref,
                osm_public_transport: problem.osm_public_transport,
                stop_type: problem.stop_type,
                uic_ref: problem.uic_ref,
                match_type: problem.match_type
            };
            // Add all osm_ prefixed properties from problem
            Object.keys(problem).forEach(key => {
                if (key.startsWith('osm_')) {
                    osmData[key] = problem[key];
                }
            });
            html += PopupRenderer.generatePopupHtml(osmData, 'osm');
        } else {
            html += '<div class="alert alert-warning">OSM info not available</div>';
        }

        // Add OSM iD Editor link below the popup
        if (problem.osm_node_id) {
            const osmEditorUrl = `https://www.openstreetmap.org/edit?node=${problem.osm_node_id}`;
            html += `<div class="mt-2">
                <a href="${osmEditorUrl}" class="osm-editor-link" target="_blank" rel="noopener noreferrer">
                    <i class="fas fa-external-link-alt"></i>
                    Edit in OSM iD Editor
                </a>
            </div>`;
        }
        html += '</div>';
        
        html += '</div>'; // End row
        html += '</div>'; // End problem-section-item
        
        return html;
    }

    /**
     * Helper to identify mismatched attributes for display
     */
    function getMismatchedAttributes(problem) {
        const attributesToCheck = [
            { atlas: 'atlas_operator', osm: 'osm_operator', label: 'Operator' },
            { atlas: 'atlas_designation_official', osm: 'osm_name', label: 'Name' },
            { atlas: 'atlas_designation', osm: 'osm_local_ref', label: 'Local Reference' },
            { atlas: 'atlas_transport_type', osm: 'osm_public_transport', label: 'Transport Type' }
        ];
        
        const mismatches = [];
        attributesToCheck.forEach(attr => {
            const atlasValue = problem[attr.atlas] || '';
            const osmValue = problem[attr.osm] || '';
            
            // Consider it a mismatch if values are different
            if (atlasValue !== osmValue) {
                mismatches.push(attr);
            }
        });
        return mismatches;
    }

    /**
     * Generate action buttons for distance problems
     */
    function generateDistanceActionButtons(problem) {
        const distance = problem.distance_m ? Math.round(problem.distance_m) : 'unknown';
        const distanceInfo = problem.distance_m ? 
            `The distance between ATLAS and OSM entries is ${distance} meters (threshold: 20m).` :
            'The distance between ATLAS and OSM entries is greater than 20 meters.';
        
        return `
            <div class="problem-section-item">
                <h6><i class="fas fa-tools"></i> Resolution Actions</h6>
                <div class="alert alert-info">
                    <small><i class="fas fa-info-circle"></i> ${distanceInfo} Please determine which location is correct.</small>
                </div>
                <div class="d-flex flex-wrap gap-2">
                    <button class="btn btn-success professional-button solution-btn" data-solution="Atlas correct">
                        <i class="fas fa-check-circle"></i> Atlas correct
                    </button>
                    <button class="btn btn-primary professional-button solution-btn" data-solution="OSM correct">
                        <i class="fas fa-check-circle"></i> OSM correct
                    </button>
                    <button class="btn btn-warning professional-button solution-btn" data-solution="Both correct">
                        <i class="fas fa-pause-circle"></i> Both correct
                    </button>
                    <button class="btn btn-danger professional-button solution-btn" data-solution="Not a match">
                        <i class="fas fa-times-circle"></i> Not a match
                    </button>
                </div>
            </div>
        `;
    }

    /**
     * Generate action buttons for isolated problems
     */
    function generateIsolatedActionButtons(problem) {
        if (problem.stop_type === 'unmatched') { // Isolated ATLAS
            return `
                <div class="problem-section-item">
                    <h6><i class="fas fa-tools"></i> Resolution Actions</h6>
                    <div class="alert alert-info">
                        <small><i class="fas fa-info-circle"></i> This ATLAS entry has no corresponding OSM entry within 50 meters.</small>
                    </div>
                    <div class="d-flex flex-wrap gap-2">
                        <button class="btn btn-danger professional-button solution-btn" data-solution="Should be deleted">
                            <i class="fas fa-trash"></i> Should be deleted
                        </button>
                        <button class="btn btn-info professional-button solution-btn" data-solution="Missing OSM">
                            <i class="fas fa-plus-circle"></i> Missing OSM
                        </button>
                    </div>
                </div>
            `;
        } else if (problem.stop_type === 'osm') { // Isolated OSM
            return `
                <div class="problem-section-item">
                    <h6><i class="fas fa-tools"></i> Resolution Actions</h6>
                    <div class="alert alert-info">
                        <small><i class="fas fa-info-circle"></i> This OSM entry has no corresponding ATLAS entry.</small>
                    </div>
                    <div class="d-flex flex-wrap gap-2">
                        <button class="btn btn-danger professional-button solution-btn" data-solution="Should be deleted">
                            <i class="fas fa-trash"></i> Should be deleted
                        </button>
                        <button class="btn btn-info professional-button solution-btn" data-solution="Missing ATLAS">
                            <i class="fas fa-plus-circle"></i> Missing ATLAS
                        </button>
                    </div>
                </div>
            `;
        }
        // Fallback for unexpected cases
        return `
            <div class="problem-section-item">
                <h6><i class="fas fa-exclamation-triangle text-danger"></i> Data Inconsistency</h6>
                <div class="alert alert-danger">
                    This entry is flagged with an 'isolated' problem, but its type is <code>${problem.stop_type || 'undefined'}</code>, which is not expected for this problem type. Please report this issue.
                </div>
            </div>
        `;
    }

    /**
     * Generate action buttons for attributes problems
     */
    function generateAttributesActionButtons(problem) {
        let html = '<div class="problem-section-item">';
        html += '<h6><i class="fas fa-tools"></i> Resolution Actions</h6>';
        
        const mismatches = getMismatchedAttributes(problem);
        let solution = {};
        if (problem.solution && problem.solution.trim() !== '' && problem.solution.trim().startsWith('{')) {
            try {
                solution = JSON.parse(problem.solution);
            } catch (e) {
                console.error("Error parsing solution JSON:", e);
                solution = {};
            }
        } else if (problem.solution) {
            // Handle legacy string solutions
            html += `<div class="alert alert-warning"><strong>Legacy Solution:</strong> ${problem.solution}</div>`;
        }

        if (mismatches.length > 0) {
            html += '<p><small><i class="fas fa-info-circle"></i> For each mismatched attribute, choose the correct source.</small></p>';
            html += '<table class="table table-sm attribute-resolution-table"><tbody>';

            mismatches.forEach(attr => {
                const atlasValue = problem[attr.atlas] || '<em>(empty)</em>';
                const osmValue = problem[attr.osm] || '<em>(empty)</em>';
                const resolvedValue = solution[attr.label];

                html += `<tr>
                    <td><strong>${attr.label}</strong></td>
                    <td class="attribute-value">${atlasValue}</td>
                    <td class="attribute-value">${osmValue}</td>
                    <td class="attribute-action">`;

                if (resolvedValue !== undefined) {
                    html += `<div class="text-success"><i class="fas fa-check-circle"></i> <strong>${resolvedValue || '<em>(empty)</em>'}</strong></div>`;
                } else {
                    html += `<div class="btn-group btn-group-sm">
                        <button class="btn btn-outline-info solution-btn" data-solution-type="attribute" data-attribute="${attr.label}" data-value="${problem[attr.atlas] || ''}">Use ATLAS</button>
                        <button class="btn btn-outline-primary solution-btn" data-solution-type="attribute" data-attribute="${attr.label}" data-value="${problem[attr.osm] || ''}">Use OSM</button>
                    </div>`;
                }

                html += '</td></tr>';
            });

            html += '</tbody></table>';
        } else {
            html += '<div class="alert alert-success"><i class="fas fa-check-circle"></i> No attribute mismatches detected.</div>';
        }

        // Add global actions
        html += '<h6 class="mt-4"><i class="fas fa-globe"></i> Overall Status</h6>';
        html += '<div class="d-flex flex-wrap gap-2">';
        html += `<button class="btn btn-danger professional-button solution-btn" data-solution-type="global" data-solution="Not a valid match">
                    <i class="fas fa-times-circle"></i> Not a valid match
                </button>`;
        html += `<button class="btn btn-secondary professional-button solution-btn" data-solution-type="global" data-solution="Skip / I do not know">
                    <i class="fas fa-forward"></i> Skip
                </button>`;
        html += '</div>';

        html += '</div>';
        return html;
    }

    /**
     * Render the UI for a single problem. Returns HTML string.
     */
    function renderSingleProblemUI(problem, entryIndex, issueIndex, totalIssues) {
        const problemType = problem.problem ? problem.problem.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase()) : "Unknown";
        let html = `<div class="issue-container" id="issue-${problem.id}" data-problem-id="${problem.id}" data-stop-id="${problem.stop_id}">`;

        // Header for the issue
        let displayText = `${problemType}`;
        if (totalIssues > 1) {
            displayText += ` (Issue ${issueIndex + 1}/${totalIssues})`;
        }
        
        // Add distance indicator for distance problems
        if (problem.problem === 'distance' && problem.distance_m) {
            const distance = Math.round(problem.distance_m);
            const distanceClass = distance > 100 ? 'high-distance' : '';
            displayText += `<span class="distance-indicator ${distanceClass}">(${distance}m apart)</span>`;
        }
        
        // Add persistence indicator to header if solution is persistent
        let persistenceIcon = '';
        if (problem.is_persistent) {
            persistenceIcon = ` <i class="fas fa-database text-success" title="This solution is persistent"></i>`;
        }
        
        html += `<h5 class="text-center mb-3">${displayText}${persistenceIcon}</h5>`;

        // Generate action buttons and content based on problem type
        let actionButtonsHtml = '';
        // Show existing solution if available
        if (problem.solution && problem.solution.trim() !== '') {
            let persistenceHtml = '';
            if (problem.is_persistent) {
                persistenceHtml = `
                    <div class="mt-2">
                        <span class="badge badge-success"><i class="fas fa-database"></i> Persistent Solution</span>
                        <small class="text-muted ml-2">This solution will be automatically applied after data imports</small>
                    </div>
                `;
            } else {
                persistenceHtml = `
                    <div class="mt-2">
                        <button class="btn btn-sm btn-outline-success make-persistent-btn" data-problem-id="${problem.id}" data-problem-type="${problem.problem}" data-stop-id="${problem.stop_id}">
                            <i class="fas fa-thumbtack"></i> Make Persistent
                        </button>
                        <small class="text-muted ml-2">Save this solution for future data imports</small>
                    </div>
                `;
            }

            actionButtonsHtml += `
                <div class="problem-section-item solution-status-section">
                    <h6><i class="fas fa-check-circle text-success"></i> Current Solution</h6>
                    <div class="alert alert-success solution-display">
                        <div class="d-flex justify-content-between align-items-center">
                            <div>
                                <strong>Proposed Solution:</strong> ${problem.solution}
                                <br><small class="text-muted">You can modify this solution by selecting a new action below.</small>
                            </div>
                            <button class="btn btn-sm btn-outline-secondary clear-solution-btn" data-problem-id="${problem.id}" data-problem-type="${problem.problem}" data-stop-id="${problem.stop_id}">
                                <i class="fas fa-undo"></i> Clear
                            </button>
                        </div>
                        ${persistenceHtml}
                    </div>
                </div>
            `;
        }

        // Add problem-specific action buttons
        switch (problem.problem) {
            case 'distance':
                actionButtonsHtml += generateDistanceActionButtons(problem);
                break;
            case 'isolated':
                actionButtonsHtml += generateIsolatedActionButtons(problem);
                break;
            case 'attributes':
                actionButtonsHtml += generateAttributeComparisonHtml(problem);
                actionButtonsHtml += generateAttributesActionButtons(problem);
                break;
        }
        html += actionButtonsHtml;
        html += '</div>'; // close issue-container
        return html;
    }

    /**
     * Setup intersection observer for scroll navigation
     */
    function setupIntersectionObserver() {
        const options = {
          root: document.getElementById('problemContent'),
          rootMargin: '0px',
          threshold: 0.6, // Use a slightly lower threshold
        };

        const observer = new IntersectionObserver((entries, observer) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    const problemId = $(entry.target).data('problem-id');

                    // Find the problem in the current entry's problems
                    const currentEntryProblems = ProblemsState.getCurrentEntryProblems();
                    const newProblemIndex = currentEntryProblems.findIndex(p => p.id === problemId);
                    if (newProblemIndex !== -1 && newProblemIndex !== ProblemsState.getCurrentEntryProblemIndex()) {
                        ProblemsState.setCurrentEntryProblemIndex(newProblemIndex);
                        const problem = currentEntryProblems[newProblemIndex];
                        ProblemsState.setCurrentProblem(problem);
                        
                        // Update map
                        const problemMap = ProblemsState.getProblemMap();
                        const markersLayer = ProblemsState.getProblemMarkersLayer();
                        const linesLayer = ProblemsState.getProblemLinesLayer();
                        
                        if (problemMap && typeof drawProblemOnMap !== 'undefined') {
                            drawProblemOnMap(problemMap, problem, {
                                markersLayer: markersLayer,
                                linesLayer: linesLayer
                            });
                        }

                        // Update active highlight
                        $('.issue-container').removeClass('active');
                        $(entry.target).addClass('active');

                        // Update notes
                        if (window.ProblemsNotes && window.ProblemsNotes.loadNotesForProblem) {
                            window.ProblemsNotes.loadNotesForProblem(problem);
                        }
                    }
                }
            });
        }, options);
        
        ProblemsState.setObserver(observer);
    }

    /**
     * Display a problem by its index in the problemsByEntry array
     */
    function displayProblem(index) {
        const problemsByEntry = ProblemsState.getProblemsByEntry();
        const totalProblems = ProblemsState.getTotalProblems();
        
        if (index < 0 || index >= problemsByEntry.length) {
            return;
        }
        
        ProblemsState.setCurrentProblemIndex(index);
        const currentEntryProblems = problemsByEntry[index];
        ProblemsState.setCurrentEntryProblems(currentEntryProblems);
        ProblemsState.setCurrentEntryProblemIndex(0); // Reset to the first issue
        ProblemsState.setCurrentProblem(currentEntryProblems[0]);

        // Update main header
        const problemCount = currentEntryProblems.length;
        const problemText = problemCount > 1 ? 'Problems' : 'Problem';
        $('#problemTypeDisplay').text(`Entry ${index + 1} of ${totalProblems} (${problemCount} ${problemText})`);

        // Clear previous content
        const container = $('#actionButtonsContent');
        container.empty();
        const observer = ProblemsState.getObserver();
        if (observer) {
            observer.disconnect();
        }

        // Render all issues for this entry
        currentEntryProblems.forEach((p, i) => {
            const problemHtml = renderSingleProblemUI(p, index, i, currentEntryProblems.length);
            container.append(problemHtml);
        });

        // Setup intersection observer for the new items
        $('.issue-container').each(function() {
            if (observer) {
                observer.observe(this);
            }
        });

        // Set first problem as active
        const firstProblem = currentEntryProblems[0];
        if (firstProblem) {
            // Make first issue active
            $(`#issue-${firstProblem.id}`).addClass('active');
            
            // Draw the problem markers and lines on the map
            const problemMap = ProblemsState.getProblemMap();
            const markersLayer = ProblemsState.getProblemMarkersLayer();
            const linesLayer = ProblemsState.getProblemLinesLayer();
            
            if (problemMap && typeof drawProblemOnMap !== 'undefined') {
                drawProblemOnMap(problemMap, firstProblem, {
                    markersLayer: markersLayer,
                    linesLayer: linesLayer
                });
            }

            // Load context if enabled
            const showContext = ProblemsState.getShowContext();
            if (showContext && window.ProblemsMap && window.ProblemsMap.loadContextData) {
                window.ProblemsMap.loadContextData(firstProblem);
            } else {
                const contextLayer = ProblemsState.getContextMarkersLayer();
                if (contextLayer) {
                    contextLayer.clearLayers();
                }
            }

            // Load notes for the first problem
            if (window.ProblemsNotes && window.ProblemsNotes.loadNotesForProblem) {
                window.ProblemsNotes.loadNotesForProblem(firstProblem);
            }
        }
        
        // Add scroll indicator if needed
        const problemContent = $('#problemContent');
        let scrollIndicator = problemContent.find('.scroll-indicator');
        if (currentEntryProblems.length > 1) {
            if (scrollIndicator.length === 0) {
                scrollIndicator = $('<div class="scroll-indicator"><i class="fas fa-chevron-down"></i></div>');
                problemContent.append(scrollIndicator);
            }
            setTimeout(() => scrollIndicator.addClass('visible'), 100);

            // Hide indicator on scroll
            problemContent.off('scroll.indicator').on('scroll.indicator', () => {
                scrollIndicator.removeClass('visible');
            });

        } else {
            scrollIndicator.remove();
        }
    }

    /**
     * Enable or disable the Previous/Next buttons
     */
    function updateNavButtons() {
        const currentProblemIndex = ProblemsState.getCurrentProblemIndex();
        const currentPage = ProblemsState.getCurrentPage();
        const allProblems = ProblemsState.getAllProblems();
        const totalProblems = ProblemsState.getTotalProblems();
        const problemsByEntry = ProblemsState.getProblemsByEntry();
        
        // Navigation should be disabled only if we are at the very beginning, or at the very end of ALL problems
        $('#prevProblemBtn').prop('disabled', currentProblemIndex <= 0 && currentPage === 1);
        $('#nextProblemBtn').prop('disabled', allProblems.length === totalProblems && currentProblemIndex >= problemsByEntry.length - 1);
    }

    /**
     * Helper to show a temporary message on the screen
     */
    function showTemporaryMessage(message, type = 'info') {
        const messageContainer = $('<div class="temporary-message"></div>');
        messageContainer.addClass(`alert alert-${type}`);
        messageContainer.text(message);
        
        // Add icon based on type
        let icon = '';
        switch(type) {
            case 'success': icon = '<i class="fas fa-check-circle"></i> '; break;
            case 'error': icon = '<i class="fas fa-exclamation-circle"></i> '; break;
            case 'warning': icon = '<i class="fas fa-exclamation-triangle"></i> '; break;
            case 'info': 
            default: icon = '<i class="fas fa-info-circle"></i> '; break;
        }
        messageContainer.html(icon + message);
        
        $('body').append(messageContainer);
        
        messageContainer.fadeIn(200).delay(3000).fadeOut(500, function() {
            $(this).remove();
        });
    }

    // Public API
    return {
        showKeyboardHint,
        hideKeyboardHint,
        generateAttributeComparisonHtml,
        getMismatchedAttributes,
        generateDistanceActionButtons,
        generateIsolatedActionButtons,
        generateAttributesActionButtons,
        renderSingleProblemUI,
        setupIntersectionObserver,
        displayProblem,
        updateNavButtons,
        showTemporaryMessage
    };
})();
