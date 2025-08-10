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
        // Priority-aware concise info banner for attributes, shown above the popups
        (function(){
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
     * Generate action buttons for distance problems
     */
    function generateDistanceActionButtons(problem) {
        const distanceText = problem.distance_m ? `${Math.round(problem.distance_m)} m` : 'unknown';
        const pr = Number(problem.priority);
        const atlasOp = (problem.atlas_business_org_abbr || problem.atlas_operator || '').toString().trim().toUpperCase();
        const isSbb = atlasOp === 'SBB';
        let alertClass = 'alert-info';
        let rationale = '';
        if (pr === 1) { alertClass = 'alert-danger'; rationale = `Very large distance${isSbb ? '' : ' and non‑SBB operator'}`; }
        else if (pr === 2) { alertClass = 'alert-warning'; rationale = `Large distance${isSbb ? '' : ' and non‑SBB operator'}`; }
        else { alertClass = 'alert-info'; rationale = isSbb ? 'Distance above 25 m for SBB' : 'Distance above tolerance'; }

        return `
            <div class="problem-section-item">
                <h6><i class="fas fa-tools"></i> Resolution Actions</h6>
                <div class="alert ${alertClass}">
                    <small><i class="fas fa-info-circle"></i> Distance between ATLAS and OSM: ${distanceText}. ${rationale}. Choose which location is correct.</small>
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
        const pr = Number(problem.priority);
        const isAtlas = problem.stop_type === 'unmatched';
        const subject = isAtlas ? 'ATLAS entry' : 'OSM entry';
        let alertClass = 'alert-info';
        let icon = 'info-circle';
        let intent = '';
        if (pr === 1) { alertClass = 'alert-danger'; icon = 'exclamation-circle'; intent = 'No counterpart exists for this UIC or none within 80 m'; }
        else if (pr === 2) { alertClass = 'alert-warning'; icon = 'exclamation-triangle'; intent = 'No counterpart within 50 m or platform count mismatch for this UIC'; }
        else { alertClass = 'alert-info'; icon = 'info-circle'; intent = 'Unmatched entry requiring review'; }

        if (isAtlas) { // Isolated ATLAS
            return `
                <div class="problem-section-item">
                    <h6><i class="fas fa-tools"></i> Resolution Actions</h6>
                    <div class="alert ${alertClass}">
                        <small><i class="fas fa-${icon}"></i> ${subject} is unmatched. ${intent}.</small>
                    </div>
                    <div class="d-flex flex-wrap gap-2">
                        <button class="btn btn-secondary professional-button" data-action="manual-match-atlas">Match to</button>
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
                    <div class="alert ${alertClass}">
                        <small><i class="fas fa-${icon}"></i> ${subject} is unmatched. ${intent}.</small>
                    </div>
                    <div class="d-flex flex-wrap gap-2">
                        <button class="btn btn-secondary professional-button" data-action="manual-match-osm">Match to</button>
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
                    This entry is flagged with an 'unmatched' problem, but its type is <code>${problem.stop_type || 'undefined'}</code>, which is not expected for this problem type. Please report this issue.
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
     * Generate action buttons for duplicates problems (grouped view)
     */
    function generateDuplicatesActionButtons(problem) {
        // problem is a group with members
        const isOsmGroup = problem.group_type === 'osm';
        let title = isOsmGroup
            ? `<i class="fas fa-clone"></i> OSM duplicates for UIC ${problem.uic_ref || '(none)'} · local_ref ${problem.osm_local_ref || '(none)'}`
            : `<i class="fas fa-clone"></i> ATLAS duplicates for SLOID ${problem.sloid}`;

        let html = '<div class="problem-section-item">';
        html += `<h6>${title}</h6>`;
        html += '<div class="alert alert-info"><small>' +
                (isOsmGroup ? 'Multiple OSM nodes share the same UIC and local_ref. Review each and decide which should remain.'
                             : 'Multiple entries share the same ATLAS SLOID. Review and decide which should remain.') +
                '</small></div>';

        // Table of members
        html += '<table class="table table-sm"><thead><tr>' +
                '<th>Source</th><th>Identifier</th><th>Name</th><th>Coords</th><th>Action</th></tr></thead><tbody>';

        (problem.members || []).forEach(member => {
            const isOsm = !!member.osm_node_id;
            const coords = isOsm
                ? (member.osm_lat && member.osm_lon ? `${Math.round(member.osm_lat*1e5)/1e5}, ${Math.round(member.osm_lon*1e5)/1e5}` : '-')
                : (member.atlas_lat && member.atlas_lon ? `${Math.round(member.atlas_lat*1e5)/1e5}, ${Math.round(member.atlas_lon*1e5)/1e5}` : '-');
            const name = isOsm ? (member.osm_name || member.osm_uic_name || '-')
                               : (member.atlas_designation_official || member.atlas_designation || '-');
            const ident = isOsm ? (member.osm_node_id || '-') : (member.sloid || '-');
            const sourceBadge = isOsm ? '<span class="badge badge-primary">OSM</span>' : '<span class="badge badge-info">ATLAS</span>';
            const osmEditorLink = isOsm && member.osm_node_id
                ? `<a class="btn btn-link btn-sm" href="https://www.openstreetmap.org/edit?node=${member.osm_node_id}" target="_blank" rel="noopener noreferrer">Edit</a>`
                : '';

            html += `<tr>
                <td>${sourceBadge}</td>
                <td><code>${ident}</code></td>
                <td>${name || '-'}</td>
                <td>${coords}</td>
                <td class="d-flex flex-wrap gap-2">
                    <button class="btn btn-success btn-sm solution-btn" data-solution="Keep" data-problem="duplicates" data-target-stop-id="${member.stop_id}">
                        <i class="fas fa-check-circle"></i> Keep
                    </button>
                    <button class="btn btn-danger btn-sm solution-btn" data-solution="Should be deleted" data-problem="duplicates" data-target-stop-id="${member.stop_id}">
                        <i class="fas fa-trash"></i> Should be deleted
                    </button>
                    ${osmEditorLink}
                </td>
            </tr>`;
        });

        html += '</tbody></table>';
        html += '</div>';
        return html;
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
                const isAtlas = problem.stop_type === 'unmatched';
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
                const isOsmGroup = problem.group_type === 'osm';
                const count = (problem.members && problem.members.length) ? problem.members.length : null;
                const where = isOsmGroup ? 'OSM' : 'ATLAS';
                if (pr === 2) intent = 'Duplicate ATLAS SLOID group';
                else intent = 'Duplicate OSM nodes with same UIC and local_ref';
                const suffix = count ? ` · ${count} entries` : '';
                return `
                    <div class="problem-section-item">
                        <div class="alert ${alertClass} problem-info-banner mb-0">
                            <small><i class="fas fa-${icon}"></i> ${intent} in ${where}${suffix}.</small>
                        </div>
                    </div>`;
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
            case 'unmatched':
                actionButtonsHtml += generateIsolatedActionButtons(problem);
                break;
            case 'attributes':
                actionButtonsHtml += generateAttributeComparisonHtml(problem);
                actionButtonsHtml += generateAttributesActionButtons(problem);
                break;
            case 'duplicates':
                 actionButtonsHtml += generateDuplicatesActionButtons(problem);
                 break;
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
