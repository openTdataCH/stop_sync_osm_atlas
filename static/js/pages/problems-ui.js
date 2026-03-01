// problems-ui.js - UI rendering and helpers for the Problem Identification Page

/**
 * ProblemsUI - UI rendering, display, and interaction functionality
 * Depends on: ProblemsState, PopupRenderer (from popup-renderer.js)
 */
window.ProblemsUI = (function () {
    'use strict';

    // Small UI helpers
    // Map priority to alert styling
    function getPriorityAlertStyle(priority) {
        const pr = Number(priority);
        if (pr === 1) return { alertClass: 'alert-danger', icon: 'exclamation-circle' };
        if (pr === 2) return { alertClass: 'alert-warning', icon: 'exclamation-triangle' };
        return { alertClass: 'alert-info', icon: 'info-circle' };
    }

    // Serialize data attributes for HTML
    function serializeDataAttrs(attrs) {
        return Object.entries(attrs).map(([k, v]) => `${k}="${v}"`).join(' ');
    }

    // Wrap content in a problem section item
    function wrapInSection(title, content) {
        return `<div class="problem-section-item"><h6>${title}</h6>${content}</div>`;
    }

    // Extract member display info (badge, identifier, name) with group context awareness
    function getMemberDisplayInfo(member, groupType) {
        const isOsm = groupType === 'osm' ? true : (groupType === 'atlas' ? false : !!member.osm_node_id);
        return {
            badge: `<span class="badge badge-secondary">${isOsm ? 'OSM' : 'ATLAS'}</span>`,
            ident: isOsm ? (member.osm_node_id || '-') : (member.sloid || '-'),
            name: isOsm ? (member.osm_name || member.osm_uic_name || '-')
                : (member.atlas_designation_official || member.atlas_designation || '-'),
            isOsm
        };
    }

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
        // Priority-aware concise info banner for attributes, shown above the popups
        (function () {
            const pr = Number(problem.priority);
            let alertClass = 'alert-info';
            let icon = 'info-circle';
            let intent = '';
            // Derive concrete mismatches from available fields
            const mismatches = getMismatchedAttributes(problem) || [];
            const labels = mismatches.map(m => m.label);

            if (pr === 1) {
                alertClass = 'alert-danger';
                icon = 'exclamation-circle';
                // Prefer explicit labels for critical category (UIC number or official name)
                const criticalLabels = labels.filter(l => l === 'UIC Name');
                if (criticalLabels.length > 0) {
                    intent = `Critical attribute mismatch, ${criticalLabels.join(', ')}`;
                } else {
                    // Fallback if we cannot detect specific label on the frontend
                    intent = 'Critical attribute mismatch';
                }
            } else if (pr === 2) {
                alertClass = 'alert-warning';
                icon = 'exclamation-triangle';
                if (labels.includes('Local Reference')) {
                    intent = 'Local reference differs between ATLAS and OSM';
                } else {
                    intent = 'Attribute mismatch';
                }
            } else {
                alertClass = 'alert-info';
                icon = 'info-circle';
                if (labels.includes('Operator')) {
                    intent = 'Operator differs between ATLAS and OSM';
                } else {
                    intent = 'Attribute mismatch';
                }
            }

            html += `<div class="alert ${alertClass} problem-info-banner mb-3">
                        <small><i class="fas fa-${icon}"></i> ${intent}.</small>
                     </div>`;
        })();
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
            html += PopupRenderer.generatePopupHtml(atlasData, 'atlas', { hideRoutesAndNotes: true });
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
            html += PopupRenderer.generatePopupHtml(osmData, 'osm', { hideRoutesAndNotes: true });
        } else {
            html += '<div class="alert alert-warning">OSM info not available</div>';
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
            { atlas: 'atlas_designation_official', osm: 'osm_uic_name', label: 'UIC Name' },
            { atlas: 'atlas_designation', osm: 'osm_local_ref', label: 'Local Reference' },
            // Transport type comparison removed from attributes problem resolution per requirements
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
     * Generate a concise, priority-aware information banner placed BELOW the action buttons
     */
    function generateProblemInfoBanner(problem) {
        const pr = Number(problem.priority);
        const problemType = problem.problem;
        let intent = '';
        let icon = 'info-circle';
        let alertClass = 'alert-info';

        const atlasOp = (problem.atlas_business_org_abbr || problem.atlas_operator || '').toString().trim().toUpperCase();
        const isSbb = atlasOp === 'SBB';
        const distanceText = problem.distance_m ? `${Math.round(problem.distance_m)} m` : null;

        if (pr === 1) { alertClass = 'alert-danger'; icon = 'exclamation-circle'; }
        else if (pr === 2) { alertClass = 'alert-warning'; icon = 'exclamation-triangle'; }

        switch (problemType) {
            case 'distance': {
                // Map priority to short rationale (do not repeat priority or distance)
                if (pr === 1) intent = `Very large distance${isSbb ? '' : ' and non‑SBB operator'}`;
                else if (pr === 2) intent = `Large distance${isSbb ? '' : ' and non‑SBB operator'}`;
                else intent = isSbb ? 'Distance above 25 m for SBB' : 'Distance above tolerance';
                return `
                    <div class="problem-section-item">
                        <div class="alert ${alertClass} problem-info-banner mb-0">
                            <small><i class="fas fa-${icon}"></i> ${intent}.</small>
                        </div>
                    </div>`;
            }
            case 'unmatched': {
                const isAtlas = problem.stop_type === 'atlas_unmatched';
                const subject = isAtlas ? 'ATLAS entry' : 'OSM entry';
                if (pr === 1) intent = 'No counterpart exists for this UIC or none within 80 m';
                else if (pr === 2) intent = 'No counterpart within 50 m or platform count mismatch for this UIC';
                else intent = 'Unmatched entry requiring review';
                return `
                    <div class="problem-section-item">
                        <div class="alert ${alertClass} problem-info-banner mb-0">
                            <small><i class="fas fa-${icon}"></i> ${subject} is unmatched. ${intent}.</small>
                        </div>
                    </div>`;
            }
            case 'attributes': {
                // Banner is rendered within the attribute comparison section; skip here to avoid duplication
                return '';
            }
            case 'duplicates': {
                // Info is already shown in the resolution actions banner, no need for bottom banner
                return '';
            }
        }

        // Fallback generic banner
        return `
            <div class="problem-section-item">
                <div class="alert ${alertClass} problem-info-banner mb-0">
                    <small><i class="fas fa-${icon}"></i> Issue detected.</small>
                </div>
            </div>`;
    }

    /**
     * Render the UI for a single problem. Returns HTML string.
     */
    function renderSingleProblemUI(problem, entryIndex, issueIndex, totalIssues) {
        const problemType = problem.problem ? problem.problem.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase()) : "Unknown";
        const safeId = String(problem.id).replace(/[^a-zA-Z0-9_-]/g, '-');
        let html = `<div class="issue-container" id="issue-${safeId}" data-problem-id="${problem.id}" data-stop-id="${problem.stop_id}">`;

        // Header for the issue
        // Add priority circle if present - match filter design
        let priorityBadge = '';
        if (problem.priority && !isNaN(problem.priority)) {
            const pr = String(problem.priority);
            const prClass = pr === '1' ? 'pr-1' : pr === '2' ? 'pr-2' : pr === '3' ? 'pr-3' : '';
            const selectedClass = '';
            priorityBadge = ` <span class="priority-circle ${prClass} ${selectedClass}"><span class="pc-text">P${pr}</span></span>`;
        }
        let displayText = `${problemType}${priorityBadge}`;
        if (totalIssues > 1) {
            displayText += ` (Issue ${issueIndex + 1}/${totalIssues})`;
        }

        // Add distance indicator for distance problems
        if (problem.problem === 'distance' && problem.distance_m) {
            const distance = Math.round(problem.distance_m);
            const distanceClass = distance > 100 ? 'high-distance' : '';
            displayText += `<span class="distance-indicator ${distanceClass}">(${distance}m apart)</span>`;
        }

        html += `<h5 class="text-center mb-3">${displayText}</h5>`;

        // Generate action buttons and content based on problem type
        let actionButtonsHtml = '';

        // Handle duplicates differently due to their multi-member structure
        if (problem.problem === 'duplicates') {
            if (!Array.isArray(problem.members) || problem.members.length === 0) {
                // Fallback for non-group duplicates (no members available)
                actionButtonsHtml += wrapInSection(
                    '<i class="fas fa-clone"></i> Duplicates',
                    '<div class="alert alert-info"><small>This entry is part of a duplicates group. Open the Duplicates view to resolve this issue.</small></div>' +
                    '<button class="btn btn-sm btn-outline-primary professional-button" onclick="ProblemsData.updateProblemTypeFilter(\'duplicates\', \'all\')">' +
                    '<i class="fas fa-external-link-alt"></i> Open Duplicates'
                    + '</button>'
                );
            } else {
                // Info block for Members
                let html = '<div class="problem-section-item">';
                html += '<h6><i class="fas fa-clone"></i> Duplicates</h6>';
                
                // Table of members
                html += '<table class="table table-sm"><thead><tr>' +
                    '<th>Source</th><th>Identifier</th><th>Name</th><th>Coords</th></tr></thead><tbody>';

                (problem.members || []).forEach(member => {
                    const isOsmGroup = problem.group_type === 'osm';
                    const isOsm = isOsmGroup ? true : (problem.group_type === 'atlas' ? false : !!member.osm_node_id);
                    const badge = `<span class="badge badge-secondary">${isOsm ? 'OSM' : 'ATLAS'}</span>`;
                    const ident = isOsm ? (member.osm_node_id || '-') : (member.sloid || '-');
                    const name = isOsm ? (member.osm_name || member.osm_uic_name || '-') 
                                       : (member.atlas_designation_official || member.atlas_designation || '-');
                    const coords = isOsm
                        ? (member.osm_lat && member.osm_lon ? `${Math.round(member.osm_lat * 1e5) / 1e5}, ${Math.round(member.osm_lon * 1e5) / 1e5}` : '-')
                        : (member.atlas_lat && member.atlas_lon ? `${Math.round(member.atlas_lat * 1e5) / 1e5}, ${Math.round(member.atlas_lon * 1e5) / 1e5}` : '-');

                    html += `<tr>
                        <td>${badge}</td>
                        <td>${ident}</td>
                        <td>${name || '-'}</td>
                        <td>${coords}</td>
                    </tr>`;
                });

                html += '</tbody></table></div>';
                actionButtonsHtml += html;
            }
        } else if (problem.problem === 'attributes') {
            actionButtonsHtml += generateAttributeComparisonHtml(problem);
        }
        html += actionButtonsHtml;

        // Add concise, priority-aware info banner below the resolution actions (except for distance & unmatched which already show an integrated banner)
        if (problem.problem !== 'distance' && problem.problem !== 'unmatched') {
            html += generateProblemInfoBanner(problem);
        }
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
        const firstProblemForHeader = currentEntryProblems[0];
        const isDuplicatesGroupHeader = firstProblemForHeader && firstProblemForHeader.problem === 'duplicates';
        if (isDuplicatesGroupHeader) {
            $('#problemTypeDisplay').text(`Group ${index + 1} of ${totalProblems}`);
        } else {
            $('#problemTypeDisplay').text(`Entry ${index + 1} of ${totalProblems} (${problemCount} ${problemText})`);
        }

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
        $('.issue-container').each(function () {
            if (observer) {
                observer.observe(this);
            }
        });

        // Set first problem as active
        const firstProblem = currentEntryProblems[0];
        if (firstProblem) {
            // Make first issue active
            $(`.issue-container[data-problem-id="${firstProblem.id}"]`).addClass('active');

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

            // Load notes for the first problem and setup notes container visibility
            if (firstProblem.problem === 'duplicates' && Array.isArray(firstProblem.members) && firstProblem.members.length > 0) {
                // Use unified notes loader for duplicates
                if (window.ProblemsNotes && window.ProblemsNotes.loadNotesForDuplicates) {
                    window.ProblemsNotes.loadNotesForDuplicates(firstProblem);
                }
            } else {
                // Show standard notes container for other problem types
                $('#notesSection').show();
                $('#standardNotesContainer').show();
                $('#duplicatesNotesContainer').hide();
                if (window.ProblemsNotes && window.ProblemsNotes.loadNotesForProblem) {
                    window.ProblemsNotes.loadNotesForProblem(firstProblem);
                }
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
     * Delegates to shared utility
     */
    function showTemporaryMessage(message, type) {
        SharedUtils.showTemporaryMessage(message, type);
    }

    // Public API
    return {
        showKeyboardHint,
        hideKeyboardHint,
        generateAttributeComparisonHtml,
        getMismatchedAttributes,
        renderSingleProblemUI,
        setupIntersectionObserver,
        displayProblem,
        updateNavButtons,
        showTemporaryMessage
    };
})();
